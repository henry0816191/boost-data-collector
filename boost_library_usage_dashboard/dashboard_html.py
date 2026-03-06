"""Public entrypoint for dashboard HTML generation."""

from __future__ import annotations

import json
from pathlib import Path

from boost_library_usage_dashboard.dashboard_html_index import build_index_page
from boost_library_usage_dashboard.dashboard_html_library import build_library_page


def generate_dashboard_html(
    dashboard_data_file: Path,
    output_dir: Path,
    libraries_dir: Path | None = None,
) -> None:
    """Read dashboard_data.json and generate index/library pages."""
    if not dashboard_data_file.is_file():
        raise FileNotFoundError(f"Dashboard data file not found: {dashboard_data_file}")

    output_dir.mkdir(parents=True, exist_ok=True)
    lib_dir = libraries_dir if libraries_dir is not None else output_dir / "libraries"
    lib_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(dashboard_data_file.read_text(encoding="utf-8"))
    build_index_page(data, output_dir)
    for library_name in data.get("libraries_page_data", {}) or {}:
        build_library_page(data, library_name, lib_dir)
