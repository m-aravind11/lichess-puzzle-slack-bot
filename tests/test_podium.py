import sqlite3
from contextlib import contextmanager

import pytest

import db
import migrations
from slack_helpers import podium_medal, format_result_dm


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    migrations.run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def patch_connection(conn, monkeypatch):
    @contextmanager
    def fake_get_connection():
        yield conn
        conn.commit()

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    db._puzzle_cache.clear()


def _submit(user_id, correct=True, score=10, puzzle_id="p1"):
    return db.record_submission(puzzle_id, user_id, user_id.lower(), "e4", correct, score)


def _stored(conn, user_id):
    return conn.execute(
        "SELECT score, podium_rank FROM submissions WHERE user_id = ?", (user_id,)
    ).fetchone()


def test_first_five_correct_answers_get_podium_bonus(conn):
    db.save_puzzle("p1", "fen", ["e4"])

    outcomes = [_submit(user) for user in ("U1", "U2", "U3", "U4", "U5", "U6")]

    assert [(o.score, o.podium_rank) for o in outcomes] == [(15, 1), (13, 2), (12, 3), (11, 4), (11, 5), (10, None)]
    assert _stored(conn, "U1") == (15, 1)
    assert _stored(conn, "U6") == (10, None)


def test_bonus_adds_to_the_time_score(conn):
    db.save_puzzle("p1", "fen", ["e4"])
    assert _submit("U1", score=4).score == 9


def test_wrong_answers_do_not_take_a_podium_spot(conn):
    db.save_puzzle("p1", "fen", ["e4"])

    wrong = _submit("U1", correct=False, score=0)
    first = _submit("U2")

    assert (wrong.score, wrong.podium_rank) == (0, None)
    assert (first.score, first.podium_rank) == (15, 1)


def test_deactivated_podium_submission_frees_its_spot(conn):
    db.save_puzzle("p1", "fen", ["e4"])
    _submit("U1")
    submission_id = conn.execute("SELECT id FROM submissions WHERE user_id = 'U1'").fetchone()[0]

    db.deactivate_submission(submission_id)

    assert _submit("U2").podium_rank == 1


def test_podium_is_per_puzzle(conn, monkeypatch):
    monkeypatch.setattr(db, "_now", lambda: "2024-01-01T09:00:00+00:00")
    db.save_puzzle("p1", "fen", ["e4"])
    db.save_puzzle("p2", "fen", ["d4"])

    _submit("U1", puzzle_id="p1")

    assert _submit("U2", puzzle_id="p2").podium_rank == 1


def test_closed_puzzle_gets_no_score_or_rank(conn):
    db.save_puzzle("p1", "fen", ["e4"])
    db.deactivate_puzzle("p1")

    assert _submit("U1") == db.SubmissionOutcome(db.SubmissionResult.PUZZLE_CLOSED)


@pytest.mark.parametrize("rank,expected", [
    (1, ":first_place_medal:"),
    (2, ":second_place_medal:"),
    (3, ":third_place_medal:"),
    (4, ":sports_medal:"),
    (5, ":sports_medal:"),
])
def test_podium_medal(rank, expected):
    assert podium_medal(rank) == expected


def test_result_dm_shows_podium_bonus():
    puzzle = {"puzzle_id": "p1", "posted_at": "2024-01-01T09:00:00+00:00", "solution": ["e4"]}
    text = format_result_dm(puzzle, "e4", True, 13, podium_rank=2)
    assert "+13 points\n:second_place_medal: (+3 podium bonus)" in text


def test_result_dm_without_podium_has_no_bonus_line():
    puzzle = {"puzzle_id": "p1", "posted_at": "2024-01-01T09:00:00+00:00", "solution": ["e4"]}
    assert "podium" not in format_result_dm(puzzle, "e4", True, 10)
