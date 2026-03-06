"""
Tests for CPPA Slack Tracker Models

SlackUser is defined in cppa_user_tracker; tests here use it via fixtures.
"""

import pytest
from datetime import datetime, timezone
from django.db import IntegrityError
from cppa_slack_tracker.models import (
    SlackTeam,
    SlackChannel,
    SlackMessage,
    SlackChannelMembership,
    SlackChannelMembershipChangeLog,
)


@pytest.mark.django_db
class TestSlackTeam:
    """Tests for SlackTeam model."""

    def test_create_slack_team(self):
        """Test creating a Slack team."""
        team = SlackTeam.objects.create(
            team_id="T12345678",
            team_name="Test Team",
        )

        assert team.team_id == "T12345678"
        assert team.team_name == "Test Team"
        assert str(team) == "Test Team (T12345678)"

    def test_slack_team_unique_constraint(self, _sample_slack_team):
        """Test that team_id must be unique."""
        with pytest.raises(IntegrityError):
            SlackTeam.objects.create(
                team_id="T12345678",  # Duplicate
                team_name="Another Team",
            )


@pytest.mark.django_db
class TestSlackChannel:
    """Tests for SlackChannel model."""

    def test_create_slack_channel(self, sample_slack_team, sample_slack_user):
        """Test creating a Slack channel."""
        channel = SlackChannel.objects.create(
            team=sample_slack_team,
            channel_id="C12345678",
            channel_name="general",
            channel_type="public_channel",
            description="General discussion",
            creator=sample_slack_user,
        )

        assert channel.channel_id == "C12345678"
        assert channel.channel_name == "general"
        assert channel.channel_type == "public_channel"
        assert channel.creator == sample_slack_user
        assert str(channel) == "#general (C12345678)"

    def test_slack_channel_without_creator(self, sample_slack_team):
        """Test creating a channel without a creator."""
        channel = SlackChannel.objects.create(
            team=sample_slack_team,
            channel_id="C87654321",
            channel_name="random",
            channel_type="public_channel",
        )

        assert channel.creator is None

    def test_slack_channel_unique_constraint(
        self, _sample_slack_channel, sample_slack_team
    ):
        """Test that channel_id must be unique."""
        with pytest.raises(IntegrityError):
            SlackChannel.objects.create(
                team=sample_slack_team,
                channel_id="C12345678",  # Duplicate
                channel_name="another-channel",
                channel_type="public_channel",
            )


@pytest.mark.django_db
class TestSlackMessage:
    """Tests for SlackMessage model."""

    def test_create_slack_message(self, sample_slack_channel, sample_slack_user):
        """Test creating a Slack message."""
        created_at = datetime.now(timezone.utc)
        message = SlackMessage.objects.create(
            channel=sample_slack_channel,
            ts="1234567890.123456",
            user=sample_slack_user,
            message="Hello, world!",
            slack_message_created_at=created_at,
            slack_message_updated_at=created_at,
        )

        assert message.ts == "1234567890.123456"
        assert message.user == sample_slack_user
        assert message.message == "Hello, world!"
        assert message.thread_ts is None

    def test_slack_message_in_thread(self, sample_slack_channel, sample_slack_user):
        """Test creating a threaded message."""
        created_at = datetime.now(timezone.utc)
        message = SlackMessage.objects.create(
            channel=sample_slack_channel,
            ts="1234567890.654321",
            user=sample_slack_user,
            message="Reply in thread",
            thread_ts="1234567890.123456",
            slack_message_created_at=created_at,
            slack_message_updated_at=created_at,
        )

        assert message.thread_ts == "1234567890.123456"

    def test_slack_message_unique_ts(
        self, _sample_slack_message, sample_slack_channel, sample_slack_user
    ):
        """Test that ts must be unique."""
        with pytest.raises(IntegrityError):
            SlackMessage.objects.create(
                channel=sample_slack_channel,
                ts="1234567890.123456",  # Duplicate
                user=sample_slack_user,
                message="Another message",
                slack_message_created_at=datetime.now(timezone.utc),
            )


@pytest.mark.django_db
class TestSlackChannelMembership:
    """Tests for SlackChannelMembership model."""

    def test_create_membership(self, sample_slack_channel, sample_slack_user):
        """Test creating a channel membership."""
        membership = SlackChannelMembership.objects.create(
            channel=sample_slack_channel,
            user=sample_slack_user,
            is_restricted=False,
            is_deleted=False,
        )

        assert membership.channel == sample_slack_channel
        assert membership.user == sample_slack_user
        assert not membership.is_restricted
        assert not membership.is_deleted
        assert str(membership) == f"{sample_slack_user} in {sample_slack_channel}"

    def test_membership_unique_constraint(self, sample_slack_membership):
        """Test that channel-user combination must be unique."""
        with pytest.raises(IntegrityError):
            SlackChannelMembership.objects.create(
                channel=sample_slack_membership.channel,
                user=sample_slack_membership.user,  # Duplicate combination
            )


@pytest.mark.django_db
class TestSlackChannelMembershipChangeLog:
    """Tests for SlackChannelMembershipChangeLog model."""

    def test_create_join_log(self, sample_slack_channel, sample_slack_user):
        """Test creating a join log entry."""
        log = SlackChannelMembershipChangeLog.objects.create(
            channel=sample_slack_channel,
            user=sample_slack_user,
            is_joined=True,
        )

        assert log.channel == sample_slack_channel
        assert log.user == sample_slack_user
        assert log.is_joined
        assert "joined" in str(log)

    def test_create_leave_log(self, sample_slack_channel, sample_slack_user):
        """Test creating a leave log entry."""
        log = SlackChannelMembershipChangeLog.objects.create(
            channel=sample_slack_channel,
            user=sample_slack_user,
            is_joined=False,
        )

        assert not log.is_joined
        assert "left" in str(log)
