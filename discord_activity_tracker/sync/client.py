"""Discord API client wrapper."""

import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

import discord

logger = logging.getLogger(__name__)


class DiscordSyncClient:
    """Discord client wrapper for syncing messages."""

    def __init__(self, token: str):
        """Initialize client with token."""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        self.client = discord.Client(intents=intents)
        self.token = token
        self._ready = False

    async def _ensure_ready(self):
        """Ensure client is logged in and ready."""
        if not self._ready:
            await self.client.login(self.token)
            self._ready = True

    async def get_guild(self, guild_id: int) -> Optional[discord.Guild]:
        """Get guild by ID."""
        await self._ensure_ready()
        try:
            guild = await self.client.fetch_guild(guild_id)
        except discord.NotFound:
            logger.error(f"Guild {guild_id} not found")
            return None
        except discord.Forbidden:
            logger.error(f"No access to guild {guild_id}")
            return None
        return guild

    async def get_channels(self, guild_id: int) -> List[discord.TextChannel]:
        """Get all text channels in guild."""
        guild = await self.get_guild(guild_id)
        if guild is None:
            return []

        try:
            all_channels = await guild.fetch_channels()
        except Exception as e:
            logger.error(f"Error fetching channels for guild {guild.name}: {e}")
            return []

        channels = [
            channel
            for channel in all_channels
            if isinstance(channel, discord.TextChannel)
        ]

        logger.info(f"Found {len(channels)} text channels in guild {guild.name}")
        return channels

    async def get_channel(self, channel_id: int) -> Optional[discord.TextChannel]:
        """Get channel by ID."""
        await self._ensure_ready()
        try:
            channel = await self.client.fetch_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
            logger.error(f"Channel {channel_id} is not a text channel")
            return None
        except discord.NotFound:
            logger.error(f"Channel {channel_id} not found")
            return None
        except discord.Forbidden:
            logger.error(f"No access to channel {channel_id}")
            return None

    async def fetch_messages_since(
        self,
        channel: discord.TextChannel,
        after: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch messages from channel since datetime (None = all)."""
        messages = []
        count = 0

        try:
            logger.info(
                f"Fetching messages from #{channel.name} (after={after}, limit={limit})"
            )

            async for message in channel.history(
                limit=limit, after=after, oldest_first=True
            ):
                msg_data = self._message_to_dict(message)
                messages.append(msg_data)
                count += 1

                if count % 100 == 0:
                    logger.debug(f"Fetched {count} messages from #{channel.name}")

            logger.info(f"Fetched {len(messages)} messages from #{channel.name}")

        except discord.Forbidden:
            logger.error(f"No permission to read messages in #{channel.name}")
        except discord.HTTPException as e:
            logger.error(f"HTTP error fetching messages from #{channel.name}: {e}")
        except Exception as e:
            logger.exception(
                f"Unexpected error fetching messages from #{channel.name}: {e}"
            )

        return messages

    def _message_to_dict(self, message: discord.Message) -> Dict[str, Any]:
        """Convert message to dict."""
        return {
            "id": message.id,
            "content": message.content,
            "author": {
                "id": message.author.id,
                "username": message.author.name,
                "display_name": (
                    message.author.display_name
                    if hasattr(message.author, "display_name")
                    else ""
                ),
                "avatar_url": (
                    str(message.author.avatar.url) if message.author.avatar else ""
                ),
                "bot": message.author.bot,
            },
            "created_at": message.created_at.isoformat(),
            "edited_at": message.edited_at.isoformat() if message.edited_at else None,
            "reference": {
                "message_id": (
                    message.reference.message_id if message.reference else None
                ),
            },
            "attachments": [
                {
                    "url": attachment.url,
                    "filename": attachment.filename,
                    "size": attachment.size,
                }
                for attachment in message.attachments
            ],
            "reactions": [
                {
                    "emoji": str(reaction.emoji),
                    "count": reaction.count,
                }
                for reaction in message.reactions
            ],
        }

    async def close(self):
        """Close the client connection."""
        if self._ready:
            await self.client.close()
            self._ready = False

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self._ready:
            asyncio.run(self.close())


def run_async(coro):
    """Run coroutine in sync context."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)
