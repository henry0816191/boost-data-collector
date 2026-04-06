"""
Models per docs/Schema.md — cppa_youtube_script_tracker section.

Tables:
- YouTubeChannel:      publisher channel (e.g. CppCon, C++Now); channel_id is PK
- YouTubeVideo:        individual video metadata + transcript state; video_id is PK
- YouTubeVideoSpeaker: M2M join between YouTubeVideo and cppa_user_tracker.YoutubeSpeaker
- CppaTags:            C++ community tag vocabulary
- YouTubeVideoTags:    M2M join between YouTubeVideo and CppaTags
"""

from django.db import models


class YouTubeChannel(models.Model):
    """Publishing channel a video was uploaded to (e.g. CppCon, C++Now).

    channel_id is the YouTube channel ID and serves as the primary key.
    """

    channel_id = models.CharField(max_length=64, primary_key=True)
    channel_title = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["channel_title"]
        verbose_name = "YouTube channel"
        verbose_name_plural = "YouTube channels"

    def __str__(self) -> str:
        return self.channel_title or self.channel_id


class YouTubeVideo(models.Model):
    """YouTube video metadata and transcript download state.

    video_id is the YouTube video ID and serves as the primary key.
    """

    video_id = models.CharField(max_length=32, primary_key=True)
    channel = models.ForeignKey(
        YouTubeChannel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="videos",
        db_column="channel_id",
    )
    title = models.CharField(max_length=512, blank=True)
    description = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    duration_seconds = models.IntegerField(default=0)
    view_count = models.IntegerField(null=True, blank=True)
    like_count = models.IntegerField(null=True, blank=True)
    comment_count = models.IntegerField(null=True, blank=True)
    search_term = models.CharField(max_length=255, blank=True)
    has_transcript = models.BooleanField(default=False)
    transcript_path = models.CharField(max_length=1024, blank=True)
    scraped_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at"]
        verbose_name = "YouTube video"
        verbose_name_plural = "YouTube videos"

    def __str__(self) -> str:
        return self.title or self.video_id


class YouTubeVideoSpeaker(models.Model):
    """M2M join: links a YouTubeVideo to a YoutubeSpeaker profile."""

    video = models.ForeignKey(
        YouTubeVideo,
        on_delete=models.CASCADE,
        related_name="video_speakers",
        db_column="video_id",
    )
    speaker = models.ForeignKey(
        "cppa_user_tracker.YoutubeSpeaker",
        on_delete=models.CASCADE,
        related_name="video_appearances",
        db_column="speaker_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["video", "speaker"], name="unique_video_speaker"
            )
        ]
        ordering = ["video", "speaker"]
        verbose_name = "YouTube video speaker"
        verbose_name_plural = "YouTube video speakers"

    def __str__(self) -> str:
        return f"video={self.video_id} speaker={self.speaker_id}"  # type: ignore[attr-defined]


class CppaTags(models.Model):
    """C++ community tag vocabulary (e.g. 'concurrency', 'templates', 'modules')."""

    tag_name = models.CharField(max_length=128, unique=True, db_index=True)

    class Meta:
        ordering = ["tag_name"]
        verbose_name = "CPPA tag"
        verbose_name_plural = "CPPA tags"

    def __str__(self) -> str:
        return self.tag_name


class YouTubeVideoTags(models.Model):
    """M2M join: links a YouTubeVideo to a CppaTags entry."""

    youtube_video = models.ForeignKey(
        YouTubeVideo,
        on_delete=models.CASCADE,
        related_name="video_tags",
        db_column="youtube_video_id",
    )
    cppa_tag = models.ForeignKey(
        CppaTags,
        on_delete=models.CASCADE,
        related_name="tagged_videos",
        db_column="cppa_tag_id",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["youtube_video", "cppa_tag"], name="unique_video_tag"
            )
        ]
        ordering = ["youtube_video", "cppa_tag"]
        verbose_name = "YouTube video tag"
        verbose_name_plural = "YouTube video tags"

    def __str__(self) -> str:
        return f"video={self.youtube_video_id} tag={self.cppa_tag_id}"  # type: ignore[attr-defined]
