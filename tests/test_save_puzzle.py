from contextlib import contextmanager
from unittest.mock import MagicMock

import turso_serverless

import db
import queries


def _patch_connection(monkeypatch, active_puzzle_found: bool, insert_side_effect=None):
    cur = MagicMock()
    cur.fetchone.return_value = {"puzzle_id": "p1"} if active_puzzle_found else None
    if insert_side_effect is not None:
        cur.execute.side_effect = [None, insert_side_effect]
    conn = MagicMock()
    conn.cursor.return_value = cur

    @contextmanager
    def fake_get_connection():
        yield conn

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    return cur


def test_new_puzzle_is_inserted(monkeypatch):
    cur = _patch_connection(monkeypatch, active_puzzle_found=False)
    db.save_puzzle("p1", "2024-01-01", "fen", ["e4"])
    cur.execute.assert_any_call(queries.INSERT_PUZZLE, ("p1", "2024-01-01", "fen", '["e4"]', None))


def test_resend_of_an_already_active_puzzle_is_a_no_op(monkeypatch):
    cur = _patch_connection(monkeypatch, active_puzzle_found=True)
    db.save_puzzle("p1", "2024-01-01", "fen", ["e4"])
    cur.execute.assert_called_once_with(queries.GET_ACTIVE_PUZZLE_BY_ID, ("p1",))


def test_resend_of_a_deactivated_puzzle_does_not_raise(monkeypatch):
    # The active-only check misses a soft-deleted row, so the code falls through to
    # the INSERT - which collides with that row's primary key. This must be caught
    # and treated as a no-op instead of surfacing as a 500 (the bug being fixed here).
    integrity_error = turso_serverless.IntegrityError("UNIQUE constraint failed: puzzles.puzzle_id")
    _patch_connection(monkeypatch, active_puzzle_found=False, insert_side_effect=integrity_error)
    db.save_puzzle("p1", "2024-01-01", "fen", ["e4"])
