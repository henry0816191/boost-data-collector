"""Tests for bulk DB operations in services.py."""

import pytest
from datetime import datetime, timezone

from cppa_user_tracker.models import DiscordProfile
from discord_activity_tracker.models import (
    DiscordServer,
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


def _user(uid, name, display="", bot=False):
    return {
        "user_id": uid,
        "username": name,
        "display_name": display,
        "avatar_url": "",
        "is_bot": bot,
    }


def _msg(mid, author_uid, content="", ts=None, **kwargs):
    if ts is None:
        ts = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
    return {
        "message_id": mid,
        "author": {"user_id": author_uid, **kwargs.pop("author_extra", {})},
        "content": content,
        "message_created_at": ts,
        "message_edited_at": kwargs.get("edited_at"),
        "reply_to_message_id": kwargs.get("reply_to"),
        "attachment_urls": kwargs.get("attachments", []),
        "reactions": kwargs.get("reactions", []),
    }


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


# -------------------------------------------------------------------
# bulk_upsert_discord_users
# -------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkUpsertUsers:
    def test_insert_new_users(self):
        user_data = [
            _user(1001, "alice", display="Alice"),
            _user(1002, "bob", display="Bob", bot=True),
        ]
        result = bulk_upsert_discord_users(user_data)

        assert len(result) == 2
        assert 1001 in result
        assert 1002 in result
        assert result[1001].discord_user_id == 1001
        assert DiscordProfile.objects.count() == 2

    def test_update_existing_users(self):
        DiscordProfile.objects.create(
            discord_user_id=1001,
            type="discord",
            username="alice_old",
            display_name="Old",
            is_bot=False,
        )

        result = bulk_upsert_discord_users(
            [_user(1001, "alice_new", display="New Alice")]
        )

        assert len(result) == 1
        refreshed = DiscordProfile.objects.get(discord_user_id=1001)
        assert refreshed.username == "alice_new"
        assert refreshed.display_name == "New Alice"

    def test_deduplicates_by_user_id(self):
        user_data = [
            _user(1001, "first"),
            _user(1001, "second"),
        ]
        result = bulk_upsert_discord_users(user_data)

        assert len(result) == 1
        assert DiscordProfile.objects.count() == 1
        # Last-seen wins
        assert DiscordProfile.objects.get(discord_user_id=1001).username == "second"

    def test_empty_input(self):
        result = bulk_upsert_discord_users([])
        assert result == {}


# -------------------------------------------------------------------
# bulk_upsert_discord_messages
# -------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkUpsertMessages:
    def test_insert_new_messages(self, channel):
        user_map = bulk_upsert_discord_users([_user(1001, "alice", display="Alice")])

        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
        msg_data = [
            _msg(5001, 1001, content="Hello world", ts=now),
            _msg(
                5002,
                1001,
                content="Second message",
                ts=now,
                attachments=["https://example.com/file.png"],
            ),
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
        user_map = bulk_upsert_discord_users([_user(1001, "alice")])
        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)

        # Insert first
        bulk_upsert_discord_messages(
            [_msg(5001, 1001, content="Original", ts=now)],
            channel,
            user_map,
        )

        # Update
        edited_at = datetime(2026, 2, 17, 13, 0, 0, tzinfo=timezone.utc)
        bulk_upsert_discord_messages(
            [
                _msg(
                    5001,
                    1001,
                    content="Edited content",
                    ts=now,
                    edited_at=edited_at,
                )
            ],
            channel,
            user_map,
        )

        assert DiscordMessage.objects.count() == 1
        msg = DiscordMessage.objects.get(message_id=5001)
        assert msg.content == "Edited content"
        assert msg.message_edited_at == edited_at

    def test_empty_input(self, channel):
        result = bulk_upsert_discord_messages([], channel, {})
        assert result == {}


# -------------------------------------------------------------------
# bulk_upsert_discord_reactions
# -------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkUpsertReactions:
    def test_insert_reactions(self, channel):
        user_map = bulk_upsert_discord_users([_user(1001, "alice")])
        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
        message_map = bulk_upsert_discord_messages(
            [_msg(5001, 1001, content="Test", ts=now)],
            channel,
            user_map,
        )

        reaction_data = [
            {"discord_message_id": 5001, "emoji": "\U0001f44d", "count": 3},
            {"discord_message_id": 5001, "emoji": "\U0001f389", "count": 1},
        ]
        bulk_upsert_discord_reactions(reaction_data, message_map)

        assert DiscordReaction.objects.count() == 2
        thumbs = DiscordReaction.objects.get(emoji="\U0001f44d")
        assert thumbs.count == 3

    def test_update_reaction_count(self, channel):
        user_map = bulk_upsert_discord_users([_user(1001, "alice")])
        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
        message_map = bulk_upsert_discord_messages(
            [_msg(5001, 1001, content="Test", ts=now)],
            channel,
            user_map,
        )

        # Insert
        bulk_upsert_discord_reactions(
            [{"discord_message_id": 5001, "emoji": "\U0001f44d", "count": 1}],
            message_map,
        )
        # Update
        bulk_upsert_discord_reactions(
            [{"discord_message_id": 5001, "emoji": "\U0001f44d", "count": 5}],
            message_map,
        )

        assert DiscordReaction.objects.count() == 1
        assert DiscordReaction.objects.get(emoji="\U0001f44d").count == 5


# -------------------------------------------------------------------
# bulk_process_message_batch (end-to-end orchestrator)
# -------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkProcessMessageBatch:
    def test_full_batch(self, channel):
        now = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
        messages = [
            {
                "message_id": 5001,
                "author": _user(1001, "alice", display="Alice"),
                "content": "Hello!",
                "message_created_at": now,
                "message_edited_at": None,
                "reply_to_message_id": None,
                "attachment_urls": [],
                "reactions": [
                    {"emoji": "\U0001f44d", "count": 2},
                    {"emoji": "\u2764\ufe0f", "count": 1},
                ],
            },
            {
                "message_id": 5002,
                "author": _user(1002, "bob", display="Bob"),
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
        assert DiscordProfile.objects.count() == 2
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
                "author": _user(1001, "alice"),
                "content": "Test",
                "message_created_at": now,
                "message_edited_at": None,
                "reply_to_message_id": None,
                "attachment_urls": [],
                "reactions": [{"emoji": "\U0001f44d", "count": 1}],
            },
        ]

        bulk_process_message_batch(messages, channel)
        bulk_process_message_batch(messages, channel)

        assert DiscordProfile.objects.count() == 1
        assert DiscordMessage.objects.count() == 1
        assert DiscordReaction.objects.count() == 1
