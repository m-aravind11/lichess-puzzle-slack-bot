import pytest

from scoring import MAX_SCORE, compute_score


@pytest.mark.parametrize("elapsed_seconds", [None, 0, 1, 3600, 1_000_000])
def test_wrong_answer_always_scores_zero(elapsed_seconds):
    assert compute_score(False, elapsed_seconds) == 0


def test_correct_answer_at_zero_elapsed_gets_max_score():
    assert compute_score(True, 0) == MAX_SCORE


def test_correct_answer_with_no_elapsed_time_gets_max_score():
    # No slack_ts to measure against - give full credit rather than penalize
    # for a measurement we don't have.
    assert compute_score(True, None) == MAX_SCORE


@pytest.mark.parametrize("elapsed_seconds", [-1, -3600])
def test_correct_answer_with_negative_elapsed_gets_max_score(elapsed_seconds):
    # Negative elapsed is bogus data (e.g. puzzle's slack_ts overwritten by a
    # later repost after this submission was recorded), not a real solve time.
    assert compute_score(True, elapsed_seconds) == MAX_SCORE


@pytest.mark.parametrize("minutes,expected", [
    (0, 10),
    (9, 10),
    (10, 9),        # boundary: right at a threshold drops to the next tier
    (29, 9),
    (30, 8),
    (59, 8),
    (60, 7),
    (89, 7),
    (90, 6),
    (119, 6),
    (120, 5),
    (179, 5),
    (180, 4),
    (239, 4),
    (240, 3),
    (359, 3),
    (360, 2),
    (539, 2),
    (540, 1),
    (719, 1),
    (720, 0),       # 12 hours out - no points left
    (1440, 0),      # a full day out
])
def test_correct_answer_steps_down_with_elapsed_time(minutes, expected):
    assert compute_score(True, minutes * 60) == expected


def test_score_is_always_an_int():
    assert isinstance(compute_score(True, 12345), int)


def test_score_never_exceeds_max_score():
    assert compute_score(True, 0.0001) <= MAX_SCORE


def test_score_never_goes_negative():
    assert compute_score(True, 10**9) >= 0


def test_score_is_monotonically_non_increasing_with_elapsed_time():
    minutes = [0, 1, 5, 15, 30, 60, 90, 120, 180, 240, 360, 480, 720, 1440, 2880]
    scores = [compute_score(True, m * 60) for m in minutes]
    assert scores == sorted(scores, reverse=True)
