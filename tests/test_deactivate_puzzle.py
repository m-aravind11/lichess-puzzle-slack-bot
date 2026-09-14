from contextlib import contextmanager
from unittest.mock import MagicMock

import db
import queries


def _patch_connection(monkeypatch, rowcount: int, fetchone_result):
    """Mocks the cursor deactivate_puzzle drives: rowcount from the conditional
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


def test_update_affecting_a_row_deactivates_and_skips_the_fallback_check(monkeypatch):
    cur = _patch_connection(monkeypatch, rowcount=1, fetchone_result=None)
    assert db.deactivate_puzzle("p1") == db.PUZZLE_DEACTIVATED
    cur.execute.assert_called_once_with(queries.DEACTIVATE_PUZZLE_IF_NO_ACTIVE_SUBMISSIONS, ("p1",))


def test_update_affecting_no_row_and_puzzle_missing_returns_not_found(monkeypatch):
    cur = _patch_connection(monkeypatch, rowcount=0, fetchone_result=None)
    assert db.deactivate_puzzle("nope") == db.PUZZLE_NOT_FOUND
    cur.execute.assert_any_call(queries.GET_ACTIVE_PUZZLE_BY_ID, ("nope",))


def test_update_affecting_no_row_and_puzzle_still_active_returns_has_active_submissions(monkeypatch):
    cur = _patch_connection(monkeypatch, rowcount=0, fetchone_result={"puzzle_id": "p2"})
    assert db.deactivate_puzzle("p2") == db.PUZZLE_HAS_ACTIVE_SUBMISSIONS
    cur.execute.assert_any_call(queries.GET_ACTIVE_PUZZLE_BY_ID, ("p2",))


def test_fallback_check_is_only_run_when_the_update_affects_no_row(monkeypatch):
    cur = _patch_connection(monkeypatch, rowcount=1, fetchone_result={"puzzle_id": "p3"})
    db.deactivate_puzzle("p3")
    # A truthy fetchone_result here would flip the result to HAS_ACTIVE_SUBMISSIONS
    # if the fallback query ran - it mustn't, since the fast path already succeeded.
    assert cur.execute.call_count == 1
