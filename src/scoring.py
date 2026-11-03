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

MAX_ATTEMPTS = 2
# Share of the time score a correct later attempt earns; it never gets a podium bonus.
RETRY_SCORE_FACTOR = 0.5

# Cumulative total a run is worth once it reaches each length, not a per-crossing increment.
# Bonus per streak day must never fall between milestones, so longer runs earn proportionately more.
STREAK_BONUS = {
    3: 1,
    7: 3,
    14: 7,
    30: 18,
    50: 35,
    75: 57,
    100: 80,
    125: 106,
    150: 135,
    175: 166,
    200: 200,
    225: 236,
    250: 275,
    275: 316,
    300: 360,
    325: 404,
    365: 475,
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
