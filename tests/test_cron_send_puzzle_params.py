from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
from constants import Security


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(Security, "CRON_SECRET", "s3cr3t")
    return TestClient(app_module.app)


def test_no_params_default_to_force_and_new_puzzle_false(client, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(app_module.lichess, "handle_puzzle_generation_and_sending", handler)

    response = client.get("/cron/send-puzzle", headers={"Authorization": "Bearer s3cr3t"})

    assert response.status_code == 200
    handler.assert_awaited_once_with(force=False, new_puzzle=False)


def test_force_query_param_is_passed_through(client, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(app_module.lichess, "handle_puzzle_generation_and_sending", handler)

    response = client.get(
        "/cron/send-puzzle", params={"force": "true"}, headers={"Authorization": "Bearer s3cr3t"},
    )

    assert response.status_code == 200
    handler.assert_awaited_once_with(force=True, new_puzzle=False)


def test_new_puzzle_query_param_is_passed_through(client, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(app_module.lichess, "handle_puzzle_generation_and_sending", handler)

    response = client.get(
        "/cron/send-puzzle", params={"new_puzzle": "true"}, headers={"Authorization": "Bearer s3cr3t"},
    )

    assert response.status_code == 200
    handler.assert_awaited_once_with(force=False, new_puzzle=True)


def test_both_query_params_are_passed_through(client, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(app_module.lichess, "handle_puzzle_generation_and_sending", handler)

    response = client.get(
        "/cron/send-puzzle",
        params={"force": "true", "new_puzzle": "true"},
        headers={"Authorization": "Bearer s3cr3t"},
    )

    assert response.status_code == 200
    handler.assert_awaited_once_with(force=True, new_puzzle=True)
