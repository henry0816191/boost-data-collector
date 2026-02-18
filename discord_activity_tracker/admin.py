"""Django admin configuration for Discord Activity Tracker."""

from django.contrib import admin
from .models import (
    DiscordServer,
    DiscordChannel,
    DiscordMessage,
    DiscordReaction,
)


@admin.register(DiscordServer)
class DiscordServerAdmin(admin.ModelAdmin):
    list_display = ("server_name", "server_id", "created_at", "updated_at")
    search_fields = ("server_name", "server_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DiscordChannel)
class DiscordChannelAdmin(admin.ModelAdmin):
    list_display = (
        "channel_name",
        "server",
        "channel_type",
        "last_synced_at",
        "last_activity_at",
    )
    list_filter = ("channel_type", "server")
    search_fields = ("channel_name", "channel_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DiscordMessage)
class DiscordMessageAdmin(admin.ModelAdmin):
    list_display = (
        "message_id",
        "channel",
        "author",
        "message_created_at",
        "is_deleted",
    )
    list_filter = ("is_deleted", "has_attachments", "channel")
    search_fields = ("content", "message_id", "author__username")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "message_created_at"


@admin.register(DiscordReaction)
class DiscordReactionAdmin(admin.ModelAdmin):
    list_display = ("emoji", "message", "count")
    search_fields = ("emoji", "message__message_id")
    readonly_fields = ("created_at", "updated_at")
