"""
JSON file persistence for the PR bot job queue and rate-limit state.

State file layout:
  { "postedAt": [<unix_timestamp>, ...], "queue": [<job_dict>, ...] }

When team_id is provided, state is stored in state_<team_id>.json for multi-workspace support.
"""

import json
import logging
import os
import re
import tempfile
import time
from copy import deepcopy
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_STATE: dict[str, Any] = {"postedAt": [], "queue": []}


def _sanitize_team_id_for_path(team_id: str) -> str:
    """Safe filename segment from Slack team_id (e.g. T01234ABCD -> T01234ABCD)."""
    if not team_id:
        return "default"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", team_id)


def _get_state_file_path(team_id: Optional[str] = None) -> str:
    """Resolve the state file path. If team_id is None, state.json; else state_<team_id>.json."""
    from slack_event_handler.workspace import get_data_dir

    data_dir = get_data_dir()
    if team_id:
        safe = _sanitize_team_id_for_path(team_id)
        return str(data_dir / f"state_{safe}.json")
    return str(data_dir / "state.json")


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def load_state(team_id: Optional[str] = None) -> dict[str, Any]:
    """Load state for the given team. team_id=None uses state.json (single-workspace)."""
    path = _get_state_file_path(team_id)
    _ensure_dir(path)
    if not os.path.exists(path):
        return deepcopy(_DEFAULT_STATE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.exception("Corrupt state file decoding %s", path)
        quarantine = f"{path}.corrupt.{int(time.time())}"
        try:
            os.replace(path, quarantine)
        except OSError as e:
            logger.warning("Could not quarantine %s to %s: %s", path, quarantine, e)
        return deepcopy(_DEFAULT_STATE)


def save_state(state: dict[str, Any], team_id: Optional[str] = None) -> None:
    """Save state for the given team. team_id=None uses state.json (single-workspace)."""
    path = _get_state_file_path(team_id)
    _ensure_dir(path)
    dir_path = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=dir_path,
        delete=False,
        suffix=".tmp",
    ) as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        temp_path = f.name
    os.replace(temp_path, path)
