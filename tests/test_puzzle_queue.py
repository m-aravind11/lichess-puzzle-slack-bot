"""Queued (curated, not yet sent) puzzles share the puzzles table with sent ones.
Runs against a real in-memory sqlite3 connection, since what matters is that
queued rows stay out of every "sent puzzle" query."""

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


def test_queue_puzzle_rejects_an_already_sent_puzzle(conn):
    db.save_puzzle("p1", "2024-01-01", "fen", ["e4"])
    assert db.queue_puzzle("p1", "fen", ["e4"]) is False


def test_next_queued_puzzle_is_fifo_and_advances_once_sent(conn):
    assert db.get_next_queued_puzzle() is None
    db.queue_puzzle("q1", "fen1", ["e4"])
    db.queue_puzzle("q2", "fen2", ["d4"])

    assert db.get_next_queued_puzzle() == {"puzzle_id": "q1", "fen": "fen1", "solution": ["e4"]}
    # Not consumed until it's actually sent, so a failed run retries the same one.
    assert db.get_next_queued_puzzle()["puzzle_id"] == "q1"

    db.save_puzzle("q1", "2024-01-01", "fen1", ["e4"])
    assert db.get_next_queued_puzzle()["puzzle_id"] == "q2"


def test_deactivated_queued_puzzle_is_skipped(conn):
    db.queue_puzzle("q1", "fen1", ["e4"])
    db.queue_puzzle("q2", "fen2", ["d4"])
    db.deactivate_puzzle("q1")

    assert db.get_next_queued_puzzle()["puzzle_id"] == "q2"


def test_queued_puzzle_does_not_count_as_sent_for_the_day(conn):
    db.queue_puzzle("q1", "fen", ["e4"])
    assert db.puzzle_sent_for_date("2024-01-01") is False
    assert db.get_active_puzzle_by_date("2024-01-01") is None
    assert db.get_puzzle("q1") is None


def test_puzzle_queued_after_todays_post_does_not_shadow_it_for_submissions(conn):
    # A queued row has a newer rowid than today's sent puzzle, but hasn't been
    # posted - submissions for today's puzzle must still be accepted.
    db.save_puzzle("today", "2024-01-01", "fen", ["e4"])
    db.queue_puzzle("tomorrow", "fen", ["d4"])

    assert db.record_submission("today", "U1", "alice", "e4", True, 10) == db.SubmissionResult.RECORDED


def test_puzzle_queued_before_an_earlier_send_is_latest_once_sent(conn):
    # Queued first (older rowid) but sent after "random" - latest is by send
    # time, so submissions go to the queued puzzle once it's posted.
    db.queue_puzzle("queued", "fen", ["e4"])
    db.deactivate_puzzle("queued")
    db.save_puzzle("random", "2024-01-01", "fen", ["d4"])
    db.reactivate_puzzle("queued")
    db.save_puzzle("queued", "2024-01-02", "fen", ["e4"])

    assert db.record_submission("queued", "U1", "alice", "e4", True, 10) == db.SubmissionResult.RECORDED
    assert db.record_submission("random", "U2", "bob", "d4", True, 10) == db.SubmissionResult.STALE_PUZZLE


def test_list_puzzles_filters_by_state(conn):
    db.save_puzzle("sent1", "2024-01-01", "fen", ["e4"])
    db.queue_puzzle("queued1", "fen", ["d4"])

    assert [r["puzzle_id"] for r in db.list_puzzles()] == ["sent1", "queued1"]
    assert [r["puzzle_id"] for r in db.list_puzzles(PuzzleState.QUEUED)] == ["queued1"]
    assert [r["puzzle_id"] for r in db.list_puzzles(PuzzleState.SENT)] == ["sent1"]


def test_migration_keeps_existing_puzzles_as_sent(monkeypatch):
    connection = sqlite3.connect(":memory:")
    all_migrations = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations[:6])
    migrations.run_migrations(connection)
    connection.execute(
        "INSERT INTO puzzles (puzzle_id, date, fen, solution, slack_ts, active) VALUES (?, ?, ?, ?, ?, ?)",
        ("old", "2024-01-01", "fen", '["e4"]', "1.0", 0),
    )

    monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations)
    migrations.run_migrations(connection)

    row = connection.execute(
        "SELECT puzzle_id, fen, solution, source, created_at, sent_on, sent_at, slack_ts, active FROM puzzles",
    ).fetchall()
    assert row == [("old", "fen", '["e4"]', "random", "2024-01-01", "2024-01-01", "2024-01-01", "1.0", 0)]
    connection.close()
