from unittest.mock import MagicMock

import pytest

import daily_puzzle
from daily_puzzle import LichessDailyPuzzle


@pytest.fixture
def lichess(monkeypatch):
    lp = LichessDailyPuzzle()
    monkeypatch.setattr(lp, "_fetch_json_with_retries", MagicMock(return_value={"puzzle": {}}))
    return lp


def fetched_urls(lp) -> list[str]:
    return [call.args[0] for call in lp._fetch_json_with_retries.call_args_list]


def test_fetches_one_mate_in_2_or_3_puzzle_at_the_requested_difficulty(lichess, monkeypatch):
    choice = MagicMock(return_value="mateIn3")
    monkeypatch.setattr(daily_puzzle.random, "choice", choice)

    assert lichess.get_random_puzzle("hardest") is lichess._fetch_json_with_retries.return_value
    choice.assert_called_once_with(("mateIn2", "mateIn3"))
    assert fetched_urls(lichess) == ["https://lichess.org/api/puzzle/next?angle=mateIn3&difficulty=hardest"]


def test_difficulty_is_picked_from_the_stored_weights(lichess, monkeypatch):
    weights = {"easiest": 0, "easier": 0, "normal": 0, "harder": 100, "hardest": 0}
    monkeypatch.setattr(daily_puzzle.db, "get_difficulty_weights", MagicMock(return_value=weights))

    assert {lichess.pick_difficulty() for _ in range(20)} == {"harder"}
