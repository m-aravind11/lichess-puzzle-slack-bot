"""Regression test for the same-day tie-break bug in INSERT_SUBMISSION_IF_LATEST.

Runs against a real in-memory sqlite3 connection rather than mocks - the bug was
in the SQL itself (ordering by a day with no tie-break), so a mock that just
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


def test_newer_puzzle_posted_the_same_day_is_not_shadowed_by_an_older_one(conn):
    # Two puzzles posted the same calendar day (e.g. a newPuzzle=true rerun) -
    # "latest" must be the one posted last, not an arbitrary one of the two.
    db.save_puzzle("old_puzzle", "fen1", ["e4"])
    db.save_puzzle("new_puzzle", "fen2", ["d4"])

    result = db.record_submission("new_puzzle", "U1", "alice", "d4", True, 10)
    assert result == db.SubmissionResult.RECORDED

    result = db.record_submission("old_puzzle", "U2", "bob", "e4", True, 10)
    assert result == db.SubmissionResult.STALE_PUZZLE
