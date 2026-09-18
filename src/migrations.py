import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _table_columns(conn, table: str) -> set:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _0001_create_puzzles_table(conn) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS puzzles (
            puzzle_id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            fen TEXT NOT NULL,
            solution TEXT NOT NULL
        )
    """)


def _0002_create_submissions_table(conn) -> None:
    conn.cursor().execute("""
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


def _0003_add_slack_ts_to_puzzles(conn) -> None:
    if "slack_ts" not in _table_columns(conn, "puzzles"):
        conn.cursor().execute("ALTER TABLE puzzles ADD COLUMN slack_ts TEXT")


def _0004_soft_delete_support_for_submissions(conn) -> None:
    # Replaces the inline UNIQUE(puzzle_id, user_id) from migration 0002, which would
    # block resubmission after a soft-delete (the deactivated row still occupies the
    # unique slot), with a partial index that only constrains active rows.
    if "active" in _table_columns(conn, "submissions"):
        return

    cur = conn.cursor()
    cur.execute("ALTER TABLE submissions RENAME TO submissions_old")
    cur.execute("""
        CREATE TABLE submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            puzzle_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            user_name TEXT,
            moves TEXT NOT NULL,
            correct INTEGER NOT NULL,
            submitted_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    cur.execute("""
        INSERT INTO submissions (id, puzzle_id, user_id, user_name, moves, correct, submitted_at, active)
        SELECT id, puzzle_id, user_id, user_name, moves, correct, submitted_at, 1 FROM submissions_old
    """)
    cur.execute("DROP TABLE submissions_old")
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_submissions_active_unique
        ON submissions(puzzle_id, user_id) WHERE active = 1
    """)


def _0005_add_active_to_puzzles(conn) -> None:
    if "active" not in _table_columns(conn, "puzzles"):
        conn.cursor().execute("ALTER TABLE puzzles ADD COLUMN active INTEGER NOT NULL DEFAULT 1")


def _0006_add_score_to_submissions(conn) -> None:
    if "score" not in _table_columns(conn, "submissions"):
        conn.cursor().execute("ALTER TABLE submissions ADD COLUMN score INTEGER NOT NULL DEFAULT 0")


def _0007_add_puzzle_queue_to_puzzles(conn) -> None:
    # Rebuilds puzzles so queued (not yet sent) puzzles can live in it: date
    # becomes the nullable sent_on (NULL = still queued), which SQLite can't do
    # with an in-place ALTER. sent_at orders puzzles by when they were actually
    # posted, since rowid now reflects when they were added, not sent. Existing
    # rows were all sent, so their date backfills sent_on, sent_at and created_at.
    if "sent_on" in _table_columns(conn, "puzzles"):
        return

    cur = conn.cursor()
    cur.execute("ALTER TABLE puzzles RENAME TO puzzles_old")
    cur.execute("""
        CREATE TABLE puzzles (
            puzzle_id TEXT PRIMARY KEY,
            fen TEXT NOT NULL,
            solution TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sent_on TEXT,
            sent_at TEXT,
            slack_ts TEXT,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    cur.execute("""
        INSERT INTO puzzles (puzzle_id, fen, solution, source, created_at, sent_on, sent_at, slack_ts, active)
        SELECT puzzle_id, fen, solution, 'random', date, date, date, slack_ts, active
        FROM puzzles_old ORDER BY rowid
    """)
    cur.execute("DROP TABLE puzzles_old")


def _0008_simplify_puzzle_timestamps(conn) -> None:
    # Collapses 0007's three time columns into two: added_at (when the row was
    # created) and posted_at (when it went to Slack, NULL = queued). The puzzle's
    # day is just posted_at's date, so sent_on goes. 0007 could only backfill
    # the bare date; slack_ts is the Slack post's epoch time, so rows that have
    # one get their real post time (the latest post, if the puzzle was resent).
    # Pre-queue puzzles were fetched at send time, so added_at is that moment too.
    if "posted_at" in _table_columns(conn, "puzzles"):
        return

    cur = conn.cursor()
    cur.execute("ALTER TABLE puzzles RENAME COLUMN created_at TO added_at")
    cur.execute("ALTER TABLE puzzles RENAME COLUMN sent_at TO posted_at")
    cur.execute("""
        UPDATE puzzles
        SET posted_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', CAST(slack_ts AS REAL), 'unixepoch'),
            added_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', CAST(slack_ts AS REAL), 'unixepoch')
        WHERE slack_ts IS NOT NULL AND length(posted_at) = 10
    """)
    cur.execute("ALTER TABLE puzzles DROP COLUMN sent_on")


MIGRATIONS = [
    ("0001_create_puzzles_table", _0001_create_puzzles_table),
    ("0002_create_submissions_table", _0002_create_submissions_table),
    ("0003_add_slack_ts_to_puzzles", _0003_add_slack_ts_to_puzzles),
    ("0004_soft_delete_support_for_submissions", _0004_soft_delete_support_for_submissions),
    ("0005_add_active_to_puzzles", _0005_add_active_to_puzzles),
    ("0006_add_score_to_submissions", _0006_add_score_to_submissions),
    ("0007_add_puzzle_queue_to_puzzles", _0007_add_puzzle_queue_to_puzzles),
    ("0008_simplify_puzzle_timestamps", _0008_simplify_puzzle_timestamps),
]


def run_migrations(conn) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)

    # One round trip for every already-applied migration, not one per migration -
    # each round trip to Turso is a fresh HTTPS/TLS handshake (no connection
    # pooling at that layer), and this runs on every cold start.
    cur = conn.cursor()
    cur.execute("SELECT name FROM schema_migrations")
    applied = {row[0] for row in cur.fetchall()}

    for name, migrate in MIGRATIONS:
        if name in applied:
            continue

        logger.info("Applying migration: %s", name)
        migrate(conn)
        conn.cursor().execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
            (name, datetime.now(timezone.utc).isoformat()),
        )
