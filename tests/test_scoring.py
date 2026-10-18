import pytest

from constants import Streaks
from scoring import MAX_SCORE, MIN_SCORE, STREAK_BONUS, compute_score


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
    (10, 9.5),
    (19, 9.5),
    (20, 9),
    (30, 8.5),
    (45, 8),
    (60, 7.5),
    (90, 7),
    (120, 6.5),
    (150, 6),
    (180, 5.5),
    (240, 5),
    (300, 4.5),
    (360, 4),
    (450, 3.5),
    (540, 3),
    (660, 2.5),
    (780, 2),
    (960, 1.5),
    (1199, 1.5),
    (1200, 1),
    (1400, 1),
    (10_000, 1),
])
def test_correct_answer_steps_down_with_elapsed_time(minutes, expected):
    assert compute_score(True, minutes * 60) == expected


@pytest.mark.parametrize("minutes", range(0, 1500, 7))
def test_score_is_a_multiple_of_half_a_point(minutes):
    assert (compute_score(True, minutes * 60) * 2).is_integer()


def test_correct_answer_never_scores_below_min_score():
    assert compute_score(True, 10**9) == MIN_SCORE


@pytest.mark.parametrize("minutes,old_score", [(0, 10), (10, 9), (30, 8), (60, 7), (90, 6), (120, 5), (180, 4), (240, 3), (360, 2), (540, 1)])
def test_no_solve_time_scores_less_than_the_old_whole_point_slabs(minutes, old_score):
    assert compute_score(True, minutes * 60) >= old_score


def test_score_never_exceeds_max_score():
    assert compute_score(True, 0.0001) <= MAX_SCORE


def test_score_is_monotonically_non_increasing_with_elapsed_time():
    minutes = [0, 1, 5, 15, 30, 60, 90, 120, 180, 240, 360, 480, 720, 1440, 2880]
    scores = [compute_score(True, m * 60) for m in minutes]
    assert scores == sorted(scores, reverse=True)
