from django.db import models

from cppa_user_tracker.models import DiscordProfile


class DiscordServer(models.Model):
    """Discord server/guild."""

    server_id = models.BigIntegerField(unique=True, db_index=True)
    server_name = models.CharField(max_length=255, db_index=True)
    icon_url = models.URLField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["server_name"]

    def __str__(self):
        return f"{self.server_name} ({self.server_id})"


class DiscordChannel(models.Model):
    """Discord channel within a server."""

    server = models.ForeignKey(
        DiscordServer,
        on_delete=models.CASCADE,
        related_name="channels",
        db_column="server_id",
    )
    channel_id = models.BigIntegerField(unique=True, db_index=True)
    channel_name = models.CharField(max_length=255, db_index=True)
    channel_type = models.CharField(max_length=50)  # text, voice, thread, etc.
    topic = models.TextField(blank=True)
    position = models.IntegerField(default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_activity_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["server", "position", "channel_name"]
        indexes = [
            models.Index(fields=["server", "channel_name"]),
            models.Index(fields=["last_activity_at"]),
        ]

    def __str__(self):
        return f"#{self.channel_name}"


class DiscordMessage(models.Model):
    """Discord message in a channel."""

    message_id = models.BigIntegerField(unique=True, db_index=True)
    channel = models.ForeignKey(
        DiscordChannel,
        on_delete=models.CASCADE,
        related_name="messages",
        db_column="channel_id",
    )
    author = models.ForeignKey(
        DiscordProfile,
        on_delete=models.CASCADE,
        related_name="discord_messages",
        db_column="author_id",
    )
    content = models.TextField(blank=True)
    message_created_at = models.DateTimeField(db_index=True)
    message_edited_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    reply_to_message_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    has_attachments = models.BooleanField(default=False)
    attachment_urls = models.JSONField(default=list)  # List of attachment URLs
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["channel", "message_created_at"]
        indexes = [
            models.Index(fields=["channel", "message_created_at"]),
            models.Index(fields=["message_created_at"]),
            models.Index(fields=["is_deleted"]),
        ]

    def __str__(self):
        content_preview = self.content[:50] if self.content else "(no content)"
        return f"{self.author.username}: {content_preview}"


class DiscordReaction(models.Model):
    """Reaction on a Discord message."""

    message = models.ForeignKey(
        DiscordMessage,
        on_delete=models.CASCADE,
        related_name="reactions",
        db_column="message_id",
    )
    emoji = models.CharField(max_length=255, db_index=True)
    count = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["message", "emoji"],
                name="discord_activity_tracker_msg_emoji_uniq",
            )
        ]

    def __str__(self):
        return f"{self.emoji} ({self.count})"
