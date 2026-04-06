from django.contrib import admin
from django.contrib.admin import ModelAdmin

from .models import (
    CppaTags,
    YouTubeChannel,
    YouTubeVideo,
    YouTubeVideoSpeaker,
    YouTubeVideoTags,
)


@admin.register(YouTubeChannel)
class YouTubeChannelAdmin(ModelAdmin):
    list_display = ("channel_id", "channel_title", "created_at")
    search_fields = ("channel_id", "channel_title")


@admin.register(YouTubeVideo)
class YouTubeVideoAdmin(ModelAdmin):
    list_display = (
        "video_id",
        "title",
        "channel",
        "published_at",
        "has_transcript",
        "created_at",
    )
    list_filter = ("has_transcript", "channel", "published_at")
    search_fields = ("video_id", "title", "description", "search_term")
    raw_id_fields = ("channel",)
    date_hierarchy = "published_at"


@admin.register(YouTubeVideoSpeaker)
class YouTubeVideoSpeakerAdmin(ModelAdmin):
    list_display = ("id", "video", "speaker", "created_at")
    raw_id_fields = ("video", "speaker")
    search_fields = ("video__video_id", "video__title", "speaker__display_name")


@admin.register(CppaTags)
class CppaTagsAdmin(ModelAdmin):
    list_display = ("id", "tag_name")
    search_fields = ("tag_name",)


@admin.register(YouTubeVideoTags)
class YouTubeVideoTagsAdmin(ModelAdmin):
    list_display = ("id", "youtube_video", "cppa_tag")
    raw_id_fields = ("youtube_video", "cppa_tag")
    search_fields = (
        "youtube_video__video_id",
        "youtube_video__title",
        "cppa_tag__tag_name",
    )
