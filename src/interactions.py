import logging
import time
from datetime import datetime, timezone

from fastapi import Response
from slack_sdk import WebClient

import db
from constants import ANSWER_MODAL_CALLBACK_ID, MOVES_ACTION_ID, MOVES_BLOCK_ID, SAN_TOKEN_RE
from daily_puzzle import LichessDailyPuzzle
from scoring import compute_score
from slack_helpers import dm, format_result_dm, format_seconds

logger = logging.getLogger(__name__)


def open_answer_modal(slack_client: WebClient, trigger_id: str, puzzle_id: str) -> None:
    slack_client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": ANSWER_MODAL_CALLBACK_ID,
            "private_metadata": puzzle_id,
            "title": {"type": "plain_text", "text": "Submit answer"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": MOVES_BLOCK_ID,
                    "label": {"type": "plain_text", "text": "Your line (yours and your opponent's moves, in order)"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": MOVES_ACTION_ID,
                        "placeholder": {"type": "plain_text", "text": "e.g. Nf3 Nc6 Bb5"},
                    },
                }
            ],
        },
    )


def handle_view_submission(slack_client: WebClient, lichess: LichessDailyPuzzle, payload: dict) -> dict | Response:
    t0 = time.monotonic()
    puzzle_id = payload['view']['private_metadata']
    user_id = payload['user']['id']
    text = payload['view']['state']['values'][MOVES_BLOCK_ID][MOVES_ACTION_ID]['value'].strip()
    san_moves = text.split()

    def log_timing(step: str) -> None:
        logger.info("[timing] user=%s puzzle=%s %s: %.3fs", user_id, puzzle_id, step, time.monotonic() - t0)

    if not san_moves or not all(SAN_TOKEN_RE.match(move) for move in san_moves):
        return {
            "response_action": "errors",
            "errors": {MOVES_BLOCK_ID: "Enter your line as SAN moves, e.g. Nf3 Nc6 Bb5"},
        }

    puzzle = db.get_puzzle(puzzle_id)
    log_timing("get_puzzle")
    if puzzle is None:
        return {"response_action": "errors", "errors": {MOVES_BLOCK_ID: "That puzzle isn't available anymore."}}

    correct = lichess.check_answer(puzzle['fen'], puzzle['solution'], san_moves)
    log_timing("check_answer")

    elapsed_seconds = None
    if puzzle['slack_ts']:
        posted_at = datetime.fromtimestamp(float(puzzle['slack_ts']), tz=timezone.utc)
        elapsed_seconds = (datetime.now(timezone.utc) - posted_at).total_seconds()
    score = compute_score(correct, elapsed_seconds)

    # No separate has_submitted()/get_latest_puzzle() pre-checks - record_submission()
    # does both the staleness check and the duplicate check as part of the same insert,
    # since every extra round trip here eats into Slack's 3-second interaction budget.
    result = db.record_submission(puzzle_id, user_id, user_id, text, correct, score)
    log_timing("record_submission")

    if result == db.SUBMISSION_STALE_PUZZLE:
        return {
            "response_action": "errors",
            "errors": {MOVES_BLOCK_ID: "A new puzzle has been posted - this one is no longer accepting answers."},
        }
    if result == db.SUBMISSION_DUPLICATE:
        return {
            "response_action": "errors",
            "errors": {MOVES_BLOCK_ID: "You've already submitted an answer for this puzzle."},
        }

    dm(slack_client, user_id, format_result_dm(puzzle, text, correct, score))
    log_timing("dm")

    if correct and puzzle['slack_ts']:
        slack_client.chat_postMessage(
            channel=lichess.SLACK_CHANNEL_ID,
            thread_ts=puzzle['slack_ts'],
            text=f"\U0001F389 <@{user_id}> solved it in {format_seconds(elapsed_seconds)} (+{score} pts)!",
        )
        log_timing("thread announcement")

    return Response(status_code=200)
