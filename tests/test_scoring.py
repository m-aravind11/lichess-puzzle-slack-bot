import pytest

from constants import Streaks
from scoring import MAX_SCORE, STREAK_BONUS, compute_score


def test_streak_bonus_values_strictly_increase_with_milestone_length():
    # db.record_streak_bonuses derives each crossing's incremental credit as
    # STREAK_BONUS[milestone] - (amount already credited for this run). That's only
    # ever non-negative if cumulative targets never decrease, and a crossing with no
    # new credit over the previous milestone would silently award +0 forever.
    values = [STREAK_BONUS[m] for m in Streaks.MILESTONES]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_every_milestone_has_a_bonus_value():
    assert set(STREAK_BONUS) == set(Streaks.MILESTONES)


@pytest.mark.parametrize("elapsed_seconds", [None, 0, 1, 3600, 1_000_000])
def test_wrong_answer_always_scores_zero(elapsed_seconds):
    assert compute_score(False, elapsed_seconds) == 0


def test_correct_answer_at_zero_elapsed_gets_max_score():
    assert compute_score(True, 0) == MAX_SCORE


def test_correct_answer_with_no_elapsed_time_gets_max_score():
    assert compute_score(True, None) == MAX_SCORE


@pytest.mark.parametrize("elapsed_seconds", [-1, -3600])
def test_correct_answer_with_negative_elapsed_gets_max_score(elapsed_seconds):
    assert compute_score(True, elapsed_seconds) == MAX_SCORE


@pytest.mark.parametrize("minutes,expected", [
    (0, 10),
    (9, 10),
    (10, 9),
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
    (720, 0),
    (1440, 0),
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
