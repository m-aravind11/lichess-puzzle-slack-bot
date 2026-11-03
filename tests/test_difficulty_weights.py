import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
import migrations
from constants import Security

AUTH = {"Authorization": "Bearer s3cr3t"}
DEFAULTS = {"easiest": 20, "easier": 50, "normal": 15, "harder": 10, "hardest": 5}
VALID = {"easiest": 40, "easier": 40, "normal": 20, "harder": 0, "hardest": 0}


@pytest.fixture(autouse=True)
def conn(monkeypatch):
    # TestClient runs the async handlers on a worker thread.
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    migrations.run_migrations(connection)

    @contextmanager
    def fake_get_connection():
        yield connection
        connection.commit()

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    yield connection
    connection.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(Security, "ADMIN_SECRET", "s3cr3t")
    return TestClient(app_module.app)


def test_migration_seeds_defaults_leaning_towards_easier(client):
    response = client.get("/admin/difficultyWeights", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == DEFAULTS
    assert list(response.json()) == ["easiest", "easier", "normal", "harder", "hardest"]


def test_saved_weights_are_returned_and_persisted(client):
    response = client.put("/admin/difficultyWeights", json=VALID, headers=AUTH)

    assert response.status_code == 200
    assert response.json() == VALID
    assert db.get_difficulty_weights() == VALID


@pytest.mark.parametrize("body", [
    {**VALID, "easiest": 39},
    {**VALID, "easiest": 41},
    {k: v for k, v in VALID.items() if k != "hardest"},
    {**VALID, "extreme": 0},
    {**VALID, "easiest": -10, "easier": 90},
    {**VALID, "easiest": 40.0},
    {**VALID, "harder": True, "easiest": 39},
    {**VALID, "easiest": "40"},
    [40, 40, 20, 0, 0],
])
def test_invalid_weights_are_rejected_and_not_saved(client, body):
    response = client.put("/admin/difficultyWeights", json=body, headers=AUTH)

    assert response.status_code == 400
    assert db.get_difficulty_weights() == DEFAULTS


def test_difficulty_page_is_served(client):
    response = client.get("/difficulty")

    assert response.status_code == 200
    assert "/admin/difficultyWeights" in response.text
