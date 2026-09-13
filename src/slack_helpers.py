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


def get_display_names(slack_client: WebClient) -> dict:
    """Resolves Slack user ids to display names via users.list (paginated) - one or a
    few calls for the whole workspace roster, rather than one users.info call per
    leaderboard row, which is what made an earlier version of this risk timing out."""
    names = {}
    cursor = None
    try:
        while True:
            response = slack_client.users_list(cursor=cursor, limit=200)
            for member in response['members']:
                profile = member.get('profile', {})
                names[member['id']] = profile.get('display_name') or profile.get('real_name') or member.get('name') or member['id']
            cursor = response.get('response_metadata', {}).get('next_cursor')
            if not cursor:
                break
    except SlackApiError as e:
        logger.error("Could not fetch user list: %s", e.response['error'])
    return names


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


def format_leaderboard(board: list, names: dict | None = None) -> str:
    names = names or {}
    columns = ["#", "Name", "Correct", "Incorrect", "Attempted", "Avg Time"]
    rows = [
        [
            str(i + 1),
            names.get(row["user_id"], row["user_id"]),
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
