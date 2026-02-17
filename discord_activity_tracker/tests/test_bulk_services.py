"""Tests for bulk DB operations in services.py."""

import pytest
from datetime import datetime, timezone

from discord_activity_tracker.models import (
    DiscordServer,
    DiscordUser,
    DiscordChannel,
    DiscordMessage,
    DiscordReaction,
)
from discord_activity_tracker.services import (
    bulk_upsert_discord_users,
    bulk_upsert_discord_messages,
    bulk_upsert_discord_reactions,
    bulk_process_message_batch,
)


@pytest.fixture
def server(db):
    return DiscordServer.objects.create(
        server_id=100, server_name="TestServer", icon_url=""
    )


@pytest.fixture
def channel(server):
    return DiscordChannel.objects.create(
        server=server,
        channel_id=200,
        channel_name="general",
        channel_type="text",
        topic="",
        position=0,
    )


# ---------------------------------------------------------------------------
# bulk_upsert_discord_users
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkUpsertUsers:
    def test_insert_new_users(self):
        user_data = [
            {"user_id": 1001, "username": "alice", "display_name": "Alice", "avatar_url": "", "is_bot": False},
            {"user_id": 1002, "username": "bob", "display_name": "Bob", "avatar_url": "", "is_bot": True},
        ]
        result = bulk_upsert_discord_users(user_data)

        assert len(result) == 2
        assert 1001 in result
        assert 1002 in result
        assert result[1001].user_id == 1001
        assert DiscordUser.objects.count() == 2

    def test_update_existing_users(self):
        DiscordUser.objects.create(user_id=1001, username="alice_old", display_name="Old", is_bot=False)

        user_data = [
            {"user_id": 1001, "username": "alice_new", "display_name": "New Alice", "avatar_url": "", "is_bot": False},
        ]
        result = bulk_upsert_discord_users(user_data)

        assert len(result) == 1
        refreshed = DiscordUser.objects.get(user_id=1001)
        assert refreshed.username == "alice_new"
        assert refreshed.display_name == "New Alice"

    def test_deduplicates_by_user_id(self):
        user_data = [
            {"user_id": 1001, "username": "first", "display_name": "", "avatar_url": "", "is_bot": False},
            {"user_id": 1001, "username": "second", "display_name": "", "avatar_url": "", "is_bot": False},
        ]
        result = bulk_upsert_discord_users(user_data)

        assert len(result) == 1
        assert DiscordUser.objects.count() == 1
        # Last-seen wins
        assert DiscordUser.objects.get(user_id=1001).username == "second"

    def test_empty_input(self):
        result = bulk_upsert_discord_users([])
        assert result == {}


# ---------------------------------------------------------------------------
# bulk_upsert_discord_messages
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkUpsertMessages:
    def test_insert_new_messages(self, channel):
        user_map = bulk_upsert_discord_users([
            {"user_id": 1001, "username": "alice", "display_name": "Alice", "avatar_url": "", "is_bot": False},
        ])

        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
        msg_data = [
            {
                "message_id": 5001,
                "author": {"user_id": 1001, "username": "alice"},
                "content": "Hello world",
                "message_created_at": now,
                "message_edited_at": None,
                "reply_to_message_id": None,
                "attachment_urls": [],
                "reactions": [],
            },
            {
                "message_id": 5002,
                "author": {"user_id": 1001, "username": "alice"},
                "content": "Second message",
                "message_created_at": now,
                "message_edited_at": None,
                "reply_to_message_id": None,
                "attachment_urls": ["https://example.com/file.png"],
                "reactions": [],
            },
        ]

        result = bulk_upsert_discord_messages(msg_data, channel, user_map)
        assert len(result) == 2
        assert DiscordMessage.objects.count() == 2

        msg1 = DiscordMessage.objects.get(message_id=5001)
        assert msg1.content == "Hello world"
        assert msg1.has_attachments is False

        msg2 = DiscordMessage.objects.get(message_id=5002)
        assert msg2.has_attachments is True
        assert msg2.attachment_urls == ["https://example.com/file.png"]

    def test_update_existing_messages(self, channel):
        user_map = bulk_upsert_discord_users([
            {"user_id": 1001, "username": "alice", "display_name": "", "avatar_url": "", "is_bot": False},
        ])
        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)

        # Insert first
        bulk_upsert_discord_messages([{
            "message_id": 5001,
            "author": {"user_id": 1001},
            "content": "Original",
            "message_created_at": now,
            "message_edited_at": None,
            "reply_to_message_id": None,
            "attachment_urls": [],
            "reactions": [],
        }], channel, user_map)

        # Update
        edited_at = datetime(2026, 2, 17, 13, 0, 0, tzinfo=timezone.utc)
        bulk_upsert_discord_messages([{
            "message_id": 5001,
            "author": {"user_id": 1001},
            "content": "Edited content",
            "message_created_at": now,
            "message_edited_at": edited_at,
            "reply_to_message_id": None,
            "attachment_urls": [],
            "reactions": [],
        }], channel, user_map)

        assert DiscordMessage.objects.count() == 1
        msg = DiscordMessage.objects.get(message_id=5001)
        assert msg.content == "Edited content"
        assert msg.message_edited_at == edited_at

    def test_empty_input(self, channel):
        result = bulk_upsert_discord_messages([], channel, {})
        assert result == {}


# ---------------------------------------------------------------------------
# bulk_upsert_discord_reactions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkUpsertReactions:
    def test_insert_reactions(self, channel):
        user_map = bulk_upsert_discord_users([
            {"user_id": 1001, "username": "alice", "display_name": "", "avatar_url": "", "is_bot": False},
        ])
        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
        message_map = bulk_upsert_discord_messages([{
            "message_id": 5001,
            "author": {"user_id": 1001},
            "content": "Test",
            "message_created_at": now,
            "message_edited_at": None,
            "reply_to_message_id": None,
            "attachment_urls": [],
            "reactions": [],
        }], channel, user_map)

        reaction_data = [
            {"discord_message_id": 5001, "emoji": "👍", "count": 3},
            {"discord_message_id": 5001, "emoji": "🎉", "count": 1},
        ]
        bulk_upsert_discord_reactions(reaction_data, message_map)

        assert DiscordReaction.objects.count() == 2
        thumbs = DiscordReaction.objects.get(emoji="👍")
        assert thumbs.count == 3

    def test_update_reaction_count(self, channel):
        user_map = bulk_upsert_discord_users([
            {"user_id": 1001, "username": "alice", "display_name": "", "avatar_url": "", "is_bot": False},
        ])
        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
        message_map = bulk_upsert_discord_messages([{
            "message_id": 5001,
            "author": {"user_id": 1001},
            "content": "Test",
            "message_created_at": now,
            "message_edited_at": None,
            "reply_to_message_id": None,
            "attachment_urls": [],
            "reactions": [],
        }], channel, user_map)

        # Insert
        bulk_upsert_discord_reactions(
            [{"discord_message_id": 5001, "emoji": "👍", "count": 1}],
            message_map,
        )
        # Update
        bulk_upsert_discord_reactions(
            [{"discord_message_id": 5001, "emoji": "👍", "count": 5}],
            message_map,
        )

        assert DiscordReaction.objects.count() == 1
        assert DiscordReaction.objects.get(emoji="👍").count == 5


# ---------------------------------------------------------------------------
# bulk_process_message_batch (end-to-end orchestrator)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkProcessMessageBatch:
    def test_full_batch(self, channel):
        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
        messages = [
            {
                "message_id": 5001,
                "author": {"user_id": 1001, "username": "alice", "display_name": "Alice", "avatar_url": "", "is_bot": False},
                "content": "Hello!",
                "message_created_at": now,
                "message_edited_at": None,
                "reply_to_message_id": None,
                "attachment_urls": [],
                "reactions": [
                    {"emoji": "👍", "count": 2},
                    {"emoji": "❤️", "count": 1},
                ],
            },
            {
                "message_id": 5002,
                "author": {"user_id": 1002, "username": "bob", "display_name": "Bob", "avatar_url": "", "is_bot": False},
                "content": "Hi there!",
                "message_created_at": now,
                "message_edited_at": None,
                "reply_to_message_id": 5001,
                "attachment_urls": ["https://example.com/img.png"],
                "reactions": [],
            },
        ]

        count = bulk_process_message_batch(messages, channel)

        assert count == 2
        assert DiscordUser.objects.count() == 2
        assert DiscordMessage.objects.count() == 2
        assert DiscordReaction.objects.count() == 2

        msg1 = DiscordMessage.objects.get(message_id=5001)
        assert msg1.content == "Hello!"
        assert msg1.author.username == "alice"

        msg2 = DiscordMessage.objects.get(message_id=5002)
        assert msg2.reply_to_message_id == 5001
        assert msg2.has_attachments is True

    def test_empty_batch(self, channel):
        count = bulk_process_message_batch([], channel)
        assert count == 0

    def test_idempotent(self, channel):
        """Running same batch twice should not create duplicates."""
        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
        messages = [
            {
                "message_id": 5001,
                "author": {"user_id": 1001, "username": "alice", "display_name": "", "avatar_url": "", "is_bot": False},
                "content": "Test",
                "message_created_at": now,
                "message_edited_at": None,
                "reply_to_message_id": None,
                "attachment_urls": [],
                "reactions": [{"emoji": "👍", "count": 1}],
            },
        ]

        bulk_process_message_batch(messages, channel)
        bulk_process_message_batch(messages, channel)

        assert DiscordUser.objects.count() == 1
        assert DiscordMessage.objects.count() == 1
        assert DiscordReaction.objects.count() == 1
