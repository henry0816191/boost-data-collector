"""
Unified Slack Event Listener for slack_event_handler.

Handles two event streams in a single Socket Mode connection:
  1. Huddle AI note events → process_huddle_canvas() (cppa_slack_transcript_tracker)
  2. GitHub PR URL messages on the configured channel / DMs → PR comment job queue
"""

import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime

from django.conf import settings
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from operations.slack_ops import (
    get_slack_app_token,
)

from slack_event_handler.utils.job_queue import (
    enqueue_job,
    estimated_delay_sec,
    set_slack_app,
    start_worker,
)
from slack_event_handler.utils.pr_parser import extract_pr_urls
from slack_event_handler.workspace import get_data_dir

MAX_PROCESSED_FILE_IDS = 1000

# Team scope: which features are enabled per team (see SLACK_TEAM_SCOPE_<id> in settings).
SCOPE_HUDDLE = 0
SCOPE_PR_BOT = 1

logger = logging.getLogger(__name__)


def _data_dir() -> str:
    """Return workspace data dir path (avoids CWD dependency when run from runserver)."""
    return str(get_data_dir())


def save_event_to_file(event_type: str, body: dict) -> str | None:
    """Save raw event body to a JSON file in the data folder (for debugging)."""
    try:
        data_dir = _data_dir()
        os.makedirs(data_dir, exist_ok=True)
        event = body.get("event", {})
        ts = event.get("ts") or event.get("event_ts") or str(datetime.now().timestamp())
        ts_clean = ts.replace(".", "_")
        filepath = os.path.join(data_dir, f"{event_type}_{ts_clean}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(body, f, indent=2, default=str, ensure_ascii=False)
        logger.debug("Saved event to: %s", filepath)
        return filepath
    except Exception as e:
        logger.error("Error saving event to file: %s", e)
        return None


class SlackListener:
    """Unified Slack Event Listener using Slack Bolt (Socket Mode)."""

    def __init__(
        self,
        bot_token: str | None = None,
        app_token: str | None = None,
        team_id: str | None = None,
    ):
        self._team_id = team_id
        token = (bot_token or "").strip()
        if token:
            self.bot_token = token
        else:
            raise ValueError(
                "Missing bot_token. Pass bot_token or set SLACK_TEAM_IDS and "
                "SLACK_BOT_TOKEN_<id> in .env."
            )

        app_token = (app_token or "").strip()
        self.app_token = app_token or get_slack_app_token(self._team_id)

        if not self.bot_token:
            raise ValueError("Missing SLACK_BOT_TOKEN. Set it in .env file.")
        if not self.app_token:
            raise ValueError(
                "Missing SLACK_APP_TOKEN_<id>. Set SLACK_TEAM_IDS and SLACK_APP_TOKEN_<id> in .env."
            )

        self.app = App(token=self.bot_token)

        # Per-team scope: 0 = huddle, 1 = PR bot (from SLACK_TEAM_SCOPE_<id>). Default both.
        _scope_map = getattr(settings, "SLACK_TEAM_SCOPE", None) or {}
        self._team_scope = _scope_map.get(self._team_id, [SCOPE_HUDDLE, SCOPE_PR_BOT])

        # Huddle dedup cache (LRU, capped at MAX_PROCESSED_FILE_IDS)
        self._processed_file_ids: OrderedDict = OrderedDict()
        self._processed_file_ids_lock = threading.Lock()

        # PR bot: resolve configured channel ID (None disables PR handling)
        self._pr_channel_id: str | None = self._resolve_pr_channel()

        # Wire the PR job queue to this Bolt app and start the worker for this team.
        set_slack_app(self.app, self._team_id)
        start_worker(self._team_id)

        self._register_handlers()
        logger.debug(
            "SlackListener initialised team_id=%s scope=%s (PR channel: %s)",
            self._team_id or "default",
            self._team_scope,
            self._pr_channel_id or "disabled",
        )

    # ------------------------------------------------------------------
    # PR bot helpers
    # ------------------------------------------------------------------

    def _resolve_pr_channel(self) -> str | None:
        """Resolve the configured PR bot channel name to its Slack channel ID."""
        channel_name: str = (
            getattr(settings, "SLACK_PR_BOT_CHANNEL_NAME", "") or ""
        ).strip()
        if not channel_name:
            return None
        clean = channel_name.lstrip("#")
        try:
            cursor = None
            while True:
                kwargs = {"types": "public_channel,private_channel", "limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                res = self.app.client.conversations_list(**kwargs)
                for ch in res.get("channels", []):
                    if ch.get("name") == clean:
                        logger.debug(
                            "PR bot channel resolved: #%s → %s", clean, ch["id"]
                        )
                        return ch["id"]
                cursor = res.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
            logger.warning(
                "PR bot channel '#%s' not found via conversations.list. "
                "PR handling will be disabled for channel messages (DMs still work).",
                clean,
            )
        except Exception as e:
            logger.error("Error resolving PR bot channel '%s': %s", clean, e)
        return None

    def _send_user_reply(
        self, channel: str, message_ts: str, is_dm: bool, text: str
    ) -> None:
        """Posts a thread reply for channel messages or a plain message for DMs."""
        try:
            kwargs = {"channel": channel, "text": text}
            if not is_dm:
                kwargs["thread_ts"] = message_ts
            self.app.client.chat_postMessage(**kwargs)
        except Exception as e:
            logger.warning("Error sending reply to %s: %s", channel, e)

    def _handle_pr_request(
        self,
        text: str,
        channel: str,
        message_ts: str,
        user_id: str,
        is_dm: bool,
    ) -> None:
        """Full PR comment request pipeline: parse → deduplicate → enqueue → ack."""
        allowed_org: str = (getattr(settings, "SLACK_PR_BOT_TEAM", "") or "").strip()
        valid, invalid_org = extract_pr_urls(text, allowed_org=allowed_org)

        org_hint = (
            f"only PRs under the `{allowed_org}` org are supported."
            if allowed_org
            else "Set SLACK_PR_BOT_TEAM in .env to the GitHub org name (e.g. your-org) to enable PR comments."
        )
        for entry in invalid_org:
            self._send_user_reply(
                channel,
                message_ts,
                is_dm,
                f"⚠️ Ignored `{entry['url']}` — {org_hint}",
            )

        if not valid and not invalid_org:
            example_org = allowed_org or "owner"
            self._send_user_reply(
                channel,
                message_ts,
                is_dm,
                f"No GitHub PR URL found. Paste a link like "
                f"`https://github.com/{example_org}/repo/pull/123` to post a comment.",
            )
            return

        seen: set[str] = set()
        for entry in valid:
            key = f"{entry['owner']}/{entry['repo']}#{entry['pull_number']}"
            if key in seen:
                continue
            seen.add(key)

            enqueue_job(
                owner=entry["owner"],
                repo=entry["repo"],
                pull_number=entry["pull_number"],
                channel=channel,
                message_ts=message_ts,
                user_id=user_id,
                is_dm=is_dm,
                team_id=self._team_id,
            )
            delay_sec = estimated_delay_sec(self._team_id)
            pr_ref = f"`{entry['owner']}/{entry['repo']}#{entry['pull_number']}`"
            ack = (
                f"✅ Request received for {pr_ref}. "
                f"Rate limit reached — estimated delay: {delay_sec}s."
                if delay_sec > 0
                else f"✅ Request received for {pr_ref}."
            )
            self._send_user_reply(channel, message_ts, is_dm, ack)

    # ------------------------------------------------------------------
    # Huddle helpers (ported from cppa_slack_transcript_tracker)
    # ------------------------------------------------------------------

    def _extract_file_id_from_url(self, url: str) -> str | None:
        """Extract Slack file ID (pattern: F + 10+ uppercase alphanumerics) from a URL."""
        try:
            match = re.search(r"/(F[A-Z0-9]{10,})$", url)
            return match.group(1) if match else None
        except Exception as e:
            logger.warning("Error extracting file ID from URL %s: %s", url, e)
            return None

    def _is_huddle_ai_note_event(self, event: dict) -> bool:
        """Return True if this Slack event is a huddle AI note summary."""
        try:
            ai_context = event.get("ai_context", {})
            if ai_context.get("type") == "summary":
                summary = ai_context.get("summary", {})
                return summary.get("type") == "huddle"
        except Exception:
            logger.exception(
                "Malformed event in _is_huddle_ai_note_event (event keys=%s)",
                list(event.keys()) if isinstance(event, dict) else type(event).__name__,
            )
        return False

    def _extract_file_id_from_event(self, event: dict) -> str | None:
        """Extract the huddle canvas file ID from a huddle AI note event's message blocks."""
        try:
            for block in event.get("blocks", []):
                for element in block.get("elements", []):
                    if element.get("type") == "rich_text_section":
                        for sub in element.get("elements", []):
                            if sub.get("type") == "link":
                                if sub.get("text", "").strip().lower() in (
                                    "view ai notes",
                                    "view ai note",
                                ):
                                    file_id = self._extract_file_id_from_url(
                                        sub.get("url", "")
                                    )
                                    if file_id:
                                        return file_id
        except Exception as e:
            logger.warning("Error extracting file ID from huddle event: %s", e)
        return None

    def _mark_file_processed(self, file_id: str) -> bool:
        """Atomically mark file_id as seen; returns True if newly added (False if duplicate)."""
        with self._processed_file_ids_lock:
            if file_id in self._processed_file_ids:
                return False
            while len(self._processed_file_ids) >= MAX_PROCESSED_FILE_IDS:
                self._processed_file_ids.popitem(last=False)
            self._processed_file_ids[file_id] = None
            return True

    def _unmark_file_processed(self, file_id: str) -> None:
        """Remove file_id from the dedup cache (e.g. after a processing failure)."""
        with self._processed_file_ids_lock:
            self._processed_file_ids.pop(file_id, None)

    # ------------------------------------------------------------------
    # Event handler registration
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        @self.app.event("message")
        def handle_message_events(event, body):
            subtype = event.get("subtype")
            if subtype in ("message_changed", "message_deleted"):
                return

            # -- Huddle AI note path (only if scope includes 0) --
            if SCOPE_HUDDLE in self._team_scope and self._is_huddle_ai_note_event(
                event
            ):
                logger.debug("Huddle AI note event detected")
                save_event_to_file("huddle_ai_note", body)
                file_id = self._extract_file_id_from_event(event)
                if not file_id:
                    logger.warning(
                        "Could not extract file ID from huddle AI note event"
                    )
                    return
                if not self._mark_file_processed(file_id):
                    logger.debug("File %s already processed, skipping", file_id)
                    return

                def _process_later(fid):
                    time.sleep(30)
                    logger.debug("Processing huddle canvas for file_id: %s", fid)
                    try:
                        from slack_event_handler.utils.huddle_processor import (
                            process_huddle_canvas,
                        )

                        result = process_huddle_canvas(fid)
                        if result and result.get("success"):
                            logger.debug("Processed huddle canvas %s", fid)
                            if result.get("github_url"):
                                logger.debug("GitHub URL: %s", result["github_url"])
                        else:
                            logger.error("Failed to process huddle canvas: %s", fid)
                            self._unmark_file_processed(fid)
                    except Exception as e:
                        logger.exception(
                            "Error processing huddle canvas %s: %s", fid, e
                        )
                        self._unmark_file_processed(fid)

                threading.Thread(
                    target=_process_later, args=(file_id,), daemon=True
                ).start()
                logger.debug(
                    "Huddle AI note for file_id %s queued for processing in 30s",
                    file_id,
                )
                return

            # -- PR bot path (only if scope includes 1) --
            if SCOPE_PR_BOT not in self._team_scope:
                logger.debug(
                    "Unhandled regular message event (PR bot disabled for this team)"
                )
                return

            channel_type = event.get("channel_type")
            is_dm = channel_type == "im"

            if is_dm or (
                self._pr_channel_id and event.get("channel") == self._pr_channel_id
            ):
                source = "dm" if is_dm else "channel"
                logger.debug(
                    "PR bot message [%s] user=%s channel=%s",
                    source,
                    event.get("user", "?"),
                    event.get("channel"),
                )
                self._handle_pr_request(
                    text=event.get("text") or "",
                    channel=event["channel"],
                    message_ts=event["ts"],
                    user_id=event.get("user", ""),
                    is_dm=is_dm,
                )
                return

            logger.debug("Unhandled regular message event (not huddle, not PR channel)")

        @self.app.event("file_shared")
        def handle_file_shared(event, body):
            logger.debug("File shared event received")

        @self.app.event("reaction_added")
        def handle_reaction_added(event, body):
            logger.debug("Reaction added event received")

        @self.app.event("app_mention")
        def handle_app_mention(event, body):
            logger.debug("App mention event received")

        @self.app.event({"type": "event_callback"})
        def handle_all_events(event, body):
            event_type = body.get("event", {}).get("type", "unknown")
            logger.debug("Received event: %s", event_type)

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start listening for events using Socket Mode (blocks forever)."""
        data_dir = _data_dir()
        os.makedirs(data_dir, exist_ok=True)
        logger.debug(
            "Starting unified Slack Event Handler (Socket Mode), data dir: %s",
            os.path.abspath(data_dir),
        )
        handler = SocketModeHandler(self.app, self.app_token)
        handler.start()


def start_slack_listener(
    bot_token: str | None = None,
    app_token: str | None = None,
    team_id: str | None = None,
) -> None:
    """
    Start the unified Slack event listener for one workspace.
    For multiple workspaces, call this once per team from separate threads.
    """
    listener = SlackListener(bot_token, app_token, team_id)
    listener.start()


if __name__ == "__main__":
    start_slack_listener()
