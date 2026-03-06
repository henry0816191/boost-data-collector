import re


def _version_tuple(version: str) -> tuple[int, int, int]:
    """Parse version string (e.g. '1.84.0', 'release-2.1.9-extra') to (major, minor, patch) for sorting."""
    if not version:
        return (0, 0, 0)
    parts = version.strip().split(".")
    out: list[int] = []
    for part in parts[:3]:
        number = "".join(c for c in part if c.isdigit())
        out.append(int(number) if number else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def normalize_version_str(version_str: str) -> str | None:
    """Normalize a version string for comparison; returns None if invalid or pre-1.0."""
    version = (version_str or "").strip().replace("boost-", "")
    version = version.replace("-", ".").replace("_", ".")
    if not version or version.startswith("0."):
        return None
    if len(version.split(".")) == 2:
        version = f"{version}.0"
    return version


def format_percent(current: int, total: int) -> str:
    return f"{(current / total * 100):.2f}%" if total > 0 else "0.00%"


def sanitize_library_name(library_name: str) -> str:
    """Return a filesystem-safe library name for HTML filenames."""
    safe = re.sub(r"[^\w\-.]", "_", library_name or "")
    return safe or "unknown"
