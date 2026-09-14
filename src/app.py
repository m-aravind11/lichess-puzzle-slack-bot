import contextvars
import json
import logging
import os
import uuid
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slack_sdk import WebClient

import db
from constants import Paths, Security, SlackActions
from daily_puzzle import LichessDailyPuzzle
from interactions import handle_view_submission, open_answer_modal
from slack_helpers import format_leaderboard
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
app.mount("/static", StaticFiles(directory=os.path.dirname(Paths.INDEX_HTML_PATH)), name="static")
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
    # Fail closed: an unset CRON_SECRET (misconfigured deploy, accidentally
    # deleted env var) must reject every admin request, not wave them all through.
    if not Security.CRON_SECRET or request.headers.get('Authorization') != f'Bearer {Security.CRON_SECRET}':
        raise HTTPException(status_code=401, detail="Invalid Bearer Token")


@app.get('/')
async def root():
    return FileResponse(Paths.INDEX_HTML_PATH)

@app.get('/cron/send-puzzle', dependencies=[Depends(require_admin_auth)])
async def cron_send_puzzle(force: bool = False, new_puzzle: bool = False):
    try:
        await lichess.handle_puzzle_generation_and_sending(force=force, new_puzzle=new_puzzle)
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
    if result == db.PuzzleResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    if result == db.PuzzleResult.HAS_ACTIVE_SUBMISSIONS:
        raise HTTPException(status_code=409, detail="Puzzle has active submissions")
    return Response(status_code=200)

@app.post('/puzzles/{puzzle_id}/reactivate', dependencies=[Depends(require_admin_auth)])
async def reactivate_puzzle(puzzle_id: str):
    result = db.reactivate_puzzle(puzzle_id)
    if result == db.PuzzleResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    if result == db.PuzzleResult.ALREADY_ACTIVE:
        raise HTTPException(status_code=409, detail="Puzzle is already active")
    return Response(status_code=200)

@app.post('/slack/interactions')
async def slack_interactions(request: Request):
    body = await verify_slack_request(request)
    payload = json.loads(parse_qs(body.decode())['payload'][0])

    if payload.get('type') == 'block_actions':
        action = payload['actions'][0]
        if action.get('action_id') == SlackActions.OPEN_ANSWER_MODAL:
            open_answer_modal(slack_client, payload['trigger_id'], action['value'])
        return Response(status_code=200)

    if payload.get('type') == 'view_submission' and payload['view'].get('callback_id') == SlackActions.ANSWER_MODAL_CALLBACK_ID:
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
            text=format_leaderboard(board),
        )
    except Exception:
        logger.exception("cron/send-leaderboard failed")
        raise
    return Response(status_code=200)