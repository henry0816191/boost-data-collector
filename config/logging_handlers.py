"""
Custom logging handlers for Discord and Slack notifications.
Automatically sends error logs to configured channels.
"""

import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from urllib import request
from urllib.error import URLError


COOLDOWN_TIME = 60  # 1 minute


class DiscordHandler(logging.Handler):
    """
    Logging handler that sends error messages to Discord via webhook.

    Usage in LOGGING config:
        'discord': {
            'class': 'config.logging_handlers.DiscordHandler',
            'webhook_url': 'https://discord.com/api/webhooks/...',
            'level': 'ERROR',
        }
    """

    def __init__(self, webhook_url, level=logging.ERROR, username="Django Logger"):
        super().__init__(level)
        self.webhook_url = webhook_url
        self.username = username
        self.last_notification = 0

    def emit(self, record):
        """Send log record to Discord."""
        try:
            # Check cooldown
            now = time.time()
            if now - self.last_notification < COOLDOWN_TIME:
                return
            self.last_notification = now

            # Build embed for better formatting
            embed = {
                "title": f"🚨 {record.levelname}: {record.name}",
                "description": f"```\n{record.getMessage()}\n```",
                "color": self._get_color(record.levelname),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fields": [
                    {
                        "name": "Module",
                        "value": f"`{record.module}.{record.funcName}`",
                        "inline": True,
                    },
                    {
                        "name": "Line",
                        "value": f"`{record.lineno}`",
                        "inline": True,
                    },
                ],
            }

            # Add exception info if present
            if record.exc_info:
                exc_text = "".join(traceback.format_exception(*record.exc_info))
                # Discord has a 4096 char limit for description
                if len(exc_text) > 1900:
                    exc_text = exc_text[:1900] + "\n... (truncated)"
                embed["fields"].append(
                    {
                        "name": "Exception",
                        "value": f"```python\n{exc_text}\n```",
                        "inline": False,
                    }
                )

            payload = {"username": self.username, "embeds": [embed]}

            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )

            with request.urlopen(req, timeout=10) as response:
                if response.status != 204:
                    sys.stderr.write(
                        f"Discord webhook returned status {response.status}\n"
                    )

        except URLError as e:
            # Don't fail the application if notification fails
            sys.stderr.write(f"Failed to send Discord notification: {e}\n")
        except Exception as e:
            # Prevent handler from breaking the logging system
            sys.stderr.write(f"Error in DiscordHandler: {e}\n")

    def _get_color(self, levelname):
        """Get embed color based on log level."""
        colors = {
            "DEBUG": 0x7289DA,  # Blue
            "INFO": 0x3498DB,  # Light Blue
            "WARNING": 0xF39C12,  # Orange
            "ERROR": 0xE74C3C,  # Red
            "CRITICAL": 0x992D22,  # Dark Red
        }
        return colors.get(levelname, 0x95A5A6)  # Gray default


class SlackHandler(logging.Handler):
    """
    Logging handler that sends error messages to Slack via webhook.

    Usage in LOGGING config:
        'slack': {
            'class': 'config.logging_handlers.SlackHandler',
            'webhook_url': 'https://hooks.slack.com/services/...',
            'level': 'ERROR',
        }
    """

    def __init__(
        self,
        webhook_url,
        level=logging.ERROR,
        username="Django Logger",
        channel=None,
    ):
        super().__init__(level)
        self.webhook_url = webhook_url
        self.username = username
        self.channel = channel
        self.last_notification = 0

    def emit(self, record):
        """Send log record to Slack."""
        try:
            # Check cooldown
            now = time.time()
            if now - self.last_notification < COOLDOWN_TIME:
                return
            self.last_notification = now

            # Build blocks for better formatting (Slack Block Kit)
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"🚨 {record.levelname}: {record.name}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Module:*\n`{record.module}.{record.funcName}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Line:*\n`{record.lineno}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Time:*\n{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Level:*\n`{record.levelname}`",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Message:*\n```{record.getMessage()}```",
                    },
                },
            ]

            # Add exception info if present
            if record.exc_info:
                exc_text = "".join(traceback.format_exception(*record.exc_info))
                # Slack has a 3000 char limit per block
                if len(exc_text) > 2900:
                    exc_text = exc_text[:2900] + "\n... (truncated)"

                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Exception:*\n```{exc_text}```",
                        },
                    }
                )

            payload = {
                "username": self.username,
                "blocks": blocks,
                "icon_emoji": ":warning:",
            }

            if self.channel:
                payload["channel"] = self.channel

            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )

            with request.urlopen(req, timeout=10) as response:
                if response.status != 200:
                    sys.stderr.write(
                        f"Slack webhook returned status {response.status}\n"
                    )

        except URLError as e:
            # Don't fail the application if notification fails
            sys.stderr.write(f"Failed to send Slack notification: {e}\n")
        except Exception as e:
            # Prevent handler from breaking the logging system
            sys.stderr.write(f"Error in SlackHandler: {e}\n")
