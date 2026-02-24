"""Tests for cppa_slack_transcript_tracker.utils.slack_listener."""

import json
import pytest
from unittest.mock import MagicMock, patch

from cppa_slack_transcript_tracker.utils.slack_listener import (
    save_event_to_file,
    SlackListener,
)


def test_save_event_to_file_creates_file(tmp_path):
    """save_event_to_file writes JSON to data folder and returns filepath."""
    with patch.dict("os.environ", {}, clear=False):
        with patch("os.makedirs"):
            with patch(
                "cppa_slack_transcript_tracker.utils.slack_listener.DATA_FOLDER",
                str(tmp_path),
            ):
                body = {"event": {"ts": "12345.67", "type": "message"}}
                filepath = save_event_to_file("message", body)
    assert filepath is not None
    assert filepath.endswith(".json")
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    assert data["event"]["ts"] == "12345.67"


def test_save_event_to_file_uses_event_ts_when_no_ts(tmp_path):
    """save_event_to_file uses event_ts when ts is missing."""
    with patch("os.makedirs"):
        with patch(
            "cppa_slack_transcript_tracker.utils.slack_listener.DATA_FOLDER",
            str(tmp_path),
        ):
            body = {"event": {"event_ts": "99999.11", "type": "message"}}
            filepath = save_event_to_file("message", body)
    assert "99999" in filepath or "99999_11" in filepath


@patch("cppa_slack_transcript_tracker.utils.slack_listener.App", MagicMock())
def test_slack_listener_extract_file_id_from_url():
    """_extract_file_id_from_url returns file ID from Slack file URL."""
    listener = SlackListener(bot_token="xoxb-t", app_token="xapp-t")
    url = "https://company.slack.com/files/U123/F1234567890ABC"
    assert listener._extract_file_id_from_url(url) == "F1234567890ABC"
    assert listener._extract_file_id_from_url("https://other.com/no-match") is None


@patch("cppa_slack_transcript_tracker.utils.slack_listener.App", MagicMock())
def test_slack_listener_is_huddle_ai_note_event():
    """_is_huddle_ai_note_event returns True for huddle summary type."""
    listener = SlackListener(bot_token="xoxb-t", app_token="xapp-t")
    event = {
        "ai_context": {
            "type": "summary",
            "summary": {"type": "huddle"},
        }
    }
    assert listener._is_huddle_ai_note_event(event) is True
    assert listener._is_huddle_ai_note_event({}) is False
    assert listener._is_huddle_ai_note_event({"ai_context": {"type": "other"}}) is False


@patch("cppa_slack_transcript_tracker.utils.slack_listener.App", MagicMock())
def test_slack_listener_extract_file_id_from_event():
    """_extract_file_id_from_event finds file ID from 'View AI notes' link in blocks."""
    listener = SlackListener(bot_token="xoxb-t", app_token="xapp-t")
    event = {
        "blocks": [
            {
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {
                                "type": "link",
                                "text": "View AI notes",
                                "url": "https://slack.com/files/xxx/F9876543210XY",
                            }
                        ],
                    }
                ]
            }
        ]
    }
    assert listener._extract_file_id_from_event(event) == "F9876543210XY"


def test_slack_listener_init_requires_bot_and_app_token():
    """SlackListener raises ValueError when bot or app token is missing."""
    with patch(
        "cppa_slack_transcript_tracker.utils.slack_listener.get_slack_bot_token",
        side_effect=ValueError("SLACK_BOT_TOKEN is not set"),
    ):
        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            SlackListener(bot_token=None, app_token="xapp-t")
    with patch(
        "cppa_slack_transcript_tracker.utils.slack_listener.get_slack_app_token",
        side_effect=ValueError("SLACK_APP_TOKEN is not set"),
    ):
        with pytest.raises(ValueError, match="SLACK_APP_TOKEN"):
            SlackListener(bot_token="xoxb-t", app_token=None)


@patch("cppa_slack_transcript_tracker.utils.slack_listener.App", MagicMock())
def test_slack_listener_init_accepts_tokens():
    """SlackListener initializes with provided tokens."""
    listener = SlackListener(bot_token="xoxb-token", app_token="xapp-token")
    assert listener.bot_token == "xoxb-token"
    assert listener.app_token == "xapp-token"
    assert listener.app is not None
