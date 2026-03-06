"""
Slack Activity Tracker Models

Models based on Section 6 of the Boost Data Collector Schema.
Tracks Slack teams, channels, messages, and channel memberships.
SlackUser is defined in cppa_user_tracker; this app references it.
"""

from django.db import models
from django.utils import timezone

from cppa_user_tracker.models import SlackUser


class SlackChannelType(models.TextChoices):
    """Slack channel type (matches Slack API)."""

    PUBLIC_CHANNEL = "public_channel", "Public channel"
    PRIVATE_CHANNEL = "private_channel", "Private channel"
    MPIM = "mpim", "Multi-party direct message"
    IM = "im", "Direct message"


class SlackTeam(models.Model):
    """
    Slack team (workspace) model.
    """

    team_id = models.CharField(max_length=50, unique=True)
    team_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Slack Team"
        verbose_name_plural = "Slack Teams"

    def __str__(self):
        return f"{self.team_name} ({self.team_id})"


class SlackChannel(models.Model):
    """
    Slack channel model.

    Related to SlackTeam and SlackUser (creator).
    """

    team = models.ForeignKey(
        SlackTeam,
        on_delete=models.CASCADE,
        related_name="channels",
        db_column="team_id",
    )
    channel_id = models.CharField(max_length=50, db_index=True)
    channel_name = models.CharField(max_length=255, db_index=True)
    channel_type = models.CharField(
        max_length=50,
        choices=SlackChannelType.choices,
        db_index=True,
        help_text="Type of channel (public_channel, private_channel, mpim, im).",
    )
    description = models.TextField(null=True, blank=True)
    creator = models.ForeignKey(
        SlackUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_channels",
        db_column="creator_user_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Slack Channel"
        verbose_name_plural = "Slack Channels"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "channel_id"],
                name="unique_team_channel_id",
            ),
        ]

    def __str__(self):
        return f"#{self.channel_name} ({self.channel_id})"


class SlackMessage(models.Model):
    """
    Slack message model.

    Related to SlackChannel and SlackUser (author).
    """

    channel = models.ForeignKey(
        SlackChannel, on_delete=models.CASCADE, related_name="messages"
    )
    ts = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Slack message timestamp (unique per channel)",
    )
    user = models.ForeignKey(
        SlackUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
        db_column="slack_user_id",
    )
    message = models.TextField(blank=True)
    thread_ts = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        help_text="Thread timestamp if this is a threaded message",
    )
    slack_message_created_at = models.DateTimeField(db_index=True)
    slack_message_updated_at = models.DateTimeField(
        db_index=True, null=True, blank=True
    )

    class Meta:
        verbose_name = "Slack Message"
        verbose_name_plural = "Slack Messages"
        unique_together = [["channel", "ts"]]

    def __str__(self):
        message_preview = (
            self.message[:50] + "..." if len(self.message) > 50 else self.message
        )
        return f"Message by {self.user} in {self.channel}: {message_preview}"


class SlackChannelMembership(models.Model):
    """
    Current channel membership status.

    Tracks which users are currently members of which channels.
    """

    channel = models.ForeignKey(
        SlackChannel, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        SlackUser,
        on_delete=models.CASCADE,
        related_name="channel_memberships",
        db_column="slack_user_id",
    )
    is_restricted = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Slack Channel Membership"
        verbose_name_plural = "Slack Channel Memberships"
        unique_together = [["channel", "user"]]

    def __str__(self):
        return f"{self.user} in {self.channel}"


class SlackChannelMembershipChangeLog(models.Model):
    """
    Log of channel membership changes (joins/leaves).

    Historical record of when users joined or left channels.
    """

    channel = models.ForeignKey(
        SlackChannel,
        on_delete=models.CASCADE,
        related_name="membership_changes",
    )
    user = models.ForeignKey(
        SlackUser,
        on_delete=models.CASCADE,
        related_name="membership_changes",
        db_column="slack_user_id",
    )
    is_joined = models.BooleanField(help_text="True if joined, False if left")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Slack Channel Membership Change Log"
        verbose_name_plural = "Slack Channel Membership Change Logs"
        unique_together = [["channel", "user", "created_at"]]

    def __str__(self):
        action = "joined" if self.is_joined else "left"
        return f"{self.user} {action} {self.channel} at {self.created_at}"
