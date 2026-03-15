"""
Slack Skill Adapter
This skill provides a pre-written, robust function to send messages to a Slack channel.
It uses the slack_sdk package and requires a SLACK_BOT_TOKEN environment variable.
"""

import os
import logging
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

def send_slack_message(channel: str, text: str) -> bool:
    """
    Sends a message to a specific Slack channel.
    
    Args:
        channel: The channel ID or name (e.g., "#general" or "C1234567").
        text: The message text to send.
        
    Returns:
        bool: True if successful, False otherwise.
    """
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        logger.error("SLACK_BOT_TOKEN environment variable is not set. Cannot send Slack message.")
        return False
        
    client = WebClient(token=token)
    try:
        response = client.chat_postMessage(channel=channel, text=text)
        logger.info(f"Successfully sent Slack message to {channel}")
        return True
    except SlackApiError as e:
        logger.error(f"Error sending Slack message: {e.response['error']}")
        return False
