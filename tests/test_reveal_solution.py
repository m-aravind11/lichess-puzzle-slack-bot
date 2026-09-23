from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
from constants import Security


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(Security, "CRON_SECRET", "s3cr3t")
    monkeypatch.setattr(app_module, "slack_client", MagicMock())
    return TestClient(app_module.app)


def _puzzle(**overrides) -> dict:
    puzzle = {
        "puzzle_id": "p1",
        "posted_at": "2024-01-01T09:00:00+00:00",
        "fen": "startpos",
        "solution": ["e4", "e5", "Qh5"],
        "slack_ts": "1700000000.0",
    }
    puzzle.update(overrides)
    return puzzle


def test_no_open_puzzle_posts_nothing(client, monkeypatch):
    monkeypatch.setattr(db, "close_active_puzzle", MagicMock(return_value=None))
    response = client.post("/admin/puzzle:revealSolution", headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 200
    app_module.slack_client.chat_postMessage.assert_not_called()


def test_closed_puzzle_with_no_thread_posts_nothing(client, monkeypatch):
    monkeypatch.setattr(db, "close_active_puzzle", MagicMock(return_value=_puzzle(slack_ts=None)))
    response = client.post("/admin/puzzle:revealSolution", headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 200
    app_module.slack_client.chat_postMessage.assert_not_called()


def test_open_puzzle_is_closed_and_its_solution_posted_in_thread(client, monkeypatch):
    monkeypatch.setattr(db, "close_active_puzzle", MagicMock(return_value=_puzzle()))

    response = client.post("/admin/puzzle:revealSolution", headers={"Authorization": "Bearer s3cr3t"})

    assert response.status_code == 200
    app_module.slack_client.chat_postMessage.assert_called_once()
    call = app_module.slack_client.chat_postMessage.call_args
    assert call.kwargs["thread_ts"] == "1700000000.0"
    assert call.kwargs["reply_broadcast"] is True
    assert "e4 e5 Qh5" in call.kwargs["text"]


def test_close_active_puzzle_is_called_with_todays_utc_date(client, monkeypatch):
    close = MagicMock(return_value=None)
    monkeypatch.setattr(db, "close_active_puzzle", close)

    client.post("/admin/puzzle:revealSolution", headers={"Authorization": "Bearer s3cr3t"})

    close.assert_called_once()
    date_arg = close.call_args.args[0]
    assert len(date_arg) == 10 and date_arg.count("-") == 2
