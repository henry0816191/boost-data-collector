"""
Django Admin Configuration for CPPA Slack Tracker
SlackUser is registered in cppa_user_tracker.admin.
"""

from django.contrib import admin
from .models import (
    SlackTeam,
    SlackChannel,
    SlackMessage,
    SlackChannelMembership,
    SlackChannelMembershipChangeLog,
)


@admin.register(SlackTeam)
class SlackTeamAdmin(admin.ModelAdmin):
    list_display = ("team_id", "team_name", "created_at", "updated_at")
    list_filter = ("created_at", "updated_at")
    search_fields = ("team_id", "team_name")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(SlackChannel)
class SlackChannelAdmin(admin.ModelAdmin):
    list_display = (
        "channel_id",
        "channel_name",
        "channel_type",
        "team",
        "creator",
        "created_at",
    )
    list_filter = ("channel_type", "created_at", "updated_at")
    search_fields = ("channel_id", "channel_name", "description")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    raw_id_fields = ("team", "creator")


@admin.register(SlackMessage)
class SlackMessageAdmin(admin.ModelAdmin):
    list_display = (
        "ts",
        "channel",
        "user",
        "message_preview",
        "slack_message_created_at",
    )
    list_filter = ("slack_message_created_at", "slack_message_updated_at")
    search_fields = (
        "ts",
        "message",
        "channel__channel_name",
        "user__username",
    )
    readonly_fields = (
        "ts",
        "slack_message_created_at",
        "slack_message_updated_at",
    )
    date_hierarchy = "slack_message_created_at"
    raw_id_fields = ("channel", "user")

    @admin.display(description="Message Preview")
    def message_preview(self, obj):
        """Return a short preview of the message."""
        return obj.message[:50] + "..." if len(obj.message) > 50 else obj.message


@admin.register(SlackChannelMembership)
class SlackChannelMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "channel",
        "user",
        "is_restricted",
        "is_deleted",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_restricted", "is_deleted", "created_at", "updated_at")
    search_fields = (
        "channel__channel_name",
        "user__username",
        "user__display_name",
    )
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    raw_id_fields = ("channel", "user")


@admin.register(SlackChannelMembershipChangeLog)
class SlackChannelMembershipChangeLogAdmin(admin.ModelAdmin):
    list_display = ("channel", "user", "is_joined", "created_at")
    list_filter = ("is_joined", "created_at")
    search_fields = (
        "channel__channel_name",
        "user__username",
        "user__display_name",
    )
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    raw_id_fields = ("channel", "user")
