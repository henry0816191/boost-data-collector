"""
Slack channel operations: list channels, join channel, run join-check (with allow/block list).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from operations.slack_ops.client import SlackAPIClient
from operations.slack_ops.tokens import get_slack_bot_token, get_slack_client

logger = logging.getLogger(__name__)

DEFAULT_JOIN_INTERVAL_MINUTES = 15
_check_lock = threading.Lock()
_stop_event = threading.Event()


def _parse_list_env(value: Optional[str]) -> set:
    """Parse comma-separated env value into a set of stripped, lowercased strings."""
    if not value or not str(value).strip():
        return set()
    return {s.strip().lower() for s in str(value).split(",") if s.strip()}


def _get_channel_join_config() -> dict:
    """Load channel-join config from env (CHANNEL_JOIN_*, CHANNEL_ALLOWLIST, CHANNEL_BLOCKLIST)."""
    interval_min = int(
        os.environ.get("CHANNEL_JOIN_INTERVAL_MINUTES", str(DEFAULT_JOIN_INTERVAL_MINUTES))
        or DEFAULT_JOIN_INTERVAL_MINUTES
    )
    if interval_min < 1:
        interval_min = DEFAULT_JOIN_INTERVAL_MINUTES
    public_only_str = (
        os.environ.get("CHANNEL_JOIN_PUBLIC_ONLY", "true") or "true"
    ).strip().lower()
    public_only = public_only_str in ("true", "1", "yes")
    allowlist = _parse_list_env(os.environ.get("CHANNEL_ALLOWLIST"))
    blocklist = _parse_list_env(os.environ.get("CHANNEL_BLOCKLIST"))
    return {
        "interval_minutes": interval_min,
        "public_only": public_only,
        "allowlist": allowlist,
        "blocklist": blocklist,
    }


def _channel_matches_policy(
    channel_id: str,
    channel_name: str,
    allowlist: set,
    blocklist: set,
) -> bool:
    """Return True if channel is allowed by allowlist/blocklist policy."""
    name_lower = (channel_name or "").lower()
    id_lower = (channel_id or "").lower()
    if blocklist and (name_lower in blocklist or id_lower in blocklist):
        return False
    if allowlist:
        return name_lower in allowlist or id_lower in allowlist
    return True


def channel_list(
    client: Optional[SlackAPIClient] = None,
    types: str = "public_channel",
    exclude_archived: bool = True,
) -> list[dict]:
    """
    List channels. Returns list of {"id", "name", "is_member", ...} for each channel.
    If client is None, uses get_slack_client().
    """
    if client is None:
        client = get_slack_client()
    all_channels = []
    cursor = None
    while True:
        data = client.conversations_list(
            types=types,
            exclude_archived=exclude_archived,
            limit=200,
            cursor=cursor,
        )
        if not data.get("ok"):
            logger.warning("conversations.list failed: %s", data.get("error", "unknown"))
            break
        channels = data.get("channels", [])
        all_channels.extend(channels)
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return all_channels


def channel_join(channel_id: str, client: Optional[SlackAPIClient] = None) -> dict:
    """Join a channel by ID. Returns Slack API response."""
    if client is None:
        client = get_slack_client()
    return client.conversations_join(channel_id)


def run_channel_join_check(
    bot_token: Optional[str] = None,
    *,
    client: Optional[SlackAPIClient] = None,
) -> dict:
    """
    Find public channels the bot is not in, apply allow/block list policy, and join them.
    Returns dict with keys: joined, failed, skipped_policy, error (optional).
    """
    if client is None:
        token = (bot_token or "").strip() or None
        try:
            client = get_slack_client(bot_token=token) if token else get_slack_client()
        except ValueError:
            logger.warning("Channel join check skipped: missing SLACK_BOT_TOKEN")
            return {
                "joined": [],
                "failed": [],
                "skipped_policy": [],
                "error": "Missing SLACK_BOT_TOKEN",
            }
    config = _get_channel_join_config()
    allowlist = config["allowlist"]
    blocklist = config["blocklist"]
    public_only = config["public_only"]
    types = "public_channel" if public_only else "public_channel,private_channel"

    result = {"joined": [], "failed": [], "skipped_policy": []}
    try:
        channels_to_consider = []
        cursor = None
        while True:
            data = client.conversations_list(
                types=types,
                exclude_archived=True,
                limit=200,
                cursor=cursor,
            )
            if not data.get("ok"):
                result["error"] = (
                    f"conversations.list failed: {data.get('error', 'unknown')}"
                )
                return result
            for ch in data.get("channels", []):
                if not ch.get("is_member", False):
                    channels_to_consider.append(
                        {"id": ch["id"], "name": ch.get("name", "") or ch["id"]}
                    )
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break

        to_join = []
        for ch in channels_to_consider:
            if _channel_matches_policy(ch["id"], ch["name"], allowlist, blocklist):
                to_join.append(ch)
            else:
                result["skipped_policy"].append(ch["id"])

        for ch in to_join:
            try:
                jdata = client.conversations_join(ch["id"])
                if jdata.get("ok"):
                    result["joined"].append(ch["id"])
                    logger.info("Joined channel: %s (%s)", ch["name"], ch["id"])
                else:
                    result["failed"].append(
                        {
                            "channel_id": ch["id"],
                            "channel_name": ch["name"],
                            "error": jdata.get("error", "unknown"),
                        }
                    )
            except Exception as e:
                result["failed"].append(
                    {
                        "channel_id": ch["id"],
                        "channel_name": ch["name"],
                        "error": str(e),
                    }
                )
        return result
    except Exception as e:
        logger.exception("Channel join check failed: %s", e)
        result["error"] = str(e)
        return result


def start_channel_join_background(
    bot_token: Optional[str] = None,
) -> threading.Thread:
    """Start a daemon thread that runs the channel-join check every N minutes."""
    def _run_loop():
        config = _get_channel_join_config()
        interval_seconds = config["interval_minutes"] * 60
        first_run_delay = min(60, interval_seconds)
        _stop_event.wait(first_run_delay)
        if _stop_event.is_set():
            return
        while not _stop_event.is_set():
            if _check_lock.acquire(blocking=False):
                try:
                    run_channel_join_check(bot_token)
                finally:
                    _check_lock.release()
            waited = 0
            while waited < interval_seconds and not _stop_event.is_set():
                _stop_event.wait(min(60, interval_seconds - waited))
                waited += 60

    t = threading.Thread(
        target=_run_loop,
        daemon=True,
        name="SlackChannelJoiner",
    )
    t.start()
    return t


def stop_channel_join_background() -> None:
    """Signal the background channel-join thread to stop."""
    _stop_event.set()
