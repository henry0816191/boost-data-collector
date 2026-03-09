"""
Slack Event Listener Module
Listens to Slack events using Slack Bolt
"""

import os
import json
import re
import time
import logging
import threading
from collections import OrderedDict
from datetime import datetime

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from django.conf import settings

from operations.slack_ops import (
    get_slack_app_token,
    get_slack_bot_token,
    start_channel_join_background,
)

# Data folder for saving events (relative to cwd when listener runs)
DATA_FOLDER = "data"
# Max number of file IDs to retain for deduplication (LRU eviction)
MAX_PROCESSED_FILE_IDS = 1000
logger = logging.getLogger(__name__)


def save_event_to_file(event_type, body):
    """Save event data to JSON file in data folder."""
    try:
        os.makedirs(DATA_FOLDER, exist_ok=True)
        event = body.get("event", {})
        ts = event.get("ts") or event.get("event_ts") or str(datetime.now().timestamp())
        ts_clean = ts.replace(".", "_")
        filename = f"{event_type}_{ts_clean}.json"
        filepath = os.path.join(DATA_FOLDER, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(body, f, indent=2, default=str, ensure_ascii=False)
        logger.debug("Saved to: %s", filepath)
        return filepath
    except Exception as e:
        logger.error("Error saving event to file: %s", e)
        return None


class SlackListener:
    """Slack Event Listener using Slack Bolt."""

    def __init__(self, bot_token=None, app_token=None):
        token = (bot_token or "").strip()
        if token:
            self.bot_token = token
        else:
            try:
                team_id = (
                    getattr(settings, "SLACK_TEAM_ID", None) or ""
                ).strip() or None
            except Exception:
                team_id = None
            self.bot_token = get_slack_bot_token(team_id=team_id)
        app_token = (app_token or "").strip()
        self.app_token = app_token or get_slack_app_token()
        if not self.bot_token:
            raise ValueError("Missing SLACK_BOT_TOKEN. Set it in .env file.")
        if not self.app_token:
            raise ValueError("Missing SLACK_APP_TOKEN. Set it in .env file.")
        self.app = App(token=self.bot_token)
        self._processed_file_ids = OrderedDict()
        self._processed_file_ids_lock = threading.Lock()
        self._register_handlers()
        logger.debug("SlackListener initialized")

    def _extract_file_id_from_url(self, url):
        """Extract file ID from Slack URL (IDs start with F)."""
        try:
            match = re.search(r"/(F[A-Z0-9]{10,})$", url)
            return match.group(1) if match else None
        except Exception as e:
            logger.error("Error extracting file ID from URL %s: %s", url, e)
            return None

    def _is_huddle_ai_note_event(self, event):
        """Check if this is a huddle AI note event."""
        try:
            ai_context = event.get("ai_context", {})
            if ai_context.get("type") == "summary":
                summary = ai_context.get("summary", {})
                if summary.get("type") == "huddle":
                    return True
            return False
        except Exception:
            return False

    def _extract_file_id_from_event(self, event):
        """Extract file ID from huddle AI note event."""
        try:
            blocks = event.get("blocks", [])
            for block in blocks:
                elements = block.get("elements", [])
                for element in elements:
                    if element.get("type") == "rich_text_section":
                        for sub_elem in element.get("elements", []):
                            if sub_elem.get("type") == "link":
                                link_text = sub_elem.get("text", "").strip()
                                if link_text.lower() in [
                                    "view ai notes",
                                    "view ai note",
                                ]:
                                    file_id = self._extract_file_id_from_url(
                                        sub_elem.get("url", "")
                                    )
                                    if file_id:
                                        return file_id
            return None
        except Exception as e:
            logger.error("Error extracting file ID from event: %s", e)
            return None

    def _mark_file_processed(self, file_id):
        """Atomically check and add file_id; return True if newly added, False if already seen. Evicts oldest when at capacity."""
        with self._processed_file_ids_lock:
            if file_id in self._processed_file_ids:
                return False
            while len(self._processed_file_ids) >= MAX_PROCESSED_FILE_IDS:
                self._processed_file_ids.popitem(last=False)
            self._processed_file_ids[file_id] = None
            return True

    def _unmark_file_processed(self, file_id):
        """Remove file_id from processed set (e.g. after processing failure)."""
        with self._processed_file_ids_lock:
            self._processed_file_ids.pop(file_id, None)

    def _register_handlers(self):
        """Register all event handlers."""

        @self.app.event("message")
        def handle_message_events(event, body):
            subtype = event.get("subtype")
            if subtype == "message_changed":
                return
            if subtype == "message_deleted":
                return
            if self._is_huddle_ai_note_event(event):
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
                    logger.debug(
                        "Starting processing huddle canvas for file_id: %s", fid
                    )
                    try:
                        from .huddle_processor import process_huddle_canvas

                        result = process_huddle_canvas(fid)
                        if result and result.get("success"):
                            logger.debug("Successfully processed huddle canvas %s", fid)
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
                    target=_process_later,
                    args=(file_id,),
                    daemon=True,
                ).start()
                logger.debug(
                    "Huddle AI note for file_id: %s, waiting 30 seconds (background)",
                    file_id,
                )
                return
            logger.debug("Regular message event received")

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

    def start(self):
        """Start listening for events using Socket Mode."""
        os.makedirs(DATA_FOLDER, exist_ok=True)
        logger.debug(
            "Starting Slack Event Listener (Socket Mode), events saved to %s",
            os.path.abspath(DATA_FOLDER),
        )
        handler = SocketModeHandler(self.app, self.app_token)
        handler.start()


def start_slack_listener(bot_token=None, app_token=None):
    """
    Start the Slack event listener.
    Also starts a background thread for periodic channel-join checks.
    """
    listener = SlackListener(bot_token, app_token)
    start_channel_join_background(bot_token=listener.bot_token)
    listener.start()


if __name__ == "__main__":
    start_slack_listener()
