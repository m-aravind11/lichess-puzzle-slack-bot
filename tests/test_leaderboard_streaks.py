"""Streaks are computed in SQL (see queries.LeaderboardQueries.STREAKS), so these
run get_leaderboard against a real in-memory sqlite3 connection. Puzzles and
submissions are inserted directly to control post order, active and closed
state without going through the save/close flows."""

import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
import migrations
from constants import Security, Streaks
from slack_helpers import format_leaderboard, format_leaderboard_post, format_streak_milestones
from standings import build_standings


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    migrations.run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def patch_connection(conn, monkeypatch):
    @contextmanager
    def fake_get_connection():
        yield conn
        conn.commit()

    monkeypatch.setattr(db, "get_connection", fake_get_connection)


def add_puzzles(conn, count, deactivated=(), open_=()):
    """Posts p1..p<count> on consecutive days; all closed unless listed in open_."""
    for i in range(1, count + 1):
        conn.execute(
            "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, active, closed_at)"
            " VALUES (?, 'fen', '[]', 'random', ?, ?, ?, ?)",
            (
                f"p{i}",
                f"2024-01-{i:02d}T12:00:00+00:00",
                f"2024-01-{i:02d}T12:00:00+00:00",
                0 if i in deactivated else 1,
                None if i in open_ else f"2024-01-{i + 1:02d}T06:00:00+00:00",
            ),
        )


def add_answers(conn, user_id, answers, active=True):
    """answers maps puzzle number -> correct."""
    for n, correct in answers.items():
        conn.execute(
            "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)"
            " VALUES (?, ?, ?, 'e4', ?, ?, ?, ?)",
            (f"p{n}", user_id, user_id, int(correct), 10 if correct else 0, f"2024-01-{n:02d}T12:05:00+00:00", int(active)),
        )


def streaks(user_id):
    entry = next(e for e in db.get_leaderboard() if e["user_id"] == user_id)
    return entry["current_streak"], entry["best_streak"]


def test_unbroken_run_is_both_current_and_best(conn):
    add_puzzles(conn, 4)
    add_answers(conn, "alice", {1: True, 2: True, 3: True, 4: True})
    assert streaks("alice") == (4, 4)


def test_wrong_answer_breaks_the_streak(conn):
    add_puzzles(conn, 5)
    add_answers(conn, "alice", {1: True, 2: True, 3: True, 4: False, 5: True})
    assert streaks("alice") == (1, 3)


def test_missed_puzzle_breaks_the_streak(conn):
    add_puzzles(conn, 5)
    add_answers(conn, "alice", {1: True, 2: True, 4: True, 5: True})
    assert streaks("alice") == (2, 2)


def test_missing_the_latest_closed_puzzle_ends_the_current_streak(conn):
    add_puzzles(conn, 3)
    add_answers(conn, "alice", {1: True, 2: True})
    assert streaks("alice") == (0, 2)


def test_deactivated_puzzle_does_not_break_the_streak(conn):
    add_puzzles(conn, 4, deactivated={2})
    add_answers(conn, "alice", {1: True, 3: True, 4: True})
    assert streaks("alice") == (3, 3)


def test_open_latest_puzzle_not_yet_answered_keeps_the_streak(conn):
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True, 2: True})
    assert streaks("alice") == (2, 2)


def test_open_latest_puzzle_answered_correctly_extends_the_streak(conn):
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True, 2: True, 3: True})
    assert streaks("alice") == (3, 3)


def test_deactivated_submission_breaks_the_streak(conn):
    add_puzzles(conn, 3)
    add_answers(conn, "alice", {1: True, 3: True})
    add_answers(conn, "alice", {2: True}, active=False)
    assert streaks("alice") == (1, 1)


def test_user_with_no_correct_answers_has_zero_streaks(conn):
    add_puzzles(conn, 2)
    add_answers(conn, "alice", {1: False, 2: False})
    assert streaks("alice") == (0, 0)


def test_streaks_are_per_user(conn):
    add_puzzles(conn, 3)
    add_answers(conn, "alice", {1: True, 2: True, 3: True})
    add_answers(conn, "bob", {1: True, 2: False, 3: True})
    assert streaks("alice") == (3, 3)
    assert streaks("bob") == (1, 1)


def test_grace_only_covers_the_open_puzzle_not_an_earlier_miss(conn):
    # Missed p2 (closed), p3 still open and unanswered: the open puzzle's grace
    # doesn't reach back past a real miss.
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True})
    assert streaks("alice") == (0, 1)


def test_correct_answer_on_open_puzzle_after_a_miss_starts_a_new_streak(conn):
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True, 3: True})
    assert streaks("alice") == (1, 1)


def test_wrong_answer_on_open_puzzle_keeps_the_streak_until_it_closes(conn):
    # Known, accepted limitation: grace looks only at whether the latest puzzle
    # is open, not at what the user submitted. The leaderboard posts after the
    # reveal closes it, so the posted board is still right.
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True, 2: True, 3: False})
    assert streaks("alice") == (2, 2)

    conn.execute("UPDATE puzzles SET closed_at = 'x' WHERE puzzle_id = 'p3'")
    assert streaks("alice") == (0, 2)


def test_only_the_latest_puzzle_being_open_grants_grace(conn):
    # Pre-migration-0009 puzzles were never closed (closed_at NULL). An old open
    # puzzle mustn't grant grace once a newer, closed one exists.
    add_puzzles(conn, 3, open_={1, 2})
    add_answers(conn, "alice", {1: True, 2: True})
    assert streaks("alice") == (0, 2)


def test_deactivated_latest_puzzle_falls_back_to_the_one_before(conn):
    add_puzzles(conn, 3, deactivated={3})
    add_answers(conn, "alice", {1: True, 2: True})
    assert streaks("alice") == (2, 2)


def test_consecutive_deactivated_puzzles_do_not_break_the_streak(conn):
    add_puzzles(conn, 5, deactivated={2, 3, 4})
    add_answers(conn, "alice", {1: True, 5: True})
    assert streaks("alice") == (2, 2)


def test_correct_answer_on_a_deactivated_puzzle_does_not_count(conn):
    add_puzzles(conn, 3, deactivated={2})
    add_answers(conn, "alice", {1: True, 2: True, 3: True})
    assert streaks("alice") == (2, 2)


def test_queued_puzzle_is_not_the_latest(conn):
    add_puzzles(conn, 2)
    conn.execute(
        "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, active)"
        " VALUES ('q1', 'fen', '[]', 'curated', '2024-01-05T00:00:00+00:00', 1)"
    )
    add_answers(conn, "alice", {1: True, 2: True})
    assert streaks("alice") == (2, 2)


def test_resubmission_after_a_deactivated_wrong_answer_counts(conn):
    add_puzzles(conn, 3)
    add_answers(conn, "alice", {1: True, 3: True})
    add_answers(conn, "alice", {2: False}, active=False)
    add_answers(conn, "alice", {2: True})
    assert streaks("alice") == (3, 3)


def test_best_streak_can_be_in_the_past(conn):
    add_puzzles(conn, 8)
    add_answers(conn, "alice", {1: True, 2: True, 3: True, 4: True, 6: True, 7: True, 8: True})
    assert streaks("alice") == (3, 4)


def test_post_order_decides_the_sequence_not_puzzle_id(conn):
    # p2 was posted before p1 (e.g. p1 was queued earlier but posted later).
    for puzzle_id, day in (("p2", 1), ("p1", 2), ("p3", 3)):
        conn.execute(
            "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, active, closed_at)"
            " VALUES (?, 'fen', '[]', 'random', ?, ?, 1, 'x')",
            (puzzle_id, f"2024-01-{day:02d}T12:00:00+00:00", f"2024-01-{day:02d}T12:00:00+00:00"),
        )
    # Posted back to back (days 2 and 3); by puzzle_id they'd be p1, p3 with p2 between.
    add_answers(conn, "alice", {1: True, 3: True})
    assert streaks("alice") == (2, 2)


def test_bare_date_posted_at_from_old_rows_still_orders_correctly(conn):
    # Migration 0008 left posted_at as a bare YYYY-MM-DD on rows with no slack_ts.
    add_puzzles(conn, 3)
    conn.execute("UPDATE puzzles SET posted_at = '2024-01-01' WHERE puzzle_id = 'p1'")
    add_answers(conn, "alice", {1: True, 2: True, 3: True})
    assert streaks("alice") == (3, 3)


def test_empty_leaderboard(conn):
    add_puzzles(conn, 2)
    assert db.get_leaderboard() == []


def test_leaderboard_includes_everyone(conn):
    add_puzzles(conn, 1)
    for i in range(15):
        add_answers(conn, f"U{i}", {1: True})
    assert len(db.get_leaderboard()) == 15


def _entry(user_id, current_streak):
    return {
        "user_id": user_id, "user_name": user_id.lower(), "score": 10, "correct": 1, "incorrect": 0,
        "attempted": 1, "avg_solve_seconds": 60, "current_streak": current_streak, "best_streak": current_streak,
        "house_name": None,
    }


def milestones(board):
    return build_standings(board)["milestones"]


def slack_milestones(board):
    return format_streak_milestones(build_standings(board))


def table_lines(board):
    """The player table's lines, from inside its code block."""
    return format_leaderboard(build_standings(board)).split("```")[1].strip("\n").splitlines()


def test_leaderboard_is_only_the_header_and_table():
    text = format_leaderboard(build_standings([_entry("U1", 7)]))
    assert "Current Streak" in text
    assert text.endswith("```")
    assert "<@" not in text


def test_milestones_are_listed_longest_first():
    assert slack_milestones([_entry("U1", 3), _entry("U2", 4), _entry("U3", 7)]).splitlines() == [
        "*Streak milestones*",
        "• <@U3> is on a 7-day streak.",
        "• <@U1> is on a 3-day streak.",
    ]


def test_players_on_the_same_milestone_share_a_line():
    text = slack_milestones([_entry("U1", 7), _entry("U2", 7), _entry("U3", 7)])
    assert text.endswith("• <@U1>, <@U2> and <@U3> are on a 7-day streak.")


def test_two_players_on_a_milestone_are_joined_with_and():
    text = slack_milestones([_entry("U1", 30), _entry("U2", 30)])
    assert text.endswith("• <@U1> and <@U2> are on a 30-day streak.")


@pytest.mark.parametrize("streak", Streaks.MILESTONES)
def test_every_milestone_is_announced(streak):
    assert slack_milestones([_entry("U1", streak)]).endswith(f"• <@U1> is on a {streak}-day streak.")


@pytest.mark.parametrize("streak", [0, 1, 2, 4, 5, 10, 25, 364, 366, 730])
def test_non_milestones_are_not_announced(streak):
    assert milestones([_entry("U1", streak)]) == []
    assert slack_milestones([_entry("U1", streak)]) is None


def test_milestones_carry_names_for_the_web_and_ids_for_slack_mentions():
    assert milestones([_entry("U1", 7)]) == [{"streak": 7, "players": [{"user_id": "U1", "name": "u1"}]}]


def test_table_falls_back_to_user_id_when_name_missing():
    entry = _entry("U1", 0)
    entry["user_name"] = None
    assert table_lines([entry])[2].split()[1] == "U1"


def test_table_columns_include_house():
    entry = _entry("U1", 0)
    entry.update(correct=9, attempted=12, house_name="Airbenders")
    header, _, row = table_lines([entry])
    assert header.split() == ["#", "Name", "House", "Points", "Solved", "Avg", "Solve", "Time", "Current", "Streak"]
    assert row.split()[2:5] == ["Airbenders", "10", "9/12"]


def test_table_shows_a_dash_for_players_without_a_house():
    assert table_lines([_entry("U1", 0)])[2].split()[2] == "-"


@pytest.fixture
def post_leaderboard(monkeypatch):
    """Calls /admin/leaderboard:send with the given board, returns the posted text."""
    monkeypatch.setattr(Security, "CRON_SECRET", "s3cr3t")
    post = MagicMock()
    monkeypatch.setattr(app_module.slack_client, "chat_postMessage", post)

    def run(board):
        monkeypatch.setattr(db, "is_holiday", lambda date: False)
        monkeypatch.setattr(db, "get_leaderboard", lambda: board)
        response = TestClient(app_module.app).post(
            "/admin/leaderboard:send", headers={"Authorization": "Bearer s3cr3t"},
        )
        assert response.status_code == 200
        return post.call_args.kwargs["text"]

    return run


def test_posted_leaderboard_separates_milestones_with_a_blank_line(post_leaderboard):
    standings = build_standings([_entry("U1", 7)])
    assert post_leaderboard([_entry("U1", 7)]) == f"{format_leaderboard(standings)}\n\n{format_streak_milestones(standings)}"


def test_posted_leaderboard_without_milestones_is_just_the_table(post_leaderboard):
    assert post_leaderboard([_entry("U1", 2)]) == format_leaderboard(build_standings([_entry("U1", 2)]))


def test_posted_leaderboard_is_the_formatted_post(post_leaderboard):
    entry = _entry("U1", 7)
    entry["house_name"] = "Airbenders"
    assert post_leaderboard([entry]) == format_leaderboard_post(build_standings([entry]))
