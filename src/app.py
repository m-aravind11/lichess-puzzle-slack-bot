import contextvars
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs

import requests
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slack_sdk import WebClient

import db
from constants import Paths, PuzzleState, Security, SlackActions
from daily_puzzle import LichessDailyPuzzle
from interactions import handle_view_submission, open_answer_modal
from slack_helpers import format_leaderboard, format_solution_reveal
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

@app.post('/admin/dailyPuzzle:send', dependencies=[Depends(require_admin_auth)])
async def send_daily_puzzle(force: bool = False, new_puzzle: bool = Query(False, alias="newPuzzle")):
    try:
        await lichess.handle_puzzle_generation_and_sending(force=force, new_puzzle=new_puzzle)
    except Exception:
        logger.exception("admin/dailyPuzzle:send failed")
        raise
    return Response(status_code=200)

@app.post('/admin/puzzles', dependencies=[Depends(require_admin_auth)])
async def queue_puzzle(request: Request):
    body = await request.json()
    puzzle_id = str(body.get('puzzleId', '')).strip()
    if not puzzle_id:
        raise HTTPException(status_code=400, detail="puzzleId is required")

    # Resolved here, at queue time, so a bad id is rejected immediately instead
    # of silently falling back to a random puzzle when the cron runs.
    try:
        raw_puzzle = lichess.get_puzzle_by_id(puzzle_id)
    except requests.HTTPError:
        raise HTTPException(status_code=502, detail="Could not fetch puzzleId from Lichess")

    fen, resolved_id, solution = lichess.resolve_puzzle(raw_puzzle)
    if not db.queue_puzzle(resolved_id, fen, solution):
        raise HTTPException(status_code=409, detail="Puzzle already exists")
    return Response(status_code=201)

@app.get('/admin/puzzles', dependencies=[Depends(require_admin_auth)])
async def list_puzzles(state: str | None = None):
    if state not in (None, PuzzleState.QUEUED, PuzzleState.POSTED):
        raise HTTPException(status_code=400, detail="state must be 'queued' or 'posted'")
    return [
        {
            "puzzleId": row["puzzle_id"],
            "source": row["source"],
            "addedAt": row["added_at"],
            "postedAt": row["posted_at"],
            "active": bool(row["active"]),
        }
        for row in db.list_puzzles(state)
    ]

@app.post('/admin/migrations:run', dependencies=[Depends(require_admin_auth)])
async def run_migrations():
    try:
        db.init_db()
    except Exception:
        logger.exception("admin/migrations:run failed")
        raise
    return Response(status_code=200)

@app.delete('/admin/submissions/{submission_id}', dependencies=[Depends(require_admin_auth)])
async def delete_submission(submission_id: int):
    if not db.deactivate_submission(submission_id):
        raise HTTPException(status_code=404, detail="Submission not found")
    return Response(status_code=200)

@app.delete('/admin/puzzles/{puzzle_id}', dependencies=[Depends(require_admin_auth)])
async def delete_puzzle(puzzle_id: str):
    result = db.deactivate_puzzle(puzzle_id)
    if result == db.PuzzleResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    if result == db.PuzzleResult.HAS_ACTIVE_SUBMISSIONS:
        raise HTTPException(status_code=409, detail="Puzzle has active submissions")
    return Response(status_code=200)

@app.post('/admin/puzzles/{puzzle_id}:reactivate', dependencies=[Depends(require_admin_auth)])
async def reactivate_puzzle(puzzle_id: str):
    result = db.reactivate_puzzle(puzzle_id)
    if result == db.PuzzleResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    if result == db.PuzzleResult.ALREADY_ACTIVE:
        raise HTTPException(status_code=409, detail="Puzzle is already active")
    return Response(status_code=200)

@app.post('/webhooks/slack')
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

@app.post('/admin/puzzle:revealSolution', dependencies=[Depends(require_admin_auth)])
async def reveal_puzzle_solution():
    # Cron runs this before /admin/leaderboard:send, so the solution lands in-thread
    # for everyone (including people who never answered) just ahead of the leaderboard.
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        puzzle = db.close_active_puzzle(date_str)
        if not puzzle:
            logger.info("admin/puzzle:revealSolution: no open puzzle for %s, nothing to post", date_str)
            return Response(status_code=200)
        if not puzzle['slack_ts']:
            logger.info("admin/puzzle:revealSolution: puzzle %s has no thread to post to", puzzle['puzzle_id'])
            return Response(status_code=200)

        slack_client.chat_postMessage(
            channel=lichess.SLACK_CHANNEL_ID,
            thread_ts=puzzle['slack_ts'],
            text=format_solution_reveal(puzzle),
            # Stays a threaded reply (keeps it attached to the puzzle post) but also
            # surfaces in the main channel feed, for people who never opened the thread.
            reply_broadcast=True,
        )
    except Exception:
        logger.exception("admin/puzzle:revealSolution failed")
        raise
    return Response(status_code=200)

@app.post('/admin/leaderboard:send', dependencies=[Depends(require_admin_auth)])
async def send_leaderboard():
    try:
        board = db.get_leaderboard()
        if not board:
            logger.info("admin/leaderboard:send: empty leaderboard, nothing to post")
            return Response(status_code=200)

        slack_client.chat_postMessage(
            channel=lichess.SLACK_CHANNEL_ID,
            text=format_leaderboard(board),
        )
    except Exception:
        logger.exception("admin/leaderboard:send failed")
        raise
    return Response(status_code=200)