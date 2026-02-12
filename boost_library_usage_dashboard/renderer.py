from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_module(module_name: str, file_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_dashboard_html(base_dir: Path, output_dir: Path) -> None:
    old_dir = base_dir / "old_project_files" / "boost_analysis"
    create_dashboard_py = old_dir / "create_dashboard.py"
    if not create_dashboard_py.exists():
        raise FileNotFoundError(f"Missing legacy dashboard generator: {create_dashboard_py}")

    inserted = False
    old_dir_str = str(old_dir)
    if old_dir_str not in sys.path:
        sys.path.insert(0, old_dir_str)
        inserted = True
    create_dashboard = _load_module("legacy_create_dashboard", create_dashboard_py)
    create_dashboard.DASHBOARD_DIR = output_dir
    create_dashboard.LIBRARIES_DIR = output_dir / "libraries"
    create_dashboard.LIBRARIES_DIR.mkdir(parents=True, exist_ok=True)
    create_dashboard.DASHBOARD_DATA_FILE = output_dir / "dashboard_data.json"
    create_dashboard.generate_dashboard_html()
    if inserted:
        sys.path.remove(old_dir_str)

