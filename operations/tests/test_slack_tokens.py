"""Tests for operations.slack_ops.tokens."""

import os
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


def test_get_slack_bot_token_no_args_uses_slack_team_id_fallback():
    """get_slack_bot_token() with no args uses SLACK_TEAM_ID fallback and returns token for that team."""
    with patch.object(settings, "SLACK_TEAM_ID", "T99"):
        with patch.object(settings, "SLACK_BOT_TOKEN", {"T99": "xoxb-fallback"}):
            token = get_slack_bot_token()
    assert token == "xoxb-fallback"


def test_get_slack_bot_token_raises_when_team_id_and_slack_team_id_fallback_missing():
    """get_slack_bot_token raises ValueError when team_id and SLACK_TEAM_ID fallback are missing."""
    with patch.object(settings, "SLACK_TEAM_ID", ""):
        with patch.object(settings, "SLACK_BOT_TOKEN", {}):
            with pytest.raises(ValueError, match="SLACK_TEAM_ID is required"):
                get_slack_bot_token()
    with patch.object(settings, "SLACK_TEAM_ID", ""):
        with pytest.raises(ValueError, match="SLACK_TEAM_ID is required"):
            get_slack_bot_token(None)
    with patch.object(settings, "SLACK_TEAM_ID", "   "):
        with pytest.raises(ValueError, match="SLACK_TEAM_ID is required"):
            get_slack_bot_token("   ")


def test_get_default_team_key_single():
    """get_default_team_key() returns SLACK_TEAM_ID when set."""
    with patch.object(settings, "SLACK_TEAM_ID", "only"):
        key = get_default_team_key()
    assert key == "only"


def test_get_default_team_key_raises_when_missing():
    """get_default_team_key() raises ValueError when SLACK_TEAM_ID is not set."""
    with patch.object(settings, "SLACK_TEAM_ID", ""):
        with pytest.raises(ValueError, match="SLACK_TEAM_ID is required"):
            get_default_team_key()


def test_get_slack_bot_token_missing_team_id_raises():
    """get_slack_bot_token raises ValueError when no team configured (SLACK_TEAM_ID empty and no team_id)."""
    with patch.object(settings, "SLACK_TEAM_ID", ""):
        with patch.object(settings, "SLACK_BOT_TOKEN", {}):
            with pytest.raises(ValueError, match="SLACK_TEAM_ID is required"):
                get_slack_bot_token()
            with pytest.raises(ValueError, match="SLACK_TEAM_ID is required"):
                get_slack_bot_token(None)
            with pytest.raises(ValueError, match="SLACK_TEAM_ID is required"):
                get_slack_bot_token("   ")


def test_get_slack_bot_token_missing_raises():
    """get_slack_bot_token raises ValueError when token for team_id is not set."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {}):
        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            get_slack_bot_token("T01234")


def test_get_slack_app_token_from_env():
    """get_slack_app_token returns value from settings dict when team_id is set."""
    with patch.object(settings, "SLACK_APP_TOKEN", {"T01234": "xapp-from-env"}):
        token = get_slack_app_token("T01234")
    assert token == "xapp-from-env"


def test_get_slack_app_token_no_args_uses_slack_team_id_fallback():
    """get_slack_app_token() with no args uses SLACK_TEAM_ID fallback."""
    with patch.object(settings, "SLACK_TEAM_ID", "T99"):
        with patch.object(settings, "SLACK_APP_TOKEN", {"T99": "xapp-fallback"}):
            token = get_slack_app_token()
    assert token == "xapp-fallback"


def test_get_slack_app_token_missing_raises():
    """get_slack_app_token raises ValueError when token for team is not set."""
    with patch.object(settings, "SLACK_APP_TOKEN", {}):
        with pytest.raises(ValueError, match="SLACK_APP_TOKEN"):
            get_slack_app_token("T01234")
    with patch.object(settings, "SLACK_TEAM_ID", ""):
        with patch.object(settings, "SLACK_APP_TOKEN", {}):
            with pytest.raises(ValueError, match="SLACK_TEAM_ID is required"):
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


def test_get_slack_client_no_args_uses_slack_team_id_fallback():
    """get_slack_client() with no args uses SLACK_TEAM_ID fallback and returns client with that token."""
    with patch.object(settings, "SLACK_TEAM_ID", "T99"):
        with patch.object(settings, "SLACK_BOT_TOKEN", {"T99": "xoxb-fallback-token"}):
            client = get_slack_client()
    assert isinstance(client, SlackAPIClient)
    assert client.token == "xoxb-fallback-token"


def test_get_slack_client_no_args_fallback_from_os_environ():
    """get_slack_client() with no args uses SLACK_TEAM_ID (as from os.environ) for token lookup."""
    with patch.dict(os.environ, {"SLACK_TEAM_ID": "T88"}, clear=False):
        with patch.object(settings, "SLACK_TEAM_ID", "T88"):
            with patch.object(
                settings,
                "SLACK_BOT_TOKEN",
                {"T88": "xoxb-from-env-token"},
            ):
                client = get_slack_client()
    assert isinstance(client, SlackAPIClient)
    assert client.token == "xoxb-from-env-token"


def test_get_slack_client_no_args_no_team_raises():
    """get_slack_client() with no args raises when SLACK_TEAM_ID is not set."""
    with patch.object(settings, "SLACK_TEAM_ID", ""):
        with patch.object(settings, "SLACK_BOT_TOKEN", {}):
            with pytest.raises(ValueError, match="SLACK_TEAM_ID is required"):
                get_slack_client()
