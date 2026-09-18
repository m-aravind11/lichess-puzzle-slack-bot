from unittest.mock import MagicMock

from fastapi import Response

import db
import interactions
from constants import SlackActions


def _payload(moves_text: str, puzzle_id="p1", user_id="U1", user_name="alice") -> dict:
    return {
        "view": {
            "private_metadata": puzzle_id,
            "state": {"values": {SlackActions.MOVES_BLOCK_ID: {SlackActions.MOVES_ACTION_ID: {"value": moves_text}}}},
        },
        "user": {"id": user_id, "username": user_name},
    }


def _puzzle(slack_ts=None) -> dict:
    return {
        "puzzle_id": "p1",
        "sent_on": "2024-01-01",
        "fen": "startpos",
        "solution": ["e4"],
        "slack_ts": slack_ts,
    }


def _slack_client() -> MagicMock:
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D1"}}
    return client


def test_blank_input_returns_generic_error():
    result = interactions.handle_view_submission(_slack_client(), MagicMock(), _payload("   "))
    assert result["errors"][SlackActions.MOVES_BLOCK_ID] == "Enter your own moves e.g. Nf3 Bb5"


def test_invalid_san_token_names_the_bad_move():
    result = interactions.handle_view_submission(_slack_client(), MagicMock(), _payload("Nf3 xyz123"))
    assert "xyz123" in result["errors"][SlackActions.MOVES_BLOCK_ID]


def test_puzzle_not_found_returns_error(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: None)
    result = interactions.handle_view_submission(_slack_client(), MagicMock(), _payload("e4"))
    assert result["errors"][SlackActions.MOVES_BLOCK_ID] == "That puzzle isn't available anymore."


def test_correct_answer_records_submission_and_dms_the_result(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: _puzzle())
    monkeypatch.setattr(db, "record_submission", MagicMock(return_value=db.SubmissionResult.RECORDED))
    monkeypatch.setattr(interactions, "compute_score", lambda correct, elapsed: 7)

    lichess = MagicMock()
    lichess.check_answer.return_value = True
    slack_client = _slack_client()

    result = interactions.handle_view_submission(slack_client, lichess, _payload("e4"))

    assert isinstance(result, Response) and result.status_code == 200
    db.record_submission.assert_called_once_with("p1", "U1", "alice", "e4", True, 7)
    slack_client.chat_postMessage.assert_called_once()
    assert "+7 points" in slack_client.chat_postMessage.call_args.kwargs["text"]


def test_correct_answer_with_a_channel_post_announces_in_thread(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: _puzzle(slack_ts="1700000000.0"))
    monkeypatch.setattr(db, "record_submission", MagicMock(return_value=db.SubmissionResult.RECORDED))
    monkeypatch.setattr(interactions, "compute_score", lambda correct, elapsed: 7)

    lichess = MagicMock()
    lichess.check_answer.return_value = True
    slack_client = _slack_client()

    interactions.handle_view_submission(slack_client, lichess, _payload("e4"))

    # First chat_postMessage is the DM (via dm()), second is the thread announcement.
    assert slack_client.chat_postMessage.call_count == 2
    thread_call = slack_client.chat_postMessage.call_args_list[1]
    assert thread_call.kwargs["thread_ts"] == "1700000000.0"
    assert "<@U1>" in thread_call.kwargs["text"]
    assert "+7 pts" in thread_call.kwargs["text"]


def test_incorrect_answer_does_not_announce_in_thread(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: _puzzle(slack_ts="1700000000.0"))
    monkeypatch.setattr(db, "record_submission", MagicMock(return_value=db.SubmissionResult.RECORDED))

    lichess = MagicMock()
    lichess.check_answer.return_value = False
    slack_client = _slack_client()

    interactions.handle_view_submission(slack_client, lichess, _payload("e4"))

    assert slack_client.chat_postMessage.call_count == 1
    assert "Not quite" in slack_client.chat_postMessage.call_args.kwargs["text"]


def test_duplicate_submission_returns_error_without_dm(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: _puzzle())
    monkeypatch.setattr(db, "record_submission", MagicMock(return_value=db.SubmissionResult.DUPLICATE))

    lichess = MagicMock()
    lichess.check_answer.return_value = True
    slack_client = _slack_client()

    result = interactions.handle_view_submission(slack_client, lichess, _payload("e4"))

    assert result["errors"][SlackActions.MOVES_BLOCK_ID] == "You've already submitted an answer for this puzzle."
    slack_client.chat_postMessage.assert_not_called()


def test_stale_puzzle_returns_error_without_dm(monkeypatch):
    monkeypatch.setattr(db, "get_puzzle", lambda puzzle_id: _puzzle())
    monkeypatch.setattr(db, "record_submission", MagicMock(return_value=db.SubmissionResult.STALE_PUZZLE))

    lichess = MagicMock()
    lichess.check_answer.return_value = True
    slack_client = _slack_client()

    result = interactions.handle_view_submission(slack_client, lichess, _payload("e4"))

    assert "no longer accepting answers" in result["errors"][SlackActions.MOVES_BLOCK_ID]
    slack_client.chat_postMessage.assert_not_called()
