import contextvars
import json
import logging
import uuid
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from slack_sdk import WebClient

import db
from constants import ACTION_OPEN_ANSWER_MODAL, ANSWER_MODAL_CALLBACK_ID, CRON_SECRET, INDEX_HTML_PATH
from daily_puzzle import LichessDailyPuzzle
from interactions import handle_view_submission, open_answer_modal
from slack_helpers import build_leaderboard_blocks, format_leaderboard_fallback
from slack_verify import verify_slack_request

# One id per incoming request, auto-injected into every log line (including ones
# from db.py, slack_verify.py, etc. - anywhere that doesn't have the request in
# scope to pass it explicitly) so concurrent requests' logs can be told apart.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s")
for _handler in logging.root.handlers:
    _handler.addFilter(RequestIdFilter())

logger = logging.getLogger(__name__)

app = FastAPI()
lichess = LichessDailyPuzzle()
slack_client = WebClient(token=lichess.LICHESS_OAUTH_TOKEN)


@app.middleware("http")
async def assign_request_id(request: Request, call_next):
    token = request_id_var.set(uuid.uuid4().hex[:8])
    try:
        return await call_next(request)
    finally:
        request_id_var.reset(token)


def require_admin_auth(request: Request) -> None:
    if CRON_SECRET and request.headers.get('Authorization') != f'Bearer {CRON_SECRET}':
        raise HTTPException(status_code=401, detail="Invalid Bearer Token")


@app.get('/')
async def root():
    return FileResponse(INDEX_HTML_PATH)

@app.get('/cron/send-puzzle', dependencies=[Depends(require_admin_auth)])
async def cron_send_puzzle():
    try:
        await lichess.handle_puzzle_generation_and_sending()
    except Exception:
        logger.exception("cron/send-puzzle failed")
        raise
    return Response(status_code=200)

@app.post('/admin/migrate', dependencies=[Depends(require_admin_auth)])
async def run_migrations():
    try:
        db.init_db()
    except Exception:
        logger.exception("admin/migrate failed")
        raise
    return Response(status_code=200)

@app.delete('/submissions/{submission_id}', dependencies=[Depends(require_admin_auth)])
async def delete_submission(submission_id: int):
    if not db.deactivate_submission(submission_id):
        raise HTTPException(status_code=404, detail="Submission not found")
    return Response(status_code=200)

@app.delete('/puzzles/{puzzle_id}', dependencies=[Depends(require_admin_auth)])
async def delete_puzzle(puzzle_id: str):
    result = db.deactivate_puzzle(puzzle_id)
    if result == db.PUZZLE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    if result == db.PUZZLE_HAS_ACTIVE_SUBMISSIONS:
        raise HTTPException(status_code=409, detail="Puzzle has active submissions")
    return Response(status_code=200)

@app.post('/puzzles/{puzzle_id}/reactivate', dependencies=[Depends(require_admin_auth)])
async def reactivate_puzzle(puzzle_id: str):
    result = db.reactivate_puzzle(puzzle_id)
    if result == db.PUZZLE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    if result == db.PUZZLE_ALREADY_ACTIVE:
        raise HTTPException(status_code=409, detail="Puzzle is already active")
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

@app.get('/cron/send-leaderboard', dependencies=[Depends(require_admin_auth)])
async def cron_send_leaderboard():
    try:
        board = db.get_leaderboard()
        if not board:
            logger.info("cron/send-leaderboard: empty leaderboard, nothing to post")
            return Response(status_code=200)

        slack_client.chat_postMessage(
            channel=lichess.SLACK_CHANNEL_ID,
            text=format_leaderboard_fallback(board),
            blocks=build_leaderboard_blocks(board),
        )
    except Exception:
        logger.exception("cron/send-leaderboard failed")
        raise
    return Response(status_code=200)