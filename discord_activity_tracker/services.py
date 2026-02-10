"""Service layer for Discord Activity Tracker.

All DB writes go through these functions (get_or_create_* pattern).
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

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
    server_id: int,
    server_name: str,
    icon_url: str = ""
) -> Tuple[DiscordServer, bool]:
    """Get or create server, update name/icon if changed."""
    server, created = DiscordServer.objects.get_or_create(
        server_id=server_id,
        defaults={
            "server_name": server_name,
            "icon_url": icon_url,
        }
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
    is_bot: bool = False
) -> Tuple[DiscordUser, bool]:
    """Get or create user, update fields if changed."""
    user, created = DiscordUser.objects.get_or_create(
        user_id=user_id,
        defaults={
            "username": username,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "is_bot": is_bot,
        }
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
            user.save(update_fields=["username", "display_name", "avatar_url", "is_bot", "updated_at"])
            logger.debug(f"Updated user: {username}")

    return user, created


def get_or_create_discord_channel(
    server: DiscordServer,
    channel_id: int,
    channel_name: str,
    channel_type: str,
    topic: str = "",
    position: int = 0
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
        }
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
            channel.save(update_fields=["channel_name", "channel_type", "topic", "position", "updated_at"])
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
    attachment_urls: Optional[list] = None
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
        }
    )

    return message, created


def mark_message_deleted(message: DiscordMessage, deleted_at: Optional[datetime] = None) -> DiscordMessage:
    """Mark message as deleted."""
    if deleted_at is None:
        deleted_at = django_timezone.now()

    message.is_deleted = True
    message.deleted_at = deleted_at
    message.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    logger.debug(f"Marked message {message.message_id} as deleted")
    return message


def add_or_update_reaction(
    message: DiscordMessage,
    emoji: str,
    count: int
) -> Tuple[DiscordReaction, bool]:
    """Add or update reaction."""
    reaction, created = DiscordReaction.objects.update_or_create(
        message=message,
        emoji=emoji,
        defaults={"count": count}
    )

    return reaction, created


def update_channel_last_activity(channel: DiscordChannel, last_activity_at: datetime) -> DiscordChannel:
    """Update channel last_activity_at timestamp."""
    channel.last_activity_at = last_activity_at
    channel.save(update_fields=["last_activity_at", "updated_at"])
    return channel


def update_channel_last_synced(channel: DiscordChannel, timestamp: Optional[datetime] = None) -> DiscordChannel:
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
        server=server,
        last_activity_at__gte=cutoff
    ).order_by("position", "channel_name")
