"""Queued (curated, not yet posted) puzzles share the puzzles table with posted ones.
Runs against a real in-memory sqlite3 connection, since what matters is that
queued rows stay out of every "posted puzzle" query."""

import sqlite3
from contextlib import contextmanager

import pytest

import db
import migrations
from constants import PuzzleState


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
    db._puzzle_cache.clear()


def test_queue_puzzle_rejects_a_duplicate(conn):
    assert db.queue_puzzle("q1", "fen", ["e4"]) is True
    assert db.queue_puzzle("q1", "fen", ["e4"]) is False


def test_queue_puzzle_rejects_an_already_posted_puzzle(conn):
    db.save_puzzle("p1", "fen", ["e4"])
    assert db.queue_puzzle("p1", "fen", ["e4"]) is False


def test_next_queued_puzzle_is_fifo_and_advances_once_posted(conn):
    assert db.get_next_queued_puzzle() is None
    db.queue_puzzle("q1", "fen1", ["e4"])
    db.queue_puzzle("q2", "fen2", ["d4"])

    assert db.get_next_queued_puzzle() == {"puzzle_id": "q1", "fen": "fen1", "solution": ["e4"]}
    # Not consumed until it's actually posted, so a failed run retries the same one.
    assert db.get_next_queued_puzzle()["puzzle_id"] == "q1"

    db.save_puzzle("q1", "fen1", ["e4"])
    assert db.get_next_queued_puzzle()["puzzle_id"] == "q2"


def test_deactivated_queued_puzzle_is_skipped(conn):
    db.queue_puzzle("q1", "fen1", ["e4"])
    db.queue_puzzle("q2", "fen2", ["d4"])
    db.deactivate_puzzle("q1")

    assert db.get_next_queued_puzzle()["puzzle_id"] == "q2"


def test_puzzle_day_is_the_utc_date_of_posted_at(conn, monkeypatch):
    monkeypatch.setattr(db, "_now", lambda: "2024-01-01T23:59:00+00:00")
    db.save_puzzle("p1", "fen", ["e4"])

    assert db.puzzle_sent_for_date("2024-01-01") is True
    assert db.puzzle_sent_for_date("2024-01-02") is False
    assert db.get_active_puzzle_by_date("2024-01-01")["puzzle_id"] == "p1"


def test_queued_puzzle_does_not_count_as_posted_for_the_day(conn, monkeypatch):
    monkeypatch.setattr(db, "_now", lambda: "2024-01-01T09:00:00+00:00")
    db.queue_puzzle("q1", "fen", ["e4"])
    assert db.puzzle_sent_for_date("2024-01-01") is False
    assert db.get_active_puzzle_by_date("2024-01-01") is None
    assert db.get_puzzle("q1") is None


def test_puzzle_queued_after_todays_post_does_not_shadow_it_for_submissions(conn):
    # A queued row has a newer rowid than today's posted puzzle, but hasn't been
    # posted - submissions for today's puzzle must still be accepted.
    db.save_puzzle("today", "fen", ["e4"])
    db.queue_puzzle("tomorrow", "fen", ["d4"])

    assert db.record_submission("today", "U1", "alice", "e4", True, 10) == db.SubmissionResult.RECORDED


def test_puzzle_queued_before_an_earlier_post_is_latest_once_posted(conn):
    # Queued first (older rowid) but posted after "random" - latest is by post
    # time, so submissions go to the queued puzzle once it's posted.
    db.queue_puzzle("queued", "fen", ["e4"])
    db.deactivate_puzzle("queued")
    db.save_puzzle("random", "fen", ["d4"])
    db.reactivate_puzzle("queued")
    db.save_puzzle("queued", "fen", ["e4"])

    assert db.record_submission("queued", "U1", "alice", "e4", True, 10) == db.SubmissionResult.RECORDED
    assert db.record_submission("random", "U2", "bob", "d4", True, 10) == db.SubmissionResult.STALE_PUZZLE


def test_list_puzzles_filters_by_state(conn):
    db.save_puzzle("posted1", "fen", ["e4"])
    db.queue_puzzle("queued1", "fen", ["d4"])

    assert [r["puzzle_id"] for r in db.list_puzzles()] == ["posted1", "queued1"]
    assert [r["puzzle_id"] for r in db.list_puzzles(PuzzleState.QUEUED)] == ["queued1"]
    assert [r["puzzle_id"] for r in db.list_puzzles(PuzzleState.POSTED)] == ["posted1"]


def test_migrations_keep_existing_puzzles_as_posted(monkeypatch):
    connection = sqlite3.connect(":memory:")
    all_migrations = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations[:6])
    migrations.run_migrations(connection)
    insert = "INSERT INTO puzzles (puzzle_id, date, fen, solution, slack_ts, active) VALUES (?, ?, ?, ?, ?, ?)"
    connection.execute(insert, ("posted", "2026-09-18", "fen", '["e4"]', "1789731057.798759", 0))
    connection.execute(insert, ("post_failed", "2026-09-19", "fen", '["d4"]', None, 1))

    monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations)
    migrations.run_migrations(connection)

    columns = [row[1] for row in connection.execute("PRAGMA table_info(puzzles)")]
    assert columns == ["puzzle_id", "fen", "solution", "source", "added_at", "posted_at", "slack_ts", "active"]

    rows = connection.execute("SELECT puzzle_id, fen, solution, source, added_at, posted_at, slack_ts, active FROM puzzles").fetchall()
    posted_at = "2026-09-18T11:30:57.799+00:00"
    assert rows == [
        ("posted", "fen", '["e4"]', "random", posted_at, posted_at, "1789731057.798759", 0),
        # No Slack post time to recover, so the bare date is the best available -
        # still a valid YYYY-MM-DD prefix for the puzzle-day lookup.
        ("post_failed", "fen", '["d4"]', "random", "2026-09-19", "2026-09-19", None, 1),
    ]
    connection.close()
