"""The leaderboard's content, independent of how it's shown. build_standings is
the one place standings are computed; the Slack post (slack_helpers) and the
web leaderboard (GET /admin/leaderboard) only render what it returns, so the
two always agree."""

from constants import Streaks


def build_standings(board: list) -> dict:
    """From db.get_leaderboard()'s board (already ranked):

    - players: rank, user_id, name, house (None if never assigned), points,
      correct, attempted, avg_solve_seconds, current_streak, best_streak
    - houses: rank, name, points (sum of the house's players'), correct,
      players - ranked, ties broken by more correct answers. Players never
      assigned a house aren't counted; ones who left the company still are.
    - milestones: streak and the players (user_id, name) whose current streak
      is exactly at it, longest first. The leaderboard posts once a day, so
      matching exactly announces each milestone once, the day it's hit.
    """
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
    return {"players": players, "houses": _house_standings(players), "milestones": _streak_milestones(players)}


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
