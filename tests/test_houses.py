"""Houses run end to end - HTTP route -> db -> SQL - against a real in-memory
sqlite3 connection, since one-active-house-per-player, soft deletes and name
uniqueness live in the queries and indexes themselves."""

import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
import migrations
from constants import Security
from slack_helpers import format_house_leaderboard
from standings import build_standings

AUTH = {"Authorization": "Bearer s3cr3t"}


@pytest.fixture
def conn():
    # TestClient runs the async handlers on a worker thread.
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    migrations.run_migrations(connection)
    for puzzle_id, posted_at in (("p1", "2024-01-31T12:00:00+00:00"), ("p2", "2024-02-01T12:00:00+00:00")):
        connection.execute(
            "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, active)"
            " VALUES (?, 'fen', '[]', 'random', ?, ?, 1)",
            (puzzle_id, posted_at, posted_at),
        )
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def patch_db(conn, monkeypatch):
    @contextmanager
    def fake_get_connection():
        yield conn
        conn.commit()

    monkeypatch.setattr(db, "get_connection", fake_get_connection)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(Security, "ADMIN_SECRET", "s3cr3t")
    return TestClient(app_module.app)


def answer(conn, user_id, puzzle_id, correct=True, active=True, user_name=None):
    conn.execute(
        "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)"
        " VALUES (?, ?, ?, 'e4', ?, ?, '2024-02-01T12:05:00+00:00', ?)",
        (puzzle_id, user_id, user_name or user_id.lower(), int(correct), 10 if correct else 0, int(active)),
    )


def create(client, name):
    response = client.post("/admin/houses", json={"name": name}, headers=AUTH)
    assert response.status_code == 201
    return response.json()["id"]


def put_house(client, user_id, house_id):
    return client.put(f"/admin/players/{user_id}/house", json={"houseId": house_id}, headers=AUTH)


def player(client, user_id):
    return next(p for p in client.get("/admin/players", headers=AUTH).json() if p["userId"] == user_id)


# ---- houses ----

def test_created_house_is_listed_with_no_members(client):
    house_id = create(client, "  Gryffindor  ")
    assert client.get("/admin/houses", headers=AUTH).json() == [{"id": house_id, "name": "Gryffindor", "memberCount": 0}]


def test_house_names_are_unique_ignoring_case(client):
    create(client, "Gryffindor")
    response = client.post("/admin/houses", json={"name": "gryffindor"}, headers=AUTH)
    assert response.status_code == 409


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}, {"name": None}])
def test_house_name_is_required(client, body):
    assert client.post("/admin/houses", json=body, headers=AUTH).status_code == 400


def test_houses_are_listed_by_name_with_member_counts(client, conn):
    slytherin = create(client, "Slytherin")
    gryffindor = create(client, "Gryffindor")
    answer(conn, "U1", "p1")
    answer(conn, "U2", "p1")
    put_house(client, "U1", slytherin)
    put_house(client, "U2", slytherin)
    assert client.get("/admin/houses", headers=AUTH).json() == [
        {"id": gryffindor, "name": "Gryffindor", "memberCount": 0},
        {"id": slytherin, "name": "Slytherin", "memberCount": 2},
    ]


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_houses_cannot_be_updated_or_deleted(client, method):
    house_id = create(client, "Gryffindor")
    assert client.request(method, f"/admin/houses/{house_id}", json={"name": "X"}, headers=AUTH).status_code == 404
    assert client.get("/admin/houses", headers=AUTH).json() == [{"id": house_id, "name": "Gryffindor", "memberCount": 0}]


# ---- players ----

def test_players_come_from_active_submissions_unassigned_first(client, conn):
    house_id = create(client, "Gryffindor")
    answer(conn, "U1", "p1", user_name="alice")
    answer(conn, "U1", "p2", user_name="alice")
    answer(conn, "U2", "p1", user_name="bob")
    answer(conn, "U3", "p1", user_name="carol", active=False)
    put_house(client, "U1", house_id)

    assert client.get("/admin/players", headers=AUTH).json() == [
        {"userId": "U2", "userName": "bob", "houseId": None},
        {"userId": "U1", "userName": "alice", "houseId": house_id},
    ]


def test_assign_house(client, conn):
    house_id = create(client, "Gryffindor")
    answer(conn, "U1", "p1")
    response = put_house(client, "U1", house_id)
    assert response.status_code == 200
    assert response.json() == {"userId": "U1", "houseId": house_id}
    assert player(client, "U1")["houseId"] == house_id


def test_assigning_a_player_already_in_another_house_is_refused(client, conn):
    gryffindor, slytherin = create(client, "Gryffindor"), create(client, "Slytherin")
    answer(conn, "U1", "p1")
    put_house(client, "U1", gryffindor)
    assert put_house(client, "U1", slytherin).status_code == 409
    assert player(client, "U1")["houseId"] == gryffindor


def test_reassigning_the_same_house_is_a_no_op_success(client, conn):
    house_id = create(client, "Gryffindor")
    answer(conn, "U1", "p1")
    put_house(client, "U1", house_id)
    assert put_house(client, "U1", house_id).status_code == 200
    assert player(client, "U1")["houseId"] == house_id


def unassign(client, user_id):
    return client.delete(f"/admin/players/{user_id}/house", headers=AUTH)


def test_unassign_soft_deletes_the_assignment(client, conn):
    house_id = create(client, "Gryffindor")
    answer(conn, "U1", "p1")
    put_house(client, "U1", house_id)

    assert unassign(client, "U1").status_code == 200
    assert player(client, "U1")["houseId"] is None
    assert client.get("/admin/houses", headers=AUTH).json()[0]["memberCount"] == 0
    # Their points still count for the house they were in.
    assert db.get_leaderboard()[0]["house_name"] == "Gryffindor"
    assert conn.execute("SELECT house_id, active FROM player_houses WHERE user_id = 'U1'").fetchall() == [(house_id, 0)]


def test_player_who_left_can_be_assigned_again_if_they_rejoin(client, conn):
    gryffindor, slytherin = create(client, "Gryffindor"), create(client, "Slytherin")
    answer(conn, "U1", "p1")
    put_house(client, "U1", gryffindor)
    unassign(client, "U1")

    assert put_house(client, "U1", slytherin).status_code == 200
    assert player(client, "U1")["houseId"] == slytherin
    assert db.get_leaderboard()[0]["house_name"] == "Slytherin"
    assert conn.execute("SELECT house_id, active FROM player_houses WHERE user_id = 'U1' ORDER BY id").fetchall() == [
        (gryffindor, 0), (slytherin, 1),
    ]


def test_unassigning_a_player_not_in_a_house_is_404(client, conn):
    answer(conn, "U1", "p1")
    assert unassign(client, "U1").status_code == 404
    assert unassign(client, "NOPE").status_code == 404


def test_unassigning_twice_is_404_the_second_time(client, conn):
    house_id = create(client, "Gryffindor")
    answer(conn, "U1", "p1")
    put_house(client, "U1", house_id)
    assert unassign(client, "U1").status_code == 200
    assert unassign(client, "U1").status_code == 404


def test_assigning_unknown_player_is_404(client):
    house_id = create(client, "Gryffindor")
    assert put_house(client, "NOPE", house_id).status_code == 404


def test_assigning_unknown_house_is_404(client, conn):
    answer(conn, "U1", "p1")
    assert put_house(client, "U1", 99).status_code == 404


@pytest.mark.parametrize("body", [{}, {"houseId": None}, {"houseId": "1"}, {"houseId": True}, {"houseId": 1.5}])
def test_assign_rejects_a_bad_house_id(client, conn, body):
    create(client, "Gryffindor")
    answer(conn, "U1", "p1")
    response = client.put("/admin/players/U1/house", json=body, headers=AUTH)
    assert response.status_code == 400
    assert player(client, "U1")["houseId"] is None


# ---- leaderboard ----

def test_leaderboard_entries_carry_house_name(client, conn):
    house_id = create(client, "Gryffindor")
    answer(conn, "U1", "p1")
    answer(conn, "U2", "p1")
    put_house(client, "U1", house_id)
    houses = {e["user_id"]: e["house_name"] for e in db.get_leaderboard()}
    assert houses == {"U1": "Gryffindor", "U2": None}


def _entry(user_id, house_name, score, correct):
    return {
        "user_id": user_id, "user_name": user_id.lower(), "house_name": house_name, "score": score,
        "correct": correct, "attempted": correct, "avg_solve_seconds": 60, "current_streak": 0, "best_streak": 0,
    }


def test_house_standings_sum_players_and_skip_unassigned():
    board = [
        _entry("U1", "Slytherin", 30, 3),
        _entry("U2", "Gryffindor", 20, 2),
        _entry("U3", "Gryffindor", 15, 2),
        _entry("U4", None, 100, 10),
    ]
    assert build_standings(board)["houses"] == [
        {"rank": 1, "name": "Gryffindor", "points": 35, "correct": 4, "players": 2},
        {"rank": 2, "name": "Slytherin", "points": 30, "correct": 3, "players": 1},
    ]


def test_house_standings_tie_broken_by_more_correct():
    board = [_entry("U1", "Slytherin", 30, 2), _entry("U2", "Gryffindor", 30, 3)]
    assert [h["name"] for h in build_standings(board)["houses"]] == ["Gryffindor", "Slytherin"]


def test_house_standings_are_empty_when_nobody_is_in_a_house():
    assert build_standings([_entry("U1", None, 10, 1)])["houses"] == []


def test_slack_house_standings_table():
    board = [_entry("U1", "Slytherin", 30, 3), _entry("U2", "Gryffindor", 20, 2), _entry("U3", "Gryffindor", 15, 2)]
    lines = format_house_leaderboard(build_standings(board)).splitlines()
    assert lines[0].startswith("*House standings*")
    assert lines[4].split() == ["1", "Gryffindor", "35", "4", "2"]
    assert lines[5].split() == ["2", "Slytherin", "30", "3", "1"]
    assert len(lines) == 7  # header, ```, column row, divider, 2 houses, ```


def test_slack_house_standings_are_omitted_when_nobody_is_in_a_house():
    assert format_house_leaderboard(build_standings([_entry("U1", None, 10, 1)])) is None


def test_posted_leaderboard_includes_house_standings(client, conn, monkeypatch):
    house_id = create(client, "Gryffindor")
    answer(conn, "U1", "p1")
    put_house(client, "U1", house_id)
    post = MagicMock()
    monkeypatch.setattr(app_module.slack_client, "chat_postMessage", post)

    assert client.post("/admin/leaderboard:send", headers=AUTH).status_code == 200
    text = post.call_args.kwargs["text"]
    assert text.endswith(format_house_leaderboard(build_standings(db.get_leaderboard())))


# ---- page ----

def test_houses_page_is_served_without_auth(client):
    response = client.get("/houses")
    assert response.status_code == 200
    assert "<title>Houses" in response.text
