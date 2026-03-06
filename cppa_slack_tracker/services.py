"""
Service layer for cppa_slack_tracker.

All creates/updates/deletes for this app's models must go through functions in this
module. Do not call Model.objects.create(), model.save(), or model.delete() from
outside this module (e.g. from management commands, views, or other apps).

See docs/Contributing.md for the project-wide rule.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from django.db import transaction

from cppa_user_tracker.models import SlackUser
from cppa_user_tracker.services import get_or_create_slack_user

from .fetcher import fetch_user_info
from .models import (
    SlackChannel,
    SlackChannelMembership,
    SlackChannelMembershipChangeLog,
    SlackMessage,
    SlackTeam,
)

logger = logging.getLogger(__name__)


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
        return get_or_create_slack_user(_UNKNOWN_SLACK_USER_DATA)[0]
    try:
        return SlackUser.objects.get(slack_user_id=user_id)
    except SlackUser.DoesNotExist:
        slack_user_data = fetch_user_info(user_id)
        if slack_user_data:
            return get_or_create_slack_user(slack_user_data)[0]
        return get_or_create_slack_user(_UNKNOWN_SLACK_USER_DATA)[0]


# --- SlackTeam ---
@transaction.atomic
def get_or_create_slack_team(
    team_data: dict[str, Any],
) -> tuple[SlackTeam, bool]:
    """Get or create a Slack team (workspace). Requires team_data['team_id']. Returns (SlackTeam, created)."""
    if not team_data.get("team_id"):
        raise ValueError("Slack team ID is required")
    team_id = team_data["team_id"]
    team_name = team_data.get("team_name") or team_id
    team, created = SlackTeam.objects.get_or_create(
        team_id=team_id,
        defaults={"team_name": team_name},
    )
    if not created:
        team.team_name = team_name or team.team_name
        team.save()
    return team, created


# --- SlackChannel ---
@transaction.atomic
def get_or_create_slack_channel(
    slack_channel: dict[str, Any],
    team: SlackTeam,
    creator_user_id: Optional[str] = None,
) -> tuple[Optional[SlackChannel], bool]:
    """Get or create a Slack channel. Returns (channel, created); channel is None when skipped."""
    if not slack_channel.get("id"):
        raise ValueError("Slack channel ID is required")
    creator = None
    if creator_user_id:
        creator = _get_or_fetch_slack_user(creator_user_id)
    description = ""
    purpose = slack_channel.get("purpose")
    topic = slack_channel.get("topic")
    if isinstance(purpose, dict):
        description = purpose.get("value") or ""
    elif isinstance(topic, dict):
        description = topic.get("value") or ""
    channel_name = (slack_channel.get("name") or slack_channel.get("id") or "").strip()
    if slack_channel.get("is_im"):
        channel_type = "im"
    elif slack_channel.get("is_mpim"):
        channel_type = "mpim"
    elif slack_channel.get("is_private"):
        channel_type = "private_channel"
    elif slack_channel.get("is_channel"):
        channel_type = "public_channel"
    else:
        channel_type = slack_channel.get("type", "public_channel")
    if channel_type != "public_channel":
        logger.warning(f"Skipping non-public channel: {slack_channel['id']}")
        return None, False
    channel, created = SlackChannel.objects.get_or_create(
        team=team,
        channel_id=slack_channel["id"],
        defaults={
            "channel_name": channel_name,
            "channel_type": channel_type,
            "description": description,
            "creator": creator,
        },
    )
    if not created:
        channel.channel_name = channel_name or channel.channel_name
        channel.channel_type = channel_type or channel.channel_type
        channel.description = description
        if creator is not None:
            channel.creator = creator
        channel.save()
    return channel, created


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
    change_log, _ = SlackChannelMembershipChangeLog.objects.get_or_create(
        channel=channel,
        user=user,
        created_at=created_at,
        defaults={"is_joined": is_joined},
    )
    if change_log.is_joined != is_joined:
        change_log.is_joined = is_joined
        change_log.save(update_fields=["is_joined"])
    if is_joined:
        membership, _ = SlackChannelMembership.objects.get_or_create(
            channel=channel,
            user=user,
            defaults={"is_deleted": False},
        )
        if membership.is_deleted:
            membership.is_deleted = False
            membership.save()
    else:
        SlackChannelMembership.objects.filter(channel=channel, user=user).update(
            is_deleted=True
        )
    return change_log


@transaction.atomic
def sync_channel_memberships(channel: SlackChannel, member_ids: list[str]) -> None:
    """Sync current channel memberships to match member_ids (add new, mark removed as deleted)."""
    existing_memberships = SlackChannelMembership.objects.filter(
        channel=channel,
        is_deleted=False,
    ).select_related("user")
    existing_user_ids = {m.user.slack_user_id for m in existing_memberships}
    new_member_ids = set(member_ids) - existing_user_ids
    removed_member_ids = existing_user_ids - set(member_ids)
    for user_id in new_member_ids:
        try:
            user = SlackUser.objects.get(slack_user_id=user_id)
            membership, created = SlackChannelMembership.objects.get_or_create(
                channel=channel,
                user=user,
                defaults={"is_deleted": False},
            )
            if not created and membership.is_deleted:
                membership.is_deleted = False
                membership.save()
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
    """
    Save or update a Slack message from a Slack API payload.

    Returns None when the message is ignored: subtype is in the ignore list
    (e.g. bot_message, channel_topic), or it is channel_join/channel_leave
    (membership is recorded first), or it is the "A file was commented on"
    placeholder with no user. Otherwise creates or updates a SlackMessage
    and returns it.

    Raises ValueError if user is required but missing, or if ts is missing.
    """
    subtype = slack_message.get("subtype")
    if subtype in SUBTYPE_IGNORE:
        return None
    if subtype == "channel_join":
        event_ts = slack_message.get("ts")
        if not event_ts:
            logger.warning("Skipping channel_join without ts")
            return None
        if slack_message.get("user"):
            user = _get_or_fetch_slack_user(slack_message["user"])
            add_channel_membership_change(
                channel,
                user.slack_user_id,
                event_ts,
                True,
            )
        return None
    if subtype == "channel_leave":
        event_ts = slack_message.get("ts")
        if not event_ts:
            logger.warning("Skipping channel_leave without ts")
            return None
        if slack_message.get("user"):
            user = _get_or_fetch_slack_user(slack_message["user"])
            add_channel_membership_change(
                channel,
                user.slack_user_id,
                event_ts,
                False,
            )
        return None

    user: Optional[SlackUser] = None
    text: str
    if subtype == "file_comment":
        user = _get_or_fetch_slack_user(slack_message.get("user", "") or "-1")
        text = slack_message.get("text", "")
        comment = slack_message.get("comment")
        if isinstance(comment, dict):
            text += f"\nComment: {comment.get('comment', '')}"
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
    if not ts:
        raise ValueError("Message timestamp (ts) is required")
    created_at = _parse_slack_ts_string(ts)
    edited = slack_message.get("edited")
    if not isinstance(edited, dict):
        edited = {}
    updated_at = _parse_slack_ts_string(edited.get("ts", ts)) if edited else created_at

    message, created = SlackMessage.objects.get_or_create(
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
    if not created:
        message.user = user
        message.message = clean_text
        message.thread_ts = slack_message.get("thread_ts")
        message.slack_message_created_at = created_at
        message.slack_message_updated_at = updated_at
        message.save()
    return message
