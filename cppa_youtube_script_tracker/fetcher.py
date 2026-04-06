"""
YouTube Data API v3 fetcher for cppa_youtube_script_tracker.

Adapted from cppa-brain-backend/copilot_data/scrape/youtube_cpp/scraper.py.
Fetches video metadata for C++ channels between published_after and published_before.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# Maps channel title to stable YouTube channel ID.
C_PLUS_PLUS_CHANNELS: dict[str, str] = {
    "CppCon": "UCMlGfpWw-RUdWX_JbLCukXg",
    "Meeting C++": "UCX9pk4YzHFcl3MsHIYBlEKg",
    "C++Now": "UCEfngwe09zvd9KAL33YJSQQ",
    "Jason Turner": "UCXTpTQHR7li1_HkUyAIUjkQ",
    "TheCherno": "UCQ-W1KE9EYfdxhL6S4twUNw",
    "Bo Qian": "UCEqgmyWChwmqyRdmnsS24Zw",
}

_CHANNEL_FOCUSED_TERMS: list[str] = [
    "C++",
]

# Search-term based discovery (global searches, not tied to one channel ID)
_GLOBAL_SEARCH_TERMS: list[str] = [
    "C++ programming",
    "C++ tutorial",
    "C++ advanced",
    "modern C++",
    "C++20",
    "C++23",
    "C++ templates",
    "C++ STL",
    "C++ best practices",
    "C++ performance",
    "Boost C++",
]

# Famous-figure focused discovery terms.
_FAMOUS_FIGURE_TERMS: list[str] = [
    "Bjarne Stroustrup C++",
    "Herb Sutter C++",
    "Scott Meyers C++",
    "Andrei Alexandrescu C++",
    "Nicolai Josuttis C++",
    "Chandler Carruth C++",
    "Kate Gregory C++",
    "Jason Turner C++",
    "Sean Parent C++",
    "Jonathan Boccara C++",
]

_MAX_RESULTS_PER_PAGE = 50
_DELAY_SECONDS = 0.5
_DEFAULT_MAX_QUERY_PAIRS = 30


class QuotaExceededError(RuntimeError):
    """Raised when YouTube Data API quota has been exhausted."""


def _get_api_key() -> str:
    """Return YOUTUBE_API_KEY from Django settings. Raises ValueError if missing."""
    key = (getattr(settings, "YOUTUBE_API_KEY", None) or "").strip()
    if not key:
        raise ValueError(
            "YOUTUBE_API_KEY is not set. Add it to your .env or Django settings."
        )
    return key


def _parse_duration_iso(duration_iso: str) -> int:
    """Parse ISO 8601 duration string (e.g. PT1H2M10S) to total seconds."""
    if not duration_iso or duration_iso == "PT":
        return 0
    match = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?").match(duration_iso)
    if not match:
        return 0
    return (
        int(match.group(1) or 0) * 3600
        + int(match.group(2) or 0) * 60
        + int(match.group(3) or 0)
    )


def _is_quota_exceeded_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "quotaexceeded" in text or "youtube.quota" in text


def _get_max_query_pairs() -> int:
    """
    Return max number of query pairs for one run.

    Configure with `YOUTUBE_MAX_QUERY_PAIRS` in Django settings/.env.
    """
    raw = getattr(settings, "YOUTUBE_MAX_QUERY_PAIRS", _DEFAULT_MAX_QUERY_PAIRS)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _DEFAULT_MAX_QUERY_PAIRS
    return max(1, value)


def _format_video_data(
    video_data: dict[str, Any], search_term: str = ""
) -> dict[str, Any]:
    """Normalise a YouTube API video resource into a flat metadata dict."""
    snippet = video_data.get("snippet", {})
    statistics = video_data.get("statistics", {})
    content_details = video_data.get("contentDetails", {})
    duration_iso = content_details.get("duration", "PT0S")
    view = statistics.get("viewCount")
    like = statistics.get("likeCount")
    comment = statistics.get("commentCount")
    return {
        "video_id": video_data.get("id", ""),
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt", ""),
        "duration_seconds": _parse_duration_iso(duration_iso),
        "view_count": int(view) if view is not None else None,
        "like_count": int(like) if like is not None else None,
        "comment_count": int(comment) if comment is not None else None,
        "tags": snippet.get("tags") or [],
        "search_term": search_term,
        "scraped_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def _to_rfc3339(dt: datetime) -> str:
    """Format a datetime as RFC 3339 (required by YouTube API publishedAfter/Before)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_queries(channel_title: Optional[str]) -> list[tuple[str, Optional[str]]]:
    """Return list of (query_text, channel_id_or_None) pairs to iterate over.

    Strategy:
    - If channel_title is specified:
      - Known channel ID: run several C++ terms scoped to that channel.
      - Unknown channel: run keyword searches with that channel title.
    - Otherwise:
      - Run channel-scoped queries for known channels.
      - Run global term-based discovery queries.
      - Run famous-figure discovery queries.
    """

    def _dedupe_pairs(
        pairs: list[tuple[str, Optional[str]]],
    ) -> list[tuple[str, Optional[str]]]:
        seen: set[tuple[str, Optional[str]]] = set()
        out: list[tuple[str, Optional[str]]] = []
        for query_text, ch_id in pairs:
            key = (query_text.strip().casefold(), ch_id)
            if key in seen:
                continue
            seen.add(key)
            out.append((query_text, ch_id))
        return out

    if channel_title:
        ch_id = C_PLUS_PLUS_CHANNELS.get(channel_title)
        if not ch_id:
            logger.warning(
                "fetch_videos: channel_title %r not in C_PLUS_PLUS_CHANNELS; "
                "falling back to keyword search",
                channel_title,
            )
            return _dedupe_pairs(
                [(channel_title, None), (f"{channel_title} C++", None)]
            )
        return _dedupe_pairs([(term, ch_id) for term in _CHANNEL_FOCUSED_TERMS])

    pairs: list[tuple[str, Optional[str]]] = []
    for ch_id in C_PLUS_PLUS_CHANNELS.values():
        pairs.extend((term, ch_id) for term in _CHANNEL_FOCUSED_TERMS)

    pairs.extend((term, None) for term in _FAMOUS_FIGURE_TERMS)
    pairs.extend((term, None) for term in _GLOBAL_SEARCH_TERMS)
    return _dedupe_pairs(pairs)


def _fetch_search_page(
    youtube: Any,
    query_text: str,
    ch_id: Optional[str],
    after_str: str,
    before_str: str,
    page_token: Optional[str],
) -> Optional[dict[str, Any]]:
    """Execute one search().list() call; return the response or None on error.

    Raises QuotaExceededError when API quota is exhausted.
    """
    params: dict[str, Any] = {
        "q": query_text,
        "part": "id,snippet",
        "type": "video",
        "maxResults": _MAX_RESULTS_PER_PAGE,
        "order": "date",
        "publishedAfter": after_str,
        "publishedBefore": before_str,
    }
    if ch_id:
        params["channelId"] = ch_id
    if page_token:
        params["pageToken"] = page_token
    try:
        time.sleep(_DELAY_SECONDS)
        return youtube.search().list(**params).execute()  # type: ignore[union-attr]
    except Exception as exc:  # pylint: disable=broad-exception-caught
        if _is_quota_exceeded_error(exc):
            raise QuotaExceededError("YouTube API quota exceeded.") from exc
        logger.error("fetch_videos: search API error: %s", exc)
        return None


def _fetch_video_details(youtube: Any, video_ids: list[str]) -> list[dict[str, Any]]:
    """Execute one videos().list() call; return items or empty list on error.

    Raises QuotaExceededError when API quota is exhausted.
    """
    try:
        time.sleep(_DELAY_SECONDS)
        resp = (
            youtube.videos()  # type: ignore[union-attr]
            .list(part="snippet,statistics,contentDetails", id=",".join(video_ids))
            .execute()
        )
        return resp.get("items", [])
    except Exception as exc:  # pylint: disable=broad-exception-caught
        if _is_quota_exceeded_error(exc):
            raise QuotaExceededError("YouTube API quota exceeded.") from exc
        logger.error("fetch_videos: videos.list API error: %s", exc)
        return []


def _process_one_channel_query(
    youtube: Any,
    query_text: str,
    ch_id: Optional[str],
    after_str: str,
    before_str: str,
    seen_ids: set[str],
    min_duration_seconds: int,
) -> list[dict[str, Any]]:
    """Paginate through search results for one (query, channel) pair. Returns new video dicts."""
    collected: list[dict[str, Any]] = []
    page_token: Optional[str] = None
    while True:
        response = _fetch_search_page(
            youtube, query_text, ch_id, after_str, before_str, page_token
        )
        if response is None:
            break

        new_ids = [
            item["id"]["videoId"]
            for item in response.get("items", [])
            if item.get("id", {}).get("kind") == "youtube#video"
            and item["id"]["videoId"] not in seen_ids
        ]

        for vdata in _fetch_video_details(youtube, new_ids) if new_ids else []:
            vid = vdata.get("id", "")
            if not vid or vid in seen_ids:
                continue
            duration = _parse_duration_iso(
                vdata.get("contentDetails", {}).get("duration", "PT0S")
            )
            if min_duration_seconds and duration < min_duration_seconds:
                continue
            seen_ids.add(vid)
            collected.append(_format_video_data(vdata, search_term=query_text))

        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return collected


def fetch_videos(
    published_after: datetime,
    published_before: datetime,
    channel_title: Optional[str] = None,
    skip_video_ids: Optional[set[str]] = None,
    min_duration_seconds: int = 0,
) -> list[dict[str, Any]]:
    """Fetch video metadata from the YouTube Data API v3.

    Args:
        published_after: Fetch videos published after this time.
        published_before: Fetch videos published before this time.
        channel_title: If given, restrict to that channel (key in C_PLUS_PLUS_CHANNELS
            or fallback keyword search).
        skip_video_ids: Video IDs already in DB (skipped).
        min_duration_seconds: Skip videos shorter than this.

    Returns:
        List of normalised video metadata dicts.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ImportError(
            "google-api-python-client is required: pip install google-api-python-client"
        ) from exc

    youtube = build("youtube", "v3", developerKey=_get_api_key())
    after_str = _to_rfc3339(published_after)
    before_str = _to_rfc3339(published_before)
    seen_ids: set[str] = set(skip_video_ids or set())
    all_videos: list[dict[str, Any]] = []
    query_pairs = _build_queries(channel_title)
    max_queries = _get_max_query_pairs()
    if len(query_pairs) > max_queries:
        logger.warning(
            "fetch_videos: query list truncated from %d to %d by YOUTUBE_MAX_QUERY_PAIRS",
            len(query_pairs),
            max_queries,
        )
    query_pairs = query_pairs[:max_queries]

    for idx, (query_text, ch_id) in enumerate(query_pairs, start=1):
        try:
            all_videos.extend(
                _process_one_channel_query(
                    youtube,
                    query_text,
                    ch_id,
                    after_str,
                    before_str,
                    seen_ids,
                    min_duration_seconds,
                )
            )
        except QuotaExceededError:
            logger.error(
                "fetch_videos: quota exhausted at query %d/%d (%r). "
                "Returning partial results collected so far.",
                idx,
                len(query_pairs),
                query_text,
            )
            break

    logger.info("fetch_videos: fetched %d videos", len(all_videos))
    return all_videos
