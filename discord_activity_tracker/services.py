"""Service layer for Discord Activity Tracker.

All DB writes go through these functions (get_or_create_* pattern).
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.utils import timezone as django_timezone

from .models import (
    DiscordServer,
    DiscordUser,
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


def get_or_create_discord_user(
    user_id: int,
    username: str,
    display_name: str = "",
    avatar_url: str = "",
    is_bot: bool = False,
) -> Tuple[DiscordUser, bool]:
    """Get or create user, update fields if changed."""
    user, created = DiscordUser.objects.get_or_create(
        user_id=user_id,
        defaults={
            "username": username,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "is_bot": is_bot,
        },
    )

    if not created:
        # Update fields if changed
        updated = False
        if user.username != username:
            user.username = username
            updated = True
        if user.display_name != display_name:
            user.display_name = display_name
            updated = True
        if user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            updated = True
        if user.is_bot != is_bot:
            user.is_bot = is_bot
            updated = True

        if updated:
            user.save(
                update_fields=[
                    "username",
                    "display_name",
                    "avatar_url",
                    "is_bot",
                    "updated_at",
                ]
            )
            logger.debug(f"Updated user: {username}")

    return user, created


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
    author: DiscordUser,
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
) -> Dict[int, DiscordUser]:
    """Bulk upsert users. Returns {discord_user_id: DiscordUser} with PKs."""
    if not user_data_list:
        return {}

    # Deduplicate by user_id (last-seen wins)
    unique = {d["user_id"]: d for d in user_data_list}

    now = django_timezone.now()
    instances = [
        DiscordUser(
            user_id=d["user_id"],
            username=d["username"],
            display_name=d.get("display_name", ""),
            avatar_url=d.get("avatar_url", ""),
            is_bot=d.get("is_bot", False),
            created_at=now,
            updated_at=now,
        )
        for d in unique.values()
    ]

    DiscordUser.objects.bulk_create(
        instances,
        update_conflicts=True,
        unique_fields=["user_id"],
        update_fields=["username", "display_name", "avatar_url", "is_bot", "updated_at"],
    )

    # Fetch back with PKs (bulk_create+update_conflicts doesn't return PKs for updated rows)
    db_users = DiscordUser.objects.filter(
        user_id__in=list(unique.keys())
    ).only("id", "user_id")
    return {u.user_id: u for u in db_users}


def bulk_upsert_discord_messages(
    message_data_list: List[Dict[str, Any]],
    channel: DiscordChannel,
    user_map: Dict[int, DiscordUser],
) -> Dict[int, DiscordMessage]:
    """Bulk upsert messages. Returns {discord_message_id: DiscordMessage} with PKs."""
    if not message_data_list:
        return {}

    now = django_timezone.now()
    instances = []
    for d in message_data_list:
        author = user_map.get(d["author"]["user_id"])
        if author is None:
            logger.warning(f"Skipping message {d['message_id']}: author not in user_map")
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
    db_msgs = DiscordMessage.objects.filter(
        message_id__in=msg_ids
    ).only("id", "message_id")
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
                    reaction_data.append({
                        "discord_message_id": msg["message_id"],
                        "emoji": reaction["emoji"],
                        "count": reaction.get("count", 0),
                    })
        if reaction_data:
            bulk_upsert_discord_reactions(reaction_data, message_map)

    return len(message_data_list)
