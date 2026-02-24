"""Tests for cppa_slack_tracker.workspace path helpers."""

import pytest
from pathlib import Path
from unittest.mock import patch

from cppa_slack_tracker.workspace import (
    get_workspace_root,
    get_raw_root,
    get_team_channel_dir,
    get_message_json_path,
    get_raw_team_channel_dir,
    get_raw_message_json_path,
    iter_existing_message_jsons,
)
from cppa_slack_tracker.workspace import _slug  # noqa: PLC2701


@pytest.fixture
def mock_workspace_dir(tmp_path):
    """Patch WORKSPACE_DIR to a temp path."""
    with patch("cppa_slack_tracker.workspace.settings") as m_settings:
        m_settings.WORKSPACE_DIR = tmp_path / "workspace"
        m_settings.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        yield m_settings.WORKSPACE_DIR


@pytest.fixture
def mock_get_workspace_path(tmp_path):
    """Patch get_workspace_path to return a temp app workspace."""
    app_workspace = tmp_path / "workspace" / "cppa_slack_tracker"
    app_workspace.mkdir(parents=True, exist_ok=True)
    with patch("cppa_slack_tracker.workspace.get_workspace_path") as m:
        m.return_value = app_workspace
        yield m


class TestGetWorkspaceRoot:
    def test_returns_path_from_get_workspace_path(self, mock_get_workspace_path):
        root = get_workspace_root()
        assert root == mock_get_workspace_path.return_value
        assert "cppa_slack_tracker" in str(root)


class TestGetRawRoot:
    def test_raw_root_under_workspace_dir(self, mock_workspace_dir):
        root = get_raw_root()
        assert root == mock_workspace_dir / "raw" / "cppa_slack_tracker"
        assert root.exists()

    def test_raw_root_contains_raw_segment(self, mock_workspace_dir):
        root = get_raw_root()
        assert "raw" in root.parts
        assert root.parts[-1] == "cppa_slack_tracker"


class TestSlugAndPaths:
    def test_get_team_channel_dir_sanitizes_slugs(self, mock_get_workspace_path):
        path = get_team_channel_dir("Cpplang", "boost-json")
        assert path.name == "boost-json" or "boost" in path.name
        assert path.parent.name != "Cpplang" or "Cpplang" in str(path)

    def test_get_message_json_path_format(self, mock_get_workspace_path):
        path = get_message_json_path("Team", "general", "2026-01-15")
        assert path.suffix == ".json"
        assert path.stem == "2026-01-15"

    def test_get_raw_message_json_path_under_raw(self, mock_workspace_dir):
        path = get_raw_message_json_path("Team", "general", "2026-01-15")
        assert "raw" in path.parts
        assert path.name == "2026-01-15.json"

    def test_get_raw_team_channel_dir_creates_dirs(self, mock_workspace_dir):
        path = get_raw_team_channel_dir("T1", "C1")
        assert path.exists()
        assert path.is_dir()


class TestIterExistingMessageJsons:
    def test_yields_nothing_when_workspace_missing(self, mock_get_workspace_path):
        with patch("cppa_slack_tracker.workspace.get_workspace_root") as m:
            m.return_value = Path("/nonexistent/workspace")
            paths = list(iter_existing_message_jsons())
        assert paths == []

    def test_yields_date_jsons_in_channel_dir(self, mock_get_workspace_path):
        root = mock_get_workspace_path.return_value
        team_slug, channel_slug = "Team", "general"
        base = root / _slug(team_slug) / _slug(channel_slug)
        base.mkdir(parents=True)
        (base / "2026-01-15.json").write_text("[]")
        (base / "2026-01-16.json").write_text("[]")
        (base / "not-a-date.json").write_text("{}")
        with patch(
            "cppa_slack_tracker.workspace.get_workspace_root", return_value=root
        ):
            paths = list(iter_existing_message_jsons(team_slug, channel_slug))
        stems = {p.stem for p in paths}
        assert "2026-01-15" in stems
        assert "2026-01-16" in stems
        assert "not-a-date" not in stems
