"""record_submission's INSERT_IF_OPEN gates on the puzzle row itself (active,
posted, not closed) - no "latest puzzle" concept. Runs against a real in-memory
sqlite3 connection since the gating lives in the SQL (see queries.SubmissionQueries
.INSERT_IF_OPEN), not in Python that a mock could stand in for."""

import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
import turso_serverless

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


def test_open_puzzle_accepts_a_submission(conn):
    db.save_puzzle("p1", "fen", ["e4"])
    assert db.record_submission("p1", "U1", "alice", "e4", True, 10) == db.SubmissionResult.RECORDED


def test_duplicate_submission_is_rejected(monkeypatch):
    # sqlite3's own IntegrityError isn't turso_serverless.IntegrityError, so this
    # is mocked rather than run against the real in-memory connection like the
    # rest of this file.
    cur = MagicMock()
    cur.execute.side_effect = turso_serverless.IntegrityError("duplicate")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = cur

    @contextmanager
    def fake_get_connection():
        yield mock_conn

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    assert db.record_submission("p1", "U1", "alice", "e4", True, 10) == db.SubmissionResult.DUPLICATE


def test_closing_the_puzzle_rejects_further_submissions(conn, monkeypatch):
    monkeypatch.setattr(db, "_now", lambda: "2024-01-01T20:00:00+00:00")
    db.save_puzzle("p1", "fen", ["e4"])

    closed = db.close_active_puzzle("2024-01-01")
    assert closed["puzzle_id"] == "p1"
    assert db.record_submission("p1", "U1", "alice", "e4", True, 10) == db.SubmissionResult.PUZZLE_CLOSED


def test_closing_a_date_with_no_active_puzzle_is_a_no_op(conn):
    assert db.close_active_puzzle("2024-01-01") is None


def test_closing_for_the_wrong_date_leaves_the_puzzle_open(conn, monkeypatch):
    monkeypatch.setattr(db, "_now", lambda: "2024-01-01T20:00:00+00:00")
    db.save_puzzle("p1", "fen", ["e4"])

    assert db.close_active_puzzle("2024-01-02") is None
    assert db.record_submission("p1", "U1", "alice", "e4", True, 10) == db.SubmissionResult.RECORDED


def test_reclosing_an_already_closed_puzzle_is_a_no_op(conn, monkeypatch):
    monkeypatch.setattr(db, "_now", lambda: "2024-01-01T20:00:00+00:00")
    db.save_puzzle("p1", "fen", ["e4"])

    assert db.close_active_puzzle("2024-01-01")["puzzle_id"] == "p1"
    assert db.close_active_puzzle("2024-01-01") is None


def test_a_deactivated_puzzle_rejects_submissions_even_if_never_closed(conn):
    db.save_puzzle("p1", "fen", ["e4"])
    assert db.deactivate_puzzle("p1") == db.PuzzleResult.DEACTIVATED
    assert db.record_submission("p1", "U1", "alice", "e4", True, 10) == db.SubmissionResult.PUZZLE_CLOSED


def test_closing_one_days_puzzle_does_not_affect_another_days(conn, monkeypatch):
    monkeypatch.setattr(db, "_now", lambda: "2024-01-01T20:00:00+00:00")
    db.save_puzzle("p1", "fen", ["e4"])
    monkeypatch.setattr(db, "_now", lambda: "2024-01-02T20:00:00+00:00")
    db.save_puzzle("p2", "fen", ["d4"])

    db.close_active_puzzle("2024-01-01")

    assert db.record_submission("p1", "U1", "alice", "e4", True, 10) == db.SubmissionResult.PUZZLE_CLOSED
    assert db.record_submission("p2", "U2", "bob", "d4", True, 10) == db.SubmissionResult.RECORDED
