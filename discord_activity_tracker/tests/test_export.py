"""Tests for markdown export functions."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from django.test import TestCase

from discord_activity_tracker.sync.export import (
    _make_github_anchor,
    _sanitize_discord_content,
    generate_markdown_content,
)


class MakeGitHubAnchorTests(TestCase):

    def test_basic_anchor(self):
        result = _make_github_anchor("14:30:25", "alice")
        self.assertEqual(result, "143025-utc--alice")

    def test_special_chars_in_username(self):
        result = _make_github_anchor("14:30:25", "user.name#1234")
        self.assertNotIn(".", result)
        self.assertNotIn("#", result)
        self.assertIn("username1234", result)

    def test_millisecond_timestamp(self):
        result = _make_github_anchor("14:30:25.123", "alice")
        self.assertEqual(result, "143025123-utc--alice")

    def test_matches_github_format(self):
        result = _make_github_anchor("01:32:31.841", "twopic")
        self.assertEqual(result, "013231841-utc--twopic")


class SanitizeDiscordContentTests(TestCase):

    def test_user_mention(self):
        result = _sanitize_discord_content("<@123456789>")
        self.assertEqual(result, "@user-123456789")

    def test_user_mention_with_bang(self):
        result = _sanitize_discord_content("<@!123456789>")
        self.assertEqual(result, "@user-123456789")

    def test_role_mention(self):
        result = _sanitize_discord_content("<@&987654>")
        self.assertEqual(result, "@role-987654")

    def test_channel_mention(self):
        result = _sanitize_discord_content("<#555666>")
        self.assertEqual(result, "#channel-555666")

    def test_custom_emoji(self):
        result = _sanitize_discord_content("<:thumbsup:123456>")
        self.assertEqual(result, ":thumbsup:")

    def test_animated_emoji(self):
        result = _sanitize_discord_content("<a:partyblob:789012>")
        self.assertEqual(result, ":partyblob:")

    def test_mixed_content(self):
        content = "Hey <@123> check <#456> for <:fire:789>"
        result = _sanitize_discord_content(content)
        self.assertEqual(result, "Hey @user-123 check #channel-456 for :fire:")

    def test_plain_text_unchanged(self):
        content = "Hello world, no special formatting here!"
        result = _sanitize_discord_content(content)
        self.assertEqual(result, content)

    def test_empty_string(self):
        result = _sanitize_discord_content("")
        self.assertEqual(result, "")

    def test_code_block_preserved(self):
        content = "Look at this: ```<@123> should stay```"
        result = _sanitize_discord_content(content)
        self.assertIn("<@123>", result)

    def test_inline_code_preserved(self):
        content = "Use `<@mention>` syntax"
        result = _sanitize_discord_content(content)
        self.assertIn("<@mention>", result)

    def test_mention_outside_code_block_converted(self):
        content = "Hi <@111> ```code here``` and <@222>"
        result = _sanitize_discord_content(content)
        self.assertIn("@user-111", result)
        self.assertIn("@user-222", result)

    def test_invisible_unicode_stripped(self):
        content = "\u2068\u2069```cpp\nint x = 1;\n```"
        result = _sanitize_discord_content(content)
        self.assertNotIn("\u2068", result)
        self.assertNotIn("\u2069", result)
        self.assertIn("```cpp", result)


class GenerateMarkdownContentTests(TestCase):

    def _make_mock_channel(
        self, name="general", server_name="TestServer", server_id=111, channel_id=222
    ):
        channel = MagicMock()
        channel.channel_name = name
        channel.channel_id = channel_id
        channel.server.server_name = server_name
        channel.server.server_id = server_id
        return channel

    def _make_mock_message(
        self,
        message_id,
        content,
        username,
        created_at,
        author_id=None,
        is_bot=False,
        reply_to=None,
        reactions=None,
        attachments=None,
    ):
        msg = MagicMock()
        msg.message_id = message_id
        msg.content = content
        msg.author_id = author_id or message_id
        msg.author.username = username
        msg.author.is_bot = is_bot
        msg.message_created_at = created_at
        msg.reply_to_message_id = reply_to
        msg.attachment_urls = attachments or []

        # Mock reactions queryset
        if reactions:
            mock_reactions = []
            for emoji, count in reactions:
                r = MagicMock()
                r.emoji = emoji
                r.count = count
                mock_reactions.append(r)
            msg.reactions.all.return_value = mock_reactions
        else:
            msg.reactions.all.return_value = []

        return msg

    def test_empty_messages(self):
        channel = self._make_mock_channel()
        result = generate_markdown_content(channel, "2026-02", [])
        self.assertIn("message_count: 0", result)
        self.assertIn("active_users: 0", result)

    def test_frontmatter_has_channel_and_server(self):
        channel = self._make_mock_channel(name="dev-chat", server_name="MyServer")
        result = generate_markdown_content(channel, "2026-02", [])
        self.assertIn("channel: dev-chat", result)
        self.assertIn("server: MyServer", result)

    def test_frontmatter_month_mode(self):
        channel = self._make_mock_channel()
        result = generate_markdown_content(channel, "2026-02", [])
        self.assertIn("month: 2026-02", result)
        self.assertNotIn("date:", result)

    def test_frontmatter_date_mode(self):
        channel = self._make_mock_channel()
        result = generate_markdown_content(
            channel, "2026-02", [], date_str="2026-02-15"
        )
        self.assertIn("date: 2026-02-15", result)
        self.assertNotIn("month:", result)

    def test_title_monthly(self):
        channel = self._make_mock_channel(name="general")
        result = generate_markdown_content(channel, "2026-02", [])
        self.assertIn("# #general - February 2026", result)

    def test_title_daily(self):
        channel = self._make_mock_channel(name="general")
        result = generate_markdown_content(
            channel, "2026-02", [], date_str="2026-02-15"
        )
        self.assertIn("# #general - 2026-02-15", result)

    def test_message_utc_timestamp(self):
        channel = self._make_mock_channel()
        msg = self._make_mock_message(
            message_id=1001,
            content="Hello world",
            username="alice",
            created_at=datetime(2026, 2, 15, 14, 30, 25, tzinfo=timezone.utc),
        )
        result = generate_markdown_content(channel, "2026-02", [msg])
        self.assertIn("14:30:25 UTC", result)

    def test_message_heading_format(self):
        channel = self._make_mock_channel()
        msg = self._make_mock_message(
            message_id=1001,
            content="Hello",
            username="alice",
            created_at=datetime(2026, 2, 15, 14, 30, 25, tzinfo=timezone.utc),
        )
        result = generate_markdown_content(channel, "2026-02", [msg])
        self.assertIn("### 14:30:25 UTC — @alice", result)

    def test_message_content_sanitized(self):
        channel = self._make_mock_channel()
        msg = self._make_mock_message(
            message_id=1001,
            content="Hey <@99999> check this!",
            username="alice",
            created_at=datetime(2026, 2, 15, 14, 30, 25, tzinfo=timezone.utc),
        )
        result = generate_markdown_content(channel, "2026-02", [msg])
        self.assertIn("@user-99999", result)
        self.assertNotIn("<@99999>", result)

    def test_metadata_blockquoted_before_message(self):
        channel = self._make_mock_channel()
        msg = self._make_mock_message(
            message_id=1001,
            content="Hello",
            username="alice",
            created_at=datetime(2026, 2, 15, 14, 30, 25, tzinfo=timezone.utc),
        )
        result = generate_markdown_content(channel, "2026-02", [msg])
        self.assertIn("> Url: https://discord.com/channels/", result)
        # Metadata (Url) should appear before message content
        url_pos = result.find("> Url:")
        hello_pos = result.find("Hello")
        self.assertLess(url_pos, hello_pos)

    def test_bot_label(self):
        channel = self._make_mock_channel()
        msg = self._make_mock_message(
            message_id=1001,
            content="Bot message",
            username="MEE6",
            created_at=datetime(2026, 2, 15, 14, 30, 25, tzinfo=timezone.utc),
            is_bot=True,
        )
        result = generate_markdown_content(channel, "2026-02", [msg])
        self.assertIn("(bot)", result)

    def test_non_bot_no_label(self):
        channel = self._make_mock_channel()
        msg = self._make_mock_message(
            message_id=1001,
            content="User message",
            username="alice",
            created_at=datetime(2026, 2, 15, 14, 30, 25, tzinfo=timezone.utc),
            is_bot=False,
        )
        result = generate_markdown_content(channel, "2026-02", [msg])
        self.assertNotIn("(bot)", result)

    def test_reactions_not_in_export(self):
        channel = self._make_mock_channel()
        msg = self._make_mock_message(
            message_id=1001,
            content="Great idea!",
            username="alice",
            created_at=datetime(2026, 2, 15, 14, 30, 25, tzinfo=timezone.utc),
            reactions=[("👍", 3), ("🎉", 1)],
        )
        result = generate_markdown_content(channel, "2026-02", [msg])
        self.assertNotIn("Reactions:", result)

    def test_attachments_blockquoted_with_indent(self):
        channel = self._make_mock_channel()
        msg = self._make_mock_message(
            message_id=1001,
            content="Check this file",
            username="alice",
            created_at=datetime(2026, 2, 15, 14, 30, 25, tzinfo=timezone.utc),
            attachments=["https://cdn.discord.com/attachments/1/2/image.png?ex=abc"],
        )
        result = generate_markdown_content(channel, "2026-02", [msg])
        self.assertIn("> Attachments:", result)
        self.assertIn("> - [image.png]", result)

    def test_multiple_messages_grouped_by_date(self):
        channel = self._make_mock_channel()
        msg1 = self._make_mock_message(
            message_id=1001,
            content="Morning",
            username="alice",
            created_at=datetime(2026, 2, 15, 8, 0, 0, tzinfo=timezone.utc),
        )
        msg2 = self._make_mock_message(
            message_id=1002,
            content="Evening",
            username="bob",
            created_at=datetime(2026, 2, 16, 20, 0, 0, tzinfo=timezone.utc),
            author_id=2002,
        )
        result = generate_markdown_content(channel, "2026-02", [msg1, msg2])
        self.assertIn("## 2026-02-15", result)
        self.assertIn("## 2026-02-16", result)

    def test_message_count_and_active_users(self):
        channel = self._make_mock_channel()
        msg1 = self._make_mock_message(
            message_id=1001,
            content="Hi",
            username="alice",
            created_at=datetime(2026, 2, 15, 8, 0, 0, tzinfo=timezone.utc),
            author_id=1,
        )
        msg2 = self._make_mock_message(
            message_id=1002,
            content="Hello",
            username="bob",
            created_at=datetime(2026, 2, 15, 9, 0, 0, tzinfo=timezone.utc),
            author_id=2,
        )
        msg3 = self._make_mock_message(
            message_id=1003,
            content="Hey",
            username="alice",
            created_at=datetime(2026, 2, 15, 10, 0, 0, tzinfo=timezone.utc),
            author_id=1,
        )
        result = generate_markdown_content(channel, "2026-02", [msg1, msg2, msg3])
        self.assertIn("message_count: 3", result)
        self.assertIn("active_users: 2", result)

    def test_utc_frontmatter_timestamps(self):
        channel = self._make_mock_channel()
        msg = self._make_mock_message(
            message_id=1001,
            content="Test",
            username="alice",
            created_at=datetime(2026, 2, 15, 14, 30, 25, tzinfo=timezone.utc),
        )
        result = generate_markdown_content(channel, "2026-02", [msg])
        self.assertIn("first_message: 2026-02-15T14:30:25Z", result)
        self.assertIn("last_message: 2026-02-15T14:30:25Z", result)

    def test_discord_channel_url(self):
        channel = self._make_mock_channel(server_id=111, channel_id=222)
        result = generate_markdown_content(channel, "2026-02", [])
        self.assertIn(
            "discord_channel_url: https://discord.com/channels/111/222", result
        )

    def test_two_day_split_generates_separate_content(self):
        channel = self._make_mock_channel(name="dev-chat")

        # Day 1: 3 messages
        day1_msgs = [
            self._make_mock_message(
                message_id=1001,
                content="Good morning!",
                username="alice",
                created_at=datetime(2026, 2, 15, 8, 0, 0, tzinfo=timezone.utc),
                author_id=1,
            ),
            self._make_mock_message(
                message_id=1002,
                content="Hey <@111> check <#222>",
                username="bob",
                created_at=datetime(2026, 2, 15, 9, 30, 0, tzinfo=timezone.utc),
                author_id=2,
            ),
            self._make_mock_message(
                message_id=1003,
                content="Thanks!",
                username="alice",
                created_at=datetime(2026, 2, 15, 10, 0, 0, tzinfo=timezone.utc),
                author_id=1,
                reactions=[("👍", 2)],
            ),
        ]

        # Day 2: 2 messages (one bot, one with attachment)
        day2_msgs = [
            self._make_mock_message(
                message_id=2001,
                content="Daily reminder",
                username="MEE6",
                created_at=datetime(2026, 2, 16, 6, 0, 0, tzinfo=timezone.utc),
                author_id=99,
                is_bot=True,
            ),
            self._make_mock_message(
                message_id=2002,
                content="Here's the doc",
                username="charlie",
                created_at=datetime(2026, 2, 16, 14, 0, 0, tzinfo=timezone.utc),
                author_id=3,
                attachments=["https://cdn.discord.com/files/report.pdf?token=abc"],
            ),
        ]

        # Generate per-day file for Day 1
        result_day1 = generate_markdown_content(
            channel, "2026-02", day1_msgs, date_str="2026-02-15", split_by_day=True
        )

        # Verify Day 1 output
        self.assertIn("date: 2026-02-15", result_day1)
        self.assertIn("# #dev-chat - 2026-02-15", result_day1)
        self.assertIn("message_count: 3", result_day1)
        self.assertIn("active_users: 2", result_day1)
        self.assertIn("08:00:00 UTC", result_day1)
        self.assertIn("@user-111", result_day1)  # Sanitized mention
        self.assertIn("#channel-222", result_day1)  # Sanitized channel
        self.assertNotIn("(bot)", result_day1)  # No bots on day 1

        # Generate per-day file for Day 2
        result_day2 = generate_markdown_content(
            channel, "2026-02", day2_msgs, date_str="2026-02-16", split_by_day=True
        )

        # Verify Day 2 output
        self.assertIn("date: 2026-02-16", result_day2)
        self.assertIn("# #dev-chat - 2026-02-16", result_day2)
        self.assertIn("message_count: 2", result_day2)
        self.assertIn("(bot)", result_day2)  # MEE6 is a bot
        self.assertIn("[report.pdf]", result_day2)  # Attachment link
        self.assertIn("06:00:00 UTC", result_day2)
        self.assertIn("14:00:00 UTC", result_day2)

    def test_two_day_combined_monthly(self):
        channel = self._make_mock_channel(name="general")
        msgs = [
            self._make_mock_message(
                message_id=1001,
                content="Day 1 msg",
                username="alice",
                created_at=datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc),
                author_id=1,
            ),
            self._make_mock_message(
                message_id=2001,
                content="Day 2 msg",
                username="bob",
                created_at=datetime(2026, 2, 16, 18, 0, 0, tzinfo=timezone.utc),
                author_id=2,
            ),
        ]

        result = generate_markdown_content(channel, "2026-02", msgs, split_by_day=False)

        # Both days in one file
        self.assertIn("month: 2026-02", result)
        self.assertIn("# #general - February 2026", result)
        self.assertIn("## 2026-02-15", result)
        self.assertIn("## 2026-02-16", result)
        self.assertIn("message_count: 2", result)
        self.assertIn("active_users: 2", result)
        self.assertIn("first_message: 2026-02-15T12:00:00Z", result)
        self.assertIn("last_message: 2026-02-16T18:00:00Z", result)
