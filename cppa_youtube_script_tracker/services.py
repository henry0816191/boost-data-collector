"""
Service layer for cppa_youtube_script_tracker.

All creates/updates/deletes for this app's models must go through functions in this
module. Do not call Model.objects.create(), model.save(), or model.delete() from
outside this module.

See docs/Contributing.md for the project-wide rule.
"""

from __future__ import annotations

from typing import Any, Optional

from .models import (
    CppaTags,
    YouTubeChannel,
    YouTubeVideo,
    YouTubeVideoSpeaker,
    YouTubeVideoTags,
)


def _parse_dt_field(value: Any) -> Any:
    """Parse a datetime string field; returns datetime, None, or the original value."""
    if isinstance(value, str) and value:
        from django.utils.dateparse import parse_datetime as _pd

        return _pd(value)
    return value


def get_or_create_channel(
    channel_id: str,
    channel_title: str = "",
) -> YouTubeChannel:
    """Get or create a YouTubeChannel by channel_id (PK).

    If the channel exists and channel_title differs, the title is updated.
    Returns the YouTubeChannel instance.
    """
    channel_id_val = (channel_id or "").strip()
    if not channel_id_val:
        raise ValueError("channel_id must not be empty.")
    channel_title_val = (channel_title or "").strip()
    channel, created = YouTubeChannel.objects.get_or_create(
        channel_id=channel_id_val,
        defaults={"channel_title": channel_title_val},
    )
    if not created and channel_title_val and channel.channel_title != channel_title_val:
        channel.channel_title = channel_title_val
        channel.save(update_fields=["channel_title", "updated_at"])
    return channel


def get_or_create_video(
    video_id: str,
    channel: Optional[YouTubeChannel],
    metadata_dict: dict[str, Any],
) -> tuple[YouTubeVideo, bool]:
    """Get or create a YouTubeVideo by video_id (PK). Returns (video, created).

    metadata_dict keys (all optional):
        title, description, published_at (datetime or ISO str), duration_seconds,
        view_count, like_count, comment_count, search_term, scraped_at.

    Raises ValueError if video_id is empty.
    """
    video_id_val = (video_id or "").strip()
    if not video_id_val:
        raise ValueError("video_id must not be empty.")

    published_at = _parse_dt_field(metadata_dict.get("published_at"))
    scraped_at = _parse_dt_field(metadata_dict.get("scraped_at"))

    defaults: dict[str, Any] = {
        "channel": channel,
        "title": (metadata_dict.get("title") or ""),
        "description": (metadata_dict.get("description") or ""),
        "published_at": published_at,
        "duration_seconds": int(metadata_dict.get("duration_seconds") or 0),
        "view_count": metadata_dict.get("view_count"),
        "like_count": metadata_dict.get("like_count"),
        "comment_count": metadata_dict.get("comment_count"),
        "search_term": (metadata_dict.get("search_term") or ""),
        "scraped_at": scraped_at,
    }
    video, created = YouTubeVideo.objects.get_or_create(
        video_id=video_id_val,
        defaults=defaults,
    )
    return video, created


def update_video_transcript(
    video: YouTubeVideo,
    transcript_path: str,
) -> YouTubeVideo:
    """Mark video as having a transcript and store its path. Returns the updated video."""
    video.has_transcript = True
    video.transcript_path = (transcript_path or "").strip()
    video.save(update_fields=["has_transcript", "transcript_path", "updated_at"])
    return video


def link_speaker_to_video(
    video: YouTubeVideo,
    speaker: Any,
) -> YouTubeVideoSpeaker:
    """Link a YoutubeSpeaker to a YouTubeVideo (get-or-create). Returns YouTubeVideoSpeaker."""
    join, _ = YouTubeVideoSpeaker.objects.get_or_create(
        video=video,
        speaker=speaker,
    )
    return join


def remove_speaker_links_by_name(
    video: YouTubeVideo,
    speaker_name: str,
) -> int:
    """Remove all speaker links for a video where speaker.display_name matches speaker_name.

    Returns number of deleted join rows.
    """
    speaker_name_val = (speaker_name or "").strip()
    if not speaker_name_val:
        return 0
    deleted, _ = YouTubeVideoSpeaker.objects.filter(
        video=video,
        speaker__display_name=speaker_name_val,
    ).delete()
    return int(deleted)


def get_or_create_tag(tag_name: str) -> CppaTags:
    """Get or create a CppaTags entry by tag_name.

    Raises ValueError if tag_name is empty.
    Returns the CppaTags instance.
    """
    tag_name_val = (tag_name or "").strip().lower()
    if not tag_name_val:
        raise ValueError("tag_name must not be empty.")
    tag, _ = CppaTags.objects.get_or_create(tag_name=tag_name_val)
    return tag


def link_tag_to_video(
    video: YouTubeVideo,
    tag: CppaTags,
) -> YouTubeVideoTags:
    """Link a CppaTags entry to a YouTubeVideo (get-or-create). Returns YouTubeVideoTags."""
    join, _ = YouTubeVideoTags.objects.get_or_create(
        youtube_video=video,
        cppa_tag=tag,
    )
    return join
