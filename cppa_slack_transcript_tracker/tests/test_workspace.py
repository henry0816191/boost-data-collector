"""Tests for cppa_slack_transcript_tracker.workspace."""

from pathlib import Path
from unittest.mock import patch

from cppa_slack_transcript_tracker.workspace import (
    get_workspace_root,
    get_data_dir,
    set_working_directory,
)


def test_get_workspace_root_returns_path_from_config():
    """get_workspace_root returns config workspace path for this app slug."""
    with patch(
        "cppa_slack_transcript_tracker.workspace.get_workspace_path"
    ) as mock_get:
        mock_get.return_value = Path("/tmp/workspace/cppa_slack_transcript_tracker")
        root = get_workspace_root()
    assert root == Path("/tmp/workspace/cppa_slack_transcript_tracker")
    mock_get.assert_called_once_with("cppa_slack_transcript_tracker")


def test_get_data_dir_returns_data_subdir_and_creates_it():
    """get_data_dir returns workspace/data/ and creates directory."""
    with patch(
        "cppa_slack_transcript_tracker.workspace.get_workspace_root"
    ) as mock_root:
        data_path = Path("/tmp/ws/cppa_slack_transcript_tracker/data")
        mock_root.return_value = data_path.parent
        result = get_data_dir()
    assert result == data_path
    assert result.name == "data"
    mock_root.assert_called_once()


def test_set_working_directory_chdirs_to_workspace_root():
    """set_working_directory changes cwd to workspace root."""
    with patch(
        "cppa_slack_transcript_tracker.workspace.get_workspace_root"
    ) as mock_root:
        root = Path("/tmp/workspace/cppa_slack_transcript_tracker")
        mock_root.return_value = root
        with patch("os.chdir") as mock_chdir:
            set_working_directory()
    mock_chdir.assert_called_once_with(root)
