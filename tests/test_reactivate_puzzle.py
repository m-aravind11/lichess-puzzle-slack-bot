from contextlib import contextmanager
from unittest.mock import MagicMock

import db
import queries


def _patch_connection(monkeypatch, rowcount: int, fetchone_result):
    """Mocks the cursor reactivate_puzzle drives: rowcount from the conditional
    UPDATE, and what the fallback SELECT (only reached when rowcount is 0) finds."""
    cur = MagicMock()
    cur.rowcount = rowcount
    cur.fetchone.return_value = fetchone_result
    conn = MagicMock()
    conn.cursor.return_value = cur

    @contextmanager
    def fake_get_connection():
        yield conn

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    return cur


def test_update_affecting_a_row_reactivates_and_skips_the_fallback_check(monkeypatch):
    cur = _patch_connection(monkeypatch, rowcount=1, fetchone_result=None)
    assert db.reactivate_puzzle("p1") == db.PuzzleResult.REACTIVATED
    cur.execute.assert_called_once_with(queries.PuzzleQueries.REACTIVATE, ("p1",))


def test_update_affecting_no_row_and_puzzle_missing_returns_not_found(monkeypatch):
    cur = _patch_connection(monkeypatch, rowcount=0, fetchone_result=None)
    assert db.reactivate_puzzle("nope") == db.PuzzleResult.NOT_FOUND
    cur.execute.assert_any_call(queries.PuzzleQueries.GET_BY_ID_ANY_STATE, ("nope",))


def test_update_affecting_no_row_and_puzzle_exists_returns_already_active(monkeypatch):
    cur = _patch_connection(monkeypatch, rowcount=0, fetchone_result=(1,))
    assert db.reactivate_puzzle("p2") == db.PuzzleResult.ALREADY_ACTIVE
    cur.execute.assert_any_call(queries.PuzzleQueries.GET_BY_ID_ANY_STATE, ("p2",))
