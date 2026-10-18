"""Standings shared by the Slack posts and the web leaderboard, so they always agree."""

from constants import Streaks
from scoring import STREAK_BONUS


def build_standings(
    board: list, month: str | None = None, final: bool = False, streak_bonus_increments: dict | None = None
) -> dict:
    players = [
        {
            "rank": i + 1,
            "user_id": row["user_id"],
            "name": row["user_name"] or row["user_id"],
            "house": row["house_name"],
            "points": row["score"],
            "correct": row["correct"],
            "attempted": row["attempted"],
            "avg_solve_seconds": row["avg_solve_seconds"],
            "current_streak": row["current_streak"],
            "best_streak": row["best_streak"],
            "streak_start": row.get("current_streak_start"),
        }
        for i, row in enumerate(board)
    ]
    return {
        "month": month,
        "final": final,
        "players": players,
        "houses": _house_standings(players),
        "milestones": _streak_milestones(players, streak_bonus_increments or {}),
    }


def build_all_time_standings(board: list, through: str | None) -> dict:
    players = [
        {
            "rank": i + 1,
            "user_id": row["user_id"],
            "name": row["user_name"] or row["user_id"],
            "house": row["house_name"],
            "points": row["score"],
            "correct": row["correct"],
            "attempted": row["attempted"],
            "months": row["months"],
        }
        for i, row in enumerate(board)
    ]
    return {"through": through, "players": players, "houses": _house_standings(players)}


def _house_standings(players: list) -> list:
    houses = {}
    for player in players:
        if player["house"] is None:
            continue
        house = houses.setdefault(player["house"], {"name": player["house"], "points": 0, "correct": 0, "players": 0})
        house["points"] += player["points"]
        house["correct"] += player["correct"]
        house["players"] += 1
    ranked = sorted(houses.values(), key=lambda h: (-h["points"], -h["correct"], h["name"]))
    return [{"rank": i + 1, **house} for i, house in enumerate(ranked)]


def _milestone_increment(days: int) -> int:
    """Fallback for when the real increment isn't known (e.g. no bonus was actually
    recorded for this call). Assumes a normal, uninterrupted run where every lower
    milestone was already credited on its own day -- which is what a real recorded
    increment might contradict if a prior day's cron was ever missed."""
    index = Streaks.MILESTONES.index(days)
    previous = STREAK_BONUS[Streaks.MILESTONES[index - 1]] if index > 0 else 0
    return STREAK_BONUS[days] - previous


def _streak_milestones(players: list, increments: dict) -> list:
    # Grouped by (streak, bonus), not just streak: two players at the same streak
    # length could have genuinely earned different amounts (e.g. one caught up from
    # a missed cron day), so they're kept on separate lines rather than sharing one
    # possibly-wrong number.
    by_group = {}
    for player in players:
        streak = player["current_streak"]
        if streak in Streaks.MILESTONES:
            bonus = increments.get(player["user_id"], _milestone_increment(streak))
            by_group.setdefault((streak, bonus), []).append({
                "user_id": player["user_id"],
                "name": player["name"],
                "start_date": player["streak_start"],
            })
    return [
        {"streak": streak, "bonus": bonus, "players": group}
        for (streak, bonus), group in sorted(by_group.items(), key=lambda kv: kv[0], reverse=True)
    ]


# Takes the raw board (not build_standings' "players"), so callers can compute
# candidates, write bonuses, and patch each row's score *before* calling
# build_standings -- otherwise the leaderboard table posted the same run would miss
# the bonus the milestone line right below it claims was just earned.
#
# Unlike _streak_milestones (exact match, so the Slack announcement fires once, the
# day a milestone is hit), this reports the highest milestone reached so far, every
# day the run continues. Otherwise a streak that's already past a milestone before
# this feature shipped, or whose exact-hit day the cron missed, would permanently
# lose that milestone's bonus. "bonus" here is the run's cumulative target for that
# milestone, not a per-day amount; db.record_streak_bonuses diffs it against what's
# already been credited for this run and only ever writes the newly-earned remainder.
def compute_streak_bonus_candidates(board: list) -> list:
    candidates = []
    for row in board:
        current_streak = row["current_streak"]
        if not current_streak:
            continue
        reached = [m for m in Streaks.MILESTONES if m <= current_streak]
        if reached:
            milestone = max(reached)
            candidates.append({
                "user_id": row["user_id"],
                "streak": milestone,
                "bonus": STREAK_BONUS[milestone],
                "start_date": row.get("current_streak_start"),
            })
    return candidates
