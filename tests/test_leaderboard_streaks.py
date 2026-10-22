import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
import migrations
from constants import Security, Streaks
from scoring import STREAK_BONUS
from slack_helpers import format_leaderboard, format_leaderboard_post, format_streak_milestones
from standings import build_standings, compute_streak_bonus_candidates


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


def add_answers(conn, user_id, answers, active=True, attempt=1):
    """answers maps puzzle number -> correct."""
    for n, correct in answers.items():
        conn.execute(
            "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, attempt, submitted_at, active)"
            " VALUES (?, ?, ?, 'e4', ?, ?, ?, ?, ?)",
            (
                f"p{n}", user_id, user_id, int(correct), 10 if correct else 0, attempt,
                f"2024-01-{n:02d}T12:05:00+00:00", int(active),
            ),
        )


def streaks(user_id):
    entry = next(e for e in db.get_leaderboard("2024-01") if e["user_id"] == user_id)
    return entry["current_streak"], entry["best_streak"]


def streak_start(user_id):
    entry = next(e for e in db.get_leaderboard("2024-01") if e["user_id"] == user_id)
    return entry["current_streak_start"]


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
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True})
    assert streaks("alice") == (0, 1)


def test_correct_answer_on_open_puzzle_after_a_miss_starts_a_new_streak(conn):
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True, 3: True})
    assert streaks("alice") == (1, 1)


def test_one_wrong_attempt_on_open_puzzle_keeps_the_streak(conn):
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True, 2: True, 3: False})
    assert streaks("alice") == (2, 2)

    conn.execute("UPDATE puzzles SET closed_at = 'x' WHERE puzzle_id = 'p3'")
    assert streaks("alice") == (0, 2)


def test_correct_second_attempt_on_open_puzzle_extends_the_streak(conn):
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True, 2: True, 3: False})
    add_answers(conn, "alice", {3: True}, attempt=2)
    assert streaks("alice") == (3, 3)


def test_two_attempts_count_as_one_puzzle_attempted(conn):
    add_puzzles(conn, 1)
    add_answers(conn, "alice", {1: False})
    add_answers(conn, "alice", {1: True}, attempt=2)
    entry = next(e for e in db.get_leaderboard("2024-01") if e["user_id"] == "alice")
    assert (entry["attempted"], entry["correct"], entry["incorrect"]) == (1, 1, 0)


def test_using_every_attempt_on_open_puzzle_ends_the_streak_right_away(conn):
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True, 2: True, 3: False})
    add_answers(conn, "alice", {3: False}, attempt=2)
    assert streaks("alice") == (0, 2)


def test_deactivated_wrong_answer_on_open_puzzle_restores_the_grace(conn):
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True, 2: True, 3: False})
    add_answers(conn, "alice", {3: False}, active=False, attempt=2)
    assert streaks("alice") == (2, 2)


def test_only_the_latest_puzzle_being_open_grants_grace(conn):
    # Pre-migration-0009 puzzles were never closed.
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


def test_current_streak_start_is_the_current_runs_start_not_the_past_bests(conn):
    # Same setup as above: the longer run (1-4) is in the past; the current run is 6-8.
    add_puzzles(conn, 8)
    add_answers(conn, "alice", {1: True, 2: True, 3: True, 4: True, 6: True, 7: True, 8: True})
    assert streak_start("alice") == "2024-01-06"


def test_current_streak_start_survives_a_deactivated_puzzle_mid_run(conn):
    add_puzzles(conn, 4, deactivated={2})
    add_answers(conn, "alice", {1: True, 3: True, 4: True})
    assert streaks("alice") == (3, 3)
    assert streak_start("alice") == "2024-01-01"


def test_current_streak_start_extends_through_an_open_unanswered_grace_puzzle(conn):
    add_puzzles(conn, 3, open_={3})
    add_answers(conn, "alice", {1: True, 2: True})
    assert streaks("alice") == (2, 2)
    assert streak_start("alice") == "2024-01-01"


def test_current_streak_start_is_none_when_there_is_no_current_streak(conn):
    add_puzzles(conn, 3)
    add_answers(conn, "alice", {1: True, 2: True})
    assert streaks("alice") == (0, 2)
    assert streak_start("alice") is None


def test_post_order_decides_the_sequence_not_puzzle_id(conn):
    for puzzle_id, day in (("p2", 1), ("p1", 2), ("p3", 3)):
        conn.execute(
            "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, active, closed_at)"
            " VALUES (?, 'fen', '[]', 'random', ?, ?, 1, 'x')",
            (puzzle_id, f"2024-01-{day:02d}T12:00:00+00:00", f"2024-01-{day:02d}T12:00:00+00:00"),
        )
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
    assert db.get_leaderboard("2024-01") == []


def test_leaderboard_includes_everyone(conn):
    add_puzzles(conn, 1)
    for i in range(15):
        add_answers(conn, f"U{i}", {1: True})
    assert len(db.get_leaderboard("2024-01")) == 15


def _entry(user_id, current_streak):
    return {
        "user_id": user_id, "user_name": user_id.lower(), "score": 10, "correct": 1, "incorrect": 0,
        "attempted": 1, "avg_solve_seconds": 60, "current_streak": current_streak, "best_streak": current_streak,
        "house_name": None,
    }


def _increment(days):
    """What a normal, uninterrupted run actually gains at this crossing -- the
    Slack message shows this, not the milestone's raw cumulative target."""
    index = list(Streaks.MILESTONES).index(days)
    previous = STREAK_BONUS[Streaks.MILESTONES[index - 1]] if index > 0 else 0
    return STREAK_BONUS[days] - previous


def milestones(board):
    return build_standings(board)["milestones"]


def slack_milestones(board):
    return format_streak_milestones(build_standings(board))


def table_lines(board):
    return format_leaderboard(build_standings(board)).split("```")[1].strip("\n").splitlines()


def test_leaderboard_is_only_the_header_and_table():
    text = format_leaderboard(build_standings([_entry("U1", 7)]))
    assert "Current Streak" in text
    assert text.endswith("```")
    assert "<@" not in text


def test_milestones_are_listed_longest_first():
    assert slack_milestones([_entry("U1", 3), _entry("U2", 4), _entry("U3", 7)]).splitlines() == [
        "*Streak milestones*",
        f"• <@U3> is on a 7-day streak (+{_increment(7)} bonus points).",
        f"• <@U1> is on a 3-day streak (+{_increment(3)} bonus points).",
    ]


def test_players_on_the_same_milestone_share_a_line():
    text = slack_milestones([_entry("U1", 7), _entry("U2", 7), _entry("U3", 7)])
    assert text.endswith(f"• <@U1>, <@U2> and <@U3> are on a 7-day streak (+{_increment(7)} bonus points).")


def test_two_players_on_a_milestone_are_joined_with_and():
    text = slack_milestones([_entry("U1", 30), _entry("U2", 30)])
    assert text.endswith(f"• <@U1> and <@U2> are on a 30-day streak (+{_increment(30)} bonus points).")


def test_players_at_the_same_streak_with_different_real_increments_get_separate_lines():
    # e.g. U2 caught up from a missed cron day and so actually earned more than the
    # "normal progression" assumption for a 7-day streak -- they must not share a
    # line with U1's (correct, smaller) amount or vice versa.
    standings = build_standings(
        [_entry("U1", 7), _entry("U2", 7)], streak_bonus_increments={"U1": _increment(7), "U2": 25}
    )
    assert format_streak_milestones(standings).splitlines() == [
        "*Streak milestones*",
        "• <@U2> is on a 7-day streak (+25 bonus points).",
        f"• <@U1> is on a 7-day streak (+{_increment(7)} bonus points).",
    ]


@pytest.mark.parametrize("streak", Streaks.MILESTONES)
def test_every_milestone_is_announced(streak):
    bonus = _increment(streak)
    assert slack_milestones([_entry("U1", streak)]).endswith(f"• <@U1> is on a {streak}-day streak (+{bonus} bonus points).")


@pytest.mark.parametrize("streak", [0, 1, 2, 4, 5, 10, 25, 364, 366, 730])
def test_non_milestones_are_not_announced(streak):
    assert milestones([_entry("U1", streak)]) == []
    assert slack_milestones([_entry("U1", streak)]) is None


def test_milestones_carry_names_for_the_web_and_ids_for_slack_mentions():
    assert milestones([_entry("U1", 7)]) == [{
        "streak": 7,
        "bonus": _increment(7),
        "players": [{"user_id": "U1", "name": "u1", "start_date": None}],
    }]


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
    monkeypatch.setattr(Security, "CRON_SECRET", "s3cr3t")
    post = MagicMock()
    monkeypatch.setattr(app_module.slack_client, "chat_postMessage", post)

    def run(board):
        monkeypatch.setattr(db, "store_finished_months", lambda: None)
        monkeypatch.setattr(db, "is_holiday", lambda date: False)
        monkeypatch.setattr(db, "list_unannounced_months", lambda: [])
        monkeypatch.setattr(db, "get_leaderboard_month", lambda: {"month": "2024-01", "final": False})
        monkeypatch.setattr(db, "get_leaderboard", lambda month: board)
        monkeypatch.setattr(db, "record_streak_bonuses", lambda candidates, end_date: {})
        response = TestClient(app_module.app).post(
            "/admin/leaderboard:send", headers={"Authorization": "Bearer s3cr3t"},
        )
        assert response.status_code == 200
        return post.call_args.kwargs["text"]

    return run


@pytest.fixture
def post_leaderboard_for_real(monkeypatch):
    """Like post_leaderboard, but db.get_leaderboard and db.record_streak_bonuses run
    for real against a fresh connection, instead of being stubbed out -- for tests
    that need to exercise the actual streak-bonus write path, not just the
    formatting. A dedicated connection (not the shared `conn` fixture), because
    TestClient runs the request in a different thread than the fixture is created
    in, and sqlite3 connections are single-thread by default."""
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    migrations.run_migrations(connection)

    @contextmanager
    def fake_get_connection():
        yield connection
        connection.commit()

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    monkeypatch.setattr(Security, "CRON_SECRET", "s3cr3t")
    post = MagicMock()
    monkeypatch.setattr(app_module.slack_client, "chat_postMessage", post)
    monkeypatch.setattr(db, "store_finished_months", lambda: None)
    monkeypatch.setattr(db, "is_holiday", lambda date: False)
    monkeypatch.setattr(db, "list_unannounced_months", lambda: [])
    monkeypatch.setattr(db, "get_leaderboard_month", lambda: {"month": "2024-01", "final": False})

    def run():
        response = TestClient(app_module.app).post(
            "/admin/leaderboard:send", headers={"Authorization": "Bearer s3cr3t"},
        )
        assert response.status_code == 200
        return post.call_args.kwargs["text"]

    yield connection, run
    connection.close()


def test_posted_leaderboard_separates_milestones_with_a_blank_line(post_leaderboard):
    standings = build_standings([_entry("U1", 7)], "2024-01")
    assert post_leaderboard([_entry("U1", 7)]) == f"{format_leaderboard(standings)}\n\n{format_streak_milestones(standings)}"


def test_posted_leaderboard_without_milestones_is_just_the_table(post_leaderboard):
    assert post_leaderboard([_entry("U1", 2)]) == format_leaderboard(build_standings([_entry("U1", 2)], "2024-01"))


def test_posted_leaderboard_is_the_formatted_post(post_leaderboard):
    entry = _entry("U1", 7)
    entry["house_name"] = "Airbenders"
    assert post_leaderboard([entry]) == format_leaderboard_post(build_standings([entry], "2024-01"))


def _bonus_rows(conn, user_id):
    return conn.execute(
        "SELECT streak, start_date, end_date, bonus FROM streak_bonuses WHERE user_id = ? ORDER BY start_date",
        (user_id,),
    ).fetchall()


def test_record_streak_bonuses_writes_a_row_per_milestone_hit(conn):
    add_puzzles(conn, 7)
    add_answers(conn, "alice", {n: True for n in range(1, 8)})
    board = db.get_leaderboard("2024-01")

    db.record_streak_bonuses(compute_streak_bonus_candidates(board), end_date="2024-01-07")

    assert _bonus_rows(conn, "alice") == [(7, "2024-01-01", "2024-01-07", STREAK_BONUS[7])]


def test_record_streak_bonuses_does_not_double_award_the_same_streak_instance(conn):
    add_puzzles(conn, 7)
    add_answers(conn, "alice", {n: True for n in range(1, 8)})
    candidates = compute_streak_bonus_candidates(db.get_leaderboard("2024-01"))

    db.record_streak_bonuses(candidates, end_date="2024-01-07")
    db.record_streak_bonuses(candidates, end_date="2024-01-07")

    assert len(_bonus_rows(conn, "alice")) == 1


def test_record_streak_bonuses_returns_only_the_increments_actually_written(conn):
    add_puzzles(conn, 7)
    add_answers(conn, "alice", {n: True for n in range(1, 8)})
    candidates = compute_streak_bonus_candidates(db.get_leaderboard("2024-01"))

    first = db.record_streak_bonuses(candidates, end_date="2024-01-07")
    second = db.record_streak_bonuses(candidates, end_date="2024-01-07")

    assert first == {"alice": STREAK_BONUS[7]}
    assert second == {}


def test_record_streak_bonuses_credits_only_the_incremental_amount_within_one_run(conn):
    # Day 3: hits the 3-day milestone.
    add_puzzles(conn, 3)
    add_answers(conn, "alice", {1: True, 2: True, 3: True})
    board = db.get_leaderboard("2024-01")
    db.record_streak_bonuses(compute_streak_bonus_candidates(board), end_date="2024-01-03")
    assert _bonus_rows(conn, "alice") == [(3, "2024-01-01", "2024-01-03", STREAK_BONUS[3])]

    # Days 4-7: same unbroken streak reaches the 7-day milestone.
    for i in range(4, 8):
        conn.execute(
            "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, active, closed_at)"
            " VALUES (?, 'fen', '[]', 'random', ?, ?, 1, ?)",
            (
                f"p{i}", f"2024-01-{i:02d}T12:00:00+00:00", f"2024-01-{i:02d}T12:00:00+00:00",
                f"2024-01-{i + 1:02d}T06:00:00+00:00",
            ),
        )
    add_answers(conn, "alice", {4: True, 5: True, 6: True, 7: True})
    board = db.get_leaderboard("2024-01")
    db.record_streak_bonuses(compute_streak_bonus_candidates(board), end_date="2024-01-07")

    # A second, immutable row for just the newly-earned remainder (not the full
    # 7-day target again) -- so the two rows' total matches the 7-day target exactly,
    # and the first row (already possibly counted in a closed month) is untouched.
    assert _bonus_rows(conn, "alice") == [
        (3, "2024-01-01", "2024-01-03", STREAK_BONUS[3]),
        (7, "2024-01-01", "2024-01-07", STREAK_BONUS[7] - STREAK_BONUS[3]),
    ]
    assert sum(row[3] for row in _bonus_rows(conn, "alice")) == STREAK_BONUS[7]


def test_record_streak_bonuses_credits_the_highest_milestone_already_passed(conn):
    # alice's streak is already well past the 30-day milestone the first time this
    # runs (e.g. the day this feature ships), without ever having hit 30 exactly
    # while this code was live.
    add_puzzles(conn, 34)
    add_answers(conn, "alice", {n: True for n in range(1, 35)})
    board = db.get_leaderboard("2024-01")

    db.record_streak_bonuses(compute_streak_bonus_candidates(board), end_date="2024-02-03")

    assert _bonus_rows(conn, "alice") == [(30, "2024-01-01", "2024-02-03", STREAK_BONUS[30])]


def test_record_streak_bonuses_awards_again_after_a_streak_resets(conn):
    # Day 3: alice hits a 3-day streak and the cron awards it.
    add_puzzles(conn, 3)
    add_answers(conn, "alice", {1: True, 2: True, 3: True})
    first_board = db.get_leaderboard("2024-01")
    db.record_streak_bonuses(compute_streak_bonus_candidates(first_board), end_date="2024-01-03")

    # Days 4-7: the streak breaks on day 4, then rebuilds to another 3-day streak by day 7.
    for i in range(4, 8):
        conn.execute(
            "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, active, closed_at)"
            " VALUES (?, 'fen', '[]', 'random', ?, ?, 1, ?)",
            (
                f"p{i}", f"2024-01-{i:02d}T12:00:00+00:00", f"2024-01-{i:02d}T12:00:00+00:00",
                f"2024-01-{i + 1:02d}T06:00:00+00:00",
            ),
        )
    add_answers(conn, "alice", {4: False, 5: True, 6: True, 7: True})
    second_board = db.get_leaderboard("2024-01")
    db.record_streak_bonuses(compute_streak_bonus_candidates(second_board), end_date="2024-01-07")

    assert _bonus_rows(conn, "alice") == [
        (3, "2024-01-01", "2024-01-03", STREAK_BONUS[3]),
        (3, "2024-01-05", "2024-01-07", STREAK_BONUS[3]),
    ]


def test_streak_bonus_is_added_into_the_monthly_leaderboard_score(conn):
    add_puzzles(conn, 3)
    add_answers(conn, "alice", {1: True, 2: True, 3: True})
    board = db.get_leaderboard("2024-01")
    db.record_streak_bonuses(compute_streak_bonus_candidates(board), end_date="2024-01-03")

    entry = next(e for e in db.get_leaderboard("2024-01") if e["user_id"] == "alice")
    base_score = 10 * 3  # three correct, full marks, no podium bonus for a lone solver's first puzzles
    assert entry["score"] == base_score + STREAK_BONUS[3]


def test_a_later_crossing_does_not_inflate_an_already_closed_months_total(conn):
    # January: alice hits the 7-day milestone; that month's total gets computed (and,
    # in production, frozen into monthly_scores) while her bonus total for January is
    # exactly the 7-day target.
    add_puzzles(conn, 7)
    add_answers(conn, "alice", {n: True for n in range(1, 8)})
    board = db.get_leaderboard("2024-01")
    db.record_streak_bonuses(compute_streak_bonus_candidates(board), end_date="2024-01-07")

    january_bonus_total = next(
        row[1] for row in conn.execute(
            "SELECT user_id, SUM(bonus) FROM streak_bonuses WHERE substr(end_date, 1, 7) = '2024-01'"
            " GROUP BY user_id"
        ).fetchall() if row[0] == "alice"
    )
    assert january_bonus_total == STREAK_BONUS[7]

    # February: the same unbroken run reaches the 14-day milestone.
    for i in range(8, 15):
        conn.execute(
            "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, active, closed_at)"
            " VALUES (?, 'fen', '[]', 'random', ?, ?, 1, ?)",
            (
                f"p{i}", f"2024-02-{i - 7:02d}T12:00:00+00:00", f"2024-02-{i - 7:02d}T12:00:00+00:00",
                f"2024-02-{i - 6:02d}T06:00:00+00:00",
            ),
        )
    add_answers(conn, "alice", {n: True for n in range(8, 15)})
    board = db.get_leaderboard("2024-02")
    db.record_streak_bonuses(compute_streak_bonus_candidates(board), end_date="2024-02-14")

    # January's already-recorded total is untouched; only February gained the
    # incremental remainder, so the two months' totals don't double-count.
    rows = dict(conn.execute(
        "SELECT substr(end_date, 1, 7) AS month, SUM(bonus) FROM streak_bonuses"
        " WHERE user_id = 'alice' GROUP BY month"
    ).fetchall())
    assert rows == {"2024-01": STREAK_BONUS[7], "2024-02": STREAK_BONUS[14] - STREAK_BONUS[7]}
    assert sum(rows.values()) == STREAK_BONUS[14]


def test_leaderboard_post_includes_todays_just_earned_bonus_in_the_points_column(post_leaderboard_for_real):
    # Regression test: the posted leaderboard table's Points column must already
    # reflect today's bonus, not lag a day behind the milestone line announcing it.
    real_conn, post = post_leaderboard_for_real
    add_puzzles(real_conn, 7)
    add_answers(real_conn, "alice", {n: True for n in range(1, 8)})

    text = post()

    base_score = 10 * 7  # seven correct, flat score -- this raw-insert helper applies no podium bonus
    expected_points = base_score + STREAK_BONUS[7]
    row = next(line for line in text.splitlines() if "alice" in line)
    assert row.split()[3] == str(expected_points)
    # alice's very first cron run already finds her 7 days in (nothing credited
    # earlier for this run), so the real, actually-credited amount is the full
    # 7-day target, not the smaller "day 3 already credited separately" assumption.
    assert f"+{STREAK_BONUS[7]} bonus points" in text
