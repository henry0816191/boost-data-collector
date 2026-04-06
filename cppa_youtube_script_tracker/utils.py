"""
Speaker extraction utilities for cppa_youtube_script_tracker.

Priority order:
1) description patterns
2) title pattern
3) transcript introduction patterns
4) fallback to "unknown"
"""

from __future__ import annotations

import re
from typing import Iterable

UNKNOWN_SPEAKER_NAME = "unknown"

_SEPARATORS = (" - ", " — ", " | ")
_INTRO_RE = re.compile(
    r"(?i)\b(?:i am|my name is)\s+([A-Z][A-Za-z'`-]*(?:\s+[A-Z][A-Za-z'`-]*){0,4})"
)


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\x00", "").replace("\u2019", "'").strip()


def _slugify_speaker_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", clean_text(name).lower()).strip("_")
    return slug or "unknown"


def build_speaker_external_id(
    speaker_name: str,
    channel_id: str = "",
    video_id: str = "",
) -> str:
    """Build a stable speaker external identifier from channel/video context."""
    slug = _slugify_speaker_name(speaker_name)
    channel_id = clean_text(channel_id)
    video_id = clean_text(video_id)
    if channel_id:
        return f"youtube:channel:{channel_id}:speaker:{slug}"
    if video_id:
        return f"youtube:video:{video_id}:speaker:{slug}"
    return f"youtube:name:{slug}"


def _normalize_name(name: str) -> str:
    name = re.sub(r"\s+", " ", clean_text(name))
    name = name.strip(" .,:;\"'`-")
    return name


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _extract_speaker_colon_line(description: str) -> list[str]:
    # Example: "Speaker: Ehsan Amiri"
    matches = re.findall(r"(?im)^\s*speaker\s*:\s*(.+?)\s*$", description or "")
    return [_normalize_name(m) for m in matches if _normalize_name(m)]


def _extract_middle_name_from_triplet(
    text: str, title: str = "", channel_title: str = ""
) -> str:
    """
    Try parsing structures like:
      {title} - {speaker} - {channel}
    """
    text_norm = clean_text(text)
    if not text_norm:
        return ""

    for sep in _SEPARATORS:
        if sep not in text_norm:
            continue
        parts = [_normalize_name(p) for p in text_norm.split(sep)]
        parts = [p for p in parts if p]
        if len(parts) < 3:
            continue
        candidate = parts[-2]
        last = parts[-1].casefold()
        first = parts[0].casefold()
        title_cf = clean_text(title).casefold()
        channel_cf = clean_text(channel_title).casefold()

        # Prefer high-confidence: title/speaker/channel match pattern.
        if channel_cf and channel_cf in last:
            return candidate
        if title_cf and title_cf in first:
            return candidate

    return ""


def _extract_from_intro_pattern(text: str) -> list[str]:
    matches = _INTRO_RE.findall(text or "")
    return [_normalize_name(m) for m in matches if _normalize_name(m)]


def extract_speakers_from_description(
    description: str, title: str = "", channel_title: str = ""
) -> list[str]:
    """
    Description-based speaker extraction:
    - line starting with "Speaker:"
    - 4th non-empty line pattern: {title} - {speaker} - {channel}
    - intro pattern: "I am ..." / "my name is ..."
    """
    description = clean_text(description)
    if not description:
        return []

    speakers: list[str] = []
    speakers.extend(_extract_speaker_colon_line(description))

    non_empty_lines = [ln.strip() for ln in description.splitlines() if ln.strip()]
    if len(non_empty_lines) >= 4:
        candidate = _extract_middle_name_from_triplet(
            non_empty_lines[3], title=title, channel_title=channel_title
        )
        if candidate:
            speakers.append(candidate)

    for line in non_empty_lines:
        candidate = _extract_middle_name_from_triplet(
            line, title=title, channel_title=channel_title
        )
        if candidate:
            speakers.append(candidate)

    speakers.extend(_extract_from_intro_pattern(description))
    return _dedupe_keep_order(speakers)


def extract_speakers_from_title(title: str, channel_title: str = "") -> list[str]:
    """
    Title-based extraction for structures:
      {title} - {speaker} - {channel}
    """
    title = clean_text(title)
    if not title:
        return []

    candidate = _extract_middle_name_from_triplet(
        title, title=title, channel_title=channel_title
    )
    if candidate:
        return [candidate]
    return []


def extract_speakers_from_transcript_text(transcript_text: str) -> list[str]:
    """
    Transcript fallback extraction using introduction patterns.
    We prioritize early transcript content where introductions usually appear.
    """
    transcript_text = clean_text(transcript_text)
    if not transcript_text:
        return []
    early_text = transcript_text[:8000]
    return _dedupe_keep_order(_extract_from_intro_pattern(early_text))


def resolve_speakers(
    *,
    title: str,
    description: str,
    channel_title: str = "",
    transcript_text: str = "",
) -> list[str]:
    """
    Resolve speakers using priority:
      description -> title -> transcript -> ["unknown"]
    """
    from_description = extract_speakers_from_description(
        description=description, title=title, channel_title=channel_title
    )
    if from_description:
        return from_description

    from_title = extract_speakers_from_title(title=title, channel_title=channel_title)
    if from_title:
        return from_title

    from_transcript = extract_speakers_from_transcript_text(transcript_text)
    if from_transcript:
        return from_transcript

    return [UNKNOWN_SPEAKER_NAME]
