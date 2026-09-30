"""Standings shared by the Slack posts and the web leaderboard, so they always agree."""

from constants import Streaks


def build_standings(board: list, month: str | None = None, final: bool = False) -> dict:
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
        }
        for i, row in enumerate(board)
    ]
    return {
        "month": month,
        "final": final,
        "players": players,
        "houses": _house_standings(players),
        "milestones": _streak_milestones(players),
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


def _streak_milestones(players: list) -> list:
    by_milestone = {}
    for player in players:
        if player["current_streak"] in Streaks.MILESTONES:
            by_milestone.setdefault(player["current_streak"], []).append(
                {"user_id": player["user_id"], "name": player["name"]}
            )
    return [{"streak": days, "players": by_milestone[days]} for days in sorted(by_milestone, reverse=True)]
