"""
Service layer for cppa_slack_tracker.

All creates/updates/deletes for this app's models must go through functions in this
module. Do not call Model.objects.create(), model.save(), or model.delete() from
outside this module (e.g. from management commands, views, or other apps).

See docs/Contributing.md for the project-wide rule.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from django.db import transaction

from cppa_user_tracker.models import SlackUser
from cppa_user_tracker.services import add_or_update_slack_user

from .fetcher import fetch_user_info
from .models import (
    SlackChannel,
    SlackChannelMembership,
    SlackChannelMembershipChangeLog,
    SlackMessage,
    SlackTeam,
)


# Slack message subtypes to ignore
SUBTYPE_IGNORE = [
    "app_conversation_leave",
    "app_conversation_join",
    "bot_add",
    "bot_message",
    "bot_remove",
    "channel_purpose",
    "channel_archive",
    "channel_name",
    "channel_topic",
    "channel_convert_to_public",
    "document_comment_root",
    "huddle_thread",
    "pinned_item",
    "reminder_add",
    "reply_broadcast",
    "sh_room_created",
    "slack_audio",
    "slack_image",
    "slack_video",
]


# --- Helpers ---
def _parse_slack_timestamp(timestamp: Optional[float]) -> datetime:
    """Convert Slack timestamp to datetime."""
    if timestamp:
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass
    return datetime.now(timezone.utc)


def _parse_slack_ts_string(ts: str) -> datetime:
    """Convert Slack timestamp string to datetime."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return datetime.now(timezone.utc)


# Synthetic "unknown" Slack user when a real user cannot be resolved (do not call API)
_UNKNOWN_SLACK_USER_ID = "-1"
_UNKNOWN_SLACK_USER_DATA = {
    "id": _UNKNOWN_SLACK_USER_ID,
    "name": "unknown",
    "real_name": "Unknown",
    "profile": {"image_72": ""},
}


def _get_or_fetch_slack_user(user_id: str) -> SlackUser:
    """Get a Slack user from DB; if not found, fetch via fetch_user_info and upsert. Returns unknown user (id -1) if not found."""
    if user_id == _UNKNOWN_SLACK_USER_ID:
        return add_or_update_slack_user(_UNKNOWN_SLACK_USER_DATA)
    try:
        return SlackUser.objects.get(slack_user_id=user_id)
    except SlackUser.DoesNotExist:
        slack_user_data = fetch_user_info(user_id)
        if slack_user_data:
            return add_or_update_slack_user(slack_user_data)
        return add_or_update_slack_user(_UNKNOWN_SLACK_USER_DATA)


# --- SlackTeam ---
@transaction.atomic
def add_or_update_slack_team(team_data: dict[str, Any]) -> SlackTeam:
    """Add or update a Slack team (workspace). Requires team_data['team_id']. Returns the SlackTeam."""
    if not team_data.get("team_id"):
        raise ValueError("Slack team ID is required")
    team, _ = SlackTeam.objects.update_or_create(
        team_id=team_data["team_id"],
        defaults={
            "team_name": team_data.get("team_name", team_data["team_id"]),
        },
    )
    return team


# --- SlackChannel ---
@transaction.atomic
def add_or_update_slack_channel(
    slack_channel: dict[str, Any],
    team: SlackTeam,
    creator_user_id: Optional[str] = None,
) -> SlackChannel:
    """Add or update a Slack channel. Requires slack_channel['id']. Returns the SlackChannel."""
    if not slack_channel.get("id"):
        raise ValueError("Slack channel ID is required")
    creator = None
    if creator_user_id:
        creator = _get_or_fetch_slack_user(creator_user_id)
    description = ""
    if slack_channel.get("purpose"):
        description = slack_channel["purpose"].get("value") or ""
    elif slack_channel.get("topic"):
        description = slack_channel["topic"].get("value") or ""
    channel, _ = SlackChannel.objects.update_or_create(
        channel_id=slack_channel["id"],
        defaults={
            "team": team,
            "channel_name": slack_channel.get("name", slack_channel["id"]),
            "channel_type": slack_channel.get("type", "public_channel"),
            "description": description,
            "creator": creator,
        },
    )
    return channel


# --- SlackChannelMembership ---
@transaction.atomic
def add_channel_membership_change(
    channel: SlackChannel,
    slack_user_id: str,
    ts: str,
    is_joined: bool,
) -> SlackChannelMembershipChangeLog:
    """Record a channel join/leave and update current membership. Returns the change log entry. Raises ValueError if user not found."""
    try:
        user = SlackUser.objects.get(slack_user_id=slack_user_id)
    except SlackUser.DoesNotExist:
        raise ValueError(f"User {slack_user_id} not found")
    created_at = _parse_slack_ts_string(ts)
    change_log = SlackChannelMembershipChangeLog.objects.create(
        channel=channel,
        user=user,
        is_joined=is_joined,
        created_at=created_at,
    )
    if is_joined:
        SlackChannelMembership.objects.update_or_create(
            channel=channel,
            user=user,
            defaults={"is_deleted": False},
        )
    else:
        SlackChannelMembership.objects.filter(channel=channel, user=user).update(
            is_deleted=True
        )
    return change_log


def sync_channel_memberships(channel: SlackChannel, member_ids: list[str]) -> None:
    """Sync current channel memberships to match member_ids (add new, mark removed as deleted)."""
    existing_memberships = SlackChannelMembership.objects.filter(
        channel=channel,
        is_deleted=False,
    )
    existing_user_ids = {m.user.slack_user_id for m in existing_memberships}
    new_member_ids = set(member_ids) - existing_user_ids
    removed_member_ids = existing_user_ids - set(member_ids)
    for user_id in new_member_ids:
        try:
            user = SlackUser.objects.get(slack_user_id=user_id)
            SlackChannelMembership.objects.update_or_create(
                channel=channel,
                user=user,
                defaults={"is_deleted": False},
            )
        except SlackUser.DoesNotExist:
            continue
    for user_id in removed_member_ids:
        try:
            user = SlackUser.objects.get(slack_user_id=user_id)
            SlackChannelMembership.objects.filter(channel=channel, user=user).update(
                is_deleted=True
            )
        except SlackUser.DoesNotExist:
            continue


# --- SlackMessage ---
def _message_text_for_subtype(
    slack_message: dict[str, Any], subtype: str
) -> Optional[str]:
    """Return message text for me_message; None for unknown."""
    if subtype == "me_message":
        return f"<@{slack_message.get('user')}> {slack_message.get('text', '')}"
    return None


@transaction.atomic
def save_slack_message(
    channel: SlackChannel,
    slack_message: dict[str, Any],
) -> Optional[SlackMessage]:
    """Save or update a Slack message. Returns None if the message is ignored (e.g. join/leave). Raises ValueError for unknown subtype or missing user."""
    subtype = slack_message.get("subtype")
    if subtype in SUBTYPE_IGNORE:
        return None
    if subtype == "channel_join":
        if slack_message.get("user"):
            user = _get_or_fetch_slack_user(slack_message["user"])
            add_channel_membership_change(
                channel,
                user.slack_user_id,
                slack_message.get("ts", ""),
                True,
            )
        return None
    if subtype == "channel_leave":
        if slack_message.get("user"):
            user = _get_or_fetch_slack_user(slack_message["user"])
            add_channel_membership_change(
                channel,
                user.slack_user_id,
                slack_message.get("ts", ""),
                False,
            )
        return None

    user: Optional[SlackUser] = None
    text: str
    if subtype == "file_comment":
        user = _get_or_fetch_slack_user(slack_message.get("user", "") or "-1")
        text = slack_message.get("text", "")
        if slack_message.get("comment"):
            text += f"\nComment: {slack_message.get('comment', {}).get('comment', '')}"
    elif subtype:
        text = _message_text_for_subtype(slack_message, subtype) or ""
    else:
        text = slack_message.get("text", "")

    if user is None:
        user_id = slack_message.get("user")
        if not user_id:
            if slack_message.get("text") == "A file was commented on":
                return None
            raise ValueError("User not found")
        user = _get_or_fetch_slack_user(user_id)

    clean_text = text.replace("\x00", "").replace("\u0000", "")
    ts = slack_message.get("ts")
    created_at = _parse_slack_ts_string(ts)
    edited = slack_message.get("edited", {})
    updated_at = _parse_slack_ts_string(edited.get("ts", ts)) if edited else created_at

    message, created = SlackMessage.objects.update_or_create(
        channel=channel,
        ts=ts,
        defaults={
            "user": user,
            "message": clean_text,
            "thread_ts": slack_message.get("thread_ts"),
            "slack_message_created_at": created_at,
            "slack_message_updated_at": updated_at,
        },
    )
    return message
