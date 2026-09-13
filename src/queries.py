GET_ACTIVE_PUZZLE_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1"

INSERT_PUZZLE = """
    INSERT INTO puzzles (puzzle_id, date, fen, solution, slack_ts, active)
    VALUES (?, ?, ?, ?, ?, 1)
"""

GET_LATEST_PUZZLE = "SELECT * FROM puzzles WHERE active = 1 ORDER BY date DESC LIMIT 1"

GET_PUZZLE_BY_ID = "SELECT * FROM puzzles WHERE puzzle_id = ? AND active = 1"

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
