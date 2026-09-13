import json
import logging
import os
import re
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from slack_sdk import WebClient

import db
from daily_puzzle import LichessDailyPuzzle
from slack_helpers import dm, get_display_name
from slack_verify import verify_slack_request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SAN_TOKEN_RE = re.compile(r'^(?:[O0]-[O0](?:-[O0])?|[KQRBN]?[a-h]?[1-8]?[x*]?[a-h][1-8](?:=[QRBN])?)[+#]?$', re.IGNORECASE)
INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), 'static', 'index.html')

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
    return FileResponse(INDEX_HTML_PATH)

@app.post('/submit')
async def submit_response(submission: Submission) -> bool:
    moves=submission.moves.split(' ')
    solution=lichess.get_solution(submission.lichess_puzzle_id)
    return True if moves==solution else False

@app.post('/send_puzzle')
async def send_daily_puzzle():
    await lichess.handle_puzzle_generation_and_sending()
    return "Ok"

@app.delete('/submissions/{submission_id}')
async def delete_submission(submission_id: int):
    if not db.deactivate_submission(submission_id):
        raise HTTPException(status_code=404, detail="Submission not found or already inactive")
    return {"ok": True}

@app.post('/slack/events')
async def slack_events(request: Request):
    body = await verify_slack_request(request)
    payload = json.loads(body)

    if payload.get('type') == 'url_verification':
        return {"challenge": payload['challenge']}

    if request.headers.get('X-Slack-Retry-Num'):
        # Slack re-delivering an event we (probably) already handled - e.g. it didn't
        # get an ack in time. Reprocessing risks the "already answered" DM firing on
        # what the user experiences as their first and only message.
        return {"ok": True}

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
        return {"ok": True}  # not move-like - leave normal thread chatter alone

    puzzle = db.get_puzzle_by_slack_ts(thread_ts)
    if puzzle is None:
        return {"ok": True}

    user_id = event['user']
    puzzle_date = datetime.strptime(puzzle['date'], '%Y-%m-%d').strftime('%B %d, %Y')
    puzzle_link = f"<https://lichess.org/training/{puzzle['puzzle_id']}|Puzzle - {puzzle_date}>"

    if db.has_submitted(puzzle['puzzle_id'], user_id):
        dm(slack_client, user_id, f"You've already submitted an answer for {puzzle_link} - only your first attempt counts.")
        return {"ok": True}

    correct = lichess.check_answer(puzzle['fen'], puzzle['solution'], san_moves)

    if not db.record_submission(puzzle['puzzle_id'], user_id, get_display_name(slack_client, user_id), text, correct):
        return {"ok": True}  # duplicate delivery of the same event, already recorded

    result_text = (
        "That's correct - nice work!" if correct
        else f"Not quite. The solution was: `{' '.join(puzzle['solution'])}`"
    )
    dm(slack_client, user_id, f"{puzzle_link}\nYou answered: `{text}`\n{result_text}")

    return {"ok": True}

@app.post('/slack/leaderboard')
async def leaderboard_command(request: Request):
    await verify_slack_request(request)
    board = db.get_leaderboard()

    if not board:
        return {"response_type": "ephemeral", "text": "No submissions yet."}

    lines = [f"{i + 1}. <@{row['user_id']}> - {row['score']}" for i, row in enumerate(board)]
    header = "*🏆 Leaderboard* _(puzzles solved correctly)_"
    return {"response_type": "in_channel", "text": f"{header}\n" + "\n".join(lines)}