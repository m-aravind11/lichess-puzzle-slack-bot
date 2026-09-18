import asyncio
from unittest.mock import MagicMock

import db
from daily_puzzle import LichessDailyPuzzle

LICHESS_RESPONSE = {
    "game": {"pgn": "1. e4 e5"},
    "puzzle": {"id": "new1", "solution": ["g1f3"]},  # Nf3 - legal for white after 1. e4 e5
}

QUEUED_PUZZLE = {
    "puzzle_id": "queued1",
    "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
    "solution": ["Nf3"],
}

EXISTING = {
    "puzzle_id": "p1",
    "posted_at": "2024-01-01T09:00:00+00:00",
    "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
    "solution": ["Nf3"],
    "slack_ts": "1600000000.0",
}


def _run(coro):
    """No pytest-asyncio/anyio plugin in this project's deps - drive the
    coroutine directly instead of adding one just for these few tests."""
    return asyncio.run(coro)


def _lichess(monkeypatch, existing_active=None, sent_today=False):
    lichess = LichessDailyPuzzle()
    monkeypatch.setattr(lichess, "get_random_puzzle", MagicMock(return_value=LICHESS_RESPONSE))
    monkeypatch.setattr(lichess, "send_puzzle_to_slack", MagicMock(return_value="1700000000.0"))
    monkeypatch.setattr(db, "get_active_puzzle_by_date", MagicMock(return_value=existing_active))
    monkeypatch.setattr(db, "puzzle_sent_for_date", MagicMock(return_value=sent_today))
    monkeypatch.setattr(db, "update_puzzle_slack_ts", MagicMock())
    monkeypatch.setattr(db, "save_puzzle", MagicMock())
    monkeypatch.setattr(db, "get_next_queued_puzzle", MagicMock(return_value=None))
    return lichess


def test_skips_when_already_sent_and_not_forced(monkeypatch):
    lichess = _lichess(monkeypatch, sent_today=True)

    _run(lichess.handle_puzzle_generation_and_sending())

    lichess.get_random_puzzle.assert_not_called()
    lichess.send_puzzle_to_slack.assert_not_called()
    db.save_puzzle.assert_not_called()


def test_generates_and_saves_a_fresh_puzzle_when_none_sent_today(monkeypatch):
    lichess = _lichess(monkeypatch, sent_today=False)

    _run(lichess.handle_puzzle_generation_and_sending())

    lichess.get_random_puzzle.assert_called_once()
    lichess.send_puzzle_to_slack.assert_called_once()
    db.save_puzzle.assert_called_once()
    assert db.save_puzzle.call_args.kwargs["puzzle_id"] == "new1"


def test_force_resends_the_existing_puzzle_without_fetching_a_new_one(monkeypatch):
    lichess = _lichess(monkeypatch, existing_active=EXISTING)

    _run(lichess.handle_puzzle_generation_and_sending(force=True))

    lichess.get_random_puzzle.assert_not_called()
    lichess.send_puzzle_to_slack.assert_called_once()
    assert lichess.send_puzzle_to_slack.call_args.args[2] == "p1"
    db.update_puzzle_slack_ts.assert_called_once_with("p1", "1700000000.0")
    db.save_puzzle.assert_not_called()


def test_force_with_nothing_active_falls_back_to_generating_fresh(monkeypatch):
    # e.g. today's puzzle was deactivated - nothing live left to resend.
    lichess = _lichess(monkeypatch, existing_active=None)

    _run(lichess.handle_puzzle_generation_and_sending(force=True))

    lichess.get_random_puzzle.assert_called_once()
    db.save_puzzle.assert_called_once()
    db.update_puzzle_slack_ts.assert_not_called()


def test_uses_the_next_queued_puzzle_when_there_is_one(monkeypatch):
    lichess = _lichess(monkeypatch, sent_today=False)
    monkeypatch.setattr(db, "get_next_queued_puzzle", MagicMock(return_value=QUEUED_PUZZLE))

    _run(lichess.handle_puzzle_generation_and_sending())

    lichess.get_random_puzzle.assert_not_called()
    db.save_puzzle.assert_called_once()
    assert db.save_puzzle.call_args.kwargs["puzzle_id"] == "queued1"
    assert db.save_puzzle.call_args.kwargs["fen"] == QUEUED_PUZZLE["fen"]


def test_new_puzzle_flag_always_fetches_fresh_even_if_already_sent(monkeypatch):
    lichess = _lichess(monkeypatch, sent_today=True, existing_active=EXISTING)

    _run(lichess.handle_puzzle_generation_and_sending(new_puzzle=True))

    db.get_active_puzzle_by_date.assert_not_called()
    db.puzzle_sent_for_date.assert_not_called()
    lichess.get_random_puzzle.assert_called_once()
    lichess.send_puzzle_to_slack.assert_called_once()
    db.save_puzzle.assert_called_once()
    assert db.save_puzzle.call_args.kwargs["puzzle_id"] == "new1"
