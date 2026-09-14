GET_ACTIVE_PUZZLE_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1"

INSERT_PUZZLE = """
    INSERT INTO puzzles (puzzle_id, date, fen, solution, slack_ts, active)
    VALUES (?, ?, ?, ?, ?, 1)
"""

GET_PUZZLE_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1"

# No-op (rowcount 0) if puzzle_id isn't the latest active puzzle; duplicate still
# raises IntegrityError via the partial unique index.
INSERT_SUBMISSION_IF_LATEST = """
    INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, score, submitted_at, active)
    SELECT ?, ?, ?, ?, ?, ?, ?, 1
    WHERE ? = (SELECT puzzle_id FROM puzzles WHERE active = 1 ORDER BY date DESC LIMIT 1)
"""

DEACTIVATE_SUBMISSION = """
    UPDATE submissions SET active = 0 WHERE id = ? AND active = 1
"""

# Conditional on no active submissions existing for the puzzle, so the common
# case (safe to delete) is a single atomic round trip instead of a separate
# check-then-update that could race with a submission landing in between.
DEACTIVATE_PUZZLE_IF_NO_ACTIVE_SUBMISSIONS = """
    UPDATE puzzles SET active = 0
    WHERE puzzle_id = ? AND active = 1
      AND NOT EXISTS (SELECT 1 FROM submissions WHERE puzzle_id = puzzles.puzzle_id AND active = 1)
"""

REACTIVATE_PUZZLE = "UPDATE puzzles SET active = 1 WHERE puzzle_id = ? AND active = 0"

# Ignores active - only used to tell "no such puzzle" apart from "already active"
# after REACTIVATE_PUZZLE's conditional update affects no row.
GET_PUZZLE_BY_ID_ANY_STATE = "SELECT 1 FROM puzzles WHERE puzzle_id = ?"

LEADERBOARD_TOTALS = """
    SELECT user_id, MAX(user_name) AS user_name,
           COUNT(*) AS attempted, SUM(correct) AS correct,
           COUNT(*) - SUM(correct) AS incorrect, SUM(score) AS score
    FROM submissions
    WHERE active = 1
    GROUP BY user_id
"""

LEADERBOARD_SOLVE_TIMES = """
    SELECT s.user_id, s.submitted_at, p.slack_ts
    FROM submissions s
    JOIN puzzles p ON p.puzzle_id = s.puzzle_id
    WHERE s.active = 1 AND s.correct = 1 AND p.slack_ts IS NOT NULL
"""
