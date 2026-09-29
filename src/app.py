import contextvars
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs

import requests
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slack_sdk import WebClient

import db
from constants import Paths, PlayerHouseResult, PuzzleState, Security, SlackActions
from daily_puzzle import LichessDailyPuzzle
from interactions import handle_view_submission, open_answer_modal
from slack_helpers import format_leaderboard_post, format_seconds, format_solution_reveal
from standings import build_standings
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


def _bearer_matches(request: Request, secret: str | None) -> bool:
    # Fail closed: an unset secret (misconfigured deploy, accidentally deleted
    # env var) matches nothing, rather than waving every request through.
    # compare_digest, so response time doesn't leak how much of a guess was right.
    return bool(secret) and hmac.compare_digest(
        request.headers.get('Authorization', '').encode(), f'Bearer {secret}'.encode(),
    )


def require_admin_auth(request: Request) -> None:
    # People - the admin pages, curl. ADMIN_SECRET only: the cron's secret
    # never needs to reach a person, and each can be rotated on its own.
    if not _bearer_matches(request, Security.ADMIN_SECRET):
        raise HTTPException(status_code=401, detail="Invalid Bearer Token")


def require_cron_auth(request: Request) -> None:
    # The scheduled routes. ADMIN_SECRET works too, for manual reruns (?force).
    if not (_bearer_matches(request, Security.CRON_SECRET) or _bearer_matches(request, Security.ADMIN_SECRET)):
        raise HTTPException(status_code=401, detail="Invalid Bearer Token")


@app.get('/')
async def root():
    return FileResponse(Paths.INDEX_HTML_PATH)

# These pages are public - they hold no data, and every call they make goes
# through the admin routes below, with the secret the user types in.
@app.get('/houses')
async def houses_page():
    return FileResponse(Paths.HOUSES_HTML_PATH)

@app.get('/leaderboard')
async def leaderboard_page():
    return FileResponse(Paths.LEADERBOARD_HTML_PATH)

@app.get('/holidays')
async def holidays_page():
    return FileResponse(Paths.HOLIDAYS_HTML_PATH)

@app.post('/admin/dailyPuzzle:send', dependencies=[Depends(require_cron_auth)])
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

@app.post('/admin/puzzle:revealSolution', dependencies=[Depends(require_cron_auth)])
async def reveal_puzzle_solution():
    # Cron runs this the day after a puzzle is posted, before /admin/leaderboard:send
    # and the next /admin/dailyPuzzle:send, so the solution lands in-thread for
    # everyone (including people who never answered) just ahead of the leaderboard.
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        puzzle = db.close_previous_puzzle(date_str)
        if not puzzle:
            logger.info("admin/puzzle:revealSolution: no open puzzle posted before %s, nothing to post", date_str)
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

@app.post('/admin/leaderboard:send', dependencies=[Depends(require_cron_auth)])
async def send_leaderboard():
    # Posted only on puzzle days, like the puzzle itself.
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if db.is_holiday(date_str):
        logger.info("admin/leaderboard:send: %s is a holiday, skipping", date_str)
        return Response(status_code=200)

    try:
        board = db.get_leaderboard()
        if not board:
            logger.info("admin/leaderboard:send: empty leaderboard, nothing to post")
            return Response(status_code=200)

        slack_client.chat_postMessage(
            channel=lichess.SLACK_CHANNEL_ID,
            text=format_leaderboard_post(build_standings(board)),
        )
    except Exception:
        logger.exception("admin/leaderboard:send failed")
        raise
    return Response(status_code=200)

@app.get('/admin/houses', dependencies=[Depends(require_admin_auth)])
async def list_houses():
    return [
        {"id": row["id"], "name": row["name"], "memberCount": row["member_count"]}
        for row in db.list_houses()
    ]

@app.post('/admin/houses', dependencies=[Depends(require_admin_auth)])
async def create_house(request: Request):
    name = str((await request.json()).get('name') or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    house_id = db.create_house(name)
    if house_id is None:
        raise HTTPException(status_code=409, detail="A house with that name already exists")
    return JSONResponse(status_code=201, content={"id": house_id, "name": name})

@app.get('/admin/players', dependencies=[Depends(require_admin_auth)])
async def list_players():
    return [
        {
            "userId": row["user_id"],
            "userName": row["user_name"],
            "houseId": row["house_id"],
        }
        for row in db.list_players()
    ]

@app.put('/admin/players/{user_id}/house', dependencies=[Depends(require_admin_auth)])
async def assign_player_house(user_id: str, request: Request):
    house_id = (await request.json()).get('houseId')
    # bool is an int subclass - reject it so `true` doesn't quietly mean house 1.
    if not isinstance(house_id, int) or isinstance(house_id, bool):
        raise HTTPException(status_code=400, detail="houseId must be an integer")

    result = db.assign_player_house(user_id, house_id)
    if result == PlayerHouseResult.PLAYER_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Player not found")
    if result == PlayerHouseResult.HOUSE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="House not found")
    if result == PlayerHouseResult.ALREADY_ASSIGNED:
        raise HTTPException(status_code=409, detail="Player is already in another house")
    return {"userId": user_id, "houseId": house_id}

@app.delete('/admin/players/{user_id}/house', dependencies=[Depends(require_admin_auth)])
async def unassign_player_house(user_id: str):
    if not db.unassign_player_house(user_id):
        raise HTTPException(status_code=404, detail="Player isn't in a house")
    return Response(status_code=200)

@app.get('/admin/leaderboard', dependencies=[Depends(require_admin_auth)])
async def get_leaderboard():
    """The same standings /admin/leaderboard:send posts to Slack, as JSON."""
    standings = build_standings(db.get_leaderboard())
    return {
        "players": [
            {
                "rank": p["rank"],
                "userName": p["name"],
                "house": p["house"],
                "points": p["points"],
                "correct": p["correct"],
                "attempted": p["attempted"],
                "avgSolveTime": format_seconds(p["avg_solve_seconds"]),
                "currentStreak": p["current_streak"],
                "bestStreak": p["best_streak"],
            }
            for p in standings["players"]
        ],
        "houses": standings["houses"],
        "milestones": [
            {"streak": m["streak"], "players": [p["name"] for p in m["players"]]}
            for m in standings["milestones"]
        ],
    }

def _parse_holiday_date(date: str) -> str:
    # strptime rather than date.fromisoformat, which also takes compact forms
    # like 20240101 - rows must match substr(posted_at, 1, 10) exactly.
    try:
        return datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

@app.get('/admin/holidays', dependencies=[Depends(require_admin_auth)])
async def list_holidays():
    return [{"date": date} for date in db.list_holidays()]

@app.put('/admin/holidays/{date}', dependencies=[Depends(require_admin_auth)])
async def add_holiday(date: str):
    date = _parse_holiday_date(date)
    # A past day's puzzle has already gone out (or not), so a holiday there
    # would change nothing. Dates are UTC, like a puzzle's day.
    if date < datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        raise HTTPException(status_code=400, detail="date is in the past")
    db.add_holiday(date)
    return {"date": date}

@app.delete('/admin/holidays/{date}', dependencies=[Depends(require_admin_auth)])
async def remove_holiday(date: str):
    if not db.remove_holiday(_parse_holiday_date(date)):
        raise HTTPException(status_code=404, detail="Not a holiday")
    return Response(status_code=200)
