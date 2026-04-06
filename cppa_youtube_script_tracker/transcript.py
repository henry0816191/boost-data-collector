"""
VTT transcript downloader for cppa_youtube_script_tracker.

Adapted from cppa-brain-backend/copilot_data/scrape/youtube_cpp/scraper.py
(YouTubeCppScraper._content_download / _setup_ytdlp).
Uses yt-dlp to download auto-generated or manual English subtitles as .vtt files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_YDL_OPTS_BASE: dict = {
    "skip_download": True,
    "force_ipv4": True,
    "writesubtitles": True,
    "writeautomaticsub": True,
    "subtitleslangs": ["en"],
    "subtitlesformat": "vtt",
    "quiet": False,
    "no_warnings": False,
    "ignore_no_formats_error": True,
    "extractor_args": {
        "youtube": ["player_client=tv,web_safari"],
    },
}


def download_vtt(
    video_id: str,
    output_dir: Path,
    cookies_file: Optional[str] = None,
) -> Optional[Path]:
    """Download the English VTT transcript for video_id into output_dir.

    Tries manual captions first, then auto-generated. Returns the Path to the
    downloaded .vtt file on success, or None if no transcript was found.

    Args:
        video_id: YouTube video ID (11 characters).
        output_dir: Directory where the .vtt file will be written.
        cookies_file: Optional path to a cookies.txt for authenticated requests.

    Returns:
        Path to the downloaded file (e.g. output_dir/{video_id}.en.vtt), or None.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise ImportError("yt-dlp is required: pip install yt-dlp") from exc

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    url = f"https://www.youtube.com/watch?v={video_id}"
    outtmpl = str(output_dir / "%(id)s.%(ext)s")

    ydl_opts = dict(_YDL_OPTS_BASE)
    ydl_opts["outtmpl"] = outtmpl
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("download_vtt: yt-dlp error for %s: %s", video_id, exc)
        return None

    # yt-dlp writes {video_id}.{lang}.vtt; try most common pattern first
    expected = output_dir / f"{video_id}.en.vtt"
    if expected.exists():
        logger.debug("download_vtt: found %s", expected)
        return expected

    # Fallback: look for any .vtt file matching the video_id
    matches = list(output_dir.glob(f"{video_id}*.vtt"))
    if matches:
        logger.debug("download_vtt: found %s (fallback glob)", matches[0])
        return matches[0]

    logger.info("download_vtt: no VTT transcript found for %s", video_id)
    return None
