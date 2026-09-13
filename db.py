import json
import os
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone

import turso_serverless

import migrations
import queries

TURSO_DATABASE_URL = os.environ['TURSO_DATABASE_URL']
TURSO_AUTH_TOKEN = os.environ['TURSO_AUTH_TOKEN']


@contextmanager
def get_connection():
    conn = turso_serverless.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(cursor, row) -> dict:
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def init_db() -> None:
    with get_connection() as conn:
        migrations.run_migrations(conn)


def save_puzzle(puzzle_id: str, date: str, fen: str, solution: list, slack_ts: str | None = None) -> None:
    with get_connection() as conn:
        conn.cursor().execute(
            queries.SAVE_PUZZLE,
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


def get_puzzle_by_slack_ts(slack_ts: str) -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(queries.GET_PUZZLE_BY_SLACK_TS, (slack_ts,))
        row = cur.fetchone()
        return _row_to_puzzle(_row_to_dict(cur, row)) if row else None


def get_puzzle(puzzle_id: str) -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(queries.GET_PUZZLE_BY_ID, (puzzle_id,))
        row = cur.fetchone()
        return _row_to_puzzle(_row_to_dict(cur, row)) if row else None


def has_submitted(puzzle_id: str, user_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(queries.HAS_SUBMITTED, (puzzle_id, user_id))
        return cur.fetchone() is not None


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
            solve_times[row["user_id"]].append(_solve_seconds(row["submitted_at"], row["slack_ts"]))

    for user_id, entry in board.items():
        times = solve_times.get(user_id)
        entry["avg_solve_seconds"] = sum(times) / len(times) if times else None

    ranked = sorted(
        board.values(),
        key=lambda r: (-r["correct"], r["avg_solve_seconds"] is None, r["avg_solve_seconds"] or 0),
    )
    return ranked[:limit]
