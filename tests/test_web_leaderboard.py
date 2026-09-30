import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
import migrations
from constants import Security

AUTH = {"Authorization": "Bearer s3cr3t"}


@pytest.fixture
def conn():
    # TestClient runs the async handlers on a worker thread.
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    migrations.run_migrations(connection)
    for i in range(1, 4):
        connection.execute(
            "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, slack_ts, active, closed_at)"
            " VALUES (?, 'fen', '[]', 'random', ?, ?, ?, 1, ?)",
            (f"p{i}", f"2024-01-0{i}T12:00:00+00:00", f"2024-01-0{i}T12:00:00+00:00",
             str(1704110400 + (i - 1) * 86400), f"2024-01-0{i + 1}T06:00:00+00:00"),
        )
    yield connection
    connection.close()


@pytest.fixture
def client(conn, monkeypatch):
    @contextmanager
    def fake_get_connection():
        yield conn
        conn.commit()

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    monkeypatch.setattr(Security, "ADMIN_SECRET", "s3cr3t")
    return TestClient(app_module.app)


def answer(conn, user_id, n, correct, score):
    conn.execute(
        "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)"
        " VALUES (?, ?, ?, 'e4', ?, ?, ?, 1)",
        (f"p{n}", user_id, user_id.lower(), int(correct), score, f"2024-01-0{n}T12:01:30+00:00"),
    )


def in_house(conn, user_id, house):
    conn.execute("INSERT OR IGNORE INTO houses (name) VALUES (?)", (house,))
    conn.execute(
        "INSERT INTO player_houses (user_id, house_id, assigned_at) SELECT ?, id, 'x' FROM houses WHERE name = ?",
        (user_id, house),
    )


def test_leaderboard_json_matches_the_slack_standings(client, conn):
    for n in (1, 2, 3):
        answer(conn, "ALICE", n, True, 10)
    answer(conn, "BOB", 1, True, 9)
    answer(conn, "BOB", 2, False, 0)
    answer(conn, "CAROL", 1, True, 5)
    in_house(conn, "ALICE", "Airbenders")
    in_house(conn, "BOB", "Firebenders")
    in_house(conn, "CAROL", "Firebenders")

    response = client.get("/admin/leaderboard", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {
        "month": "2024-01",
        "final": True,
        "stored": False,
        "months": ["2024-01"],
        "players": [
            {"rank": 1, "userName": "alice", "house": "Airbenders", "points": 30, "correct": 3, "attempted": 3,
             "avgSolveTime": "1m 30s", "currentStreak": 3, "bestStreak": 3},
            {"rank": 2, "userName": "bob", "house": "Firebenders", "points": 9, "correct": 1, "attempted": 2,
             "avgSolveTime": "1m 30s", "currentStreak": 0, "bestStreak": 1},
            {"rank": 3, "userName": "carol", "house": "Firebenders", "points": 5, "correct": 1, "attempted": 1,
             "avgSolveTime": "1m 30s", "currentStreak": 0, "bestStreak": 1},
        ],
        "houses": [
            {"rank": 1, "name": "Airbenders", "points": 30, "correct": 3, "players": 1},
            {"rank": 2, "name": "Firebenders", "points": 14, "correct": 2, "players": 2},
        ],
        "milestones": [{"streak": 3, "players": ["alice"]}],
    }


def test_leaderboard_json_when_nobody_has_played(client):
    assert client.get("/admin/leaderboard", headers=AUTH).json() == {
        "month": "2024-01", "final": True, "stored": False, "months": ["2024-01"],
        "players": [], "houses": [], "milestones": [],
    }


def test_leaderboard_json_before_any_puzzle_is_posted(client, conn):
    conn.execute("DELETE FROM puzzles")
    assert client.get("/admin/leaderboard", headers=AUTH).json() == {
        "month": None, "final": False, "stored": False, "months": [],
        "players": [], "houses": [], "milestones": [],
    }


@pytest.mark.parametrize("path,title", [("/leaderboard", "<title>Leaderboard"), ("/houses", "<title>Houses")])
def test_pages_are_served_without_auth(client, path, title):
    response = client.get(path)
    assert response.status_code == 200
    assert title in response.text


@pytest.mark.parametrize("path", ["/static/admin.js", "/static/admin.css"])
def test_shared_page_assets_are_served(client, path):
    assert client.get(path).status_code == 200
