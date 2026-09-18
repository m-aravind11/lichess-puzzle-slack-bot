"""Runs against a real in-memory sqlite3 connection - save_puzzle's behaviour
lives in UPSERT_SENT's SQL (insert, mark a queued row sent, or no-op), which a
mocked cursor can't exercise."""

import sqlite3
from contextlib import contextmanager

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
def patch_connection(conn, monkeypatch):
    @contextmanager
    def fake_get_connection():
        yield conn
        conn.commit()

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    db._puzzle_cache.clear()


def _row(conn, puzzle_id):
    cur = conn.execute(
        "SELECT source, sent_on, sent_at, slack_ts, active FROM puzzles WHERE puzzle_id = ?", (puzzle_id,),
    )
    return cur.fetchone()


def test_new_puzzle_is_inserted_as_sent(conn):
    db.save_puzzle("p1", "2024-01-01", "fen", ["e4"], slack_ts="1.0")
    source, sent_on, sent_at, slack_ts, active = _row(conn, "p1")
    assert (source, sent_on, slack_ts, active) == ("random", "2024-01-01", "1.0", 1)
    assert sent_at is not None


def test_resend_of_an_already_sent_puzzle_is_a_no_op(conn):
    db.save_puzzle("p1", "2024-01-01", "fen", ["e4"], slack_ts="1.0")
    original = _row(conn, "p1")

    db.save_puzzle("p1", "2024-01-02", "fen", ["e4"], slack_ts="2.0")

    assert _row(conn, "p1") == original


def test_resend_of_a_deactivated_puzzle_does_not_raise_or_reactivate(conn):
    db.save_puzzle("p1", "2024-01-01", "fen", ["e4"])
    conn.execute("UPDATE puzzles SET active = 0 WHERE puzzle_id = 'p1'")

    db.save_puzzle("p1", "2024-01-02", "fen", ["e4"])

    _, sent_on, _, _, active = _row(conn, "p1")
    assert (sent_on, active) == ("2024-01-01", 0)


def test_sending_a_queued_puzzle_marks_it_sent(conn):
    db.queue_puzzle("q1", "fen", ["e4"])

    db.save_puzzle("q1", "2024-01-01", "fen", ["e4"], slack_ts="1.0")

    source, sent_on, sent_at, slack_ts, active = _row(conn, "q1")
    assert (source, sent_on, slack_ts, active) == ("curated", "2024-01-01", "1.0", 1)
    assert sent_at is not None
