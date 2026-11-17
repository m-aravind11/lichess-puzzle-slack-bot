from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

from scoring import PODIUM_BONUS

MIN_TEMPTING_PLAYERS = 2
MIN_BROKEN_STREAK = 3


def _seconds_since(posted_ts: str, submitted_at: str) -> float | None:
    posted_at = datetime.fromtimestamp(float(posted_ts), tz=timezone.utc)
    seconds = (datetime.fromisoformat(submitted_at) - posted_at).total_seconds()
    # Negative when a repost overwrote slack_ts after the submission.
    return seconds if seconds >= 0 else None


def _first_move_stats(puzzle: dict, submissions: list, solved: set, move_san: Callable) -> tuple:
    players_by_wrong_move = defaultdict(set)
    slipped = set()
    for s in submissions:
        tokens = s["moves"].split()
        if s["correct"] or not tokens:
            continue
        san = move_san(puzzle["fen"], tokens[0])
        if san == puzzle["solution"][0]:
            if len(tokens) > 1 and s["user_id"] not in solved:
                slipped.add(s["user_id"])
        elif san:
            players_by_wrong_move[san].add(s["user_id"])

    tempting = max(players_by_wrong_move.items(), key=lambda kv: len(kv[1]), default=None)
    tempting_move = (
        {"san": tempting[0], "players": len(tempting[1])}
        if tempting and len(tempting[1]) >= MIN_TEMPTING_PLAYERS else None
    )
    so_close = {"san": puzzle["solution"][0], "players": len(slipped)} if slipped else None
    return tempting_move, so_close


def _podium(puzzle: dict, submissions: list) -> dict | None:
    podium = {s["podium_rank"]: s for s in submissions if s["podium_rank"]}
    if not podium:
        return None
    last = podium.get(len(PODIUM_BONUS))
    filled_seconds = _seconds_since(puzzle["slack_ts"], last["submitted_at"]) if last else None
    return {"taken": len(podium), "spots": len(PODIUM_BONUS), "filled_seconds": filled_seconds}


def _month_record(puzzle: dict, submissions: list, earlier_first_solves: list) -> dict | None:
    solves = [
        (seconds, s["user_id"])
        for s in submissions if s["correct"]
        if (seconds := _seconds_since(puzzle["slack_ts"], s["submitted_at"])) is not None
    ]
    earlier = [
        seconds for row in earlier_first_solves
        if (seconds := _seconds_since(row["slack_ts"], row["first_solved_at"])) is not None
    ]
    if not solves or not earlier:
        return None
    seconds, user_id = min(solves)
    return {"seconds": seconds, "user_id": user_id} if seconds < min(earlier) else None


def _broken_streaks(broken: list) -> dict | None:
    if not broken:
        return None
    longest = max(b["streak"] for b in broken)
    return {
        "count": len(broken),
        "longest": longest,
        "longest_user_ids": [b["user_id"] for b in broken if b["streak"] == longest],
    }


def build_puzzle_stats(puzzle: dict, reveal_data: dict, move_san: Callable[[str, str], str | None]) -> dict:
    submissions = reveal_data["submissions"]
    solved = {s["user_id"] for s in submissions if s["correct"]}
    tempting_move, so_close = _first_move_stats(puzzle, submissions, solved, move_san)

    return {
        "players": len({s["user_id"] for s in submissions}),
        "solved": len(solved),
        "month_record": _month_record(puzzle, submissions, reveal_data["earlier_first_solves"]),
        "podium": _podium(puzzle, submissions),
        "tempting_move": tempting_move,
        "so_close": so_close,
        "broken_streaks": _broken_streaks(reveal_data["broken_streaks"]),
    }
