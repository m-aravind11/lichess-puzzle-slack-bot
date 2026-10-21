import asyncio
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db
import migrations
from constants import Security
from slack_helpers import format_holiday_notice

AUTH = {"Authorization": "Bearer s3cr3t"}


def day(offset: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=offset)).strftime("%Y-%m-%d")


@pytest.fixture
def conn():
    # TestClient runs the async handlers on a worker thread.
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    migrations.run_migrations(connection)
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


def listed(client):
    return [h["date"] for h in client.get("/admin/holidays", headers=AUTH).json()]


def post_puzzle(conn, puzzle_id, date):
    posted_at = f"{date}T11:30:00+00:00"
    conn.execute(
        "INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, closed_at, active)"
        " VALUES (?, 'fen', '[]', 'random', ?, ?, ?, 1)",
        (puzzle_id, posted_at, posted_at, posted_at),
    )
    conn.execute(
        "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)"
        " VALUES (?, 'U1', 'alice', 'e4', 1, 10, ?, 1)",
        (puzzle_id, posted_at),
    )


def test_holidays_are_listed_in_date_order(client):
    for date in (day(3), day(1), day(2)):
        assert client.put(f"/admin/holidays/{date}", headers=AUTH).json() == {"date": date}
    assert listed(client) == [day(1), day(2), day(3)]


def test_adding_a_holiday_twice_is_a_no_op(client):
    assert client.put(f"/admin/holidays/{day(1)}", headers=AUTH).status_code == 200
    assert client.put(f"/admin/holidays/{day(1)}", headers=AUTH).status_code == 200
    assert listed(client) == [day(1)]


def test_today_can_be_a_holiday_but_the_past_cannot(client):
    assert client.put(f"/admin/holidays/{day(0)}", headers=AUTH).status_code == 200
    response = client.put(f"/admin/holidays/{day(-1)}", headers=AUTH)
    assert response.status_code == 400
    assert listed(client) == [day(0)]


@pytest.mark.parametrize("date", ["2030-02-30", "20300101", "tomorrow"])
def test_holiday_date_must_be_yyyy_mm_dd(client, date):
    assert client.put(f"/admin/holidays/{date}", headers=AUTH).status_code == 400
    assert client.delete(f"/admin/holidays/{date}", headers=AUTH).status_code == 400


def test_remove_holiday(client):
    client.put(f"/admin/holidays/{day(1)}", headers=AUTH)
    assert client.delete(f"/admin/holidays/{day(1)}", headers=AUTH).status_code == 200
    assert listed(client) == []
    assert client.delete(f"/admin/holidays/{day(1)}", headers=AUTH).status_code == 404


def test_past_holiday_can_still_be_removed(client, conn):
    conn.execute("INSERT INTO holidays (date, added_at) VALUES (?, 'x')", (day(-5),))
    assert client.delete(f"/admin/holidays/{day(-5)}", headers=AUTH).status_code == 200


@pytest.mark.parametrize("method, path", [
    ("GET", "/admin/holidays"),
    ("PUT", "/admin/holidays/2030-01-01"),
    ("DELETE", "/admin/holidays/2030-01-01"),
])
def test_holiday_routes_require_auth(client, method, path):
    assert client.request(method, path).status_code == 401


def test_holidays_page_is_public(client):
    response = client.get("/holidays")
    assert response.status_code == 200
    assert "<title>Holidays" in response.text


@pytest.fixture
def sent(monkeypatch):
    calls = MagicMock()
    monkeypatch.setattr(app_module.lichess, "_generate_and_send_puzzle", calls.generate)
    monkeypatch.setattr(app_module.lichess, "_resend_puzzle", calls.resend)
    return calls


def send(**flags):
    asyncio.run(app_module.lichess.handle_puzzle_generation_and_sending(**flags))


def test_no_puzzle_is_sent_on_a_holiday(conn, sent):
    db.add_holiday(day(0))
    send()
    sent.generate.assert_not_called()


def test_puzzle_is_sent_on_a_normal_day(conn, sent):
    db.add_holiday(day(1))
    send()
    sent.generate.assert_called_once()


@pytest.mark.parametrize("flags", [{"force": True}, {"new_puzzle": True}])
def test_manual_send_overrides_a_holiday(conn, sent, flags):
    db.add_holiday(day(0))
    send(**flags)
    sent.generate.assert_called_once()


FRIDAY = datetime(2026, 10, 23, 11, 30, tzinfo=timezone.utc)


def test_next_puzzle_date_skips_the_weekend(conn):
    assert app_module.lichess.next_puzzle_date(FRIDAY).strftime("%Y-%m-%d") == "2026-10-26"


def test_next_puzzle_date_skips_upcoming_holidays(conn):
    db.add_holiday("2026-10-26")
    db.add_holiday("2026-10-27")
    assert app_module.lichess.next_puzzle_date(FRIDAY).strftime("%Y-%m-%d") == "2026-10-28"


def test_holiday_notice_is_posted_by_the_reveal_cron(client, conn, slack, monkeypatch):
    monkeypatch.setattr(Security, "CRON_SECRET", "s3cr3t")
    db.add_holiday(day(0))

    assert client.post("/admin/puzzle:revealSolution", headers=AUTH).status_code == 200

    [call] = slack.chat_postMessage.call_args_list
    assert "thread_ts" not in call.kwargs
    assert "No puzzle today due to a holiday" in call.kwargs["text"]


def test_holiday_notice_is_separate_from_the_solution_reveal(client, conn, slack, monkeypatch):
    monkeypatch.setattr(Security, "CRON_SECRET", "s3cr3t")
    monkeypatch.setattr(db, "close_previous_puzzle", MagicMock(return_value={
        "puzzle_id": "p1", "solution": ["e4", "e5", "Qh5"], "slack_ts": "1700000000.0",
    }))
    db.add_holiday(day(0))

    client.post("/admin/puzzle:revealSolution", headers=AUTH)

    reveal, notice = slack.chat_postMessage.call_args_list
    assert reveal.kwargs["thread_ts"] == "1700000000.0"
    assert "thread_ts" not in notice.kwargs
    assert "holiday" in notice.kwargs["text"]


def test_no_holiday_notice_on_a_normal_day(client, conn, slack, monkeypatch):
    monkeypatch.setattr(Security, "CRON_SECRET", "s3cr3t")
    db.add_holiday(day(1))

    client.post("/admin/puzzle:revealSolution", headers=AUTH)

    slack.chat_postMessage.assert_not_called()


def test_holiday_notice_names_the_next_puzzle_day():
    assert "*Monday, October 26*" in format_holiday_notice(datetime(2026, 10, 26))


@pytest.fixture
def slack(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(app_module, "slack_client", fake)
    return fake


def test_leaderboard_is_skipped_on_a_holiday(client, conn, slack):
    post_puzzle(conn, "p1", day(-1))
    db.add_holiday(day(0))

    assert client.post("/admin/leaderboard:send", headers=AUTH).status_code == 200
    slack.chat_postMessage.assert_not_called()


def test_leaderboard_is_posted_on_a_normal_day(client, conn, slack):
    post_puzzle(conn, "p1", day(-1))
    db.add_holiday(day(1))

    client.post("/admin/leaderboard:send", headers=AUTH)
    slack.chat_postMessage.assert_called_once()


def test_holiday_does_not_break_a_streak(conn):
    post_puzzle(conn, "p1", day(-3))
    conn.execute("INSERT INTO holidays (date, added_at) VALUES (?, 'x')", (day(-2),))
    post_puzzle(conn, "p2", day(-1))

    [entry] = db.get_leaderboard(db.get_leaderboard_month()["month"])
    assert entry["current_streak"] == 2
