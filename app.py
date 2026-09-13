import json
import logging
import re

from fastapi import FastAPI, Request
from pydantic import BaseModel
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import db
from daily_puzzle import LichessDailyPuzzle
from slack_verify import verify_slack_request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SAN_TOKEN_RE = re.compile(r'^(?:O-O(?:-O)?|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?)[+#]?$', re.IGNORECASE)

class Submission(BaseModel):
    lichess_puzzle_id: str
    user_id: str
    moves: str

app = FastAPI()
lichess = LichessDailyPuzzle()
slack_client = WebClient(token=lichess.LICHESS_OAUTH_TOKEN)

db.init_db()

@app.get('/')
async def root():
    return {"Message": "Welcome to Lichess bot app home"}

@app.post('/submit')
async def submit_response(submission: Submission) -> bool:
    moves=submission.moves.split(' ')
    solution=lichess.get_solution(submission.lichess_puzzle_id)
    return True if moves==solution else False

@app.post('/send_puzzle')
async def send_daily_puzzle():
    await lichess.handle_puzzle_generation_and_sending()
    return "Ok"

def _dm(user_id: str, text: str) -> None:
    try:
        im = slack_client.conversations_open(users=[user_id])
        slack_client.chat_postMessage(channel=im['channel']['id'], text=text)
    except SlackApiError as e:
        logger.error("Slack DM failed: %s", e.response["error"])
        logger.error("Full response: %s", e.response.data)


@app.post('/slack/events')
async def slack_events(request: Request):
    body = await verify_slack_request(request)
    payload = json.loads(body)

    if payload.get('type') == 'url_verification':
        return {"challenge": payload['challenge']}

    event = payload.get('event', {})

    # Ignore anything that isn't a plain thread reply from a real user
    # (bot's own puzzle post has bot_id/subtype set, and has no thread_ts of its own).
    if event.get('type') != 'message' or event.get('bot_id') or event.get('subtype'):
        return {"ok": True}

    thread_ts = event.get('thread_ts')
    if not thread_ts or thread_ts == event.get('ts'):
        return {"ok": True}

    text = event.get('text', '').strip()
    san_moves = text.split()
    if not san_moves or not all(SAN_TOKEN_RE.match(move) for move in san_moves):
        return {"ok": True}  # not move-like — leave normal thread chatter alone

    puzzle = db.get_puzzle_by_slack_ts(thread_ts)
    if puzzle is None:
        return {"ok": True}

    user_id = event['user']
    if db.has_submitted(puzzle['puzzle_id'], user_id):
        _dm(user_id, "You've already answered this puzzle.")
        return {"ok": True}

    try:
        uci_moves = lichess.convert_san_moves_to_uci(puzzle['fen'], san_moves)
        correct = uci_moves == puzzle['solution']
    except (ValueError, IndexError):
        correct = False

    if not db.record_submission(puzzle['puzzle_id'], user_id, event.get('user'), text, correct):
        return {"ok": True}  # duplicate delivery of the same event, already recorded

    dm_text = "✅ Correct! Well solved." if correct else f"❌ Not quite. Solution: {' '.join(puzzle['solution'])}"
    _dm(user_id, dm_text)

    return {"ok": True}

@app.post('/slack/leaderboard')
async def leaderboard_command(request: Request):
    await verify_slack_request(request)
    board = db.get_leaderboard()

    if not board:
        return {"response_type": "ephemeral", "text": "No submissions yet."}

    lines = [f"{i + 1}. <@{row['user_id']}> — {row['score']}" for i, row in enumerate(board)]
    return {"response_type": "in_channel", "text": "*🏆 Leaderboard*\n" + "\n".join(lines)}