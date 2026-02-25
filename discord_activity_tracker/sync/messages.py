"""Message sync logic - fetch from Discord and store in DB."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.utils import timezone as django_timezone
from asgiref.sync import sync_to_async

from cppa_user_tracker.services import get_or_create_discord_profile
from ..models import DiscordServer, DiscordChannel
from ..services import (
    get_or_create_discord_server,
    get_or_create_discord_channel,
    create_or_update_discord_message,
    add_or_update_reaction,
    update_channel_last_synced,
    update_channel_last_activity,
    bulk_process_message_batch,
)
from .client import DiscordSyncClient, run_async
from .utils import parse_datetime, parse_discord_user

logger = logging.getLogger(__name__)


async def sync_guild_async(client: DiscordSyncClient, guild_id: int):
    """Sync guild/server info."""
    guild = await client.get_guild(guild_id)
    if guild is None:
        raise ValueError(f"Guild {guild_id} not found or not accessible")

    logger.info(f"Syncing guild: {guild.name} ({guild.id})")

    icon_url = str(guild.icon.url) if guild.icon else ""
    server, created = await sync_to_async(get_or_create_discord_server)(
        server_id=guild.id, server_name=guild.name, icon_url=icon_url
    )

    if created:
        logger.info(f"Created new server: {guild.name}")
    else:
        logger.debug(f"Server already exists: {guild.name}")

    return server


async def sync_channels_async(
    client: DiscordSyncClient, server: DiscordServer, guild_id: int
):
    """Sync all text channels in guild."""
    channels = await client.get_channels(guild_id)
    logger.info(f"Found {len(channels)} text channels to sync")

    synced_channels = []

    for channel in channels:
        logger.debug(f"Syncing channel: #{channel.name}")

        discord_channel, created = await sync_to_async(get_or_create_discord_channel)(
            server=server,
            channel_id=channel.id,
            channel_name=channel.name,
            channel_type=str(channel.type),
            topic=channel.topic or "",
            position=channel.position,
        )

        if created:
            logger.info(f"Created new channel: #{channel.name}")

        synced_channels.append(discord_channel)

    logger.info(f"Synced {len(synced_channels)} channels")
    return synced_channels


async def _process_message_data(channel: DiscordChannel, message_data: Dict[str, Any]):
    """Process message dict and store in DB."""
    try:
        author_data = message_data.get("author", {})
        author_info = parse_discord_user(author_data)

        author, _ = await sync_to_async(get_or_create_discord_profile)(
            discord_user_id=author_info["user_id"],
            username=author_info["username"],
            display_name=author_info["display_name"],
            avatar_url=author_info["avatar_url"],
            is_bot=author_info["is_bot"],
        )

        created_at = parse_datetime(message_data.get("created_at"))
        edited_at = parse_datetime(message_data.get("edited_at"))

        if created_at is None:
            logger.error(
                f"Message {message_data.get('id')} has no created_at timestamp"
            )
            return

        attachments = message_data.get("attachments", [])
        attachment_urls = [att.get("url") for att in attachments if att.get("url")]

        reference = message_data.get("reference", {})
        reply_to_message_id = reference.get("message_id") if reference else None

        message, created = await sync_to_async(create_or_update_discord_message)(
            message_id=message_data["id"],
            channel=channel,
            author=author,
            content=message_data.get("content", ""),
            message_created_at=created_at,
            message_edited_at=edited_at,
            reply_to_message_id=reply_to_message_id,
            attachment_urls=attachment_urls,
        )

        reactions = message_data.get("reactions", [])
        for reaction_data in reactions:
            emoji = reaction_data.get("emoji")
            count = reaction_data.get("count", 0)
            if emoji:
                await sync_to_async(add_or_update_reaction)(message, emoji, count)

        if created:
            logger.debug(
                f"Created message {message.message_id} in #{channel.channel_name}"
            )

    except Exception as e:
        logger.exception(f"Error processing message {message_data.get('id')}: {e}")


BATCH_SIZE = 500


def _prepare_message_data(
    message_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Parse raw Discord message dict into normalized format for bulk processing."""
    author_data = message_data.get("author", {})
    author_info = parse_discord_user(author_data)

    created_at = parse_datetime(message_data.get("created_at"))
    edited_at = parse_datetime(message_data.get("edited_at"))

    if created_at is None:
        logger.error(f"Message {message_data.get('id')} has no created_at timestamp")
        return None

    attachments = message_data.get("attachments", [])
    attachment_urls = [att.get("url") for att in attachments if att.get("url")]

    reference = message_data.get("reference", {})
    reply_to_message_id = reference.get("message_id") if reference else None

    return {
        "message_id": message_data["id"],
        "author": author_info,
        "content": message_data.get("content", ""),
        "message_created_at": created_at,
        "message_edited_at": edited_at,
        "reply_to_message_id": reply_to_message_id,
        "attachment_urls": attachment_urls,
        "reactions": message_data.get("reactions", []),
    }


async def _process_messages_in_batches(
    channel: DiscordChannel,
    messages: List[Dict[str, Any]],
    batch_size: int = BATCH_SIZE,
) -> int:
    """Process messages in batches using bulk DB operations."""
    total_processed = 0

    for i in range(0, len(messages), batch_size):
        batch_raw = messages[i : i + batch_size]

        batch_prepared = []
        for msg_data in batch_raw:
            prepared = _prepare_message_data(msg_data)
            if prepared is not None:
                batch_prepared.append(prepared)

        if not batch_prepared:
            continue

        count = await sync_to_async(bulk_process_message_batch)(batch_prepared, channel)
        total_processed += count

        logger.info(
            f"Batch {i // batch_size + 1}: {total_processed}/{len(messages)} "
            f"messages for #{channel.channel_name}"
        )

    return total_processed


async def sync_channel_messages_async(
    client: DiscordSyncClient,
    channel: DiscordChannel,
    guild_id: int,
    since_date: Optional[datetime] = None,
    full_sync: bool = False,
):
    """Sync messages from channel (incremental or full)."""
    logger.info(f"Syncing messages for channel: #{channel.channel_name}")

    # Determine sync start point
    if full_sync:
        after = None
        logger.info("Full sync mode: fetching all messages")
    elif since_date:
        after = since_date
        logger.info(f"Syncing messages since: {after}")
    elif channel.last_synced_at:
        after = channel.last_synced_at
        logger.info(f"Syncing messages since last sync: {after}")
    else:
        # Default: fetch last 30 days
        after = django_timezone.now() - timedelta(days=30)
        logger.info(f"First sync: fetching messages from last 30 days ({after})")

    discord_channel = await client.get_channel(channel.channel_id)
    if discord_channel is None:
        return

    # Fetch messages
    try:
        messages = await client.fetch_messages_since(
            channel=discord_channel,
            after=after,
            limit=None,  # No limit - fetch all messages
        )

        logger.info(f"Fetched {len(messages)} messages from #{channel.channel_name}")

        processed = await _process_messages_in_batches(channel, messages)
        logger.info(f"Bulk-processed {processed} messages for #{channel.channel_name}")

        if messages:
            last_message_time = parse_datetime(messages[-1]["created_at"])
            if last_message_time:
                await sync_to_async(update_channel_last_activity)(
                    channel, last_message_time
                )

        await sync_to_async(update_channel_last_synced)(channel)

        logger.info(
            f"Successfully synced {len(messages)} messages for #{channel.channel_name}"
        )

    except Exception as e:
        logger.exception(f"Error syncing messages for #{channel.channel_name}: {e}")
        raise


def sync_guild(token: str, guild_id: int):
    """Sync guild/server (sync wrapper)."""
    client = DiscordSyncClient(token)
    try:
        return run_async(sync_guild_async(client, guild_id))
    finally:
        run_async(client.close())


def sync_channels(token: str, server: DiscordServer, guild_id: int):
    """Sync channels (sync wrapper)."""
    client = DiscordSyncClient(token)
    try:
        return run_async(sync_channels_async(client, server, guild_id))
    finally:
        run_async(client.close())


def sync_channel_messages(
    token: str,
    channel: DiscordChannel,
    guild_id: int,
    since_date: Optional[datetime] = None,
    full_sync: bool = False,
):
    """Sync channel messages (sync wrapper)."""
    client = DiscordSyncClient(token)
    try:
        run_async(
            sync_channel_messages_async(
                client, channel, guild_id, since_date, full_sync
            )
        )
    finally:
        run_async(client.close())


MAX_CONCURRENT_CHANNELS = 5


async def _sync_all_channels_async(
    client: DiscordSyncClient,
    channels: List[DiscordChannel],
    guild_id: int,
    since_date: Optional[datetime] = None,
    full_sync: bool = False,
):
    """Sync multiple channels concurrently with a semaphore."""
    sem = asyncio.Semaphore(MAX_CONCURRENT_CHANNELS)

    async def _sync_one(channel: DiscordChannel):
        async with sem:
            try:
                await sync_channel_messages_async(
                    client, channel, guild_id, since_date, full_sync
                )
            except Exception as e:
                logger.error(f"Failed to sync channel #{channel.channel_name}: {e}")

    await asyncio.gather(*[_sync_one(ch) for ch in channels])


def sync_all_channels(
    token: str,
    guild_id: int,
    since_date: Optional[datetime] = None,
    full_sync: bool = False,
    active_only: bool = True,
    active_days: int = 30,
):
    """Sync all channels in guild (parallel fetch, single client)."""
    logger.info(f"Starting sync for guild {guild_id}")

    client = DiscordSyncClient(token)
    try:
        # Sync guild
        server = run_async(sync_guild_async(client, guild_id))

        # Sync channels
        channels = run_async(sync_channels_async(client, server, guild_id))

        # Filter for active channels if requested
        if active_only and not full_sync:
            cutoff = django_timezone.now() - timedelta(days=active_days)
            channels = [
                ch
                for ch in channels
                if ch.last_activity_at and ch.last_activity_at >= cutoff
            ]
            logger.info(
                f"Filtered to {len(channels)} active channels "
                f"(last {active_days} days)"
            )

        # Sync messages for channels concurrently (up to MAX_CONCURRENT_CHANNELS)
        logger.info(
            f"Syncing {len(channels)} channels "
            f"(max {MAX_CONCURRENT_CHANNELS} concurrent)"
        )
        run_async(
            _sync_all_channels_async(client, channels, guild_id, since_date, full_sync)
        )
    finally:
        run_async(client.close())

    logger.info(f"Completed sync for guild {guild_id}")
