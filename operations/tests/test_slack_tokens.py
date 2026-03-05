"""Tests for operations.slack_ops.tokens."""

import pytest
from unittest.mock import patch

from django.conf import settings

from operations.slack_ops.tokens import (
    get_slack_bot_token,
    get_slack_app_token,
    get_slack_client,
)
from operations.slack_ops.client import SlackAPIClient


def test_get_slack_bot_token_from_env():
    """get_slack_bot_token returns value from settings dict when team_id is set."""
    with patch.object(settings, "SLACK_BOT_TOKEN", {"T01234": "xoxb-from-env"}):
        token = get_slack_bot_token("T01234")
    assert token == "xoxb-from-env"


def test_get_slack_bot_token_missing_team_id_raises():
    """get_slack_bot_token raises ValueError when team_id is missing."""
    with pytest.raises(ValueError, match="team_id is required for get_slack_bot_token"):
        get_slack_bot_token()
    with pytest.raises(ValueError, match="team_id is required for get_slack_bot_token"):
        get_slack_bot_token(None)
    with pytest.raises(ValueError, match="team_id is required for get_slack_bot_token"):
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
