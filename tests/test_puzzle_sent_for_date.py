from contextlib import contextmanager
from unittest.mock import MagicMock

import db
import queries


def _patch_connection(monkeypatch, fetchone_result, description=None):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_result
    if description is not None:
        cur.description = description
    conn = MagicMock()
    conn.cursor.return_value = cur

    @contextmanager
    def fake_get_connection():
        yield conn

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    return cur


def test_puzzle_sent_for_date_true_when_a_row_exists(monkeypatch):
    cur = _patch_connection(monkeypatch, fetchone_result=(1,))
    assert db.puzzle_sent_for_date("2024-01-01") is True
    cur.execute.assert_called_once_with(queries.PuzzleQueries.EXISTS_FOR_DATE, ("2024-01-01",))


def test_puzzle_sent_for_date_false_when_no_row(monkeypatch):
    _patch_connection(monkeypatch, fetchone_result=None)
    assert db.puzzle_sent_for_date("2024-01-01") is False


def test_get_active_puzzle_by_date_returns_none_when_nothing_active(monkeypatch):
    # Covers both "nothing sent today" and "today's puzzle was deactivated" -
    # either way there's nothing live for a force resend to re-post.
    cur = _patch_connection(monkeypatch, fetchone_result=None)
    assert db.get_active_puzzle_by_date("2024-01-01") is None
    cur.execute.assert_called_once_with(queries.PuzzleQueries.GET_ACTIVE_BY_DATE, ("2024-01-01",))


def test_get_active_puzzle_by_date_returns_puzzle_dict(monkeypatch):
    description = [("puzzle_id",), ("date",), ("fen",), ("solution",), ("slack_ts",)]
    row = ("p1", "2024-01-01", "fen", '["e4"]', "1700000000.0")
    _patch_connection(monkeypatch, fetchone_result=row, description=description)

    puzzle = db.get_active_puzzle_by_date("2024-01-01")

    assert puzzle == {
        "puzzle_id": "p1",
        "date": "2024-01-01",
        "fen": "fen",
        "solution": ["e4"],
        "slack_ts": "1700000000.0",
    }


def test_update_puzzle_slack_ts_issues_update(monkeypatch):
    cur = _patch_connection(monkeypatch, fetchone_result=None)
    db.update_puzzle_slack_ts("p1", "1700000000.0")
    cur.execute.assert_called_once_with(queries.PuzzleQueries.UPDATE_SLACK_TS, ("1700000000.0", "p1"))


def test_update_puzzle_slack_ts_refreshes_a_cached_entry(monkeypatch):
    db._puzzle_cache["p1"] = {"puzzle_id": "p1", "slack_ts": "old"}
    try:
        _patch_connection(monkeypatch, fetchone_result=None)
        db.update_puzzle_slack_ts("p1", "new")
        assert db._puzzle_cache["p1"]["slack_ts"] == "new"
    finally:
        del db._puzzle_cache["p1"]


def test_update_puzzle_slack_ts_is_a_no_op_on_the_cache_when_uncached(monkeypatch):
    db._puzzle_cache.pop("p1", None)
    _patch_connection(monkeypatch, fetchone_result=None)
    db.update_puzzle_slack_ts("p1", "new")
    assert "p1" not in db._puzzle_cache
