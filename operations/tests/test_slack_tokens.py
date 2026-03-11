"""Tests for operations.slack_ops.tokens."""

import pytest
from unittest.mock import patch

from django.conf import settings

from operations.slack_ops.tokens import (
    get_slack_bot_token,
    get_slack_app_token,
    get_slack_client,
    get_default_team_key,
)
from operations.slack_ops.client import SlackAPIClient


def test_get_slack_bot_token_from_env():
    """get_slack_bot_token returns value from settings dict when team_id is set."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {"T01234": "xoxb-from-env"}):
        token = get_slack_bot_token("T01234")
    assert token == "xoxb-from-env"


def test_get_slack_bot_token_no_args_uses_single_team():
    """get_slack_bot_token() with no args uses the only key in SLACK_BOT_TOKEN."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {"T99": "xoxb-fallback"}):
        token = get_slack_bot_token()
    assert token == "xoxb-fallback"


def test_get_slack_bot_token_no_args_uses_first_team_when_multiple():
    """get_slack_bot_token() with no args uses the first key in SLACK_BOT_TOKEN when multiple."""
    with patch.object(
        settings, "SLACK_BOT_TOKEN", {"first": "xoxb-first", "second": "xoxb-second"}
    ):
        token = get_slack_bot_token()
    assert token == "xoxb-first"


def test_get_default_team_key_single():
    """get_default_team_key() returns the only key when one team."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {"only": "xoxb"}):
        key = get_default_team_key()
    assert key == "only"


def test_get_default_team_key_first_when_multiple():
    """get_default_team_key() returns first key when multiple teams."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {"A": "x", "B": "y"}):
        key = get_default_team_key()
    assert key == "A"


def test_get_default_team_key_empty_when_none():
    """get_default_team_key() returns empty string when no teams."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {}):
        key = get_default_team_key()
    assert key == ""


def test_get_slack_bot_token_missing_team_id_raises():
    """get_slack_bot_token raises ValueError when no team configured (empty SLACK_BOT_TOKEN)."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {}):
        with pytest.raises(
            ValueError, match="team id is required for get_slack_bot_token"
        ):
            get_slack_bot_token()
        with pytest.raises(
            ValueError, match="team id is required for get_slack_bot_token"
        ):
            get_slack_bot_token(None)
        with pytest.raises(
            ValueError, match="team id is required for get_slack_bot_token"
        ):
            get_slack_bot_token("   ")


def test_get_slack_bot_token_missing_raises():
    """get_slack_bot_token raises ValueError when token for team_id is not set."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {}):
        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            get_slack_bot_token("T01234")


def test_get_slack_app_token_from_env():
    """get_slack_app_token returns value from env when set."""
    with patch.object(settings, "SLACK_APP_TOKEN", None):
        with patch.dict(
            "os.environ", {"SLACK_APP_TOKEN": "xapp-from-env"}, clear=False
        ):
            token = get_slack_app_token()
    assert token == "xapp-from-env"


def test_get_slack_app_token_missing_raises():
    """get_slack_app_token raises ValueError when not set."""
    with patch.object(settings, "SLACK_APP_TOKEN", None):
        with patch.dict("os.environ", {"SLACK_APP_TOKEN": ""}, clear=False):
            with pytest.raises(ValueError, match="SLACK_APP_TOKEN"):
                get_slack_app_token()


def test_get_slack_client_with_explicit_token():
    """get_slack_client(bot_token='x') returns SlackAPIClient with that token."""
    client = get_slack_client(bot_token="xoxb-explicit")
    assert isinstance(client, SlackAPIClient)
    assert client.token == "xoxb-explicit"


def test_get_slack_client_without_token_uses_get_slack_bot_token():
    """get_slack_client(team_id=...) uses get_slack_bot_token(team_id) when bot_token not set."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {"T01234": "xoxb-env-token"}):
        client = get_slack_client(team_id="T01234")
    assert isinstance(client, SlackAPIClient)
    assert client.token == "xoxb-env-token"


def test_get_slack_client_no_args_uses_default_team():
    """get_slack_client() with no args uses default team key (single/first in SLACK_BOT_TOKEN)."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {"T99": "xoxb-fallback-token"}):
        client = get_slack_client()
    assert isinstance(client, SlackAPIClient)
    assert client.token == "xoxb-fallback-token"


def test_get_slack_client_no_args_uses_first_when_multiple():
    """get_slack_client() with no args uses first workspace key when multiple."""
    with patch.object(
        settings,
        "SLACK_BOT_TOKEN",
        {"T88": "xoxb-first", "T99": "xoxb-second"},
    ):
        client = get_slack_client()
    assert isinstance(client, SlackAPIClient)
    assert client.token == "xoxb-first"


def test_get_slack_client_no_args_no_team_raises():
    """get_slack_client() with no args raises when SLACK_BOT_TOKEN is empty."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {}):
        with pytest.raises(
            ValueError, match="team id is required for get_slack_bot_token"
        ):
            get_slack_client()
