"""Regression test for the same-date tie-break bug in INSERT_SUBMISSION_IF_LATEST.

Runs against a real in-memory sqlite3 connection rather than mocks - the bug was
in the SQL itself (ORDER BY date DESC with no tie-break), so a mock that just
records call args can't exercise it. sqlite3 speaks the same dialect Turso/libSQL
does and migrations.py already targets the stdlib DB-API, so it's a faithful stand-in.
"""

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


def test_newer_puzzle_with_same_date_is_not_shadowed_by_an_older_one(conn):
    # Two puzzles posted the same calendar date (e.g. redeploy, backfill, timezone
    # edge case) - the bug picked "latest" by date alone, which ties here and let
    # SQLite fall back to an arbitrary (in practice: insertion/rowid ascending) order,
    # so the OLDER puzzle was mistaken for the latest one.
    db.save_puzzle("old_puzzle", "2026-09-14", "fen1", ["e4"])
    db.save_puzzle("new_puzzle", "2026-09-14", "fen2", ["d4"])

    result = db.record_submission("new_puzzle", "U1", "alice", "d4", True, 10)
    assert result == db.SUBMISSION_RECORDED

    result = db.record_submission("old_puzzle", "U2", "bob", "e4", True, 10)
    assert result == db.SUBMISSION_STALE_PUZZLE


def test_latest_is_by_insertion_order_not_date_value(conn):
    # A puzzle inserted later should win even if its date field is earlier than an
    # existing row's - "latest posted" is about insertion order, not the date string.
    db.save_puzzle("first", "2026-09-14", "fen1", ["e4"])
    db.save_puzzle("second_but_earlier_date", "2026-09-01", "fen2", ["d4"])

    result = db.record_submission("second_but_earlier_date", "U1", "alice", "d4", True, 10)
    assert result == db.SUBMISSION_RECORDED

    result = db.record_submission("first", "U2", "bob", "e4", True, 10)
    assert result == db.SUBMISSION_STALE_PUZZLE
