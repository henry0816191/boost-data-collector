"""
Pinecone preprocess function for cppa_youtube_script_tracker.

Guideline source: docs/Pinecone_preprocess_guideline_c.md

Returns whole-document payloads (is_chunked=False) so the sync pipeline can
apply its configured chunking strategy.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from django.db.models import Q

from .models import YouTubeVideo


def _normalize_failed_ids(failed_ids: list[str]) -> list[str]:
    """Return stripped, non-empty, de-duplicated failed IDs preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in failed_ids:
        value = (raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _read_vtt(transcript_path: str) -> str:
    """Return plain text from a .vtt file, stripping VTT header/timestamps.

    Returns empty string if the file does not exist or cannot be read.
    """
    path = Path(transcript_path)
    if not path.exists():
        return ""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        # Skip WEBVTT header, NOTE blocks, blank lines, and timestamp lines
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        # Timestamp lines: "00:00:00.000 --> 00:00:05.000" or similar
        if "-->" in line:
            continue
        # Cue-setting lines (e.g. "align:start position:0%")
        if line.startswith("align:") or line.startswith("position:"):
            continue
        lines.append(line)

    return " ".join(lines).strip()


def _get_speaker_names(video: YouTubeVideo) -> list[str]:
    """Return a sorted list of speaker display_names linked to this video."""
    names = list(
        video.video_speakers.select_related("speaker")
        .values_list("speaker__display_name", flat=True)
        .order_by("speaker__display_name")
    )
    return [n for n in names if n]


def _build_document_content(video: YouTubeVideo, speaker_names: list[str]) -> str:
    """Build plain-text content for embedding."""
    parts: list[str] = []

    if video.title:
        parts.append(f"Title: {video.title.strip()}")
    if speaker_names:
        parts.append(f"Speakers: {', '.join(speaker_names)}")
    if video.channel and video.channel.channel_title:
        parts.append(f"Channel: {video.channel.channel_title.strip()}")
    if video.published_at:
        parts.append(f"Published: {video.published_at.isoformat()}")

    description = (video.description or "").strip()
    if description:
        parts.append(f"\nDescription:\n{description}")

    if video.has_transcript and video.transcript_path:
        transcript_text = _read_vtt(video.transcript_path)
        if transcript_text:
            parts.append(f"\nTranscript:\n{transcript_text}")

    return "\n".join(parts).strip()


def _build_candidate_queryset(
    normalized_failed: list[str], final_sync_at: datetime | None
):
    """Return the ORM queryset of candidates to preprocess."""
    queryset = YouTubeVideo.objects.select_related("channel").prefetch_related(
        "video_speakers__speaker"
    )
    if final_sync_at is None and not normalized_failed:
        return queryset.order_by("video_id")
    criteria = Q()
    if final_sync_at is not None:
        criteria |= Q(updated_at__gt=final_sync_at)
    if normalized_failed:
        criteria |= Q(video_id__in=normalized_failed)
    return queryset.filter(criteria).order_by("video_id")


def _build_video_metadata(
    video: YouTubeVideo, speaker_names: list[str]
) -> dict[str, Any]:
    """Build the Pinecone metadata dict for one video."""
    channel_title = (video.channel.channel_title if video.channel else "") or ""
    return {
        "doc_id": f"youtube-{video.video_id}",
        "ids": str(video.pk),
        "type": "youtube",
        "url": f"https://www.youtube.com/watch?v={video.video_id}",
        "title": video.title or "",
        "author": ", ".join(speaker_names),
        "channel": channel_title,
        "timestamp": int(video.published_at.timestamp()) if video.published_at else 0,
        "has_transcript": video.has_transcript,
    }


def preprocess_youtube_for_pinecone(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Build Pinecone sync documents for YouTube videos.

    Args:
        failed_ids: Previous-run failed source IDs (video_id values).
        final_sync_at: Last sync timestamp for incremental sync; None means first sync.

    Returns:
        (documents, is_chunked)
        - documents: list[{"content": str, "metadata": dict}]
        - is_chunked: False (whole docs; pipeline may chunk later)
    """
    normalized_failed = _normalize_failed_ids(failed_ids or [])
    candidates = _build_candidate_queryset(normalized_failed, final_sync_at)

    docs: list[dict[str, Any]] = []
    seen_video_ids: set[str] = set()

    for video in candidates:
        vid = (video.video_id or "").strip()
        if not vid or vid in seen_video_ids:
            continue
        seen_video_ids.add(vid)

        speaker_names = _get_speaker_names(video)
        content = _build_document_content(video, speaker_names)
        if not content:
            continue

        docs.append(
            {
                "content": content,
                "metadata": _build_video_metadata(video, speaker_names),
            }
        )

    return docs, False
