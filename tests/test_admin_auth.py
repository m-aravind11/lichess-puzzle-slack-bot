from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
from constants import Security

CRON_ROUTES = [
    ("POST", "/admin/dailyPuzzle:prepare"),
    ("POST", "/admin/dailyPuzzle:send"),
    ("POST", "/admin/puzzle:revealSolution"),
    ("POST", "/admin/leaderboard:send"),
]

ADMIN_ROUTES = [
    ("POST", "/admin/migrations:run"),
    ("DELETE", "/admin/submissions/1"),
    ("DELETE", "/admin/puzzles/p1"),
    ("POST", "/admin/puzzles/p1:reactivate"),
    ("GET", "/admin/puzzles"),
    ("GET", "/admin/houses"),
    ("POST", "/admin/houses"),
    ("GET", "/admin/players"),
    ("PUT", "/admin/players/U1/house"),
    ("DELETE", "/admin/players/U1/house"),
    ("GET", "/admin/leaderboard"),
    ("GET", "/admin/leaderboard/allTime"),
    ("GET", "/admin/difficultyWeights"),
    ("PUT", "/admin/difficultyWeights"),
]

ALL_ROUTES = CRON_ROUTES + ADMIN_ROUTES

HOUSE_DB_CALLS = ["list_houses", "create_house", "list_players", "assign_player_house", "unassign_player_house"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(Security, "CRON_SECRET", "cr0n")
    monkeypatch.setattr(Security, "ADMIN_SECRET", "s3cr3t")
    return TestClient(app_module.app)


def block_handlers(monkeypatch):
    for name in (
        "init_db", "deactivate_submission", "deactivate_puzzle", "reactivate_puzzle", "close_previous_puzzle",
        "get_leaderboard", "get_leaderboard_month", "store_finished_months", "list_stored_months",
        "list_unannounced_months", "mark_months_announced",
        "get_stored_leaderboard", "get_all_time_leaderboard", "list_puzzles", *HOUSE_DB_CALLS,
        "get_difficulty_weights", "set_difficulty_weights",
    ):
        monkeypatch.setattr(db, name, MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(app_module.lichess, "prepare_next_puzzle", MagicMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(
        app_module.lichess, "handle_puzzle_generation_and_sending",
        AsyncMock(side_effect=AssertionError("should not run")),
    )


@pytest.mark.parametrize("method,path", ALL_ROUTES)
def test_missing_auth_header_is_rejected(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", ALL_ROUTES)
def test_wrong_bearer_token_is_rejected(client, method, path):
    response = client.request(method, path, headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", ALL_ROUTES)
def test_auth_is_checked_before_the_handler_runs(client, method, path, monkeypatch):
    block_handlers(monkeypatch)
    response = client.request(method, path)
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_cron_secret_is_rejected_outside_the_cron_routes(client, method, path, monkeypatch):
    block_handlers(monkeypatch)
    response = client.request(method, path, headers={"Authorization": "Bearer cr0n"})
    assert response.status_code == 401


@pytest.mark.parametrize("token", ["cr0n", "s3cr3t"])
def test_cron_routes_accept_either_secret(client, monkeypatch, token):
    handler = AsyncMock()
    monkeypatch.setattr(app_module.lichess, "handle_puzzle_generation_and_sending", handler)
    response = client.post("/admin/dailyPuzzle:send", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    handler.assert_awaited_once()


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


def test_list_puzzles_with_valid_token_calls_through(client, monkeypatch):
    row = {"puzzle_id": "abc123", "added_at": "2024-01-01T00:00:00", "posted_at": None, "active": 1}
    monkeypatch.setattr(db, "list_puzzles", MagicMock(return_value=[row]))
    response = client.get("/admin/puzzles", params={"state": "queued"}, headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 200
    db.list_puzzles.assert_called_once_with("queued")
    assert response.json() == [
        {"puzzleId": "abc123", "addedAt": "2024-01-01T00:00:00", "postedAt": None, "active": True},
    ]


def test_list_puzzles_rejects_an_unknown_state(client, monkeypatch):
    monkeypatch.setattr(db, "list_puzzles", MagicMock(side_effect=AssertionError("should not run")))
    response = client.get("/admin/puzzles", params={"state": "bogus"}, headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 400


@pytest.mark.parametrize("method,path", ALL_ROUTES)
def test_unset_secrets_fail_closed(method, path, monkeypatch):
    monkeypatch.setattr(Security, "CRON_SECRET", None)
    monkeypatch.setattr(Security, "ADMIN_SECRET", None)
    block_handlers(monkeypatch)
    client = TestClient(app_module.app)
    assert client.request(method, path).status_code == 401
    # What an unset secret would stringify to.
    assert client.request(method, path, headers={"Authorization": "Bearer None"}).status_code == 401
    assert client.request(method, path, headers={"Authorization": "Bearer "}).status_code == 401


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_unset_admin_secret_fails_closed_even_with_cron_secret_set(method, path, monkeypatch):
    monkeypatch.setattr(Security, "CRON_SECRET", "cr0n")
    monkeypatch.setattr(Security, "ADMIN_SECRET", None)
    block_handlers(monkeypatch)
    client = TestClient(app_module.app)
    assert client.request(method, path, headers={"Authorization": "Bearer cr0n"}).status_code == 401
