import re

from core.utils.boost_version_operations import (
    loose_version_tuple,
    normalize_boost_version_string,
)


def _version_tuple(version: str) -> tuple[int, int, int]:
    """Parse version string (e.g. '1.84.0', 'release-2.1.9-extra') to (major, minor, patch) for sorting."""
    return loose_version_tuple(version)


def normalize_version_str(version_str: str) -> str | None:
    """Normalize a version string for comparison; returns None if invalid or pre-1.0."""
    return normalize_boost_version_string(version_str)


def format_percent(current: int, total: int) -> str:
    return f"{(current / total * 100):.2f}%" if total > 0 else "0.00%"


def sanitize_library_name(library_name: str) -> str:
    """Return a filesystem-safe library name for HTML filenames."""
    safe = re.sub(r"[^\w\-.]", "_", library_name or "")
    return safe or "unknown"
