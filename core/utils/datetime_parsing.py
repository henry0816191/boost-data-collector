"""Parsing date/time strings from CLI, JSON, and APIs."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_iso_datetime(raw: str | None) -> datetime | None:
    """
    Parse a date or datetime string using ``datetime.fromisoformat``.

    Accepts common ISO-style forms (e.g. ``YYYY-MM-DD``, ``YYYY-MM-DDTHH:MM:SS``,
    ``YYYY-MM-DD HH:MM:SS`` on Python 3.11+, optional fractional seconds and offsets).
    If the string ends with ``Z`` and contains ``T``, ``Z`` is treated as UTC before parsing.

    Empty or whitespace-only input returns ``None``.

    Raises:
        ValueError: If the string is non-empty but cannot be parsed.

    Timezone-aware values are converted to UTC and returned as **naive** datetimes
    (``tzinfo`` cleared). Naive input is returned unchanged.
    """
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if s.endswith("Z") and "T" in s:
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(f"Invalid ISO datetime ({s!r}): {e}") from e
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
