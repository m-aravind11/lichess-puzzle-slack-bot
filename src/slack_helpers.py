import logging
from datetime import datetime

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from constants import Streaks

logger = logging.getLogger(__name__)


def dm(slack_client: WebClient, user_id: str, text: str) -> None:
    try:
        im = slack_client.conversations_open(users=[user_id])
        slack_client.chat_postMessage(channel=im['channel']['id'], text=text)
    except SlackApiError as e:
        logger.error("Slack DM failed: %s", e.response["error"])
        logger.error("Full response: %s", e.response.data)


def format_seconds(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def format_solution(solution: list) -> str:
    """The answer as it should be typed, then the line move by move, labelled
    You/Opponent - most players are new to chess notation, so nothing is left
    for them to decode."""
    answer = " ".join(solution[0::2])
    if len(solution) == 1:
        return f"Correct answer: `{answer}`"
    steps = "\n".join(f"{'You' if i % 2 == 0 else 'Opponent'}: `{move}`" for i, move in enumerate(solution))
    return f"Correct answer: `{answer}`\nHow it plays out:\n{steps}"


def format_result_dm(puzzle: dict, submitted_text: str, correct: bool, score: int) -> str:
    puzzle_date = datetime.strptime(puzzle['posted_at'][:10], '%Y-%m-%d').strftime('%B %d, %Y')
    puzzle_link = f"<https://lichess.org/training/{puzzle['puzzle_id']}|Puzzle - {puzzle_date}>"
    result_text = (
        f"Correct - nice work! +{score} points" if correct
        else f"Not quite.\n{format_solution(puzzle['solution'])}"
    )
    return f"{puzzle_link}\nYour answer: `{submitted_text}`\n{result_text}"


def format_solution_reveal(puzzle: dict) -> str:
    return (
        f"*Solution to the above puzzle*\n{format_solution(puzzle['solution'])}\n"
        "_PS: this puzzle is no longer accepting answers._"
    )


def _format_table(columns: list, rows: list) -> str:
    """A code block with each column padded to its widest cell, so it lines up
    in Slack's monospace rendering."""
    widths = [max(len(col), *(len(r[i]) for r in rows)) for i, col in enumerate(columns)]

    def format_row(cells: list) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    table_lines = [format_row(columns), "  ".join("-" * w for w in widths)]
    table_lines += [format_row(r) for r in rows]
    return "```\n" + "\n".join(table_lines) + "\n```"


def format_leaderboard(board: list) -> str:
    columns = ["#", "Name", "Points", "Solved", "Avg Solve Time", "Current Streak"]
    rows = [
        [
            str(i + 1),
            row["user_name"] or row["user_id"],
            str(row["score"]),
            f"{row['correct']}/{row['attempted']}",
            format_seconds(row["avg_solve_seconds"]),
            str(row["current_streak"]),
        ]
        for i, row in enumerate(board)
    ]
    header = "*Leaderboard* _(ranked by points - faster solves score higher; ties broken by fastest average solve time)_"
    return f"{header}\n{_format_table(columns, rows)}"


def format_house_leaderboard(board: list) -> str | None:
    """Each house's total points - the sum of its players' - ranked, ties broken
    by more correct answers. Players never assigned a house aren't counted;
    ones who left the company still are. None when nobody on the board has a
    house."""
    houses = {}
    for row in board:
        if row["house_name"] is None:
            continue
        house = houses.setdefault(row["house_name"], {"score": 0, "correct": 0, "players": 0})
        house["score"] += row["score"]
        house["correct"] += row["correct"]
        house["players"] += 1

    if not houses:
        return None

    ranked = sorted(houses.items(), key=lambda item: (-item[1]["score"], -item[1]["correct"], item[0]))
    columns = ["#", "House", "Points", "Solved", "Players"]
    rows = [
        [str(i + 1), name, str(house["score"]), str(house["correct"]), str(house["players"])]
        for i, (name, house) in enumerate(ranked)
    ]
    return f"*House standings* _(sum of each house's players' points)_\n{_format_table(columns, rows)}"


def _join_names(names: list) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def format_streak_milestones(board: list) -> str | None:
    """One bullet per milestone reached, longest first, @-mentioning everyone on it.
    Kept separate from format_leaderboard's code block, where Slack would render
    <@U...> literally. None when nobody hit a milestone."""
    by_milestone = {}
    for row in board:
        if row["current_streak"] in Streaks.MILESTONES:
            by_milestone.setdefault(row["current_streak"], []).append(f"<@{row['user_id']}>")

    if not by_milestone:
        return None

    lines = ["*Streak milestones*"]
    for days in sorted(by_milestone, reverse=True):
        mentions = by_milestone[days]
        verb = "is" if len(mentions) == 1 else "are"
        # Slack mrkdwn has no list syntax, so bullets are a literal character.
        lines.append(f"• {_join_names(mentions)} {verb} on a {days}-day streak.")
    return "\n".join(lines)
