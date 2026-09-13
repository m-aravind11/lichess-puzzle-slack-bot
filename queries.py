SAVE_PUZZLE = """
    INSERT OR REPLACE INTO puzzles (puzzle_id, date, fen, solution, slack_ts)
    VALUES (?, ?, ?, ?, ?)
"""

GET_LATEST_PUZZLE = "SELECT * FROM puzzles ORDER BY date DESC LIMIT 1"

GET_PUZZLE_BY_SLACK_TS = "SELECT * FROM puzzles WHERE slack_ts = ?"

GET_PUZZLE_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ?"

HAS_SUBMITTED = """
    SELECT 1 FROM submissions WHERE puzzle_id = ? AND user_id = ? AND active = 1
"""

INSERT_SUBMISSION = """
    INSERT INTO submissions (puzzle_id, user_id, user_name, moves, correct, submitted_at, active)
    VALUES (?, ?, ?, ?, ?, ?, 1)
"""

DEACTIVATE_SUBMISSION = """
    UPDATE submissions SET active = 0 WHERE id = ? AND active = 1
"""

LEADERBOARD_TOTALS = """
    SELECT user_id, MAX(user_name) AS user_name,
           COUNT(*) AS attempted, SUM(correct) AS correct,
           COUNT(*) - SUM(correct) AS incorrect
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
