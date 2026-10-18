MAX_SCORE = 10
# Any correct answer while the puzzle is still open earns at least this.
MIN_SCORE = 1

# (max minutes elapsed, score); past the last one scores MIN_SCORE.
# Spread over the ~23h a puzzle is open (posted 11:30 UTC, revealed 10:50 UTC next day).
SCORE_THRESHOLDS = [
    (10, 10),
    (20, 9.5),
    (30, 9),
    (45, 8.5),
    (60, 8),
    (90, 7.5),
    (120, 7),
    (150, 6.5),
    (180, 6),
    (240, 5.5),
    (300, 5),
    (360, 4.5),
    (450, 4),
    (540, 3.5),
    (660, 3),
    (780, 2.5),
    (960, 2),
    (1200, 1.5),
]

# Added on top of the time score for the first correct answers to a puzzle, in order.
PODIUM_BONUS = (5, 3, 2, 1, 1)

# Counts toward the real leaderboard total, so the ceiling stays proportionate to what
# daily play can earn (max ~15/day): the 365-day milestone tops out under ten days of
# normal scoring, not a month and a half of it. Cumulative target per milestone length
# in days (constants.Streaks.MILESTONES) -- what a run is worth in total once it reaches
# that length, not a per-crossing increment. db.record_streak_bonuses derives the
# incremental amount actually credited at each crossing from these cumulative values.
STREAK_BONUS = {
    3: 3,
    7: 5,
    14: 10,
    30: 25,
    50: 35,
    100: 60,
    150: 80,
    200: 95,
    250: 110,
    300: 120,
    365: 130,
}


def compute_score(correct: bool, elapsed_seconds: float | None) -> float:
    # No usable post time (missing or negative slack_ts): full credit, not a penalty.
    if not correct:
        return 0
    if elapsed_seconds is None or elapsed_seconds < 0:
        return MAX_SCORE
    minutes = elapsed_seconds / 60
    for max_minutes, score in SCORE_THRESHOLDS:
        if minutes < max_minutes:
            return score
    return MIN_SCORE
