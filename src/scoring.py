MAX_SCORE = 10

# (max minutes elapsed, score) thresholds, checked in order - first match wins.
# Anything past the last threshold scores 0.
SCORE_THRESHOLDS = [
    (10, 10),
    (30, 9),
    (60, 8),
    (90, 7),
    (120, 6),
    (180, 5),
    (240, 4),
    (360, 3),
    (540, 2),
    (720, 1),
]


def compute_score(correct: bool, elapsed_seconds: float | None) -> int:
    """Points for one submission: 0 if wrong, otherwise MAX_SCORE stepped down
    by elapsed time since the puzzle was posted per SCORE_THRESHOLDS.
    elapsed_seconds is None when the puzzle has no slack_ts to measure against
    (or the value looks bogus, e.g. negative from a stale repost) - give full
    credit rather than penalize for a measurement we don't have."""
    if not correct:
        return 0
    if elapsed_seconds is None or elapsed_seconds < 0:
        return MAX_SCORE
    minutes = elapsed_seconds / 60
    for max_minutes, score in SCORE_THRESHOLDS:
        if minutes < max_minutes:
            return score
    return 0
