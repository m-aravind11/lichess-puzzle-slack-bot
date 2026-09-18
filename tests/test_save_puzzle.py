"""Runs against a real in-memory sqlite3 connection - save_puzzle's behaviour
lives in UPSERT_POSTED's SQL (insert, mark a queued row posted, or no-op), which
a mocked cursor can't exercise."""

import sqlite3
from contextlib import contextmanager

import pytest

import db
import migrations

FIRST_POST = "2024-01-01T09:00:00+00:00"
LATER_POST = "2024-01-02T09:00:00+00:00"


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
    monkeypatch.setattr(db, "_now", lambda: FIRST_POST)
    db._puzzle_cache.clear()


def _row(conn, puzzle_id):
    return conn.execute(
        "SELECT source, added_at, posted_at, slack_ts, active FROM puzzles WHERE puzzle_id = ?", (puzzle_id,),
    ).fetchone()


def test_new_puzzle_is_inserted_as_posted(conn):
    db.save_puzzle("p1", "fen", ["e4"], slack_ts="1.0")
    assert _row(conn, "p1") == ("random", FIRST_POST, FIRST_POST, "1.0", 1)


def test_resend_of_an_already_posted_puzzle_is_a_no_op(conn, monkeypatch):
    db.save_puzzle("p1", "fen", ["e4"], slack_ts="1.0")
    monkeypatch.setattr(db, "_now", lambda: LATER_POST)

    db.save_puzzle("p1", "fen", ["e4"], slack_ts="2.0")

    assert _row(conn, "p1") == ("random", FIRST_POST, FIRST_POST, "1.0", 1)


def test_resend_of_a_deactivated_puzzle_does_not_raise_or_reactivate(conn, monkeypatch):
    db.save_puzzle("p1", "fen", ["e4"])
    conn.execute("UPDATE puzzles SET active = 0 WHERE puzzle_id = 'p1'")
    monkeypatch.setattr(db, "_now", lambda: LATER_POST)

    db.save_puzzle("p1", "fen", ["e4"])

    _, _, posted_at, _, active = _row(conn, "p1")
    assert (posted_at, active) == (FIRST_POST, 0)


def test_posting_a_queued_puzzle_marks_it_posted(conn, monkeypatch):
    db.queue_puzzle("q1", "fen", ["e4"])
    monkeypatch.setattr(db, "_now", lambda: LATER_POST)

    db.save_puzzle("q1", "fen", ["e4"], slack_ts="1.0")

    assert _row(conn, "q1") == ("curated", FIRST_POST, LATER_POST, "1.0", 1)
