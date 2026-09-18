class PuzzleQueries:
    # Includes queued puzzles - deactivating one just takes it out of the queue.
    GET_ACTIVE_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1"

<<<<<<< HEAD
    # Posted only - what a submission is checked against. Keeping queued rows out
    # also keeps them out of db._puzzle_cache until they've been posted.
    GET_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1 AND posted_at IS NOT NULL"
=======
    # Sent only - what a submission is checked against. Keeping queued rows out
    # also keeps them out of db._puzzle_cache until they've been posted.
    GET_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1 AND sent_on IS NOT NULL"
>>>>>>> c9d52b4794b1ed04867c2634974d4317dbdf6739

    # Ignores active - only used to tell "no such puzzle" apart from "already active"
    # after REACTIVATE's conditional update affects no row.
    GET_BY_ID_ANY_STATE = "SELECT 1 FROM puzzles WHERE puzzle_id = ?"

<<<<<<< HEAD
    # A puzzle's day is the date part of posted_at (YYYY-MM-DD, UTC). Queued rows
    # have no posted_at, so they never match.
    #
    # Ignores active - a puzzle deactivated after being posted still counts as
    # "already posted today" for idempotency; only a force resend should bypass it.
    EXISTS_FOR_DATE = "SELECT 1 FROM puzzles WHERE substr(posted_at, 1, 10) = ? LIMIT 1"
=======
    # Ignores active - a puzzle deactivated after being sent still counts as
    # "already sent today" for idempotency; only a force resend should bypass it.
    EXISTS_FOR_DATE = "SELECT 1 FROM puzzles WHERE sent_on = ? LIMIT 1"
>>>>>>> c9d52b4794b1ed04867c2634974d4317dbdf6739

    # Active only - the puzzle a force resend re-posts. A deactivated puzzle isn't
    # resent (nothing live to resend), so the caller falls back to generating a
    # fresh one in that case.
    GET_ACTIVE_BY_DATE = """
<<<<<<< HEAD
        SELECT * FROM puzzles WHERE substr(posted_at, 1, 10) = ? AND active = 1
        ORDER BY posted_at DESC, rowid DESC LIMIT 1
    """

    INSERT_QUEUED = """
        INSERT INTO puzzles (puzzle_id, fen, solution, source, added_at, active)
=======
        SELECT * FROM puzzles WHERE sent_on = ? AND active = 1
        ORDER BY sent_at DESC, rowid DESC LIMIT 1
    """

    INSERT_QUEUED = """
        INSERT INTO puzzles (puzzle_id, fen, solution, source, created_at, active)
>>>>>>> c9d52b4794b1ed04867c2634974d4317dbdf6739
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(puzzle_id) DO NOTHING
    """

<<<<<<< HEAD
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
=======
    # Inserts a freshly fetched puzzle as sent, or marks a queued one sent (and
    # live again, in case it was deactivated while queued). An already-sent row is
    # left untouched, so a resend of the same puzzle_id keeps its original send
    # time and existing submissions stay timed against it.
    UPSERT_SENT = """
        INSERT INTO puzzles (puzzle_id, fen, solution, source, created_at, sent_on, sent_at, slack_ts, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(puzzle_id) DO UPDATE SET
            sent_on = excluded.sent_on,
            sent_at = excluded.sent_at,
            slack_ts = excluded.slack_ts,
            active = 1
        WHERE puzzles.sent_on IS NULL
    """

    # FIFO: the queue is sent in the order puzzles were added.
    GET_NEXT_QUEUED = """
        SELECT puzzle_id, fen, solution FROM puzzles
        WHERE sent_on IS NULL AND active = 1
        ORDER BY created_at ASC, rowid ASC LIMIT 1
    """

    LIST_ALL = """
        SELECT puzzle_id, source, created_at, sent_on, active FROM puzzles
        ORDER BY created_at ASC, rowid ASC
    """

    LIST_QUEUED = """
        SELECT puzzle_id, source, created_at, sent_on, active FROM puzzles
        WHERE sent_on IS NULL ORDER BY created_at ASC, rowid ASC
    """

    LIST_SENT = """
        SELECT puzzle_id, source, created_at, sent_on, active FROM puzzles
        WHERE sent_on IS NOT NULL ORDER BY sent_at ASC, rowid ASC
>>>>>>> c9d52b4794b1ed04867c2634974d4317dbdf6739
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
<<<<<<< HEAD
    # No-op (rowcount 0) if puzzle_id isn't the latest posted active puzzle;
    # duplicate still raises IntegrityError via the partial unique index. "Latest"
    # is by posted_at, not rowid - a queued puzzle added after today's post has a
    # newer rowid but hasn't been posted yet.
=======
    # No-op (rowcount 0) if puzzle_id isn't the latest sent active puzzle; duplicate
    # still raises IntegrityError via the partial unique index. "Latest" is by
    # sent_at, not rowid - a queued puzzle added after today's post has a newer
    # rowid but hasn't been posted yet.
>>>>>>> c9d52b4794b1ed04867c2634974d4317dbdf6739
    INSERT_IF_LATEST = """
        INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)
        SELECT ?, ?, ?, ?, ?, ?, ?, 1
        WHERE ? = (
<<<<<<< HEAD
            SELECT puzzle_id FROM puzzles WHERE active = 1 AND posted_at IS NOT NULL
            ORDER BY posted_at DESC, rowid DESC LIMIT 1
=======
            SELECT puzzle_id FROM puzzles WHERE active = 1 AND sent_on IS NOT NULL
            ORDER BY sent_at DESC, rowid DESC LIMIT 1
>>>>>>> c9d52b4794b1ed04867c2634974d4317dbdf6739
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
