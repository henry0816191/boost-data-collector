"""
Workspace paths for cppa_youtube_script_tracker.

Layout:
- Metadata queue: workspace/cppa_youtube_script_tracker/metadata/{video_id}.json
      (short-lived; moved to raw after DB persist)
- Raw metadata:   workspace/raw/cppa_youtube_script_tracker/metadata/{video_id}.json
      (permanent archive; never deleted)
- Raw transcripts: workspace/raw/cppa_youtube_script_tracker/transcripts/{video_id}.en.vtt
      (permanent archive; never deleted)
"""

from pathlib import Path

from config.workspace import get_workspace_path

_APP_SLUG = "cppa_youtube_script_tracker"
_RAW_APP_SLUG = f"raw/{_APP_SLUG}"


def get_workspace_root() -> Path:
    """Return this app's workspace directory (workspace/cppa_youtube_script_tracker/)."""
    return get_workspace_path(_APP_SLUG)


def get_raw_dir() -> Path:
    """Return workspace/raw/cppa_youtube_script_tracker/; creates if missing."""
    path = get_workspace_path(_RAW_APP_SLUG)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_metadata_queue_dir() -> Path:
    """Return workspace/cppa_youtube_script_tracker/metadata/; creates if missing.

    JSON files here are short-lived: moved to raw/metadata/ after DB persist.
    """
    path = get_workspace_root() / "metadata"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_metadata_dir() -> Path:
    """Return workspace/raw/cppa_youtube_script_tracker/metadata/; creates if missing.

    Permanent archive: JSON files are never deleted after being moved here.
    """
    path = get_raw_dir() / "metadata"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_transcripts_dir() -> Path:
    """Return workspace/raw/cppa_youtube_script_tracker/transcripts/; creates if missing.

    Permanent archive: VTT files are never deleted.
    """
    path = get_raw_dir() / "transcripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_metadata_queue_path(video_id: str) -> Path:
    """Return workspace/cppa_youtube_script_tracker/metadata/{video_id}.json."""
    return get_metadata_queue_dir() / f"{video_id}.json"


def get_raw_metadata_path(video_id: str) -> Path:
    """Return workspace/raw/cppa_youtube_script_tracker/metadata/{video_id}.json."""
    return get_raw_metadata_dir() / f"{video_id}.json"


def get_transcript_path(video_id: str, lang: str = "en") -> Path:
    """Return workspace/raw/cppa_youtube_script_tracker/transcripts/{video_id}.{lang}.vtt."""
    return get_raw_transcripts_dir() / f"{video_id}.{lang}.vtt"


def iter_metadata_queue_jsons():
    """Yield Path for each *.json file in the metadata queue directory."""
    queue_dir = get_workspace_root() / "metadata"
    if not queue_dir.is_dir():
        return
    for path in sorted(queue_dir.glob("*.json")):
        if not path.name.startswith("."):
            yield path
