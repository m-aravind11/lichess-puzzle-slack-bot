import json
import logging
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from slack_sdk import WebClient

import db
from constants import ACTION_OPEN_ANSWER_MODAL, ANSWER_MODAL_CALLBACK_ID, CRON_SECRET, INDEX_HTML_PATH
from daily_puzzle import LichessDailyPuzzle
from interactions import handle_view_submission, open_answer_modal
from slack_helpers import format_leaderboard, get_display_names
from slack_verify import verify_slack_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI()
lichess = LichessDailyPuzzle()
slack_client = WebClient(token=lichess.LICHESS_OAUTH_TOKEN)

@app.get('/')
async def root():
    return FileResponse(INDEX_HTML_PATH)

@app.get('/cron/send-puzzle')
async def cron_send_puzzle(request: Request):
    if CRON_SECRET and request.headers.get('Authorization') != f'Bearer {CRON_SECRET}':
        raise HTTPException(status_code=401, detail="Unauthorized")
    await lichess.handle_puzzle_generation_and_sending()
    return Response(status_code=200)

@app.post('/admin/migrate')
async def run_migrations(request: Request):
    if CRON_SECRET and request.headers.get('Authorization') != f'Bearer {CRON_SECRET}':
        raise HTTPException(status_code=401, detail="Unauthorized")
    db.init_db()
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
            open_answer_modal(slack_client, payload['trigger_id'], action['value'])
        return Response(status_code=200)

    if payload.get('type') == 'view_submission' and payload['view'].get('callback_id') == ANSWER_MODAL_CALLBACK_ID:
        return handle_view_submission(slack_client, lichess, payload)

    return Response(status_code=200)

@app.get('/cron/send-leaderboard')
async def cron_send_leaderboard(request: Request):
    if CRON_SECRET and request.headers.get('Authorization') != f'Bearer {CRON_SECRET}':
        raise HTTPException(status_code=401, detail="Unauthorized")

    board = db.get_leaderboard()
    if not board:
        return Response(status_code=200)

    names = get_display_names(slack_client)
    slack_client.chat_postMessage(
        channel=lichess.SLACK_CHANNEL_ID,
        text=format_leaderboard(board, names),
    )
    return Response(status_code=200)