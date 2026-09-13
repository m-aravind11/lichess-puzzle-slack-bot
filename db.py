import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get('DB_PATH', 'db.sqlite3')


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS puzzles (
                puzzle_id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                fen TEXT NOT NULL,
                solution TEXT NOT NULL,
                slack_ts TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                puzzle_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT,
                moves TEXT NOT NULL,
                correct INTEGER NOT NULL,
                submitted_at TEXT NOT NULL,
                UNIQUE(puzzle_id, user_id)
            )
        """)
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(puzzles)")}
        if "slack_ts" not in existing_columns:
            conn.execute("ALTER TABLE puzzles ADD COLUMN slack_ts TEXT")


def save_puzzle(puzzle_id: str, date: str, fen: str, solution: list, slack_ts: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO puzzles (puzzle_id, date, fen, solution, slack_ts) VALUES (?, ?, ?, ?, ?)",
            (puzzle_id, date, fen, json.dumps(solution), slack_ts),
        )


def _row_to_puzzle(row: sqlite3.Row) -> dict:
    return {
        "puzzle_id": row["puzzle_id"],
        "date": row["date"],
        "fen": row["fen"],
        "solution": json.loads(row["solution"]),
        "slack_ts": row["slack_ts"],
    }


def get_latest_puzzle() -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM puzzles ORDER BY date DESC LIMIT 1").fetchone()
    return _row_to_puzzle(row) if row else None


def get_puzzle_by_slack_ts(slack_ts: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM puzzles WHERE slack_ts = ?", (slack_ts,)).fetchone()
    return _row_to_puzzle(row) if row else None


def has_submitted(puzzle_id: str, user_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM submissions WHERE puzzle_id = ? AND user_id = ?",
            (puzzle_id, user_id),
        ).fetchone()
    return row is not None


def record_submission(puzzle_id: str, user_id: str, user_name: str, moves: str, correct: bool) -> bool:
    """Returns False if the user already submitted for this puzzle (no-op), True if recorded."""
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, submitted_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (puzzle_id, user_id, user_name, moves, int(correct), datetime.now(timezone.utc).isoformat()),
            )
        except sqlite3.IntegrityError:
            return False
    return True


def get_leaderboard(limit: int = 10) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT user_id, MAX(user_name) AS user_name, SUM(correct) AS score
            FROM submissions
            GROUP BY user_id
            ORDER BY score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [{"user_id": r["user_id"], "user_name": r["user_name"], "score": r["score"]} for r in rows]
