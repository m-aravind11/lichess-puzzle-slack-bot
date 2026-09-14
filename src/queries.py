class PuzzleQueries:
    GET_ACTIVE_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1"

    GET_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1"

    # Ignores active - only used to tell "no such puzzle" apart from "already active"
    # after REACTIVATE's conditional update affects no row.
    GET_BY_ID_ANY_STATE = "SELECT 1 FROM puzzles WHERE puzzle_id = ?"

    # Ignores active - a puzzle deactivated after being sent still counts as
    # "already sent today" for idempotency; only a force resend should bypass it.
    EXISTS_FOR_DATE = "SELECT 1 FROM puzzles WHERE date = ? LIMIT 1"

    # Active only - the puzzle a force resend re-posts. A deactivated puzzle isn't
    # resent (nothing live to resend), so the caller falls back to generating a
    # fresh one in that case.
    GET_ACTIVE_BY_DATE = "SELECT * FROM puzzles WHERE date = ? AND active = 1 ORDER BY rowid DESC LIMIT 1"

    INSERT = """
        INSERT INTO puzzles (puzzle_id, date, fen, solution, slack_ts, active)
        VALUES (?, ?, ?, ?, ?, 1)
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


class SubmissionQueries:
    # No-op (rowcount 0) if puzzle_id isn't the latest active puzzle; duplicate still
    # raises IntegrityError via the partial unique index.
    INSERT_IF_LATEST = """
        INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)
        SELECT ?, ?, ?, ?, ?, ?, ?, 1
        WHERE ? = (SELECT puzzle_id FROM puzzles WHERE active = 1 ORDER BY rowid DESC LIMIT 1)
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
