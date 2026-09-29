class PuzzleQueries:
    # Includes queued puzzles - deactivating one just takes it out of the queue.
    GET_ACTIVE_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1"

    # Posted only - what a submission is checked against. Keeping queued rows out
    # also keeps them out of db._puzzle_cache until they've been posted.
    GET_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1 AND posted_at IS NOT NULL"

    # Ignores active - only used to tell "no such puzzle" apart from "already active"
    # after REACTIVATE's conditional update affects no row.
    GET_BY_ID_ANY_STATE = "SELECT 1 FROM puzzles WHERE puzzle_id = ?"

    # A puzzle's day is the date part of posted_at (YYYY-MM-DD, UTC). Queued rows
    # have no posted_at, so they never match.
    #
    # Ignores active - a puzzle deactivated after being posted still counts as
    # "already posted today" for idempotency; only a force resend should bypass it.
    EXISTS_FOR_DATE = "SELECT 1 FROM puzzles WHERE substr(posted_at, 1, 10) = ? LIMIT 1"

    # Active only - the puzzle a force resend re-posts. A deactivated puzzle isn't
    # resent (nothing live to resend), so the caller falls back to generating a
    # fresh one in that case.
    GET_ACTIVE_BY_DATE = """
        SELECT * FROM puzzles WHERE substr(posted_at, 1, 10) = ? AND active = 1
        ORDER BY posted_at DESC, rowid DESC LIMIT 1
    """

    # The puzzle whose solution the reveal cron posts: it runs the day after the
    # puzzle went out, ahead of that day's new puzzle, so it looks strictly before
    # today. Ignores active and closed_at - the caller checks those - so a
    # retriggered reveal finds the same (already closed) puzzle and no-ops,
    # instead of falling through to an older, never-closed one and revealing it.
    GET_LATEST_POSTED_BEFORE_DATE = """
        SELECT * FROM puzzles WHERE posted_at IS NOT NULL AND substr(posted_at, 1, 10) < ?
        ORDER BY posted_at DESC, rowid DESC LIMIT 1
    """

    INSERT_QUEUED = """
        INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, active)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(puzzle_id) DO NOTHING
    """

    # Inserts a freshly fetched puzzle as posted, or marks a queued one posted (and
    # live again, in case it was deactivated while queued). An already-posted row
    # is left untouched, so a resend of the same puzzle_id keeps its original post
    # time and existing submissions stay timed against it.
    UPSERT_POSTED = """
        INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, posted_at, slack_ts, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(puzzle_id) DO UPDATE SET
            posted_at = excluded.posted_at,
            slack_ts = excluded.slack_ts,
            active = 1
        WHERE puzzles.posted_at IS NULL
    """

    # FIFO: the queue is posted in the order puzzles were added.
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

    # Conditional on no active submissions existing for the puzzle, so the common
    # case (safe to delete) is a single atomic round trip instead of a separate
    # check-then-update that could race with a submission landing in between.
    DEACTIVATE_IF_NO_ACTIVE_SUBMISSIONS = """
        UPDATE puzzles SET active = 0
        WHERE puzzle_id = ? AND active = 1
          AND NOT EXISTS (SELECT 1 FROM submissions WHERE puzzle_id = puzzles.puzzle_id AND active = 1)
    """

    REACTIVATE = "UPDATE puzzles SET active = 1 WHERE puzzle_id = ? AND active = 0"

    # No-op (rowcount 0) if already closed, so a retriggered cron doesn't re-post.
    CLOSE_IF_OPEN = "UPDATE puzzles SET closed_at = ? WHERE puzzle_id = ? AND closed_at IS NULL"


class SubmissionQueries:
    # No-op (rowcount 0) if the puzzle isn't active, posted, and still open;
    # duplicate still raises IntegrityError via the partial unique index.
    INSERT_IF_OPEN = """
        INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)
        SELECT ?, ?, ?, ?, ?, ?, ?, 1
        WHERE EXISTS (
            SELECT 1 FROM puzzles WHERE puzzle_id = ? AND active = 1 AND posted_at IS NOT NULL AND closed_at IS NULL
        )
    """

    DEACTIVATE = "UPDATE submissions SET active = 0 WHERE id = ? AND active = 1"


class LeaderboardQueries:
    TOTALS = """
        SELECT user_id, MAX(user_name) AS user_name,
               COUNT(*) AS attempted, SUM(correct) AS correct,
               COUNT(*) - SUM(correct) AS incorrect, SUM(score) AS score
        FROM submissions
        WHERE active = 1
        GROUP BY user_id
    """

    SOLVE_TIMES = """
        SELECT s.user_id, s.submitted_at, p.slack_ts
        FROM submissions s
        JOIN puzzles p ON p.puzzle_id = s.puzzle_id
        WHERE s.active = 1 AND s.correct = 1 AND p.slack_ts IS NOT NULL
    """

    # A streak is consecutive correct answers over posted, active puzzles - not
    # calendar days - so a day nothing was posted, or a deactivated puzzle, leaves
    # no gap. seq numbers those puzzles in post order; within a user's wins,
    # n - ROW_NUMBER() is constant across an unbroken run (gaps-and-islands), so
    # grouping by it yields each run. A run is current if it reaches the latest
    # puzzle - or the one before, while the latest is still open and the user may
    # not have answered it yet. Users with no correct answers get no row.
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
            SELECT n, closed_at IS NULL AS is_open FROM seq ORDER BY n DESC LIMIT 1
        )
        SELECT r.user_id,
               MAX(r.len) AS best_streak,
               COALESCE(MAX(CASE WHEN r.last_n >= l.n - l.is_open THEN r.len END), 0) AS current_streak
        FROM runs r CROSS JOIN latest l
        GROUP BY r.user_id
    """

    # Each player's house - get_leaderboard tags each entry with it. Includes
    # soft-deleted mappings: a player who left the company still counts toward
    # their house's score. Houses never change, but a player who rejoined has
    # more than one row, so take their latest.
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

    # No row back if the name is taken (names are unique, case-insensitively).
    INSERT = "INSERT INTO houses (name) VALUES (?) ON CONFLICT(name) DO NOTHING RETURNING id"


class PlayerQueries:
    # Players are whoever has an active submission; unassigned ones first, since
    # those are the ones that need attention.
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

    # No-op (rowcount 0) if the player already has an active assignment. The
    # conflict target names the partial unique index's WHERE, so inactive
    # (soft-deleted) rows don't block a new one.
    ASSIGN = """
        INSERT INTO player_houses (user_id, house_id, assigned_at, active) VALUES (?, ?, ?, 1)
        ON CONFLICT(user_id) WHERE active = 1 DO NOTHING
    """

    UNASSIGN = "UPDATE player_houses SET active = 0 WHERE user_id = ? AND active = 1"


class HolidayQueries:
    # date is YYYY-MM-DD (UTC), the same day format as substr(posted_at, 1, 10).
    LIST = "SELECT date FROM holidays ORDER BY date"

    EXISTS = "SELECT 1 FROM holidays WHERE date = ?"

    # Idempotent: re-adding a holiday is a no-op, so a range can be re-submitted.
    INSERT = "INSERT INTO holidays (date, added_at) VALUES (?, ?) ON CONFLICT(date) DO NOTHING"

    DELETE = "DELETE FROM holidays WHERE date = ?"
