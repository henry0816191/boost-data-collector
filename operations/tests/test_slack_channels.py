"""Tests for operations.slack_ops.channels."""

from unittest.mock import MagicMock, patch

from operations.slack_ops.channels import (
    _channel_matches_policy,
    _get_channel_join_config,
    _parse_list_env,
    channel_list,
    channel_join,
    run_channel_join_check,
)
from operations.slack_ops.client import SlackAPIClient


# --- _parse_list_env ---


def test_parse_list_env_empty_or_none():
    """_parse_list_env returns empty set for None, empty string, or whitespace."""
    assert _parse_list_env(None) == set()
    assert _parse_list_env("") == set()
    assert _parse_list_env("   ") == set()


def test_parse_list_env_single_value():
    """_parse_list_env returns one lowercased stripped value."""
    assert _parse_list_env("general") == {"general"}
    assert _parse_list_env("  GENERAL  ") == {"general"}


def test_parse_list_env_comma_separated():
    """_parse_list_env splits on comma and lowercases."""
    assert _parse_list_env("a,b,c") == {"a", "b", "c"}
    assert _parse_list_env("  A ,  B ,  C  ") == {"a", "b", "c"}


def test_parse_list_env_skips_empty_parts():
    """_parse_list_env skips empty segments between commas."""
    assert _parse_list_env("a,,b") == {"a", "b"}


# --- _channel_matches_policy ---


def test_channel_matches_policy_blocklist_by_name():
    """_channel_matches_policy returns False when channel name is in blocklist."""
    assert (
        _channel_matches_policy("C1", "secret", allowlist=set(), blocklist={"secret"})
        is False
    )


def test_channel_matches_policy_blocklist_by_id():
    """_channel_matches_policy returns False when channel id is in blocklist."""
    assert (
        _channel_matches_policy("c1", "general", allowlist=set(), blocklist={"c1"})
        is False
    )


def test_channel_matches_policy_empty_lists_allows():
    """_channel_matches_policy returns True when allowlist and blocklist are empty."""
    assert (
        _channel_matches_policy("C1", "any", allowlist=set(), blocklist=set()) is True
    )


def test_channel_matches_policy_allowlist_match():
    """_channel_matches_policy returns True when name or id in allowlist."""
    assert (
        _channel_matches_policy("C1", "general", allowlist={"general"}, blocklist=set())
        is True
    )
    assert (
        _channel_matches_policy("c1", "other", allowlist={"c1"}, blocklist=set())
        is True
    )


def test_channel_matches_policy_allowlist_no_match():
    """_channel_matches_policy returns False when allowlist set but channel not in it."""
    assert (
        _channel_matches_policy("C1", "other", allowlist={"general"}, blocklist=set())
        is False
    )


def test_channel_matches_policy_blocklist_takes_precedence():
    """_channel_matches_policy returns False if in both allowlist and blocklist (block wins)."""
    assert (
        _channel_matches_policy("C1", "ch", allowlist={"ch"}, blocklist={"ch"}) is False
    )


# --- _get_channel_join_config ---


def test_get_channel_join_config_defaults():
    """_get_channel_join_config returns default interval and public_only when env has defaults."""
    with patch.dict(
        "os.environ",
        {
            "CHANNEL_JOIN_INTERVAL_MINUTES": "15",
            "CHANNEL_JOIN_PUBLIC_ONLY": "true",
            "CHANNEL_ALLOWLIST": "",
            "CHANNEL_BLOCKLIST": "",
        },
        clear=False,
    ):
        config = _get_channel_join_config()
    assert config["interval_minutes"] == 15
    assert config["public_only"] is True
    assert config["allowlist"] == set()
    assert config["blocklist"] == set()


def test_get_channel_join_config_parses_allowlist_blocklist():
    """_get_channel_join_config parses CHANNEL_ALLOWLIST and CHANNEL_BLOCKLIST."""
    with patch(
        "os.environ.get",
        side_effect=lambda k, d=None: {
            "CHANNEL_JOIN_INTERVAL_MINUTES": "30",
            "CHANNEL_JOIN_PUBLIC_ONLY": "true",
            "CHANNEL_ALLOWLIST": "ch1, ch2",
            "CHANNEL_BLOCKLIST": "blocked",
        }.get(k, d),
    ):
        config = _get_channel_join_config()
    assert config["allowlist"] == {"ch1", "ch2"}
    assert config["blocklist"] == {"blocked"}


# --- channel_list ---


def test_channel_list_uses_client_and_paginates():
    """channel_list calls client.conversations_list and paginates until no cursor."""
    mock_client = MagicMock(spec=SlackAPIClient)
    mock_client.conversations_list.side_effect = [
        {
            "ok": True,
            "channels": [{"id": "C1", "name": "general"}],
            "response_metadata": {"next_cursor": "cur1"},
        },
        {
            "ok": True,
            "channels": [{"id": "C2", "name": "random"}],
            "response_metadata": {},
        },
    ]
    out = channel_list(client=mock_client)
    assert len(out) == 2
    assert out[0]["id"] == "C1"
    assert out[1]["id"] == "C2"
    assert mock_client.conversations_list.call_count == 2


def test_channel_list_stops_on_not_ok():
    """channel_list stops and returns collected channels when ok is False."""
    mock_client = MagicMock(spec=SlackAPIClient)
    mock_client.conversations_list.return_value = {"ok": False, "error": "invalid_auth"}
    out = channel_list(client=mock_client)
    assert out == []


# --- channel_join ---


def test_channel_join_calls_client():
    """channel_join calls client.conversations_join with channel_id."""
    mock_client = MagicMock(spec=SlackAPIClient)
    mock_client.conversations_join.return_value = {"ok": True}
    out = channel_join("C123", client=mock_client)
    mock_client.conversations_join.assert_called_once_with("C123")
    assert out == {"ok": True}


# --- run_channel_join_check ---


def test_run_channel_join_check_joins_allowed_skips_policy():
    """run_channel_join_check joins allowed channels and skips blocklisted."""
    mock_client = MagicMock(spec=SlackAPIClient)
    mock_client.conversations_list.return_value = {
        "ok": True,
        "channels": [
            {"id": "C1", "name": "general", "is_member": False},
            {"id": "C2", "name": "secret", "is_member": False},
        ],
        "response_metadata": {},
    }
    mock_client.conversations_join.side_effect = [{"ok": True}, {"ok": True}]
    with patch(
        "operations.slack_ops.channels._get_channel_join_config",
        return_value={
            "allowlist": set(),
            "blocklist": {"secret"},
            "public_only": True,
            "interval_minutes": 15,
        },
    ):
        result = run_channel_join_check(client=mock_client)
    assert "C1" in result["joined"]
    assert "C2" in result["skipped_policy"]
    assert result["failed"] == []


def test_run_channel_join_check_reports_failed_join():
    """run_channel_join_check appends to failed when conversations_join returns not ok."""
    mock_client = MagicMock(spec=SlackAPIClient)
    mock_client.conversations_list.return_value = {
        "ok": True,
        "channels": [{"id": "C1", "name": "general", "is_member": False}],
        "response_metadata": {},
    }
    mock_client.conversations_join.return_value = {
        "ok": False,
        "error": "method_not_supported_for_channel_type",
    }
    with patch(
        "operations.slack_ops.channels._get_channel_join_config",
        return_value={
            "allowlist": set(),
            "blocklist": set(),
            "public_only": True,
            "interval_minutes": 15,
        },
    ):
        result = run_channel_join_check(client=mock_client)
    assert result["joined"] == []
    assert len(result["failed"]) == 1
    assert result["failed"][0]["channel_id"] == "C1"
    assert result["failed"][0]["error"] == "method_not_supported_for_channel_type"


def test_run_channel_join_check_only_considers_non_member():
    """run_channel_join_check only considers channels where is_member is False."""
    mock_client = MagicMock(spec=SlackAPIClient)
    mock_client.conversations_list.return_value = {
        "ok": True,
        "channels": [
            {"id": "C1", "name": "general", "is_member": True},
            {"id": "C2", "name": "other", "is_member": False},
        ],
        "response_metadata": {},
    }
    with patch(
        "operations.slack_ops.channels._get_channel_join_config",
        return_value={
            "allowlist": set(),
            "blocklist": set(),
            "public_only": True,
            "interval_minutes": 15,
        },
    ):
        result = run_channel_join_check(client=mock_client)
    mock_client.conversations_join.assert_called_once_with("C2")
    assert result["joined"] == ["C2"]
