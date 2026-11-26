import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
import migrations
from constants import Security
from daily_puzzle import LichessDailyPuzzle
from queries import LeaderboardQueries
from alternative_mates import judge

AUTH = {"Authorization": "Bearer s3cr3t"}
POSTED_TS = 1704110400  # 2024-01-01T12:00:00Z

# Any bishop move uncovers check from b8; Black can only block with ...Rc8, then Rxc8#.
FEN = "1R3B1k/K5pp/2r5/8/8/8/8/8 w - - 0 1"
SOLUTION = ["Be7+", "Rc8", "Rxc8#"]
PUZZLE = {"puzzle_id": "p1", "fen": FEN, "solution": SOLUTION, "slack_ts": str(POSTED_TS)}

lp = LichessDailyPuzzle()


@pytest.mark.parametrize("moves", [["Bd6+", "Rxc8#"], ["Ba3", "Rxc8"], ["bb4", "rxc8"]])
def test_alternative_line_that_forces_mate_is_accepted(moves):
    assert judge(lp, PUZZLE, moves).accepted


@pytest.mark.parametrize("moves, reason", [
    (["Qh5", "Rxc8"], "illegal"),
    (["Bxg7+", "Rxc8"], "escape"),
    (["Rb7", "Rxc8"], "escape"),
    (["Bd6+"], "doesn't mate"),
    (["Bd6+", "Rxc8", "Kb7"], "3 moves"),
    (["Bd6+", "Rb7"], "doesn't mate"),
])
def test_lines_that_do_not_force_mate_are_rejected(moves, reason):
    verdict = judge(lp, PUZZLE, moves)
    assert not verdict.accepted
    assert reason in verdict.reason


def test_the_stored_solution_is_accepted():
    assert judge(lp, PUZZLE, ["Be7", "Rxc8"]).accepted


# Stored line is Qxg6+ Kh8 Rh1+ Qh4 Rxh4#, but ...Qh7 blocks the check just as well.
BLOCK_PUZZLE = {
    "fen": "r4rk1/p3q3/1p2p1p1/3n4/3p4/2P3Q1/PP2NP2/2K3R1 w - - 0 23",
    "solution": ["Qxg6+", "Kh8", "Rh1+", "Qh4", "Rxh4#"],
}


@pytest.mark.parametrize("moves", [["Qxg6+", "Rh1+", "Rxh7#"], ["qg6", "rh1", "qh7"], ["Qg6", "Rh1", "Rh4"]])
def test_line_against_an_equally_good_reply_to_the_recorded_one_is_accepted(moves):
    assert judge(lp, BLOCK_PUZZLE, moves).accepted


@pytest.mark.parametrize("moves", [["Qxg6+", "Qxg7#"], ["Qg6", "Qg7"], ["Qxg6+", "Qxg7", "Rh1#"], ["Qg6", "Rh1", "Rg7"]])
def test_line_that_needs_a_weaker_reply_is_rejected(moves):
    assert not judge(lp, BLOCK_PUZZLE, moves).accepted


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    migrations.run_migrations(connection)
    connection.execute(
        "INSERT INTO puzzles (puzzle_id, fen, solution, added_at, posted_at, slack_ts, active)"
        " VALUES ('p1', ?, ?, '2024-01-01T12:00:00+00:00', '2024-01-01T12:00:00+00:00', ?, 1)",
        (FEN, '["Be7+", "Rc8", "Rxc8#"]', str(POSTED_TS)),
    )
    yield connection
    connection.close()


@pytest.fixture
def client(conn, monkeypatch, slack):
    @contextmanager
    def fake_get_connection():
        yield conn
        conn.commit()

    monkeypatch.setattr(db, "get_connection", fake_get_connection)
    monkeypatch.setattr(db, "_puzzle_cache", {})
    monkeypatch.setattr(Security, "ADMIN_SECRET", "s3cr3t")
    monkeypatch.setattr(app_module.lichess, "SLACK_CHANNEL_ID", "C1")
    return TestClient(app_module.app)


@pytest.fixture
def slack(monkeypatch):
    client = MagicMock()
    client.conversations_open.side_effect = lambda users: {"channel": {"id": f"D-{users[0]}"}}
    monkeypatch.setattr(app_module, "slack_client", client)
    return client


def dms(slack):
    return {
        c.kwargs["channel"]: c.kwargs["text"]
        for c in slack.chat_postMessage.call_args_list if c.kwargs["channel"].startswith("D-")
    }


def thread_posts(slack):
    return [c.kwargs for c in slack.chat_postMessage.call_args_list if c.kwargs["channel"] == "C1"]


def submit(conn, user_id, moves, correct, score, minutes, attempt=1, podium_rank=None):
    conn.execute(
        "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, podium_rank, attempt,"
        " submitted_at, active) VALUES ('p1', ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (user_id, user_id.lower(), moves, correct, score, podium_rank, attempt,
         f"2024-01-01T12:{minutes:02d}:00+00:00"),
    )


def rows(conn):
    return {
        (user_id, attempt): (correct, score, podium_rank, active)
        for user_id, attempt, correct, score, podium_rank, active in conn.execute(
            "SELECT user_id, attempt, correct, score, podium_rank, active FROM submissions"
        )
    }


def test_updates_scores_without_touching_podiums(client, conn):
    submit(conn, "SOLVER", "Be7 Rxc8", 1, 15, minutes=2, podium_rank=1)
    submit(conn, "ALT", "Bd6 Rxc8", 0, 0, minutes=5)
    submit(conn, "ALT_THEN_SOLVED", "Bc5 Rxc8", 0, 0, minutes=6)
    submit(conn, "ALT_THEN_SOLVED", "Be7 Rxc8", 1, 4.5, minutes=25, attempt=2)
    submit(conn, "ALT_THEN_WRONG", "Bb4 Rxc8", 0, 0, minutes=7)
    submit(conn, "ALT_THEN_WRONG", "Rb7", 0, 0, minutes=8, attempt=2)
    submit(conn, "WRONG_THEN_ALT", "Rb7", 0, 0, minutes=3)
    submit(conn, "WRONG_THEN_ALT", "Ba3 Rxc8", 0, 0, minutes=25, attempt=2)
    submit(conn, "WRONG", "Bxg7 Rxc8", 0, 0, minutes=4)

    response = client.post("/admin/puzzles/p1:acceptAlternativeMates", headers=AUTH)

    assert response.status_code == 200
    assert {c["userId"] for c in response.json()["changes"]} == {
        "ALT", "ALT_THEN_SOLVED", "ALT_THEN_WRONG", "WRONG_THEN_ALT",
    }
    assert rows(conn) == {
        ("SOLVER", 1): (1, 15, 1, 1),
        ("ALT", 1): (1, 10, None, 1),
        ("ALT_THEN_SOLVED", 1): (1, 10, None, 1),
        ("ALT_THEN_SOLVED", 2): (0, 0, None, 1),
        ("ALT_THEN_WRONG", 1): (1, 10, None, 1),
        ("ALT_THEN_WRONG", 2): (0, 0, None, 1),
        ("WRONG_THEN_ALT", 1): (0, 0, None, 1),
        ("WRONG_THEN_ALT", 2): (1, 4.5, None, 1),
        ("WRONG", 1): (0, 0, None, 1),
    }


def test_is_idempotent(client, conn):
    submit(conn, "ALT", "Bd6 Rxc8", 0, 0, minutes=5)
    submit(conn, "ALT_THEN_SOLVED", "Bc5 Rxc8", 0, 0, minutes=6)
    submit(conn, "ALT_THEN_SOLVED", "Be7 Rxc8", 1, 4.5, minutes=25, attempt=2)

    client.post("/admin/puzzles/p1:acceptAlternativeMates", headers=AUTH)
    after_first = rows(conn)
    response = client.post("/admin/puzzles/p1:acceptAlternativeMates", headers=AUTH)

    assert response.json()["changes"] == []
    assert rows(conn) == after_first


def test_dry_run_reports_changes_without_writing(client, conn):
    submit(conn, "ALT", "Bd6 Rxc8", 0, 0, minutes=5)

    response = client.post("/admin/puzzles/p1:acceptAlternativeMates?dryRun=true", headers=AUTH)

    assert [c["score"] for c in response.json()["changes"]] == [10]
    assert rows(conn) == {("ALT", 1): (0, 0, None, 1)}


def test_accepted_solve_keeps_the_streak(client, conn):
    submit(conn, "ALT", "Bd6 Rxc8", 0, 0, minutes=5)

    client.post("/admin/puzzles/p1:acceptAlternativeMates", headers=AUTH)

    streaks = {row[0]: row[2] for row in conn.execute(LeaderboardQueries.STREAKS)}
    assert streaks == {"ALT": 1}


def test_unknown_puzzle_is_404(client):
    assert client.post("/admin/puzzles/nope:acceptAlternativeMates", headers=AUTH).status_code == 404


def test_requires_admin_auth(client):
    assert client.post("/admin/puzzles/p1:acceptAlternativeMates").status_code == 401


def test_new_solvers_get_a_dm_and_one_thread_announcement(client, conn, slack):
    submit(conn, "ALT", "Bd6 Rxc8", 0, 0, minutes=5)
    submit(conn, "ALT_THEN_SOLVED", "Bc5 Rxc8", 0, 0, minutes=6)
    submit(conn, "ALT_THEN_SOLVED", "Be7 Rxc8", 1, 4.5, minutes=25, attempt=2)
    submit(conn, "WRONG", "Bxg7 Rxc8", 0, 0, minutes=4)

    client.post("/admin/puzzles/p1:acceptAlternativeMates", headers=AUTH)

    sent = dms(slack)
    assert set(sent) == {"D-ALT", "D-ALT_THEN_SOLVED"}
    assert "another forced mate" in sent["D-ALT"] and "+10 points" in sent["D-ALT"]
    assert "+10 points" in sent["D-ALT_THEN_SOLVED"]
    assert [(p["thread_ts"], p["text"]) for p in thread_posts(slack)] == [(
        str(POSTED_TS),
        ":tada: *Another way to mate!* These players found a different forced mate, and their answers now count:\n"
        "• <@ALT> solved it in 5m 0s (+10 pts)\n"
        "• <@ALT_THEN_SOLVED> solved it in 6m 0s (+10 pts)",
    )]


def test_dry_run_and_rerun_send_nothing(client, conn, slack):
    submit(conn, "ALT", "Bd6 Rxc8", 0, 0, minutes=5)

    client.post("/admin/puzzles/p1:acceptAlternativeMates?dryRun=true", headers=AUTH)
    assert not slack.chat_postMessage.called

    client.post("/admin/puzzles/p1:acceptAlternativeMates", headers=AUTH)
    slack.reset_mock()
    client.post("/admin/puzzles/p1:acceptAlternativeMates", headers=AUTH)
    assert not slack.chat_postMessage.called
