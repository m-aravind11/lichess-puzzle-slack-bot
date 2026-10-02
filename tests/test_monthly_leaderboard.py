import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
import migrations
from constants import Security
from slack_helpers import format_all_time_leaderboard_post, format_leaderboard
from standings import build_all_time_standings, build_standings

AUTH = {"Authorization": "Bearer s3cr3t"}


@pytest.fixture
def conn():
    # TestClient runs the async handlers on a worker thread.
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    migrations.run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def patch_db(conn, monkeypatch):
    @contextmanager
    def fake_get_connection():
        yield conn
        conn.commit()

    monkeypatch.setattr(db, "get_connection", fake_get_connection)


@pytest.fixture
def now(monkeypatch):
    def set_month(month):
        monkeypatch.setattr(db, "_utc_month", lambda: month)
    set_month("2026-10")
    return set_month


def post(conn, puzzle_id, day, open_=False, active=True):
    """Posts a puzzle at noon UTC on day (YYYY-MM-DD), closed unless open_."""
    posted_at = f"{day}T12:00:00+00:00"
    conn.execute(
        "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, active, closed_at)"
        " VALUES (?, 'fen', '[]', 'random', ?, ?, ?, ?)",
        (puzzle_id, posted_at, posted_at, int(active), None if open_ else "x"),
    )


def answer(conn, user_id, puzzle_id, score, submitted_at="2026-09-01T12:05:00+00:00", active=True):
    conn.execute(
        "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)"
        " VALUES (?, ?, ?, 'e4', ?, ?, ?, ?)",
        (puzzle_id, user_id, user_id.lower(), int(score > 0), score, submitted_at, int(active)),
    )


def points(month):
    return {e["user_id"]: e["score"] for e in db.get_leaderboard(month)}


def stored(conn):
    return conn.execute(
        "SELECT month, user_id, points, correct, attempted FROM monthly_scores ORDER BY month, user_id"
    ).fetchall()


def test_board_only_counts_puzzles_posted_in_the_month(conn):
    post(conn, "aug", "2026-08-31")
    post(conn, "sep1", "2026-09-01")
    post(conn, "sep2", "2026-09-15")
    answer(conn, "U1", "aug", 10)
    answer(conn, "U1", "sep1", 9)
    answer(conn, "U1", "sep2", 8)
    answer(conn, "U2", "aug", 7)

    assert points("2026-09") == {"U1": 17}
    assert points("2026-08") == {"U1": 10, "U2": 7}


def test_last_days_puzzle_answered_on_the_1st_counts_for_its_own_month(conn):
    post(conn, "sep30", "2026-09-30")
    answer(conn, "U1", "sep30", 6, submitted_at="2026-10-01T02:00:00+00:00")
    assert points("2026-09") == {"U1": 6}
    assert points("2026-10") == {}


def test_attempts_and_correct_are_monthly_too(conn):
    post(conn, "aug", "2026-08-31")
    post(conn, "sep", "2026-09-01")
    answer(conn, "U1", "aug", 10)
    answer(conn, "U1", "sep", 0)
    [entry] = db.get_leaderboard("2026-09")
    assert (entry["attempted"], entry["correct"], entry["incorrect"]) == (1, 0, 1)
    assert entry["avg_solve_seconds"] is None


def test_streaks_carry_across_months(conn):
    post(conn, "aug", "2026-08-31")
    post(conn, "sep", "2026-09-01")
    answer(conn, "U1", "aug", 10)
    answer(conn, "U1", "sep", 10)
    [entry] = db.get_leaderboard("2026-09")
    assert (entry["current_streak"], entry["best_streak"]) == (2, 2)


def test_no_month_before_anything_is_posted(conn, now):
    assert db.get_leaderboard_month() is None


def test_board_shows_the_latest_puzzles_month(conn, now):
    now("2026-09")
    post(conn, "aug", "2026-08-31")
    post(conn, "sep", "2026-09-01", open_=True)
    assert db.get_leaderboard_month() == {"month": "2026-09", "final": False}


def test_month_in_progress_is_not_final_even_with_its_latest_puzzle_closed(conn, now):
    now("2026-09")
    post(conn, "sep", "2026-09-01")
    assert db.get_leaderboard_month() == {"month": "2026-09", "final": False}


def test_on_the_1st_after_the_reveal_the_month_just_ended_is_final(conn, now):
    now("2026-10")
    post(conn, "sep30", "2026-09-30")
    assert db.get_leaderboard_month() == {"month": "2026-09", "final": True}


def test_ended_month_is_not_final_while_its_last_puzzle_is_open(conn, now):
    now("2026-10")
    post(conn, "sep30", "2026-09-30", open_=True)
    assert db.get_leaderboard_month() == {"month": "2026-09", "final": False}


def test_deactivated_latest_puzzle_does_not_pick_the_month(conn, now):
    post(conn, "sep30", "2026-09-30")
    post(conn, "oct1", "2026-10-01", active=False)
    assert db.get_leaderboard_month()["month"] == "2026-09"


def test_finished_months_are_stored_per_player(conn, now):
    now("2026-10")
    post(conn, "aug", "2026-08-31")
    post(conn, "sep1", "2026-09-01")
    post(conn, "sep2", "2026-09-02")
    answer(conn, "U1", "aug", 10)
    answer(conn, "U1", "sep1", 9)
    answer(conn, "U1", "sep2", 0)
    answer(conn, "U2", "sep1", 5)

    db.store_finished_months()
    assert stored(conn) == [
        ("2026-08", "U1", 10, 1, 1),
        ("2026-09", "U1", 9, 1, 2),
        ("2026-09", "U2", 5, 1, 1),
    ]


def test_month_in_progress_is_not_stored(conn, now):
    now("2026-09")
    post(conn, "aug", "2026-08-31")
    post(conn, "sep", "2026-09-01")
    answer(conn, "U1", "aug", 10)
    answer(conn, "U1", "sep", 9)

    db.store_finished_months()
    assert stored(conn) == [("2026-08", "U1", 10, 1, 1)]


def test_ended_month_waits_for_its_last_puzzle_to_close(conn, now):
    now("2026-10")
    post(conn, "sep30", "2026-09-30", open_=True)
    answer(conn, "U1", "sep30", 10)

    db.store_finished_months()
    assert stored(conn) == []

    conn.execute("UPDATE puzzles SET closed_at = 'x' WHERE puzzle_id = 'sep30'")
    db.store_finished_months()
    assert stored(conn) == [("2026-09", "U1", 10, 1, 1)]


def test_storing_again_is_a_no_op(conn, now):
    post(conn, "sep", "2026-09-01")
    answer(conn, "U1", "sep", 10)
    db.store_finished_months()
    db.store_finished_months()
    assert stored(conn) == [("2026-09", "U1", 10, 1, 1)]


def test_stored_month_is_not_rewritten_by_later_changes(conn, now):
    post(conn, "sep", "2026-09-01")
    answer(conn, "U1", "sep", 10)
    db.store_finished_months()

    conn.execute("UPDATE submissions SET active = 0")
    answer(conn, "U2", "sep", 4)
    db.store_finished_months()
    assert stored(conn) == [("2026-09", "U1", 10, 1, 1)]


def test_deactivated_submissions_are_not_stored(conn, now):
    post(conn, "sep", "2026-09-01")
    answer(conn, "U1", "sep", 10, active=False)
    answer(conn, "U2", "sep", 5)
    db.store_finished_months()
    assert stored(conn) == [("2026-09", "U2", 5, 1, 1)]


def all_time():
    return [(e["user_id"], e["score"], e["correct"], e["attempted"], e["months"]) for e in db.get_all_time_leaderboard()]


def test_all_time_adds_up_stored_months_but_not_the_one_in_progress(conn, now):
    now("2026-10")
    for puzzle_id, day in (("aug", "2026-08-31"), ("sep", "2026-09-01"), ("oct", "2026-10-01")):
        post(conn, puzzle_id, day)
    answer(conn, "U1", "aug", 10)
    answer(conn, "U1", "sep", 9)
    answer(conn, "U1", "oct", 8)
    answer(conn, "U2", "sep", 0)
    answer(conn, "U3", "oct", 3)
    db.store_finished_months()

    assert all_time() == [("U1", 19, 2, 2, 2), ("U2", 0, 0, 1, 1)]


def test_all_time_ties_are_broken_by_more_correct_then_name(conn, now):
    for puzzle_id, day in (("aug", "2026-08-30"), ("aug2", "2026-08-31")):
        post(conn, puzzle_id, day)
    answer(conn, "BOB", "aug", 10)
    answer(conn, "ALICE", "aug", 10)
    answer(conn, "CAROL", "aug", 5)
    answer(conn, "CAROL", "aug2", 5)
    db.store_finished_months()

    assert [row[0] for row in all_time()] == ["CAROL", "ALICE", "BOB"]


def test_all_time_uses_the_latest_months_name(conn, now):
    post(conn, "aug", "2026-08-31")
    post(conn, "sep", "2026-09-01")
    conn.execute(
        "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)"
        " VALUES ('aug', 'U1', 'old', 'e4', 1, 10, 'x', 1), ('sep', 'U1', 'new', 'e4', 1, 10, 'x', 1)"
    )
    db.store_finished_months()
    assert db.get_all_time_leaderboard()[0]["user_name"] == "new"


def test_all_time_is_empty_before_any_month_is_stored(conn, now):
    assert db.get_all_time_leaderboard() == []


def test_slack_title_names_the_month():
    entry = {
        "user_id": "U1", "user_name": "u1", "score": 10, "correct": 1, "attempted": 1,
        "avg_solve_seconds": 60, "current_streak": 1, "best_streak": 1, "house_name": None,
    }
    assert format_leaderboard(build_standings([entry], "2026-09")).startswith("*Leaderboard - September 2026*")
    assert format_leaderboard(build_standings([entry], "2026-09", final=True)).startswith("*Final standings - September 2026*")


@pytest.fixture
def send(conn, monkeypatch):
    monkeypatch.setattr(Security, "CRON_SECRET", "s3cr3t")
    monkeypatch.setattr(db, "is_holiday", lambda date: False)
    client = TestClient(app_module.app)

    def run():
        post_message = MagicMock()
        monkeypatch.setattr(app_module.slack_client, "chat_postMessage", post_message)
        assert client.post("/admin/leaderboard:send", headers=AUTH).status_code == 200
        return [c.kwargs["text"] for c in post_message.call_args_list]

    return run


def test_month_rollover_end_to_end(conn, now, send):
    now("2026-09")
    post(conn, "aug", "2026-08-31")
    post(conn, "sep29", "2026-09-29")
    post(conn, "sep30", "2026-09-30", open_=True)
    answer(conn, "U2", "aug", 5)
    answer(conn, "U1", "sep29", 10)
    answer(conn, "U1", "sep30", 9)
    answer(conn, "U2", "sep29", 4)
    aug, aug_all_time, text = send()
    assert aug.startswith("*Final standings - August 2026*")
    assert aug_all_time.startswith("*All-time standings - through August 2026*")
    assert text.startswith("*Leaderboard - September 2026*")

    # Oct 1: the reveal has closed Sep 30's puzzle.
    now("2026-10")
    conn.execute("UPDATE puzzles SET closed_at = 'x' WHERE puzzle_id = 'sep30'")
    monthly, all_time_text = send()
    assert monthly.startswith("*Final standings - September 2026*")
    assert all_time_text.startswith("*All-time standings - through September 2026*")
    assert stored(conn) == [("2026-08", "U2", 5, 1, 1), ("2026-09", "U1", 19, 2, 2), ("2026-09", "U2", 4, 1, 1)]
    assert all_time() == [("U1", 19, 2, 2, 1), ("U2", 9, 2, 2, 2)]

    # Oct 2
    post(conn, "oct1", "2026-10-01")
    answer(conn, "U2", "oct1", 7)
    [text] = send()
    assert text.startswith("*Leaderboard - October 2026*")
    assert {e["user_id"]: e["score"] for e in db.get_leaderboard("2026-10")} == {"U2": 7}


def test_month_nobody_answered_posts_nothing_not_even_all_time(conn, now, send):
    post(conn, "aug", "2026-08-31")
    answer(conn, "U1", "aug", 10)
    db.store_finished_months()
    db.mark_months_announced(["2026-08"])
    post(conn, "sep30", "2026-09-30")
    assert send() == []
    assert stored(conn) == [("2026-08", "U1", 10, 1, 1)]


def test_missed_run_on_the_1st_posts_the_final_standings_on_the_next_run(conn, now, send):
    post(conn, "sep30", "2026-09-30")
    answer(conn, "U1", "sep30", 10)
    post(conn, "oct1", "2026-10-01", open_=True)
    answer(conn, "U1", "oct1", 7)

    monthly, all_time_text, text = send()
    assert monthly.startswith("*Final standings - September 2026*")
    assert all_time_text.startswith("*All-time standings - through September 2026*")
    assert text.startswith("*Leaderboard - October 2026*")


def test_announced_month_is_not_posted_again(conn, now, send):
    post(conn, "sep30", "2026-09-30")
    answer(conn, "U1", "sep30", 10)
    assert len(send()) == 2
    assert send() == []


def test_final_standings_have_no_streaks(conn, now, send):
    post(conn, "sep30", "2026-09-30")
    answer(conn, "U1", "sep30", 10)
    monthly, _ = send()
    assert monthly.split("\n")[4].split()[-1] == "-"


def test_holiday_on_the_1st_delays_both_posts_to_the_next_run(conn, now, send, monkeypatch):
    post(conn, "sep30", "2026-09-30")
    answer(conn, "U1", "sep30", 10)

    monkeypatch.setattr(db, "is_holiday", lambda date: True)
    assert send() == []
    assert stored(conn) == [("2026-09", "U1", 10, 1, 1)]

    monkeypatch.setattr(db, "is_holiday", lambda date: False)
    monthly, all_time_text = send()
    assert monthly.startswith("*Final standings - September 2026*")
    assert all_time_text.startswith("*All-time standings - through September 2026*")
    assert stored(conn) == [("2026-09", "U1", 10, 1, 1)]


def test_stored_month_keeps_the_final_ranking_and_solve_times(conn, now):
    post(conn, "sep", "2026-09-01")
    conn.execute("UPDATE puzzles SET slack_ts = '1788264000'")  # 2026-09-01T12:00:00Z
    answer(conn, "U1", "sep", 10, submitted_at="2026-09-01T12:05:00+00:00")
    answer(conn, "U2", "sep", 10, submitted_at="2026-09-01T12:01:00+00:00")
    db.store_finished_months()

    assert conn.execute(
        "SELECT user_id, rank, avg_solve_seconds FROM monthly_scores ORDER BY rank"
    ).fetchall() == [("U2", 1, 60.0), ("U1", 2, 300.0)]
    assert [e["user_id"] for e in db.get_stored_leaderboard("2026-09")] == ["U2", "U1"]


def test_stored_board_is_only_its_month_with_no_streaks(conn, now):
    for puzzle_id, day in (("aug", "2026-08-31"), ("sep", "2026-09-01")):
        post(conn, puzzle_id, day)
    answer(conn, "U1", "aug", 10)
    answer(conn, "U1", "sep", 9)
    db.store_finished_months()

    [entry] = db.get_stored_leaderboard("2026-09")
    assert (entry["score"], entry["correct"], entry["attempted"]) == (9, 1, 1)
    assert (entry["current_streak"], entry["best_streak"]) == (None, None)


def test_unstored_month_has_no_stored_board(conn, now):
    assert db.get_stored_leaderboard("2026-09") is None


@pytest.fixture
def web(conn, monkeypatch):
    monkeypatch.setattr(Security, "ADMIN_SECRET", "s3cr3t")
    client = TestClient(app_module.app)
    return lambda path: client.get(path, headers=AUTH)


def test_web_lists_stored_months_and_the_latest_newest_first(conn, now, web):
    for puzzle_id, day in (("aug", "2026-08-31"), ("sep", "2026-09-01"), ("oct", "2026-10-01")):
        post(conn, puzzle_id, day)
    answer(conn, "U1", "aug", 10)
    answer(conn, "U1", "sep", 9)
    db.store_finished_months()

    data = web("/admin/leaderboard").json()
    assert (data["month"], data["stored"], data["months"]) == ("2026-10", False, ["2026-10", "2026-09", "2026-08"])


def test_web_shows_a_stored_month(conn, now, web):
    post(conn, "aug", "2026-08-31")
    post(conn, "sep", "2026-09-01")
    answer(conn, "U1", "aug", 10)
    answer(conn, "U2", "aug", 4)
    answer(conn, "U1", "sep", 9)
    db.store_finished_months()

    data = web("/admin/leaderboard?month=2026-08").json()
    assert (data["month"], data["final"], data["stored"]) == ("2026-08", True, True)
    assert [(p["rank"], p["userName"], p["points"], p["currentStreak"]) for p in data["players"]] == [
        (1, "u1", 10, None), (2, "u2", 4, None),
    ]
    assert data["milestones"] == []


def test_web_asking_for_the_latest_month_by_name_gets_the_live_board(conn, now, web):
    post(conn, "sep", "2026-09-01")
    answer(conn, "U1", "sep", 10)
    db.store_finished_months()
    data = web("/admin/leaderboard?month=2026-09").json()
    assert data["stored"] is False
    assert data["players"][0]["currentStreak"] == 1


def test_web_unstored_month_is_404(conn, now, web):
    post(conn, "sep", "2026-09-01")
    assert web("/admin/leaderboard?month=2026-05").status_code == 404


@pytest.mark.parametrize("month", ["2026", "Sept", "2026-13", "2026-09-01"])
def test_web_bad_month_is_400(conn, now, web, month):
    post(conn, "sep", "2026-09-01")
    assert web(f"/admin/leaderboard?month={month}").status_code == 400


def test_web_all_time(conn, now, web):
    for puzzle_id, day in (("aug", "2026-08-31"), ("sep", "2026-09-01"), ("oct", "2026-10-01")):
        post(conn, puzzle_id, day)
    answer(conn, "U1", "aug", 10)
    answer(conn, "U1", "sep", 9)
    answer(conn, "U2", "sep", 4)
    answer(conn, "U2", "oct", 10)
    conn.execute("INSERT INTO houses (name) VALUES ('Gryffindor')")
    conn.execute("INSERT INTO player_houses (user_id, house_id, assigned_at) VALUES ('U2', 1, 'x')")
    db.store_finished_months()

    assert web("/admin/leaderboard/allTime").json() == {
        "through": "2026-09",
        "months": ["2026-10", "2026-09", "2026-08"],
        "players": [
            {"rank": 1, "userName": "u1", "house": None, "points": 19, "correct": 2, "attempted": 2, "months": 2},
            {"rank": 2, "userName": "u2", "house": "Gryffindor", "points": 4, "correct": 1, "attempted": 1, "months": 1},
        ],
        "houses": [{"rank": 1, "name": "Gryffindor", "points": 4, "correct": 1, "players": 1}],
    }


def test_web_all_time_before_any_month_is_stored(conn, now, web):
    assert web("/admin/leaderboard/allTime").json() == {"through": None, "months": [], "players": [], "houses": []}


def test_slack_all_time_post():
    board = [
        {"user_id": "U1", "user_name": "u1", "house_name": "Gryffindor", "score": 19, "correct": 2, "attempted": 3, "months": 2},
        {"user_id": "U2", "user_name": None, "house_name": None, "score": 4, "correct": 1, "attempted": 1, "months": 1},
    ]
    text = format_all_time_leaderboard_post(build_all_time_standings(board, "2026-09"))
    lines = text.splitlines()
    assert lines[0].startswith("*All-time standings - through September 2026*")
    assert lines[2].split() == ["#", "Name", "House", "Points", "Solved", "Months"]
    assert lines[4].split() == ["1", "u1", "Gryffindor", "19", "2/3", "2"]
    assert lines[5].split() == ["2", "U2", "-", "4", "1/1", "1"]
    assert "*House standings* _(sum of each house's players' points all-time)_" in text


def test_finished_month_is_stored_even_on_a_holiday(conn, now, send, monkeypatch):
    monkeypatch.setattr(db, "is_holiday", lambda date: True)
    post(conn, "sep", "2026-09-30")
    answer(conn, "U1", "sep", 10)
    assert send() == []
    assert stored(conn) == [("2026-09", "U1", 10, 1, 1)]
