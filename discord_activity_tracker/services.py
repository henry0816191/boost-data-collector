"""Service layer for Discord Activity Tracker.

All DB writes go through these functions (get_or_create_* pattern).
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.utils import timezone as django_timezone

from cppa_user_tracker.models import DiscordProfile
from cppa_user_tracker.services import get_or_create_discord_profile
from .models import (
    DiscordServer,
    DiscordChannel,
    DiscordMessage,
    DiscordReaction,
)

logger = logging.getLogger(__name__)


def get_or_create_discord_server(
    server_id: int, server_name: str, icon_url: str = ""
) -> Tuple[DiscordServer, bool]:
    """Get or create server, update name/icon if changed."""
    server, created = DiscordServer.objects.get_or_create(
        server_id=server_id,
        defaults={
            "server_name": server_name,
            "icon_url": icon_url,
        },
    )

    if not created:
        # Update fields if changed
        updated = False
        if server.server_name != server_name:
            server.server_name = server_name
            updated = True
        if server.icon_url != icon_url:
            server.icon_url = icon_url
            updated = True

        if updated:
            server.save(update_fields=["server_name", "icon_url", "updated_at"])
            logger.debug(f"Updated server: {server_name}")

    return server, created


def get_or_create_discord_channel(
    server: DiscordServer,
    channel_id: int,
    channel_name: str,
    channel_type: str,
    topic: str = "",
    position: int = 0,
) -> Tuple[DiscordChannel, bool]:
    """Get or create channel, update fields if changed."""
    channel, created = DiscordChannel.objects.get_or_create(
        channel_id=channel_id,
        defaults={
            "server": server,
            "channel_name": channel_name,
            "channel_type": channel_type,
            "topic": topic,
            "position": position,
        },
    )

    if not created:
        # Update fields if changed
        updated = False
        if channel.channel_name != channel_name:
            channel.channel_name = channel_name
            updated = True
        if channel.channel_type != channel_type:
            channel.channel_type = channel_type
            updated = True
        if channel.topic != topic:
            channel.topic = topic
            updated = True
        if channel.position != position:
            channel.position = position
            updated = True

        if updated:
            channel.save(
                update_fields=[
                    "channel_name",
                    "channel_type",
                    "topic",
                    "position",
                    "updated_at",
                ]
            )
            logger.debug(f"Updated channel: {channel_name}")

    return channel, created


def create_or_update_discord_message(
    message_id: int,
    channel: DiscordChannel,
    author: DiscordProfile,
    content: str,
    message_created_at: datetime,
    message_edited_at: Optional[datetime] = None,
    reply_to_message_id: Optional[int] = None,
    attachment_urls: Optional[list] = None,
) -> Tuple[DiscordMessage, bool]:
    """Create or update message."""
    if attachment_urls is None:
        attachment_urls = []

    message, created = DiscordMessage.objects.update_or_create(
        message_id=message_id,
        defaults={
            "channel": channel,
            "author": author,
            "content": content,
            "message_created_at": message_created_at,
            "message_edited_at": message_edited_at,
            "reply_to_message_id": reply_to_message_id,
            "has_attachments": len(attachment_urls) > 0,
            "attachment_urls": attachment_urls,
            "is_deleted": False,
        },
    )

    return message, created


def mark_message_deleted(
    message: DiscordMessage, deleted_at: Optional[datetime] = None
) -> DiscordMessage:
    """Mark message as deleted."""
    if deleted_at is None:
        deleted_at = django_timezone.now()

    message.is_deleted = True
    message.deleted_at = deleted_at
    message.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    logger.debug(f"Marked message {message.message_id} as deleted")
    return message


def add_or_update_reaction(
    message: DiscordMessage, emoji: str, count: int
) -> Tuple[DiscordReaction, bool]:
    """Add or update reaction."""
    reaction, created = DiscordReaction.objects.update_or_create(
        message=message, emoji=emoji, defaults={"count": count}
    )

    return reaction, created


def update_channel_last_activity(
    channel: DiscordChannel, last_activity_at: datetime
) -> DiscordChannel:
    """Update channel last_activity_at timestamp."""
    channel.last_activity_at = last_activity_at
    channel.save(update_fields=["last_activity_at", "updated_at"])
    return channel


def update_channel_last_synced(
    channel: DiscordChannel, timestamp: Optional[datetime] = None
) -> DiscordChannel:
    """Update channel last_synced_at (defaults to now)."""
    if timestamp is None:
        timestamp = django_timezone.now()

    channel.last_synced_at = timestamp
    channel.save(update_fields=["last_synced_at", "updated_at"])
    logger.info(f"Updated last_synced_at for channel {channel.channel_name}")
    return channel


def get_active_channels(server: DiscordServer, days: int = 30) -> list:
    """Get channels with activity in last N days."""
    from datetime import timedelta

    cutoff = django_timezone.now() - timedelta(days=days)

    return DiscordChannel.objects.filter(
        server=server, last_activity_at__gte=cutoff
    ).order_by("position", "channel_name")


# ---------------------------------------------------------------------------
# Bulk operations (for high-throughput message sync)
# ---------------------------------------------------------------------------


def bulk_upsert_discord_users(
    user_data_list: List[Dict[str, Any]],
) -> Dict[int, DiscordProfile]:
    """Bulk upsert Discord user profiles. Returns {discord_user_id: DiscordProfile} with PKs.

    Uses get_or_create per user because DiscordProfile uses multi-table
    inheritance (BaseProfile) which doesn't support bulk_create(update_conflicts=True).
    Typical batches have 10-50 unique users, so individual creates are fine.
    """
    if not user_data_list:
        return {}

    # Deduplicate by user_id (last-seen wins)
    unique = {d["user_id"]: d for d in user_data_list}

    # Fetch existing profiles in one query
    existing = {
        p.discord_user_id: p
        for p in DiscordProfile.objects.filter(discord_user_id__in=list(unique.keys()))
    }

    result = {}
    for uid, d in unique.items():
        if uid in existing:
            profile = existing[uid]
            username_val = d["username"] or ""
            display_name_val = d.get("display_name", "") or ""
            avatar_url_val = d.get("avatar_url", "") or ""
            updated = False
            if username_val and profile.username != username_val:
                profile.username = username_val
                updated = True
            if display_name_val and profile.display_name != display_name_val:
                profile.display_name = display_name_val
                updated = True
            if avatar_url_val and profile.avatar_url != avatar_url_val:
                profile.avatar_url = avatar_url_val
                updated = True
            if profile.is_bot != d.get("is_bot", False):
                profile.is_bot = d.get("is_bot", False)
                updated = True
            if updated:
                profile.save()
            result[uid] = profile
        else:
            profile, _ = get_or_create_discord_profile(
                discord_user_id=uid,
                username=d["username"],
                display_name=d.get("display_name", ""),
                avatar_url=d.get("avatar_url", ""),
                is_bot=d.get("is_bot", False),
            )
            result[uid] = profile

    return result


def bulk_upsert_discord_messages(
    message_data_list: List[Dict[str, Any]],
    channel: DiscordChannel,
    user_map: Dict[int, DiscordProfile],
) -> Dict[int, DiscordMessage]:
    """Bulk upsert messages. Returns {discord_message_id: DiscordMessage} with PKs."""
    if not message_data_list:
        return {}

    now = django_timezone.now()
    instances = []
    for d in message_data_list:
        author = user_map.get(d["author"]["user_id"])
        if author is None:
            logger.warning(
                f"Skipping message {d['message_id']}: author not in user_map"
            )
            continue
        attachments = d.get("attachment_urls", [])
        instances.append(
            DiscordMessage(
                message_id=d["message_id"],
                channel=channel,
                author=author,
                content=d.get("content", ""),
                message_created_at=d["message_created_at"],
                message_edited_at=d.get("message_edited_at"),
                reply_to_message_id=d.get("reply_to_message_id"),
                has_attachments=len(attachments) > 0,
                attachment_urls=attachments,
                is_deleted=False,
                created_at=now,
                updated_at=now,
            )
        )

    if not instances:
        return {}

    DiscordMessage.objects.bulk_create(
        instances,
        update_conflicts=True,
        unique_fields=["message_id"],
        update_fields=[
            "channel",
            "author",
            "content",
            "message_created_at",
            "message_edited_at",
            "reply_to_message_id",
            "has_attachments",
            "attachment_urls",
            "is_deleted",
            "updated_at",
        ],
    )

    msg_ids = [inst.message_id for inst in instances]
    db_msgs = DiscordMessage.objects.filter(message_id__in=msg_ids).only(
        "id", "message_id"
    )
    return {m.message_id: m for m in db_msgs}


def bulk_upsert_discord_reactions(
    reaction_data_list: List[Dict[str, Any]],
    message_map: Dict[int, DiscordMessage],
) -> None:
    """Bulk upsert reactions."""
    if not reaction_data_list:
        return

    now = django_timezone.now()
    # Deduplicate by (message_id, emoji) — keep last
    seen = {}
    for d in reaction_data_list:
        msg = message_map.get(d["discord_message_id"])
        if msg is None:
            continue
        key = (msg.pk, d["emoji"])
        seen[key] = DiscordReaction(
            message=msg,
            emoji=d["emoji"],
            count=d.get("count", 1),
            created_at=now,
            updated_at=now,
        )

    if not seen:
        return

    DiscordReaction.objects.bulk_create(
        list(seen.values()),
        update_conflicts=True,
        unique_fields=["message", "emoji"],
        update_fields=["count", "updated_at"],
    )


def bulk_process_message_batch(
    message_data_list: List[Dict[str, Any]],
    channel: DiscordChannel,
) -> int:
    """Orchestrate bulk upsert: users → messages → reactions. Returns count."""
    if not message_data_list:
        return 0

    with transaction.atomic():
        # Phase 1: users
        user_data_by_id = {}
        for msg in message_data_list:
            author = msg["author"]
            user_data_by_id[author["user_id"]] = author
        user_map = bulk_upsert_discord_users(list(user_data_by_id.values()))

        # Phase 2: messages
        message_map = bulk_upsert_discord_messages(message_data_list, channel, user_map)

        # Phase 3: reactions
        reaction_data = []
        for msg in message_data_list:
            for reaction in msg.get("reactions", []):
                if reaction.get("emoji"):
                    reaction_data.append(
                        {
                            "discord_message_id": msg["message_id"],
                            "emoji": reaction["emoji"],
                            "count": reaction.get("count", 0),
                        }
                    )
        if reaction_data:
            bulk_upsert_discord_reactions(reaction_data, message_map)

    return len(message_data_list)
