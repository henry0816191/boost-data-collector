"""Shared markdown file writing."""

from pathlib import Path


def write_markdown(path: str | Path, content: str, *, encoding: str = "utf-8") -> Path:
    """
    Write content to a markdown file. Creates parent directories if needed.
    Returns the resolved path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding)
    return path.resolve()
