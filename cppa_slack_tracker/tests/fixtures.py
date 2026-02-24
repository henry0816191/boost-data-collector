"""
Test fixtures for CPPA Slack Tracker
"""

import pytest
from datetime import datetime, timezone
from cppa_user_tracker.models import Identity, Email, SlackUser
from cppa_slack_tracker.models import (
    SlackTeam,
    SlackChannel,
    SlackMessage,
    SlackChannelMembership,
)


@pytest.fixture
def sample_identity(db):
    """Create a sample identity."""
    return Identity.objects.create(
        display_name="Test User",
        description="Test identity",
    )


@pytest.fixture
def sample_email(db, sample_slack_user):
    """Create a sample email linked to the sample Slack user."""
    return Email.objects.create(
        base_profile=sample_slack_user,
        email="test@example.com",
        is_primary=True,
        is_active=True,
    )


@pytest.fixture
def sample_slack_user(db, sample_identity):
    """Create a sample Slack user (SlackUser is from cppa_user_tracker)."""
    return SlackUser.objects.create(
        identity=sample_identity,
        slack_user_id="U12345678",
        username="testuser",
        display_name="Test User",
        avatar_url="https://example.com/avatar.jpg",
    )


@pytest.fixture
def sample_slack_team(db):
    """Create a sample Slack team."""
    return SlackTeam.objects.create(
        team_id="T12345678",
        team_name="Test Team",
    )


@pytest.fixture
def sample_slack_channel(db, sample_slack_team, sample_slack_user):
    """Create a sample Slack channel."""
    return SlackChannel.objects.create(
        team=sample_slack_team,
        channel_id="C12345678",
        channel_name="general",
        channel_type="public_channel",
        description="General discussion",
        creator=sample_slack_user,
    )


@pytest.fixture
def sample_slack_message(db, sample_slack_channel, sample_slack_user):
    """Create a sample Slack message."""
    return SlackMessage.objects.create(
        channel=sample_slack_channel,
        ts="1234567890.123456",
        user=sample_slack_user,
        message="Hello, world!",
        slack_message_created_at=datetime.now(timezone.utc),
        slack_message_updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_slack_membership(db, sample_slack_channel, sample_slack_user):
    """Create a sample channel membership."""
    return SlackChannelMembership.objects.create(
        channel=sample_slack_channel,
        user=sample_slack_user,
        is_restricted=False,
        is_deleted=False,
    )


@pytest.fixture
def sample_slack_user_data():
    """Return sample Slack user API data."""
    return {
        "id": "U87654321",
        "name": "janedoe",
        "real_name": "Jane Doe",
        "profile": {
            "email": "jane@example.com",
            "image_72": "https://example.com/jane.jpg",
        },
        "updated": 1609459200,  # 2021-01-01 00:00:00 UTC
    }


@pytest.fixture
def sample_slack_channel_data():
    """Return sample Slack channel API data."""
    return {
        "id": "C87654321",
        "name": "random",
        "type": "public_channel",
        "purpose": {
            "value": "Random discussions",
        },
        "creator": "U12345678",
        "created": 1609459200,  # 2021-01-01 00:00:00 UTC
    }


@pytest.fixture
def sample_slack_message_data():
    """Return sample Slack message API data."""
    return {
        "user": "U12345678",
        "text": "This is a test message",
        "ts": "1609459200.123456",
        "thread_ts": None,
    }
