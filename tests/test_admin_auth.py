from unittest.mock import AsyncMock, MagicMock

import pytest
import requests
from fastapi.testclient import TestClient

import app as app_module
import db
from constants import Security

ADMIN_ROUTES = [
    ("POST", "/admin/dailyPuzzle:send"),
    ("POST", "/admin/migrations:run"),
    ("DELETE", "/admin/submissions/1"),
    ("DELETE", "/admin/puzzles/p1"),
    ("POST", "/admin/puzzles/p1:reactivate"),
    ("POST", "/admin/leaderboard:send"),
    ("POST", "/admin/puzzles"),
    ("GET", "/admin/puzzles"),
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(Security, "CRON_SECRET", "s3cr3t")
    return TestClient(app_module.app)


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_missing_auth_header_is_rejected(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_wrong_bearer_token_is_rejected(client, method, path):
    response = client.request(method, path, headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_auth_is_checked_before_the_handler_runs(client, method, path, monkeypatch):
    # None of these should touch the DB or Slack when auth fails - patch every
    # handler's underlying call with something that fails loudly if invoked.
    monkeypatch.setattr(db, "init_db", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "deactivate_submission", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "deactivate_puzzle", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "reactivate_puzzle", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "get_leaderboard", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "queue_puzzle", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "list_puzzles", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(app_module.lichess, "get_puzzle_by_id", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(
        app_module.lichess, "handle_puzzle_generation_and_sending",
        AsyncMock(side_effect=AssertionError("should not run")),
    )
    response = client.request(method, path)
    assert response.status_code == 401


def test_correct_bearer_token_reaches_the_handler(client, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(app_module.lichess, "handle_puzzle_generation_and_sending", handler)
    response = client.post("/admin/dailyPuzzle:send", headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 200
    handler.assert_awaited_once()


def test_delete_submission_with_valid_token_calls_through(client, monkeypatch):
    monkeypatch.setattr(db, "deactivate_submission", MagicMock(return_value=True))
    response = client.delete("/admin/submissions/1", headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 200
    db.deactivate_submission.assert_called_once_with(1)


RAW_LICHESS_PUZZLE = {
    "game": {"pgn": "1. e4 e5"},
    "puzzle": {"id": "abc123", "solution": ["g1f3"]},  # Nf3 - legal for white after 1. e4 e5
}


def test_queue_puzzle_with_valid_token_calls_through(client, monkeypatch):
    monkeypatch.setattr(app_module.lichess, "get_puzzle_by_id", MagicMock(return_value=RAW_LICHESS_PUZZLE))
    monkeypatch.setattr(db, "queue_puzzle", MagicMock(return_value=True))
    response = client.post(
        "/admin/puzzles",
        json={"puzzleId": "abc123"},
        headers={"Authorization": "Bearer s3cr3t"},
    )
    assert response.status_code == 201
    app_module.lichess.get_puzzle_by_id.assert_called_once_with("abc123")
    db.queue_puzzle.assert_called_once()
    assert db.queue_puzzle.call_args.args[0] == "abc123"


def test_queue_puzzle_rejects_missing_puzzle_id(client):
    response = client.post(
        "/admin/puzzles",
        json={},
        headers={"Authorization": "Bearer s3cr3t"},
    )
    assert response.status_code == 400


def test_queue_puzzle_rejects_a_puzzle_id_lichess_cannot_fetch(client, monkeypatch):
    monkeypatch.setattr(app_module.lichess, "get_puzzle_by_id", MagicMock(side_effect=requests.HTTPError()))
    response = client.post(
        "/admin/puzzles",
        json={"puzzleId": "badid"},
        headers={"Authorization": "Bearer s3cr3t"},
    )
    assert response.status_code == 502


def test_queue_puzzle_rejects_duplicate(client, monkeypatch):
    monkeypatch.setattr(app_module.lichess, "get_puzzle_by_id", MagicMock(return_value=RAW_LICHESS_PUZZLE))
    monkeypatch.setattr(db, "queue_puzzle", MagicMock(return_value=False))
    response = client.post(
        "/admin/puzzles",
        json={"puzzleId": "abc123"},
        headers={"Authorization": "Bearer s3cr3t"},
    )
    assert response.status_code == 409


def test_list_puzzles_with_valid_token_calls_through(client, monkeypatch):
    row = {"puzzle_id": "abc123", "source": "curated", "added_at": "2024-01-01T00:00:00", "posted_at": None, "active": 1}
    monkeypatch.setattr(db, "list_puzzles", MagicMock(return_value=[row]))
    response = client.get("/admin/puzzles", params={"state": "queued"}, headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 200
    db.list_puzzles.assert_called_once_with("queued")
    assert response.json() == [
        {"puzzleId": "abc123", "source": "curated", "addedAt": "2024-01-01T00:00:00", "postedAt": None, "active": True},
    ]


def test_list_puzzles_rejects_an_unknown_state(client, monkeypatch):
    monkeypatch.setattr(db, "list_puzzles", MagicMock(side_effect=AssertionError("should not run")))
    response = client.get("/admin/puzzles", params={"state": "bogus"}, headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 400


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_unset_cron_secret_fails_closed(method, path, monkeypatch):
    # A misconfigured deploy (or an accidentally deleted env var) must reject
    # every admin route, not wave every request through unauthenticated.
    monkeypatch.setattr(Security, "CRON_SECRET", None)
    monkeypatch.setattr(db, "deactivate_submission", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "deactivate_puzzle", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "reactivate_puzzle", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "get_leaderboard", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "init_db", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "queue_puzzle", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(db, "list_puzzles", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(app_module.lichess, "get_puzzle_by_id", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(
        app_module.lichess, "handle_puzzle_generation_and_sending",
        AsyncMock(side_effect=AssertionError("should not run")),
    )
    client = TestClient(app_module.app)
    response = client.request(method, path)
    assert response.status_code == 401

    # Even the (previously) correct bearer token can't work when there's no secret to check against.
    response = client.request(method, path, headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 401
