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
                solution TEXT NOT NULL
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


def save_puzzle(puzzle_id: str, date: str, fen: str, solution: list) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO puzzles (puzzle_id, date, fen, solution) VALUES (?, ?, ?, ?)",
            (puzzle_id, date, fen, json.dumps(solution)),
        )


def get_latest_puzzle() -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM puzzles ORDER BY date DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return {
        "puzzle_id": row["puzzle_id"],
        "date": row["date"],
        "fen": row["fen"],
        "solution": json.loads(row["solution"]),
    }


def has_submitted(puzzle_id: str, user_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM submissions WHERE puzzle_id = ? AND user_id = ?",
            (puzzle_id, user_id),
        ).fetchone()
    return row is not None


def record_submission(puzzle_id: str, user_id: str, user_name: str, moves: str, correct: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, submitted_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (puzzle_id, user_id, user_name, moves, int(correct), datetime.now(timezone.utc).isoformat()),
        )


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
