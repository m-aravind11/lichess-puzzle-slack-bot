import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

import db
import migrations
from constants import PuzzleState
from daily_puzzle import LichessDailyPuzzle

LICHESS_RESPONSE = {
    "game": {"pgn": "1. e4 e5"},
    "puzzle": {"id": "random1", "solution": ["g1f3"], "rating": 1234},
}


@pytest.fixture(autouse=True)
def conn(monkeypatch):
    connection = sqlite3.connect(":memory:")
    migrations.run_migrations(connection)

    @contextmanager
    def fake_get_connection():
        yield connection
        connection.commit()

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    yield connection
    connection.close()


@pytest.fixture
def lichess(monkeypatch):
    lp = LichessDailyPuzzle()
    monkeypatch.setattr(lp, "get_random_puzzle", MagicMock(return_value=LICHESS_RESPONSE))
    monkeypatch.setattr(lp, "pick_difficulty", MagicMock(return_value="harder"))
    return lp


def test_queues_a_random_puzzle_when_queue_is_empty(lichess):
    lichess.prepare_next_puzzle()

    lichess.get_random_puzzle.assert_called_once_with("harder")
    assert db.get_next_queued_puzzle() == {
        "puzzle_id": "random1",
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "solution": ["Nf3"],
        "difficulty": "harder",
        "rating": 1234,
    }


def test_skips_fetching_when_something_is_queued(lichess):
    db.queue_puzzle("queued1", "fen", ["e4"])

    lichess.prepare_next_puzzle()

    lichess.get_random_puzzle.assert_not_called()
    assert [p["puzzle_id"] for p in db.list_puzzles(PuzzleState.QUEUED)] == ["queued1"]
