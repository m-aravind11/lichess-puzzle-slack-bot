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


def format_result_dm(puzzle: dict, submitted_text: str, correct: bool, score: int) -> str:
    puzzle_date = datetime.strptime(puzzle['date'], '%Y-%m-%d').strftime('%B %d, %Y')
    puzzle_link = f"<https://lichess.org/training/{puzzle['puzzle_id']}|Puzzle - {puzzle_date}>"
    result_text = (
        f"That's correct - nice work! +{score} points" if correct
        else f"Not quite. The solution was: `{' '.join(puzzle['solution'])}`"
    )
    return f"{puzzle_link}\nYou answered: `{submitted_text}`\n{result_text}"


def format_leaderboard_fallback(board: list) -> str:
    """Plain-text summary for the notification/screen-reader `text` param - Slack
    requires it alongside `blocks`, but it's never what's actually displayed in
    a channel that supports blocks."""
    entries = [f"{i + 1}. {row['user_name'] or row['user_id']} ({row['score']} pts)" for i, row in enumerate(board)]
    return "Leaderboard: " + " | ".join(entries)


def build_leaderboard_blocks(board: list) -> list:
    """Block Kit layout instead of a monospace table - a fixed-width table
    either truncates or forces horizontal scrolling on Slack mobile, while
    section fields reflow to one column on narrow screens automatically."""
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Leaderboard* _(ranked by points - faster solves score higher; ties broken by fastest average solve time)_",
            },
        },
        {"type": "divider"},
    ]
    for i, row in enumerate(board):
        name = row["user_name"] or row["user_id"]
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*{i + 1}. {name}*\n{row['score']} pts"},
                {
                    "type": "mrkdwn",
                    "text": (
                        f"Correct {row['correct']}, Incorrect {row['incorrect']} ({row['attempted']} attempted)\n"
                        f"avg {format_seconds(row['avg_solve_seconds'])}"
                    ),
                },
            ],
        })
    return blocks
