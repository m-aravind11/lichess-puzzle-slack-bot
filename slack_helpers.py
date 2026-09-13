import logging

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
