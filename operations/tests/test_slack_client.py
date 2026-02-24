"""Tests for operations.slack_ops.client (SlackAPIClient)."""

from unittest.mock import MagicMock, patch

from operations.slack_ops.client import SlackAPIClient


def test_client_init_sets_token_and_headers():
    """SlackAPIClient.__init__ sets token and session Authorization header."""
    c = SlackAPIClient("xoxb-token")
    assert c.token == "xoxb-token"
    assert "Authorization" in c.session.headers
    assert "xoxb-token" in c.session.headers["Authorization"]
    assert "Content-Type" in c.session.headers


def test_client_init_default_retry_settings():
    """SlackAPIClient has default max_retries and retry_delay."""
    c = SlackAPIClient("t")
    assert c.max_retries == 3
    assert c.retry_delay == 1


def test_conversations_list_calls_request_with_params():
    """conversations_list calls _request with GET and correct params."""
    c = SlackAPIClient("t")
    c._request = MagicMock(return_value={"ok": True, "channels": []})
    c.conversations_list(
        types="public_channel", exclude_archived=True, limit=100, cursor="x"
    )
    c._request.assert_called_once()
    assert c._request.call_args[0][0] == "GET"
    assert c._request.call_args[0][1] == "conversations.list"
    params = c._request.call_args[1]["params"]
    assert params["types"] == "public_channel"
    assert params["exclude_archived"] is True
    assert params["limit"] == 100
    assert params["cursor"] == "x"


def test_conversations_join_calls_request_with_channel():
    """conversations_join calls _request with POST and channel in json_data."""
    c = SlackAPIClient("t")
    c._request = MagicMock(return_value={"ok": True})
    c.conversations_join("C12345")
    c._request.assert_called_once()
    assert c._request.call_args[0][0] == "POST"
    assert c._request.call_args[0][1] == "conversations.join"
    assert c._request.call_args[1]["json_data"] == {"channel": "C12345"}


def test_conversations_info_calls_request():
    """conversations_info calls _request with channel param."""
    c = SlackAPIClient("t")
    c._request = MagicMock(return_value={"ok": True, "channel": {"id": "C1"}})
    c.conversations_info("C1")
    c._request.assert_called_once_with(
        "GET", "conversations.info", params={"channel": "C1"}
    )


def test_users_info_calls_request():
    """users_info calls _request with user param."""
    c = SlackAPIClient("t")
    c._request = MagicMock(return_value={"ok": True, "user": {"id": "U1"}})
    c.users_info("U1")
    c._request.assert_called_once_with("GET", "users.info", params={"user": "U1"})


def test_files_info_calls_request():
    """files_info calls _request with file param."""
    c = SlackAPIClient("t")
    c._request = MagicMock(return_value={"ok": True, "file": {"id": "F1"}})
    c.files_info("F1")
    c._request.assert_called_once_with(
        "GET", "files.info", params={"file": "F1"}, timeout=30
    )


def test_request_get_success_returns_json():
    """_request returns JSON when GET returns 200 and ok=True."""
    c = SlackAPIClient("t")
    c.session.get = MagicMock(
        return_value=MagicMock(
            status_code=200,
            json=lambda: {"ok": True, "channels": []},
            headers={},
            raise_for_status=MagicMock(),
        )
    )
    out = c._request("GET", "conversations.list", params={"types": "public_channel"})
    assert out["ok"] is True
    assert out["channels"] == []


def test_request_post_success_returns_json():
    """_request returns JSON when POST returns 200."""
    c = SlackAPIClient("t")
    c.session.post = MagicMock(
        return_value=MagicMock(
            status_code=200,
            json=lambda: {"ok": True},
            headers={},
            raise_for_status=MagicMock(),
        )
    )
    out = c._request("POST", "conversations.join", json_data={"channel": "C1"})
    assert out["ok"] is True


def test_request_rate_limited_retries_with_retry_after():
    """_request retries when response has ok=False and error=rate_limited."""
    c = SlackAPIClient("t")
    c.session.get = MagicMock(
        side_effect=[
            MagicMock(
                status_code=200,
                json=lambda: {"ok": False, "error": "rate_limited"},
                headers={"Retry-After": "1"},
                raise_for_status=MagicMock(),
            ),
            MagicMock(
                status_code=200,
                json=lambda: {"ok": True, "channels": []},
                headers={},
                raise_for_status=MagicMock(),
            ),
        ]
    )
    with patch("time.sleep"):
        out = c._request("GET", "conversations.list", params={})
    assert out["ok"] is True
