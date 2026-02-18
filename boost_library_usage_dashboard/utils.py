import re


def normalize_version_str(version_str: str) -> str | None:
    version = (version_str or "").replace("-", ".").replace("_", ".")
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

