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
from slack_helpers import (
    format_all_time_leaderboard_post, format_leaderboard_post, format_seconds, format_solution_reveal,
)
from standings import build_all_time_standings, build_standings
from slack_verify import verify_slack_request

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
    # Fail closed on an unset secret; compare_digest to avoid a timing leak.
    return bool(secret) and hmac.compare_digest(
        request.headers.get('Authorization', '').encode(), f'Bearer {secret}'.encode(),
    )


def require_admin_auth(request: Request) -> None:
    if not _bearer_matches(request, Security.ADMIN_SECRET):
        raise HTTPException(status_code=401, detail="Invalid Bearer Token")


def require_cron_auth(request: Request) -> None:
    if not (_bearer_matches(request, Security.CRON_SECRET) or _bearer_matches(request, Security.ADMIN_SECRET)):
        raise HTTPException(status_code=401, detail="Invalid Bearer Token")


@app.get('/')
async def root():
    return FileResponse(Paths.INDEX_HTML_PATH)

# Public pages: they hold no data and call the admin routes with the typed-in secret.
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

    # Resolved now, so a bad id fails here rather than at cron time.
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
            reply_broadcast=True,
        )
    except Exception:
        logger.exception("admin/puzzle:revealSolution failed")
        raise
    return Response(status_code=200)

@app.post('/admin/leaderboard:send', dependencies=[Depends(require_cron_auth)])
async def send_leaderboard():
    try:
        # Before the holiday check, so storing doesn't wait for a puzzle day.
        db.store_finished_months()

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if db.is_holiday(date_str):
            logger.info("admin/leaderboard:send: %s is a holiday, skipping", date_str)
            return Response(status_code=200)

        leaderboard_month = db.get_leaderboard_month()
        board = db.get_leaderboard(leaderboard_month["month"]) if leaderboard_month else []
        if not board:
            logger.info("admin/leaderboard:send: empty leaderboard, nothing to post")
            return Response(status_code=200)

        slack_client.chat_postMessage(
            channel=lichess.SLACK_CHANNEL_ID,
            text=format_leaderboard_post(build_standings(board, **leaderboard_month)),
        )

        # final implies the month was just stored, so all-time includes it.
        if leaderboard_month["final"]:
            slack_client.chat_postMessage(
                channel=lichess.SLACK_CHANNEL_ID,
                text=format_all_time_leaderboard_post(
                    build_all_time_standings(db.get_all_time_leaderboard(), leaderboard_month["month"])
                ),
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
    # bool is an int subclass, so reject it explicitly.
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

def _leaderboard_months(current_month: str | None) -> list:
    months = set(db.list_stored_months())
    if current_month:
        months.add(current_month)
    return sorted(months, reverse=True)

@app.get('/admin/leaderboard/allTime', dependencies=[Depends(require_admin_auth)])
async def get_all_time_leaderboard():
    stored_months = db.list_stored_months()
    standings = build_all_time_standings(db.get_all_time_leaderboard(), stored_months[0] if stored_months else None)
    leaderboard_month = db.get_leaderboard_month()
    return {
        "through": standings["through"],
        "months": _leaderboard_months(leaderboard_month["month"] if leaderboard_month else None),
        "players": [
            {
                "rank": p["rank"],
                "userName": p["name"],
                "house": p["house"],
                "points": p["points"],
                "correct": p["correct"],
                "attempted": p["attempted"],
                "months": p["months"],
            }
            for p in standings["players"]
        ],
        "houses": standings["houses"],
    }

@app.get('/admin/leaderboard', dependencies=[Depends(require_admin_auth)])
async def get_leaderboard(month: str | None = None):
    leaderboard_month = db.get_leaderboard_month()
    current_month = leaderboard_month["month"] if leaderboard_month else None
    stored = month is not None and month != current_month
    if stored:
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
        board = db.get_stored_leaderboard(month)
        if board is None:
            raise HTTPException(status_code=404, detail="No stored leaderboard for that month")
        standings = build_standings(board, month, final=True)
    elif leaderboard_month:
        standings = build_standings(db.get_leaderboard(current_month), **leaderboard_month)
    else:
        standings = build_standings([])

    return {
        "month": standings["month"],
        "final": standings["final"],
        "stored": stored,
        "months": _leaderboard_months(current_month),
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
    # Not date.fromisoformat, which also accepts compact forms like 20240101.
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
    if date < datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        raise HTTPException(status_code=400, detail="date is in the past")
    db.add_holiday(date)
    return {"date": date}

@app.delete('/admin/holidays/{date}', dependencies=[Depends(require_admin_auth)])
async def remove_holiday(date: str):
    if not db.remove_holiday(_parse_holiday_date(date)):
        raise HTTPException(status_code=404, detail="Not a holiday")
    return Response(status_code=200)
