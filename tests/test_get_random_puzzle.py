from unittest.mock import MagicMock

import pytest

import daily_puzzle
from daily_puzzle import Constants, LichessDailyPuzzle


def puzzle_with(*themes: str) -> dict:
    return {"puzzle": {"themes": list(themes)}}


@pytest.fixture
def lichess(monkeypatch):
    lp = LichessDailyPuzzle()
    monkeypatch.setattr(lp, "_fetch_json_with_retries", MagicMock())
    return lp


def fetched_themes(lp) -> list[str]:
    return [call.args[0].split("angle=")[1].split("&")[0] for call in lp._fetch_json_with_retries.call_args_list]


def test_pattern_puzzle_of_wanted_length_returned(lichess, monkeypatch):
    monkeypatch.setattr(daily_puzzle.random, "choice", lambda seq: "smotheredMate")
    wanted = puzzle_with("mateIn2", "smotheredMate")
    lichess._fetch_json_with_retries.return_value = wanted

    assert lichess.get_random_puzzle() is wanted
    assert fetched_themes(lichess) == ["smotheredMate"]


def test_pattern_puzzle_refetched_until_wanted_length(lichess, monkeypatch):
    monkeypatch.setattr(daily_puzzle.random, "choice", lambda seq: "backRankMate")
    wanted = puzzle_with("mateIn3", "backRankMate")
    lichess._fetch_json_with_retries.side_effect = [
        puzzle_with("mateIn1", "backRankMate"),
        puzzle_with("mateIn4", "backRankMate"),
        wanted,
    ]

    assert lichess.get_random_puzzle() is wanted
    assert fetched_themes(lichess) == ["backRankMate"] * 3


def test_last_pattern_puzzle_kept_after_misses(lichess, monkeypatch):
    monkeypatch.setattr(daily_puzzle.random, "choice", lambda seq: "hookMate")
    puzzles = [puzzle_with("mateIn1", "hookMate")] * (Constants.PATTERN_FETCH_ATTEMPTS - 1) + [puzzle_with("mateIn4", "hookMate")]
    lichess._fetch_json_with_retries.side_effect = puzzles

    assert lichess.get_random_puzzle() is puzzles[-1]
    assert fetched_themes(lichess) == ["hookMate"] * Constants.PATTERN_FETCH_ATTEMPTS
