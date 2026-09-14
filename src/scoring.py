MAX_SCORE = 10
# Half-life chosen so a solve near the end of a ~24h puzzle window rounds to 0,
# while the first couple of hours still show a meaningful points gradient.
HALF_LIFE_MINUTES = 120


def compute_score(correct: bool, elapsed_seconds: float | None) -> int:
    """Points for one submission: 0 if wrong, otherwise MAX_SCORE decayed by
    elapsed time since the puzzle was posted (halves every HALF_LIFE_MINUTES).
    elapsed_seconds is None when the puzzle has no slack_ts to measure against
    (or the value looks bogus, e.g. negative from a stale repost) - give full
    credit rather than penalize for a measurement we don't have."""
    if not correct:
        return 0
    if elapsed_seconds is None or elapsed_seconds < 0:
        return MAX_SCORE
    minutes = elapsed_seconds / 60
    return round(MAX_SCORE * 0.5 ** (minutes / HALF_LIFE_MINUTES))
