import sqlite3
from contextlib import contextmanager
from datetime import datetime

import pytest

import db
import migrations


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    migrations.run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def patch_db(conn, monkeypatch):
    @contextmanager
    def fake_get_connection():
        yield conn

    monkeypatch.setattr(db, "get_connection", fake_get_connection)


def post(conn, puzzle_id, day, active=True):
    posted_at = f"{day}T12:00:00+00:00"
    slack_ts = str(int(datetime.fromisoformat(posted_at).timestamp()))
    conn.execute(
        "INSERT INTO puzzles (puzzle_id, fen, solution, added_at, posted_at, slack_ts, active, closed_at)"
        " VALUES (?, 'fen', '[]', ?, ?, ?, ?, 'x')",
        (puzzle_id, posted_at, posted_at, slack_ts, int(active)),
    )
    return {"puzzle_id": puzzle_id, "posted_at": posted_at}


def answer(conn, user_id, puzzle_id, correct, submitted_at="2026-09-01T12:05:00+00:00", attempt=1, active=True):
    conn.execute(
        "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, attempt, submitted_at, active)"
        " VALUES (?, ?, ?, 'e4', ?, 0, ?, ?, ?)",
        (puzzle_id, user_id, user_id.lower(), int(correct), attempt, submitted_at, int(active)),
    )


def broken(conn, puzzle, min_streak=3):
    return [(r["user_id"], r["streak"]) for r in db.get_reveal_data(puzzle, min_streak)["broken_streaks"]]


@pytest.fixture
def days(conn):
    return [post(conn, f"d{day}", f"2026-09-{day:02d}") for day in range(1, 6)]


def solve(conn, user_id, puzzles):
    for puzzle in puzzles:
        answer(conn, user_id, puzzle["puzzle_id"], True, submitted_at=puzzle["posted_at"])


def test_wrong_and_missed_both_break_a_streak(conn, days):
    solve(conn, "WRONG", days[:4])
    answer(conn, "WRONG", "d5", False)
    answer(conn, "WRONG", "d5", False, attempt=2)
    solve(conn, "MISSED", days[1:4])
    assert broken(conn, days[4]) == [("WRONG", 4), ("MISSED", 3)]


def test_solving_keeps_the_streak(conn, days):
    solve(conn, "U1", days)
    assert broken(conn, days[4]) == []


def test_a_wrong_first_attempt_then_solve_keeps_the_streak(conn, days):
    solve(conn, "U1", days[:4])
    answer(conn, "U1", "d5", False)
    answer(conn, "U1", "d5", True, attempt=2)
    assert broken(conn, days[4]) == []


def test_short_or_already_broken_streaks_are_not_counted(conn, days):
    solve(conn, "SHORT", days[2:4])
    solve(conn, "OLD", days[:3])
    assert broken(conn, days[4]) == []


def test_deactivated_puzzles_are_skipped_in_the_run(conn, days):
    conn.execute("UPDATE puzzles SET active = 0 WHERE puzzle_id = 'd4'")
    solve(conn, "U1", days[:3])
    assert broken(conn, days[4]) == [("U1", 3)]


def test_later_puzzles_do_not_affect_an_earlier_reveal(conn, days):
    solve(conn, "U1", days[:3])
    assert broken(conn, days[3]) == [("U1", 3)]


def test_earlier_first_solves_are_this_months_earlier_puzzles_only(conn, days):
    aug = post(conn, "aug", "2026-08-31")
    answer(conn, "U1", "aug", True, submitted_at="2026-08-31T12:00:01+00:00")
    answer(conn, "U1", "d1", True, submitted_at="2026-09-01T12:09:00+00:00")
    answer(conn, "U2", "d1", True, submitted_at="2026-09-01T12:03:00+00:00")
    answer(conn, "U3", "d1", False, submitted_at="2026-09-01T12:01:00+00:00")
    answer(conn, "U4", "d1", True, submitted_at="2026-09-01T12:00:30+00:00", active=False)
    answer(conn, "U1", "d2", True, submitted_at="2026-09-02T12:07:00+00:00")
    answer(conn, "U1", "d3", True, submitted_at="2026-09-03T12:00:01+00:00")
    conn.execute("UPDATE puzzles SET active = 0 WHERE puzzle_id = 'd2'")

    rows = db.get_reveal_data(days[2], 3)["earlier_first_solves"]

    assert [r["first_solved_at"] for r in rows] == ["2026-09-01T12:03:00+00:00"]
    assert db.get_reveal_data(aug, 3)["earlier_first_solves"] == []
