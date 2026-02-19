"""
Slack Event Listener Module
Listens to Slack events using Slack Bolt
"""
import os
import json
import re
import time
import logging
from datetime import datetime

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from operations.slack_ops import (
    get_slack_app_token,
    get_slack_bot_token,
    start_channel_join_background,
)

# Data folder for saving events (relative to cwd when listener runs)
DATA_FOLDER = "data"
processed_file_ids = set()
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
        self.bot_token = bot_token or get_slack_bot_token()
        self.app_token = app_token or get_slack_app_token()
        if not self.bot_token:
            raise ValueError("Missing SLACK_BOT_TOKEN. Set it in .env file.")
        if not self.app_token:
            raise ValueError("Missing SLACK_APP_TOKEN. Set it in .env file.")
        self.app = App(token=self.bot_token)
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
                                if link_text.lower() in ["view ai notes", "view ai note"]:
                                    file_id = self._extract_file_id_from_url(sub_elem.get("url", ""))
                                    if file_id:
                                        return file_id
            return None
        except Exception as e:
            logger.error("Error extracting file ID from event: %s", e)
            return None

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
                    logger.warning("Could not extract file ID from huddle AI note event")
                    return
                if file_id in processed_file_ids:
                    logger.debug("File %s already processed, skipping", file_id)
                    return
                processed_file_ids.add(file_id)
                logger.debug("Huddle AI note for file_id: %s, waiting 30 seconds", file_id)
                time.sleep(30)
                logger.debug("Starting processing huddle canvas for file_id: %s", file_id)
                try:
                    from .huddle_processor import process_huddle_canvas
                    result = process_huddle_canvas(file_id)
                    if result and result.get("success"):
                        logger.debug("Successfully processed huddle canvas %s", file_id)
                        if result.get("github_url"):
                            logger.debug("GitHub URL: %s", result["github_url"])
                    else:
                        logger.error("Failed to process huddle canvas: %s", file_id)
                        processed_file_ids.discard(file_id)
                except Exception as e:
                    logger.exception("Error processing huddle canvas %s: %s", file_id, e)
                    processed_file_ids.discard(file_id)
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
