"""
Render Boost Library Usage Dashboard HTML from dashboard_data.json.

All HTML is generated inside this Django app; no dependency on old_project_files.
"""

from __future__ import annotations

from pathlib import Path

from boost_library_usage_dashboard.dashboard_html import generate_dashboard_html


def render_dashboard_html(base_dir: Path, output_dir: Path) -> None:
    """Generate dashboard HTML files from dashboard_data.json in output_dir.

    Expects the analyzer to have already written output_dir/dashboard_data.json.
    Writes output_dir/index.html and output_dir/libraries/<name>.html.

    Args:
        base_dir: Project base directory (unused; kept for API compatibility).
        output_dir: Directory containing dashboard_data.json and where HTML is written.
    """
    del base_dir  # no longer used; HTML is generated from JSON only
    data_file = output_dir / "dashboard_data.json"
    libraries_dir = output_dir / "libraries"
    generate_dashboard_html(
        dashboard_data_file=data_file,
        output_dir=output_dir,
        libraries_dir=libraries_dir,
    )
