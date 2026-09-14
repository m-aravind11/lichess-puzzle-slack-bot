from unittest.mock import MagicMock

import db
import interactions


def _views_open_call(slack_client: MagicMock) -> dict:
    return slack_client.views_open.call_args.kwargs


def _label(slack_client: MagicMock) -> str:
    return _views_open_call(slack_client)["view"]["blocks"][0]["label"]["text"]


def _hint(slack_client: MagicMock) -> str:
    return _views_open_call(slack_client)["view"]["blocks"][0]["hint"]["text"]


def test_label_shows_player_move_count(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: {"solution": ["Bc2+", "Ka1", "Re1+", "Nb1", "Rxb1#"]})
    slack_client = MagicMock()

    interactions.open_answer_modal(slack_client, "trigger1", "p1")

    assert _label(slack_client) == "Your moves (3-move puzzle)"


def test_label_for_one_move_puzzle(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: {"solution": ["Qh4#"]})
    slack_client = MagicMock()

    interactions.open_answer_modal(slack_client, "trigger1", "p1")

    assert _label(slack_client) == "Your moves (1-move puzzle)"


def test_label_falls_back_when_puzzle_not_found(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: None)
    slack_client = MagicMock()

    interactions.open_answer_modal(slack_client, "trigger1", "p1")

    assert _label(slack_client) == "Your moves"


def test_hint_explains_opponent_moves_are_automatic(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: {"solution": ["e4"]})
    slack_client = MagicMock()

    interactions.open_answer_modal(slack_client, "trigger1", "p1")

    assert "added automatically" in _hint(slack_client)


def test_private_metadata_still_carries_puzzle_id(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: {"solution": ["e4"]})
    slack_client = MagicMock()

    interactions.open_answer_modal(slack_client, "trigger1", "p1")

    assert _views_open_call(slack_client)["view"]["private_metadata"] == "p1"
