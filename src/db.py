import json
import os
import queue
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone

import turso_serverless

import migrations
import queries

TURSO_DATABASE_URL = os.environ['VERCEL_TURSO_TURSO_DATABASE_URL']
TURSO_AUTH_TOKEN = os.environ['VERCEL_TURSO_TURSO_AUTH_TOKEN']

# DB Connection pool
_pool: "queue.Queue" = queue.Queue()


def _acquire_connection():
    try:
        return _pool.get_nowait()
    except queue.Empty:
        return turso_serverless.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)


@contextmanager
def get_connection():
    conn = _acquire_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.put(conn)


def _row_to_dict(cursor, row) -> dict:
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def init_db() -> None:
    with get_connection() as conn:
        migrations.run_migrations(conn)


def save_puzzle(puzzle_id: str, date: str, fen: str, solution: list, slack_ts: str | None = None) -> None:
    """Creates the puzzle row the first time it's posted. A resend of the same
    puzzle_id (e.g. testing, a duplicate cron trigger) is a no-op, so existing
    submissions stay timed against the original post rather than a later one."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(queries.GET_ACTIVE_PUZZLE_BY_ID, (puzzle_id,))
        if cur.fetchone() is not None:
            return
        cur.execute(
            queries.INSERT_PUZZLE,
            (puzzle_id, date, fen, json.dumps(solution), slack_ts),
        )


def _row_to_puzzle(row: dict) -> dict:
    return {
        "puzzle_id": row["puzzle_id"],
        "date": row["date"],
        "fen": row["fen"],
        "solution": json.loads(row["solution"]),
        "slack_ts": row["slack_ts"],
    }


def get_latest_puzzle() -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(queries.GET_LATEST_PUZZLE)
        row = cur.fetchone()
        return _row_to_puzzle(_row_to_dict(cur, row)) if row else None


# Puzzle rows are only ever inserted, never updated (see queries.py) - once
# fetched, a puzzle_id's data can't go stale, so it's safe to cache for the
# life of the process instead of round-tripping to Turso on every submission.
_puzzle_cache: dict = {}


def get_puzzle(puzzle_id: str) -> dict | None:
    if puzzle_id in _puzzle_cache:
        return _puzzle_cache[puzzle_id]

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(queries.GET_PUZZLE_BY_ID, (puzzle_id,))
        row = cur.fetchone()
        puzzle = _row_to_puzzle(_row_to_dict(cur, row)) if row else None

    if puzzle is not None:
        _puzzle_cache[puzzle_id] = puzzle
    return puzzle


def record_submission(puzzle_id: str, user_id: str, user_name: str, moves: str, correct: bool) -> bool:
    """Returns False if the user already has an active submission for this puzzle (no-op), True if recorded."""
    with get_connection() as conn:
        try:
            conn.cursor().execute(
                queries.INSERT_SUBMISSION,
                (puzzle_id, user_id, user_name, moves, int(correct), datetime.now(timezone.utc).isoformat()),
            )
        except turso_serverless.IntegrityError:
            return False
    return True


def deactivate_submission(submission_id: int) -> bool:
    """Soft-deletes a submission by id. Returns True if a row was affected."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(queries.DEACTIVATE_SUBMISSION, (submission_id,))
        return cur.rowcount > 0


def _solve_seconds(submitted_at: str, puzzle_slack_ts: str) -> float:
    posted_at = datetime.fromtimestamp(float(puzzle_slack_ts), tz=timezone.utc)
    submitted_at = datetime.fromisoformat(submitted_at)
    return (submitted_at - posted_at).total_seconds()


def get_leaderboard(limit: int = 10) -> list:
    """Ranks by correct answers, breaking ties by fastest average solve time
    (time from puzzle post to submission, over correct answers only)."""
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(queries.LEADERBOARD_TOTALS)
        board = {row["user_id"]: row for row in (_row_to_dict(cur, r) for r in cur.fetchall())}

        cur.execute(queries.LEADERBOARD_SOLVE_TIMES)
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
        key=lambda r: (-r["correct"], r["avg_solve_seconds"] is None, r["avg_solve_seconds"] or 0),
    )
    return ranked[:limit]
