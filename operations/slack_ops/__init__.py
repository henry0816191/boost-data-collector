"""
Slack operations: channel list/join, messages, client, fetcher (file download, huddle transcript).
Similar to github_ops; use get_slack_client() or token helpers.
"""

from operations.slack_ops.channels import (
    channel_join,
    channel_list,
    run_channel_join_check,
    start_channel_join_background,
    stop_channel_join_background,
)
from operations.slack_ops.client import SlackAPIClient
from operations.slack_ops.fetcher import (
    SlackFetcher,
    download_file,
    fetch_huddle_transcript,
    get_file_info,
    get_slack_fetcher,
)
from operations.slack_ops.messages import get_channel_messages
from operations.slack_ops.tokens import (
    get_slack_app_token,
    get_slack_bot_token,
    get_slack_client,
)

__all__ = [
    "channel_join",
    "channel_list",
    "download_file",
    "fetch_huddle_transcript",
    "get_channel_messages",
    "get_file_info",
    "get_slack_app_token",
    "get_slack_bot_token",
    "get_slack_client",
    "get_slack_fetcher",
    "run_channel_join_check",
    "SlackAPIClient",
    "SlackFetcher",
    "start_channel_join_background",
    "stop_channel_join_background",
]
