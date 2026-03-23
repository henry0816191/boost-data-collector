"""
Custom logging handlers for the Boost Data Collector project.

SafeRotatingFileHandler: RotatingFileHandler that serializes emit() with a lock
so rollover (close → rename → reopen) is not run while another thread is writing.
On Windows, every rollover rename (including .1 → .2, etc.) and removal of
existing backup targets is retried on PermissionError [WinError 32] because files
can stay locked briefly after close (or another process may have them open). The
base RotatingFileHandler only uses custom rotate() for the final move; this
subclass overrides doRollover() so all renames and deletes share the same safe path.

DiscordHandler / SlackHandler: send ERROR-level log records to Discord/Slack
webhooks when ENABLE_ERROR_NOTIFICATIONS is True and webhook URLs are set.
"""

import json
import logging
import logging.handlers
import os
import sys
import threading
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


# Retry rollover rename/remove on Windows when file is still locked (PermissionError 32).
_ROTATE_RETRY_COUNT = 10
_ROTATE_RETRY_DELAY_SEC = 0.5


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """
    Thread-safe RotatingFileHandler. Use this when multiple threads write to
    the same log file (e.g. Celery + thread pools). On Windows, the standard
    RotatingFileHandler can raise PermissionError during rollover because
    os.rename() / os.remove() can fail if the file is still open. This handler
    serializes emit() and retries rename and remove on WinError 32 so rollover
    usually succeeds; otherwise it skips and logging continues.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._emit_lock = threading.Lock()

    def emit(self, record):
        with self._emit_lock:
            super().emit(record)

    def _safe_rename(self, source, dest):
        """Rename source to dest, retrying on Windows PermissionError [WinError 32].
        If rename still fails after retries (e.g. another process has the file),
        skip this rename so rollover / logging can continue.
        """
        for attempt in range(_ROTATE_RETRY_COUNT):
            try:
                os.rename(source, dest)
                return
            except OSError as e:
                # WinError 32: "file is being used by another process"
                if getattr(e, "winerror", None) != 32:
                    raise
                if attempt == _ROTATE_RETRY_COUNT - 1:
                    try:
                        sys.stderr.write(
                            "SafeRotatingFileHandler: rollover skipped "
                            "(file in use). Logging continues.\n"
                        )
                    except Exception:
                        pass
                    return
                time.sleep(_ROTATE_RETRY_DELAY_SEC)

    def _safe_remove(self, path):
        """Remove path, retrying on Windows PermissionError [WinError 32].
        If remove still fails after retries, log and return so rollover continues.
        No-op if path is already absent (including races with other processes).
        """
        if not os.path.exists(path):
            return
        for attempt in range(_ROTATE_RETRY_COUNT):
            try:
                os.remove(path)
                return
            except OSError as e:
                if not os.path.exists(path):
                    return
                if getattr(e, "winerror", None) != 32:
                    raise
                if attempt == _ROTATE_RETRY_COUNT - 1:
                    try:
                        sys.stderr.write(
                            "SafeRotatingFileHandler: rollover skipped "
                            "(file in use). Logging continues.\n"
                        )
                    except Exception:
                        pass
                    return
                time.sleep(_ROTATE_RETRY_DELAY_SEC)

    def rotate(self, source, dest):
        """Delegate to _safe_rename (used for the final base → .1 move)."""
        self._safe_rename(source, dest)

    def doRollover(self):
        """Like RotatingFileHandler.doRollover but safe renames for all backup steps."""
        if self.stream:
            self.stream.close()
            self.stream = None
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename("%s.%d" % (self.baseFilename, i))
                dfn = self.rotation_filename("%s.%d" % (self.baseFilename, i + 1))
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        self._safe_remove(dfn)
                    self._safe_rename(sfn, dfn)
            dfn = self.rotation_filename(self.baseFilename + ".1")
            if os.path.exists(dfn):
                self._safe_remove(dfn)
            self.rotate(self.baseFilename, dfn)
        if not self.delay:
            self.stream = self._open()
