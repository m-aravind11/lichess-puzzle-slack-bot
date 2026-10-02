import logging
from datetime import datetime

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

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
    answer = " ".join(solution[0::2])
    if len(solution) == 1:
        return f"Correct answer: `{answer}`"
    steps = "\n".join(f"{'You' if i % 2 == 0 else 'Opponent'}: `{move}`" for i, move in enumerate(solution))
    return f"Correct answer: `{answer}`\nHow it plays out:\n{steps}"


def format_month(month: str) -> str:
    return datetime.strptime(month, "%Y-%m").strftime("%B %Y")


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
    widths = [max(len(col), *(len(r[i]) for r in rows)) for i, col in enumerate(columns)]

    def format_row(cells: list) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    table_lines = [format_row(columns), "  ".join("-" * w for w in widths)]
    table_lines += [format_row(r) for r in rows]
    return "```\n" + "\n".join(table_lines) + "\n```"


def format_leaderboard(standings: dict) -> str:
    columns = ["#", "Name", "House", "Points", "Solved", "Avg Solve Time", "Current Streak"]
    rows = [
        [
            str(p["rank"]),
            p["name"],
            p["house"] or "-",
            str(p["points"]),
            f"{p['correct']}/{p['attempted']}",
            format_seconds(p["avg_solve_seconds"]),
            "-" if p["current_streak"] is None else str(p["current_streak"]),
        ]
        for p in standings["players"]
    ]
    title = "Final standings" if standings["final"] else "Leaderboard"
    if standings["month"]:
        title = f"{title} - {format_month(standings['month'])}"
    header = f"*{title}* _(ranked by this month's points - faster solves score higher; ties broken by fastest average solve time)_"
    return f"{header}\n{_format_table(columns, rows)}"


def format_house_leaderboard(standings: dict, points_of: str = "this month") -> str | None:
    if not standings["houses"]:
        return None

    columns = ["#", "House", "Points", "Solved", "Players"]
    rows = [
        [str(h["rank"]), h["name"], str(h["points"]), str(h["correct"]), str(h["players"])]
        for h in standings["houses"]
    ]
    return f"*House standings* _(sum of each house's players' points {points_of})_\n{_format_table(columns, rows)}"


def format_all_time_leaderboard_post(standings: dict) -> str:
    columns = ["#", "Name", "House", "Points", "Solved", "Months"]
    rows = [
        [str(p["rank"]), p["name"], p["house"] or "-", str(p["points"]), f"{p['correct']}/{p['attempted']}", str(p["months"])]
        for p in standings["players"]
    ]
    header = (
        f"*All-time standings - through {format_month(standings['through'])}* "
        "_(every finished month's points added up)_"
    )
    sections = [f"{header}\n{_format_table(columns, rows)}", format_house_leaderboard(standings, "all-time")]
    return "\n\n".join(section for section in sections if section)


def _join_names(names: list) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def format_streak_milestones(standings: dict) -> str | None:
    # Outside the table's code block, where Slack would render <@U...> literally.
    if not standings["milestones"]:
        return None

    lines = ["*Streak milestones*"]
    for milestone in standings["milestones"]:
        mentions = [f"<@{p['user_id']}>" for p in milestone["players"]]
        verb = "is" if len(mentions) == 1 else "are"
        lines.append(f"• {_join_names(mentions)} {verb} on a {milestone['streak']}-day streak.")
    return "\n".join(lines)


def format_leaderboard_post(standings: dict) -> str:
    sections = [format_leaderboard(standings), format_streak_milestones(standings), format_house_leaderboard(standings)]
    return "\n\n".join(section for section in sections if section)
