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
    """get_slack_bot_token returns value from env when set."""
    with patch.object(settings, "SLACK_BOT_TOKEN", None):
        with patch.dict(
            "os.environ", {"SLACK_BOT_TOKEN": "xoxb-from-env"}, clear=False
        ):
            token = get_slack_bot_token()
    assert token == "xoxb-from-env"


def test_get_slack_bot_token_missing_raises():
    """get_slack_bot_token raises ValueError when not set."""
    with patch.object(settings, "SLACK_BOT_TOKEN", None):
        with patch.dict("os.environ", {"SLACK_BOT_TOKEN": ""}, clear=False):
            with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
                get_slack_bot_token()


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
    """get_slack_client() without token uses get_slack_bot_token (when set)."""
    with patch.object(settings, "SLACK_BOT_TOKEN", None):
        with patch.dict(
            "os.environ", {"SLACK_BOT_TOKEN": "xoxb-env-token"}, clear=False
        ):
            client = get_slack_client()
    assert isinstance(client, SlackAPIClient)
    assert client.token == "xoxb-env-token"
