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
from constants import PuzzleResult, PuzzleSource, PuzzleState, SubmissionResult
from queries import LeaderboardQueries, PuzzleQueries, SubmissionQueries

logger = logging.getLogger(__name__)

TURSO_DATABASE_URL = os.environ['TURSO_DATABASE_URL']
TURSO_AUTH_TOKEN = os.environ['TURSO_AUTH_TOKEN']

# Module-level, so a warm serverless invocation reuses connections from the
# previous request instead of paying a fresh Turso handshake every time.
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
        # Pooled connection's HTTP stream died server-side (idle timeout,
        # redeploy). Drop it instead of returning it to the pool - a poisoned
        # connection would fail the same way for every future invocation.
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
    """A pooled connection can go stale between calls (Turso closes idle HTTP
    streams server-side). get_connection() evicts a stale one on failure, so
    retrying once here gets a fresh connection instead of surfacing a 500."""
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
def save_puzzle(puzzle_id: str, date: str, fen: str, solution: list, slack_ts: str | None = None) -> None:
    """Creates the puzzle row the first time it's posted. A resend of the same
    puzzle_id (e.g. testing, a duplicate cron trigger) is a no-op, so existing
    submissions stay timed against the original post rather than a later one.
    puzzle_id is the primary key, so this also covers a resend after the row
    was soft-deleted (deactivate_puzzle) - the active-only check above won't
    see it, but the row's still there, and the plain INSERT would otherwise
    hit an IntegrityError on that key instead of quietly no-op'ing like every
    other resend does."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.GET_ACTIVE_BY_ID, (puzzle_id,))
        if cur.fetchone() is not None:
            logger.info("save_puzzle: %s already active, no-op", puzzle_id)
            return
        try:
            cur.execute(
                PuzzleQueries.INSERT,
                (puzzle_id, date, fen, json.dumps(solution), slack_ts),
            )
        except turso_serverless.IntegrityError:
            logger.info("save_puzzle: %s already exists (likely deactivated), no-op", puzzle_id)
            return
        logger.info("save_puzzle: inserted %s (date=%s, slack_ts=%s)", puzzle_id, date, slack_ts)


@_retry_stale_connection
def puzzle_sent_for_date(date: str) -> bool:
    """True if any puzzle (active or deactivated) was already posted on this UTC
    date - the daily fetch picks a random puzzle_id each call, so unlike
    save_puzzle's id-based dedup, a retriggered cron needs this date check to
    avoid posting a second, different puzzle for the same day."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.EXISTS_FOR_DATE, (date,))
        return cur.fetchone() is not None


def _row_to_puzzle(row: dict) -> dict:
    return {
        "puzzle_id": row["puzzle_id"],
        "date": row["date"],
        "fen": row["fen"],
        "solution": json.loads(row["solution"]),
        "slack_ts": row["slack_ts"],
    }


@_retry_stale_connection
def get_active_puzzle_by_date(date: str) -> dict | None:
    """The live puzzle for a date, if one is still active - what a force
    resend re-posts instead of fetching a new one from Lichess."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.GET_ACTIVE_BY_DATE, (date,))
        row = cur.fetchone()
        return _row_to_puzzle(_row_to_dict(cur, row)) if row else None


@_retry_stale_connection
def update_puzzle_slack_ts(puzzle_id: str, slack_ts: str | None) -> None:
    """Points a puzzle at its latest Slack post (a resend re-posts to the
    channel, so solve-time scoring should measure from that post, not a
    stale/failed one)."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(PuzzleQueries.UPDATE_SLACK_TS, (slack_ts, puzzle_id))
    if puzzle_id in _puzzle_cache:
        _puzzle_cache[puzzle_id]["slack_ts"] = slack_ts


# Puzzle rows are only ever inserted, never updated (see queries.py) - once
# fetched, a puzzle_id's data can't go stale, so it's safe to cache for the
# life of the process instead of round-tripping to Turso on every submission.
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
    """Records a submission, checking in the same statement that puzzle_id is still
    the latest active puzzle (see SubmissionQueries.INSERT_IF_LATEST) - one Turso round
    trip covering both the staleness check and the write. Returns one of
    SubmissionResult.RECORDED, .DUPLICATE (an active submission already exists for this
    puzzle/user), or .STALE_PUZZLE (a newer puzzle has since been posted). score is
    computed by the caller (see scoring.compute_score) since only it knows the puzzle's
    post time."""
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                SubmissionQueries.INSERT_IF_LATEST,
                (puzzle_id, user_id, user_name, moves, int(correct), score, datetime.now(timezone.utc).isoformat(), puzzle_id),
            )
        except turso_serverless.IntegrityError:
            logger.info("record_submission: duplicate puzzle=%s user=%s", puzzle_id, user_id)
            return SubmissionResult.DUPLICATE

        if cur.rowcount == 0:
            logger.info("record_submission: stale puzzle=%s user=%s (no longer latest)", puzzle_id, user_id)
            return SubmissionResult.STALE_PUZZLE

        logger.info(
            "record_submission: recorded puzzle=%s user=%s correct=%s score=%d",
            puzzle_id, user_id, correct, score,
        )
        return SubmissionResult.RECORDED


@_retry_stale_connection
def deactivate_submission(submission_id: int) -> bool:
    """Soft-deletes a submission by id. Returns True if a row was affected."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(SubmissionQueries.DEACTIVATE, (submission_id,))
        deleted = cur.rowcount > 0
        logger.info("deactivate_submission: id=%s -> %s", submission_id, "deleted" if deleted else "not found")
        return deleted


@_retry_stale_connection
def deactivate_puzzle(puzzle_id: str) -> str:
    """Soft-deletes a puzzle by id, refusing when it still has active submissions
    against it - those submissions' scores and solve times feed the leaderboard,
    so orphaning them would leave it pointing at a puzzle that no longer exists.
    Returns one of PuzzleResult.DEACTIVATED, .NOT_FOUND (no active puzzle with
    this id), or .HAS_ACTIVE_SUBMISSIONS."""
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
    """Reverses deactivate_puzzle. Returns one of PuzzleResult.REACTIVATED,
    .NOT_FOUND (no puzzle with this id exists at all), or .ALREADY_ACTIVE."""
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


@_retry_stale_connection
def get_leaderboard(limit: int = 10) -> list:
    """Ranks by total points (see scoring.compute_score - faster correct answers
    score higher), breaking ties by fastest average solve time (time from puzzle
    post to submission, over correct answers only)."""
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(LeaderboardQueries.TOTALS)
        board = {row["user_id"]: row for row in (_row_to_dict(cur, r) for r in cur.fetchall())}

        cur.execute(LeaderboardQueries.SOLVE_TIMES)
        solve_times = defaultdict(list)
        for row in (_row_to_dict(cur, r) for r in cur.fetchall()):
            seconds = _solve_seconds(row["submitted_at"], row["slack_ts"])
            # A negative value means the puzzle's stored slack_ts was overwritten by a
            # later repost (puzzles.puzzle_id is the primary key) after this submission
            # was recorded against the earlier post - bad data, not a real solve time.
            if seconds >= 0:
                solve_times[row["user_id"]].append(seconds)

    for user_id, entry in board.items():
        times = solve_times.get(user_id)
        entry["avg_solve_seconds"] = sum(times) / len(times) if times else None

    ranked = sorted(
        board.values(),
        key=lambda r: (-r["score"], -r["correct"], r["avg_solve_seconds"] is None, r["avg_solve_seconds"] or 0),
    )
    return ranked[:limit]
