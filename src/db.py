import functools
import json
import logging
import os
import queue
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone

import turso_serverless

import migrations
from constants import PlayerHouseResult, PuzzleResult, PuzzleSource, PuzzleState, SubmissionResult
from queries import HolidayQueries, HouseQueries, LeaderboardQueries, PlayerQueries, PuzzleQueries, SubmissionQueries

logger = logging.getLogger(__name__)

TURSO_DATABASE_URL = os.environ['TURSO_DATABASE_URL']
TURSO_AUTH_TOKEN = os.environ['TURSO_AUTH_TOKEN']

# Module-level so warm serverless invocations reuse connections.
_pool: "queue.Queue" = queue.Queue()


def _acquire_connection():
    try:
        return _pool.get_nowait()
    except queue.Empty:
        return turso_serverless.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)


@contextmanager
def get_connection():
    conn = _acquire_connection()
    stale = False
    try:
        yield conn
        conn.commit()
    except turso_serverless.OperationalError:
        # Turso closed the stream (idle timeout, redeploy); don't return it to the pool.
        stale = True
        logger.warning("Pooled Turso connection is stale, evicting from pool")
        raise
    except Exception:
        logger.exception("DB operation failed, rolling back")
        conn.rollback()
        raise
    finally:
        if not stale:
            _pool.put(conn)


def _retry_stale_connection(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except turso_serverless.OperationalError:
            logger.warning("Retrying %s after stale connection eviction", fn.__name__)
            return fn(*args, **kwargs)
    return wrapper


def _row_to_dict(cursor, row) -> dict:
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def init_db() -> None:
    with get_connection() as conn:
        migrations.run_migrations(conn)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@_retry_stale_connection
def save_puzzle(puzzle_id: str, fen: str, solution: list, slack_ts: str | None = None) -> None:
    """Resending an already-posted puzzle_id is a no-op."""
    now = _now()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            PuzzleQueries.UPSERT_POSTED,
            (puzzle_id, fen, json.dumps(solution), PuzzleSource.RANDOM, now, now, slack_ts),
        )
        if cur.rowcount == 0:
            logger.info("save_puzzle: %s already posted, no-op", puzzle_id)
            return
        logger.info("save_puzzle: %s posted (posted_at=%s, slack_ts=%s)", puzzle_id, now, slack_ts)


@_retry_stale_connection
def queue_puzzle(puzzle_id: str, fen: str, solution: list) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            PuzzleQueries.INSERT_QUEUED,
            (puzzle_id, fen, json.dumps(solution), PuzzleSource.CURATED, _now()),
        )
        if cur.rowcount == 0:
            logger.info("queue_puzzle: %s already exists, no-op", puzzle_id)
            return False
        logger.info("queue_puzzle: queued %s", puzzle_id)
        return True


@_retry_stale_connection
def get_next_queued_puzzle() -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.GET_NEXT_QUEUED)
        row = cur.fetchone()
        if row is None:
            return None
        puzzle_id, fen, solution = row
        return {"puzzle_id": puzzle_id, "fen": fen, "solution": json.loads(solution)}


_LIST_QUERIES = {
    None: PuzzleQueries.LIST_ALL,
    PuzzleState.QUEUED: PuzzleQueries.LIST_QUEUED,
    PuzzleState.POSTED: PuzzleQueries.LIST_POSTED,
}


@_retry_stale_connection
def list_puzzles(state: str | None = None) -> list:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_LIST_QUERIES[state])
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


@_retry_stale_connection
def puzzle_sent_for_date(date: str) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.EXISTS_FOR_DATE, (date,))
        return cur.fetchone() is not None


def _row_to_puzzle(row: dict) -> dict:
    return {
        "puzzle_id": row["puzzle_id"],
        "posted_at": row["posted_at"],
        "fen": row["fen"],
        "solution": json.loads(row["solution"]),
        "slack_ts": row["slack_ts"],
    }


@_retry_stale_connection
def get_active_puzzle_by_date(date: str) -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.GET_ACTIVE_BY_DATE, (date,))
        row = cur.fetchone()
        return _row_to_puzzle(_row_to_dict(cur, row)) if row else None


@_retry_stale_connection
def close_previous_puzzle(before_date: str) -> dict | None:
    """None if deactivated or already closed, so a retried reveal doesn't re-post."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.GET_LATEST_POSTED_BEFORE_DATE, (before_date,))
        row = cur.fetchone()
        if row is None:
            return None
        row = _row_to_dict(cur, row)
        if not row["active"]:
            logger.info("close_previous_puzzle: %s is deactivated, no-op", row["puzzle_id"])
            return None
        puzzle = _row_to_puzzle(row)

        cur.execute(PuzzleQueries.CLOSE_IF_OPEN, (_now(), puzzle['puzzle_id']))
        if cur.rowcount == 0:
            logger.info("close_previous_puzzle: %s already closed, no-op", puzzle['puzzle_id'])
            return None

        logger.info("close_previous_puzzle: closed %s", puzzle['puzzle_id'])
        return puzzle


@_retry_stale_connection
def update_puzzle_slack_ts(puzzle_id: str, slack_ts: str | None) -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.UPDATE_SLACK_TS, (slack_ts, puzzle_id))
    if puzzle_id in _puzzle_cache:
        _puzzle_cache[puzzle_id]["slack_ts"] = slack_ts


# A posted puzzle's fen/solution never change; update_puzzle_slack_ts refreshes slack_ts.
_puzzle_cache: dict = {}


@_retry_stale_connection
def get_puzzle(puzzle_id: str) -> dict | None:
    if puzzle_id in _puzzle_cache:
        return _puzzle_cache[puzzle_id]

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.GET_BY_ID, (puzzle_id,))
        row = cur.fetchone()
        puzzle = _row_to_puzzle(_row_to_dict(cur, row)) if row else None

    if puzzle is not None:
        _puzzle_cache[puzzle_id] = puzzle
    return puzzle


@_retry_stale_connection
def record_submission(puzzle_id: str, user_id: str, user_name: str, moves: str, correct: bool, score: int) -> str:
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                SubmissionQueries.INSERT_IF_OPEN,
                (puzzle_id, user_id, user_name, moves, int(correct), score, datetime.now(timezone.utc).isoformat(), puzzle_id),
            )
        except turso_serverless.IntegrityError:
            logger.info("record_submission: duplicate puzzle=%s user=%s", puzzle_id, user_id)
            return SubmissionResult.DUPLICATE

        if cur.rowcount == 0:
            logger.info("record_submission: closed puzzle=%s user=%s", puzzle_id, user_id)
            return SubmissionResult.PUZZLE_CLOSED

        logger.info(
            "record_submission: recorded puzzle=%s user=%s correct=%s score=%d",
            puzzle_id, user_id, correct, score,
        )
        return SubmissionResult.RECORDED


@_retry_stale_connection
def deactivate_submission(submission_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(SubmissionQueries.DEACTIVATE, (submission_id,))
        deleted = cur.rowcount > 0
        logger.info("deactivate_submission: id=%s -> %s", submission_id, "deleted" if deleted else "not found")
        return deleted


@_retry_stale_connection
def deactivate_puzzle(puzzle_id: str) -> str:
    """Refuses while the puzzle has active submissions."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.DEACTIVATE_IF_NO_ACTIVE_SUBMISSIONS, (puzzle_id,))
        if cur.rowcount > 0:
            logger.info("deactivate_puzzle: %s -> deactivated", puzzle_id)
            return PuzzleResult.DEACTIVATED

        cur.execute(PuzzleQueries.GET_ACTIVE_BY_ID, (puzzle_id,))
        result = PuzzleResult.HAS_ACTIVE_SUBMISSIONS if cur.fetchone() is not None else PuzzleResult.NOT_FOUND
        logger.info("deactivate_puzzle: %s -> %s", puzzle_id, result)
        return result


@_retry_stale_connection
def reactivate_puzzle(puzzle_id: str) -> str:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.REACTIVATE, (puzzle_id,))
        if cur.rowcount > 0:
            logger.info("reactivate_puzzle: %s -> reactivated", puzzle_id)
            return PuzzleResult.REACTIVATED

        cur.execute(PuzzleQueries.GET_BY_ID_ANY_STATE, (puzzle_id,))
        result = PuzzleResult.ALREADY_ACTIVE if cur.fetchone() is not None else PuzzleResult.NOT_FOUND
        logger.info("reactivate_puzzle: %s -> %s", puzzle_id, result)
        return result


def _solve_seconds(submitted_at: str, puzzle_slack_ts: str) -> float:
    posted_at = datetime.fromtimestamp(float(puzzle_slack_ts), tz=timezone.utc)
    submitted_at = datetime.fromisoformat(submitted_at)
    return (submitted_at - posted_at).total_seconds()


def _utc_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@_retry_stale_connection
def get_leaderboard_month() -> dict | None:
    """The latest posted puzzle's month; final once it's over and its last puzzle closed."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(LeaderboardQueries.LATEST_PUZZLE)
        row = cur.fetchone()
    if row is None:
        return None
    month, is_open = row
    return {"month": month, "final": not is_open and month < _utc_month()}


@_retry_stale_connection
def store_finished_months() -> None:
    """A month is finished once it's over, unless its last puzzle is still open."""
    cutoff = _utc_month()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(LeaderboardQueries.LATEST_PUZZLE)
        latest = cur.fetchone()
        if latest is not None and latest[1]:
            cutoff = min(cutoff, latest[0])

        cur.execute(LeaderboardQueries.UNSTORED_MONTHS_BEFORE, (cutoff,))
        months = [row[0] for row in cur.fetchall()]
        now = _now()
        for month in months:
            board = _month_board(cur, month)
            params = []
            for rank, entry in enumerate(board, start=1):
                params += [
                    month, entry["user_id"], entry["user_name"], rank, entry["score"],
                    entry["correct"], entry["attempted"], entry["avg_solve_seconds"], now,
                ]
            rows = ", ".join([LeaderboardQueries.STORE_MONTH_ROW] * len(board))
            cur.execute(LeaderboardQueries.STORE_MONTH.format(rows=rows), params)
            logger.info("store_finished_months: stored %s (%d players)", month, len(board))


@_retry_stale_connection
def list_stored_months() -> list:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(LeaderboardQueries.STORED_MONTHS)
        return [row[0] for row in cur.fetchall()]


@_retry_stale_connection
def list_unannounced_months() -> list:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(LeaderboardQueries.UNANNOUNCED_MONTHS)
        return [row[0] for row in cur.fetchall()]


@_retry_stale_connection
def mark_months_announced(months: list) -> None:
    now = _now()
    with get_connection() as conn:
        cur = conn.cursor()
        for month in months:
            cur.execute(LeaderboardQueries.MARK_ANNOUNCED, (month, now))


@_retry_stale_connection
def get_stored_leaderboard(month: str) -> list | None:
    """None if the month isn't stored."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(LeaderboardQueries.STORED_MONTH, (month,))
        board = [_row_to_dict(cur, r) for r in cur.fetchall()]
        if not board:
            return None

        cur.execute(LeaderboardQueries.HOUSE_MEMBERS)
        houses = dict(cur.fetchall())

    for entry in board:
        entry["house_name"] = houses.get(entry["user_id"])
        entry["current_streak"] = None
        entry["best_streak"] = None
    return board


@_retry_stale_connection
def get_all_time_leaderboard() -> list:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(LeaderboardQueries.ALL_TIME)
        board = [_row_to_dict(cur, r) for r in cur.fetchall()]

        cur.execute(LeaderboardQueries.HOUSE_MEMBERS)
        houses = dict(cur.fetchall())

    for entry in board:
        entry["house_name"] = houses.get(entry["user_id"])
    return sorted(board, key=lambda r: (-r["score"], -r["correct"], (r["user_name"] or r["user_id"]).lower()))


@_retry_stale_connection
def get_leaderboard(month: str) -> list:
    """Ties broken by more correct, then faster average solve time."""
    with get_connection() as conn:
        return _month_board(conn.cursor(), month)


def _month_board(cur, month: str) -> list:
    cur.execute(LeaderboardQueries.TOTALS, (month,))
    board = {row["user_id"]: row for row in (_row_to_dict(cur, r) for r in cur.fetchall())}

    cur.execute(LeaderboardQueries.SOLVE_TIMES, (month,))
    solve_times = defaultdict(list)
    for row in (_row_to_dict(cur, r) for r in cur.fetchall()):
        seconds = _solve_seconds(row["submitted_at"], row["slack_ts"])
        # Negative: slack_ts was overwritten by a later repost after this submission.
        if seconds >= 0:
            solve_times[row["user_id"]].append(seconds)

    cur.execute(LeaderboardQueries.STREAKS)
    streaks = {row["user_id"]: row for row in (_row_to_dict(cur, r) for r in cur.fetchall())}

    cur.execute(LeaderboardQueries.HOUSE_MEMBERS)
    houses = dict(cur.fetchall())

    for user_id, entry in board.items():
        entry["house_name"] = houses.get(user_id)
        times = solve_times.get(user_id)
        entry["avg_solve_seconds"] = sum(times) / len(times) if times else None
        streak = streaks.get(user_id)
        entry["current_streak"] = streak["current_streak"] if streak else 0
        entry["best_streak"] = streak["best_streak"] if streak else 0

    return sorted(
        board.values(),
        key=lambda r: (-r["score"], -r["correct"], r["avg_solve_seconds"] is None, r["avg_solve_seconds"] or 0),
    )


@_retry_stale_connection
def list_houses() -> list:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(HouseQueries.LIST)
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


@_retry_stale_connection
def create_house(name: str) -> int | None:
    """None if the name is taken."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(HouseQueries.INSERT, (name,))
        row = cur.fetchone()
        if row is None:
            logger.info("create_house: %r already exists, no-op", name)
            return None
        logger.info("create_house: created %r (id=%s)", name, row[0])
        return row[0]


@_retry_stale_connection
def list_players() -> list:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PlayerQueries.LIST)
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


@_retry_stale_connection
def assign_player_house(user_id: str, house_id: int) -> str:
    """A player's house is fixed once assigned."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PlayerQueries.EXISTS, (user_id,))
        if cur.fetchone() is None:
            return PlayerHouseResult.PLAYER_NOT_FOUND

        cur.execute(HouseQueries.EXISTS, (house_id,))
        if cur.fetchone() is None:
            return PlayerHouseResult.HOUSE_NOT_FOUND

        cur.execute(PlayerQueries.ASSIGN, (user_id, house_id, _now()))
        if cur.rowcount > 0:
            logger.info("assign_player_house: user=%s -> house=%s", user_id, house_id)
            return PlayerHouseResult.ASSIGNED

        cur.execute(PlayerQueries.GET_HOUSE, (user_id,))
        current = cur.fetchone()[0]
        result = PlayerHouseResult.ASSIGNED if current == house_id else PlayerHouseResult.ALREADY_ASSIGNED
        logger.info("assign_player_house: user=%s already in house=%s, asked for %s -> %s", user_id, current, house_id, result)
        return result


@_retry_stale_connection
def unassign_player_house(user_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PlayerQueries.UNASSIGN, (user_id,))
        unassigned = cur.rowcount > 0
        logger.info("unassign_player_house: user=%s -> %s", user_id, "unassigned" if unassigned else "not assigned")
        return unassigned


@_retry_stale_connection
def list_holidays() -> list:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(HolidayQueries.LIST)
        return [row[0] for row in cur.fetchall()]


@_retry_stale_connection
def is_holiday(date: str) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(HolidayQueries.EXISTS, (date,))
        return cur.fetchone() is not None


@_retry_stale_connection
def add_holiday(date: str) -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(HolidayQueries.INSERT, (date, _now()))
        logger.info("add_holiday: %s -> %s", date, "added" if cur.rowcount > 0 else "already a holiday")


@_retry_stale_connection
def remove_holiday(date: str) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(HolidayQueries.DELETE, (date,))
        removed = cur.rowcount > 0
        logger.info("remove_holiday: %s -> %s", date, "removed" if removed else "not a holiday")
        return removed
