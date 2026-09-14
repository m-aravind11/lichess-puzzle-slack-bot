from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
from constants import Security

ADMIN_ROUTES = [
    ("GET", "/cron/send-puzzle"),
    ("POST", "/admin/migrate"),
    ("DELETE", "/submissions/1"),
    ("DELETE", "/puzzles/p1"),
    ("POST", "/puzzles/p1/reactivate"),
    ("GET", "/cron/send-leaderboard"),
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
    monkeypatch.setattr(
        app_module.lichess, "handle_puzzle_generation_and_sending",
        AsyncMock(side_effect=AssertionError("should not run")),
    )
    response = client.request(method, path)
    assert response.status_code == 401


def test_correct_bearer_token_reaches_the_handler(client, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(app_module.lichess, "handle_puzzle_generation_and_sending", handler)
    response = client.get("/cron/send-puzzle", headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 200
    handler.assert_awaited_once()


def test_delete_submission_with_valid_token_calls_through(client, monkeypatch):
    monkeypatch.setattr(db, "deactivate_submission", MagicMock(return_value=True))
    response = client.delete("/submissions/1", headers={"Authorization": "Bearer s3cr3t"})
    assert response.status_code == 200
    db.deactivate_submission.assert_called_once_with(1)


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
