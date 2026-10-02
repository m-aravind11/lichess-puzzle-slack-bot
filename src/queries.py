class PuzzleQueries:
    GET_ACTIVE_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1"

    # Posted only, which also keeps queued rows out of db._puzzle_cache.
    GET_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1 AND posted_at IS NOT NULL"

    GET_BY_ID_ANY_STATE = "SELECT 1 FROM puzzles WHERE puzzle_id = ?"

    # Ignores active: a puzzle deactivated after posting still counts as posted that day.
    EXISTS_FOR_DATE = "SELECT 1 FROM puzzles WHERE substr(posted_at, 1, 10) = ? LIMIT 1"

    GET_ACTIVE_BY_DATE = """
        SELECT * FROM puzzles WHERE substr(posted_at, 1, 10) = ? AND active = 1
        ORDER BY posted_at DESC, rowid DESC LIMIT 1
    """

    # Ignores active and closed_at so a retried reveal finds the same, already
    # closed puzzle and no-ops, rather than revealing an older one.
    GET_LATEST_POSTED_BEFORE_DATE = """
        SELECT * FROM puzzles WHERE posted_at IS NOT NULL AND substr(posted_at, 1, 10) < ?
        ORDER BY posted_at DESC, rowid DESC LIMIT 1
    """

    INSERT_QUEUED = """
        INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, active)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(puzzle_id) DO NOTHING
    """

    # An already-posted row is left untouched, so a resend keeps its original post time.
    UPSERT_POSTED = """
        INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, slack_ts, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(puzzle_id) DO UPDATE SET
            posted_at = excluded.posted_at,
            slack_ts = excluded.slack_ts,
            active = 1
        WHERE puzzles.posted_at IS NULL
    """

    GET_NEXT_QUEUED = """
        SELECT puzzle_id, fen, solution FROM puzzles
        WHERE posted_at IS NULL AND active = 1
        ORDER BY added_at ASC, rowid ASC LIMIT 1
    """

    LIST_ALL = """
        SELECT puzzle_id, source, added_at, posted_at, active FROM puzzles
        ORDER BY added_at ASC, rowid ASC
    """

    LIST_QUEUED = """
        SELECT puzzle_id, source, added_at, posted_at, active FROM puzzles
        WHERE posted_at IS NULL ORDER BY added_at ASC, rowid ASC
    """

    LIST_POSTED = """
        SELECT puzzle_id, source, added_at, posted_at, active FROM puzzles
        WHERE posted_at IS NOT NULL ORDER BY posted_at ASC, rowid ASC
    """

    UPDATE_SLACK_TS = "UPDATE puzzles SET slack_ts = ? WHERE puzzle_id = ?"

    # One statement, so it can't race a submission landing in between.
    DEACTIVATE_IF_NO_ACTIVE_SUBMISSIONS = """
        UPDATE puzzles SET active = 0
        WHERE puzzle_id = ? AND active = 1
          AND NOT EXISTS (SELECT 1 FROM submissions WHERE puzzle_id = puzzles.puzzle_id AND active = 1)
    """

    REACTIVATE = "UPDATE puzzles SET active = 1 WHERE puzzle_id = ? AND active = 0"

    CLOSE_IF_OPEN = "UPDATE puzzles SET closed_at = ? WHERE puzzle_id = ? AND closed_at IS NULL"


class SubmissionQueries:
    # A duplicate raises IntegrityError via the partial unique index.
    INSERT_IF_OPEN = """
        INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)
        SELECT ?, ?, ?, ?, ?, ?, ?, 1
        WHERE EXISTS (
            SELECT 1 FROM puzzles WHERE puzzle_id = ? AND active = 1 AND posted_at IS NOT NULL AND closed_at IS NULL
        )
    """

    DEACTIVATE = "UPDATE submissions SET active = 0 WHERE id = ? AND active = 1"


class LeaderboardQueries:
    # A submission counts toward its puzzle's month, substr(posted_at, 1, 7), not
    # the month it was submitted in.
    LATEST_PUZZLE = """
        SELECT substr(posted_at, 1, 7) AS month, closed_at IS NULL AS is_open FROM puzzles
        WHERE posted_at IS NOT NULL AND active = 1
        ORDER BY posted_at DESC, rowid DESC LIMIT 1
    """

    TOTALS = """
        SELECT s.user_id, MAX(s.user_name) AS user_name,
               COUNT(*) AS attempted, SUM(s.correct) AS correct,
               COUNT(*) - SUM(s.correct) AS incorrect, SUM(s.score) AS score
        FROM submissions s
        JOIN puzzles p ON p.puzzle_id = s.puzzle_id
        WHERE s.active = 1 AND substr(p.posted_at, 1, 7) = ?
        GROUP BY s.user_id
    """

    SOLVE_TIMES = """
        SELECT s.user_id, s.submitted_at, p.slack_ts
        FROM submissions s
        JOIN puzzles p ON p.puzzle_id = s.puzzle_id
        WHERE s.active = 1 AND s.correct = 1 AND p.slack_ts IS NOT NULL AND substr(p.posted_at, 1, 7) = ?
    """

    UNSTORED_MONTHS_BEFORE = """
        SELECT DISTINCT substr(p.posted_at, 1, 7) AS month
        FROM submissions s
        JOIN puzzles p ON p.puzzle_id = s.puzzle_id
        WHERE s.active = 1 AND substr(p.posted_at, 1, 7) < ?
          AND substr(p.posted_at, 1, 7) NOT IN (SELECT month FROM monthly_scores)
        ORDER BY month
    """

    # {rows} is one STORE_MONTH_ROW per player.
    STORE_MONTH = """
        INSERT INTO monthly_scores
            (month, user_id, user_name, rank, points, correct, attempted, avg_solve_seconds, stored_at)
        VALUES {rows}
        ON CONFLICT(month, user_id) DO NOTHING
    """
    STORE_MONTH_ROW = "(?, ?, ?, ?, ?, ?, ?, ?, ?)"

    STORED_MONTHS = "SELECT DISTINCT month FROM monthly_scores ORDER BY month DESC"

    UNANNOUNCED_MONTHS = """
        SELECT DISTINCT month FROM monthly_scores
        WHERE month NOT IN (SELECT month FROM announced_months)
        ORDER BY month
    """

    MARK_ANNOUNCED = "INSERT INTO announced_months (month, announced_at) VALUES (?, ?) ON CONFLICT(month) DO NOTHING"

    STORED_MONTH = """
        SELECT user_id, user_name, attempted, correct, attempted - correct AS incorrect,
               points AS score, avg_solve_seconds
        FROM monthly_scores
        WHERE month = ?
        ORDER BY rank
    """

    # user_name comes from the latest month, in case it changed.
    ALL_TIME = """
        SELECT m.user_id,
               (SELECT l.user_name FROM monthly_scores l WHERE l.user_id = m.user_id
                ORDER BY l.month DESC LIMIT 1) AS user_name,
               SUM(m.points) AS score, SUM(m.correct) AS correct, SUM(m.attempted) AS attempted,
               COUNT(*) AS months
        FROM monthly_scores m
        GROUP BY m.user_id
    """

    # Gaps-and-islands over active posted puzzles in post order. A run is current
    # if it reaches the latest puzzle, or the one before while the latest is open
    # and unanswered (one answer per puzzle, so a wrong one already broke it).
    STREAKS = """
        WITH seq AS (
            SELECT puzzle_id, closed_at,
                   ROW_NUMBER() OVER (ORDER BY posted_at, rowid) AS n
            FROM puzzles WHERE posted_at IS NOT NULL AND active = 1
        ),
        wins AS (
            SELECT s.user_id, seq.n,
                   seq.n - ROW_NUMBER() OVER (PARTITION BY s.user_id ORDER BY seq.n) AS run
            FROM submissions s JOIN seq ON seq.puzzle_id = s.puzzle_id
            WHERE s.active = 1 AND s.correct = 1
        ),
        runs AS (
            SELECT user_id, COUNT(*) AS len, MAX(n) AS last_n FROM wins GROUP BY user_id, run
        ),
        latest AS (
            SELECT n, puzzle_id, closed_at IS NULL AS is_open FROM seq ORDER BY n DESC LIMIT 1
        ),
        answered_latest AS (
            SELECT DISTINCT s.user_id FROM submissions s JOIN latest l ON l.puzzle_id = s.puzzle_id
            WHERE s.active = 1
        )
        SELECT r.user_id,
               MAX(r.len) AS best_streak,
               COALESCE(MAX(CASE WHEN r.last_n >= l.n - (l.is_open AND a.user_id IS NULL) THEN r.len END), 0)
                   AS current_streak
        FROM runs r CROSS JOIN latest l
        LEFT JOIN answered_latest a ON a.user_id = r.user_id
        GROUP BY r.user_id
    """

    # Includes soft-deleted rows so leavers still count for their house; a
    # rejoiner's latest row wins.
    HOUSE_MEMBERS = """
        SELECT ph.user_id, h.name AS house_name
        FROM player_houses ph JOIN houses h ON h.id = ph.house_id
        WHERE ph.id = (SELECT MAX(id) FROM player_houses WHERE user_id = ph.user_id)
    """


class HouseQueries:
    LIST = """
        SELECT h.id, h.name, COUNT(ph.user_id) AS member_count
        FROM houses h LEFT JOIN player_houses ph ON ph.house_id = h.id AND ph.active = 1
        GROUP BY h.id
        ORDER BY h.name
    """

    EXISTS = "SELECT 1 FROM houses WHERE id = ?"

    INSERT = "INSERT INTO houses (name) VALUES (?) ON CONFLICT(name) DO NOTHING RETURNING id"


class PlayerQueries:
    LIST = """
        SELECT s.user_id, MAX(s.user_name) AS user_name, MAX(ph.house_id) AS house_id
        FROM submissions s
        LEFT JOIN player_houses ph ON ph.user_id = s.user_id AND ph.active = 1
        WHERE s.active = 1
        GROUP BY s.user_id
        ORDER BY MAX(ph.house_id) IS NOT NULL, MAX(s.user_name) COLLATE NOCASE
    """

    EXISTS = "SELECT 1 FROM submissions WHERE user_id = ? AND active = 1 LIMIT 1"

    GET_HOUSE = "SELECT house_id FROM player_houses WHERE user_id = ? AND active = 1"

    # The conflict target repeats the partial index's WHERE, so soft-deleted rows don't block.
    ASSIGN = """
        INSERT INTO player_houses (user_id, house_id, assigned_at, active) VALUES (?, ?, ?, 1)
        ON CONFLICT(user_id) WHERE active = 1 DO NOTHING
    """

    UNASSIGN = "UPDATE player_houses SET active = 0 WHERE user_id = ? AND active = 1"


class HolidayQueries:
    LIST = "SELECT date FROM holidays ORDER BY date"

    EXISTS = "SELECT 1 FROM holidays WHERE date = ?"

    INSERT = "INSERT INTO holidays (date, added_at) VALUES (?, ?) ON CONFLICT(date) DO NOTHING"

    DELETE = "DELETE FROM holidays WHERE date = ?"
