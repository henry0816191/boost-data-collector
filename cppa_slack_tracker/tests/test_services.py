"""
Tests for cppa_slack_tracker.services.
"""

import pytest

from cppa_user_tracker.services import get_or_create_slack_user
from cppa_slack_tracker.services import (
    get_or_create_slack_channel,
    get_or_create_slack_team,
    add_channel_membership_change,
    save_slack_message,
    sync_channel_memberships,
    _parse_slack_ts_string,
)
from cppa_slack_tracker.models import (
    SlackChannelMembership,
    SlackChannelMembershipChangeLog,
)
from cppa_user_tracker.models import Email, SlackUser


@pytest.mark.django_db
class TestSlackService:
    """Tests for cppa_slack_tracker.services."""

    def test_add_slack_team(self):
        """Test adding a Slack team."""
        team_data = {
            "team_id": "T12345678",
            "team_name": "Test Team",
        }
        team, _ = get_or_create_slack_team(team_data)

        assert team.team_id == "T12345678"
        assert team.team_name == "Test Team"

    def test_update_slack_team(self, sample_slack_team):
        """Test updating an existing Slack team."""
        team_data = {
            "team_id": "T12345678",
            "team_name": "Updated Team Name",
        }

        team, _ = get_or_create_slack_team(team_data)
        assert team.team_id == "T12345678"
        assert team.team_name == "Updated Team Name"

    def test_add_slack_user(self, sample_slack_user_data):
        """Test adding a Slack user."""
        user, _ = get_or_create_slack_user(sample_slack_user_data)
        assert user.slack_user_id == "U87654321"
        assert user.username == "janedoe"
        assert user.display_name == "Jane Doe"
        assert user.avatar_url == "https://example.com/jane.jpg"
        # Email is created when provided in profile; identity is not created here
        emails = Email.objects.filter(base_profile=user)
        assert emails.exists()
        assert emails.first().email == "jane@example.com"

    def test_add_slack_user_without_email(self):
        """Test adding a Slack user without email: no email or identity created."""
        user_data = {
            "id": "U11111111",
            "name": "nomail",
            "real_name": "No Email User",
            "profile": {},
        }
        user, _ = get_or_create_slack_user(user_data)
        assert user.slack_user_id == "U11111111"
        assert user.identity is None
        emails = Email.objects.filter(base_profile=user)
        assert not emails.exists()

    def test_update_slack_user(self, sample_slack_user):
        """Test updating an existing Slack user."""
        user_data = {
            "id": "U12345678",
            "name": "updateduser",
            "real_name": "Updated Name",
            "profile": {
                "image_72": "https://example.com/new-avatar.jpg",
            },
        }

        user, _ = get_or_create_slack_user(user_data)
        assert user.slack_user_id == "U12345678"
        assert user.username == "updateduser"
        assert user.display_name == "Updated Name"

    def test_add_slack_channel(
        self, sample_slack_team, sample_slack_user, sample_slack_channel_data
    ):
        """Test adding a Slack channel."""
        channel, _ = get_or_create_slack_channel(
            sample_slack_channel_data,
            sample_slack_team,
        )

        assert channel.channel_id == "C87654321"
        assert channel.channel_name == "random"
        assert channel.channel_type == "public_channel"
        assert channel.description == "Random discussions"
        assert channel.creator == sample_slack_user

    def test_add_channel_membership_change(
        self, sample_slack_channel, sample_slack_user
    ):
        """Test adding a channel membership change."""
        log = add_channel_membership_change(
            sample_slack_channel,
            "U12345678",
            "1609459200.123456",
            is_joined=True,
        )

        assert log.channel == sample_slack_channel
        assert log.user == sample_slack_user
        assert log.is_joined

        # Check that membership was created
        membership = SlackChannelMembership.objects.get(
            channel=sample_slack_channel, user=sample_slack_user
        )
        assert not membership.is_deleted

    def test_add_channel_leave(
        self, sample_slack_channel, sample_slack_user, sample_slack_membership
    ):
        """Test adding a channel leave event."""
        log = add_channel_membership_change(
            sample_slack_channel,
            "U12345678",
            "1609459200.123456",
            is_joined=False,
        )

        assert not log.is_joined

        # Check that membership was marked as deleted
        membership = SlackChannelMembership.objects.get(
            channel=sample_slack_channel, user=sample_slack_user
        )
        assert membership.is_deleted

    def test_save_slack_message(
        self,
        sample_slack_channel,
        sample_slack_user,
        sample_slack_message_data,
    ):
        """Test saving a Slack message."""
        message = save_slack_message(
            sample_slack_channel,
            sample_slack_message_data,
        )

        assert message is not None
        assert message.channel == sample_slack_channel
        assert message.user == sample_slack_user
        assert message.message == "This is a test message"
        assert message.ts == "1609459200.123456"

    def test_save_slack_message_channel_join(
        self, sample_slack_channel, sample_slack_user
    ):
        """Test that channel_join messages are handled correctly."""
        message_data = {
            "user": "U12345678",
            "text": "joined the channel",
            "ts": "1609459200.123456",
            "subtype": "channel_join",
        }

        message = save_slack_message(
            sample_slack_channel,
            message_data,
        )
        # Should return None (not saved as message)
        assert message is None

        # But should create membership change log
        logs = SlackChannelMembershipChangeLog.objects.filter(
            channel=sample_slack_channel,
            user=sample_slack_user,
            is_joined=True,
        )
        assert logs.exists()

    def test_save_slack_message_with_ignored_subtype(self, sample_slack_channel):
        """Test that ignored subtypes return None."""
        message_data = {
            "text": "Bot message",
            "ts": "1609459200.123456",
            "subtype": "bot_message",
        }

        message = save_slack_message(
            sample_slack_channel,
            message_data,
        )
        assert message is None

    def test_update_slack_message(self, sample_slack_message):
        """Test updating an existing message."""
        message_data = {
            "user": "U12345678",
            "text": "Updated message text",
            "ts": "1234567890.123456",
            "edited": {
                "ts": "1234567891.000000",
            },
        }

        message = save_slack_message(
            sample_slack_message.channel,
            message_data,
        )

        assert message.message == "Updated message text"
        assert message.slack_message_updated_at is not None

    def test_sync_channel_memberships(
        self, sample_slack_channel, sample_slack_user, sample_identity
    ):
        """Test syncing channel memberships."""
        # Create another user (SlackUser from cppa_user_tracker)
        user2 = SlackUser.objects.create(
            identity=sample_identity,
            slack_user_id="U22222222",
            username="user2",
        )

        # Create initial membership
        SlackChannelMembership.objects.create(
            channel=sample_slack_channel,
            user=sample_slack_user,
        )

        # Sync with new member list
        sync_channel_memberships(
            sample_slack_channel,
            ["U22222222"],
        )

        # Check that user1 is marked as deleted
        membership1 = SlackChannelMembership.objects.get(
            channel=sample_slack_channel, user=sample_slack_user
        )
        assert membership1.is_deleted

        # Check that user2 was added
        membership2 = SlackChannelMembership.objects.get(
            channel=sample_slack_channel, user=user2
        )
        assert not membership2.is_deleted

    def test_parse_slack_ts_string(self):
        """Test parsing Slack timestamp strings."""
        ts = "1609459200.123456"
        dt = _parse_slack_ts_string(ts)
        assert dt.year == 2021
        assert dt.month == 1
        assert dt.day == 1

    def test_save_slack_message_me_message_subtype(
        self, sample_slack_channel, sample_slack_user
    ):
        """Test that me_message subtype stores text as <@user_id> text."""
        message_data = {
            "user": "U12345678",
            "text": "waves",
            "ts": "1609459200.123456",
            "subtype": "me_message",
        }
        message = save_slack_message(sample_slack_channel, message_data)
        assert message is not None
        assert message.message == "<@U12345678> waves"

    def test_save_slack_message_unknown_user_fetches_info_and_creates_unknown_without_fetch_for_sentinel(
        self, sample_slack_channel
    ):
        """When user is not in DB, fetch_user_info is called for that id; when API returns nothing, message is saved with unknown user (-1), and -1 is never passed to fetch_user_info."""
        from unittest.mock import patch
        from cppa_user_tracker.models import SlackUser

        message_data = {
            "user": "U99999999",  # not in DB
            "text": "from unknown",
            "ts": "1609459200.999999",
        }
        with patch(
            "cppa_slack_tracker.services.fetch_user_info",
            return_value=None,
        ) as mock_fetch:
            message = save_slack_message(sample_slack_channel, message_data)
        assert message is not None
        assert message.message == "from unknown"
        # Unknown user should be created with slack_user_id -1
        unknown = SlackUser.objects.get(slack_user_id="-1")
        assert unknown.username == "unknown"
        assert message.user == unknown
        # fetch_user_info should have been called for U99999999, not for -1
        mock_fetch.assert_called()
        calls = [c[0][0] for c in mock_fetch.call_args_list]
        assert "U99999999" in calls
        assert "-1" not in calls
