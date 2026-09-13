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


def get_display_name(slack_client: WebClient, user_id: str) -> str:
    try:
        info = slack_client.users_info(user=user_id)
        profile = info['user'].get('profile', {})
        return profile.get('display_name') or profile.get('real_name') or info['user'].get('name') or user_id
    except SlackApiError as e:
        logger.error("Could not fetch display name for %s: %s", user_id, e.response['error'])
        return user_id


def format_seconds(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def format_result_dm(puzzle: dict, submitted_text: str, correct: bool) -> str:
    puzzle_date = datetime.strptime(puzzle['date'], '%Y-%m-%d').strftime('%B %d, %Y')
    puzzle_link = f"<https://lichess.org/training/{puzzle['puzzle_id']}|Puzzle - {puzzle_date}>"
    result_text = (
        "That's correct - nice work!" if correct
        else f"Not quite. The solution was: `{' '.join(puzzle['solution'])}`"
    )
    return f"{puzzle_link}\nYou answered: `{submitted_text}`\n{result_text}"


def format_leaderboard(board: list) -> str:
    columns = ["#", "Name", "Correct", "Incorrect", "Attempted", "Avg Time"]
    rows = [
        [
            str(i + 1),
            row["user_name"] or row["user_id"],
            str(row["correct"]),
            str(row["incorrect"]),
            str(row["attempted"]),
            format_seconds(row["avg_solve_seconds"]),
        ]
        for i, row in enumerate(board)
    ]
    widths = [max(len(col), *(len(r[i]) for r in rows)) for i, col in enumerate(columns)]

    def format_row(cells: list) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    table_lines = [format_row(columns), "  ".join("-" * w for w in widths)]
    table_lines += [format_row(r) for r in rows]

    header = "*🏆 Leaderboard* _(ties broken by fastest average solve time)_"
    table = "```\n" + "\n".join(table_lines) + "\n```"
    return f"{header}\n{table}"
