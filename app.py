import json
import logging
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from slack_sdk import WebClient

import db
from constants import (
    ACTION_OPEN_ANSWER_MODAL,
    ANSWER_MODAL_CALLBACK_ID,
    CRON_SECRET,
    INDEX_HTML_PATH,
    MOVES_ACTION_ID,
    MOVES_BLOCK_ID,
    SAN_TOKEN_RE,
    Submission,
)
from daily_puzzle import LichessDailyPuzzle
from slack_helpers import dm, format_leaderboard, format_result_dm, format_seconds, get_display_name
from slack_verify import verify_slack_request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
lichess = LichessDailyPuzzle()
slack_client = WebClient(token=lichess.LICHESS_OAUTH_TOKEN)

db.init_db()

@app.get('/')
async def root():
    return FileResponse(INDEX_HTML_PATH)

@app.post('/submit')
async def submit_response(submission: Submission) -> bool:
    moves=submission.moves.split(' ')
    solution=lichess.get_solution(submission.lichess_puzzle_id)
    return True if moves==solution else False

@app.post('/send_puzzle')
async def send_daily_puzzle():
    await lichess.handle_puzzle_generation_and_sending()
    return Response(status_code=200)

@app.get('/cron/send-puzzle')
async def cron_send_puzzle(request: Request):
    if CRON_SECRET and request.headers.get('Authorization') != f'Bearer {CRON_SECRET}':
        raise HTTPException(status_code=401, detail="Unauthorized")
    await lichess.handle_puzzle_generation_and_sending()
    return Response(status_code=200)

@app.delete('/submissions/{submission_id}')
async def delete_submission(submission_id: int):
    if not db.deactivate_submission(submission_id):
        raise HTTPException(status_code=404, detail="Submission not found or already inactive")
    return Response(status_code=200)

@app.post('/slack/interactions')
async def slack_interactions(request: Request):
    body = await verify_slack_request(request)
    payload = json.loads(parse_qs(body.decode())['payload'][0])

    if payload.get('type') == 'block_actions':
        action = payload['actions'][0]
        if action.get('action_id') == ACTION_OPEN_ANSWER_MODAL:
            slack_client.views_open(
                trigger_id=payload['trigger_id'],
                view={
                    "type": "modal",
                    "callback_id": ANSWER_MODAL_CALLBACK_ID,
                    "private_metadata": action['value'],  # puzzle_id
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
        return Response(status_code=200)

    if payload.get('type') == 'view_submission' and payload['view'].get('callback_id') == ANSWER_MODAL_CALLBACK_ID:
        puzzle_id = payload['view']['private_metadata']
        user_id = payload['user']['id']
        text = payload['view']['state']['values'][MOVES_BLOCK_ID][MOVES_ACTION_ID]['value'].strip()
        san_moves = text.split()

        if not san_moves or not all(SAN_TOKEN_RE.match(move) for move in san_moves):
            return {
                "response_action": "errors",
                "errors": {MOVES_BLOCK_ID: "Enter your line as SAN moves, e.g. Nf3 Nc6 Bb5"},
            }

        puzzle = db.get_puzzle(puzzle_id)
        if puzzle is None:
            return {"response_action": "errors", "errors": {MOVES_BLOCK_ID: "That puzzle isn't available anymore."}}

        if db.has_submitted(puzzle_id, user_id):
            return {
                "response_action": "errors",
                "errors": {MOVES_BLOCK_ID: "You've already submitted an answer for this puzzle."},
            }

        correct = lichess.check_answer(puzzle['fen'], puzzle['solution'], san_moves)
        user_name = get_display_name(slack_client, user_id)

        if not db.record_submission(puzzle_id, user_id, user_name, text, correct):
            return Response(status_code=200)  # duplicate delivery of the same submission, already recorded

        dm(slack_client, user_id, format_result_dm(puzzle, text, correct))

        if correct and puzzle['slack_ts']:
            posted_at = datetime.fromtimestamp(float(puzzle['slack_ts']), tz=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - posted_at).total_seconds()
            slack_client.chat_postMessage(
                channel=lichess.SLACK_CHANNEL_ID,
                thread_ts=puzzle['slack_ts'],
                text=f"\U0001F389 <@{user_id}> solved it in {format_seconds(elapsed)}!",
            )

        return Response(status_code=200)

    return Response(status_code=200)

@app.post('/slack/leaderboard')
async def leaderboard_command(request: Request):
    await verify_slack_request(request)
    board = db.get_leaderboard()

    if not board:
        return {"response_type": "ephemeral", "text": "No submissions yet."}

    return {"response_type": "in_channel", "text": format_leaderboard(board)}