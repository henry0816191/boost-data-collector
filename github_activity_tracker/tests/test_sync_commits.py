from unittest.mock import MagicMock, patch

from github_activity_tracker.models import FileChangeStatus
from github_activity_tracker.sync.commits import _process_commit_files


def test_process_commit_files_creates_files_and_changes():
    """_process_commit_files creates/updates GitHubFile and GitCommitFileChange for each file."""
    mock_repo = MagicMock()
    mock_commit = MagicMock()

    files = [
        {
            "filename": "added.txt",
            "status": "added",
            "additions": 10,
            "deletions": 0,
            "patch": "@@ -0,0 +1,10 @@...",
        },
        {
            "filename": "modified.txt",
            "status": "modified",
            "additions": 5,
            "deletions": 2,
        },
        {
            "filename": "deleted.txt",
            "status": "removed",
            "additions": 0,
            "deletions": 100,
        },
        {
            "previous_filename": "renamed.txt",
            "status": "renamed",
        },
        {
            "filename": "  spaced.txt  ",
            "status": " unknown_status ",
        },
        {
            "filename": "",  # Empty string, should be skipped
        },
        {
            "filename": None,  # None, should be skipped
        },
        {
            "filename": "   ",  # Whitespace, should be skipped
        },
    ]

    mock_github_file_1 = MagicMock()
    mock_github_file_2 = MagicMock()
    mock_github_file_3 = MagicMock()
    mock_github_file_4 = MagicMock()
    mock_github_file_5 = MagicMock()

    mock_create_file = MagicMock(
        side_effect=[
            (mock_github_file_1, True),
            (mock_github_file_2, False),
            (mock_github_file_3, False),
            (mock_github_file_4, True),
            (mock_github_file_5, True),
        ]
    )

    mock_add_change = MagicMock()

    with patch(
        "github_activity_tracker.sync.commits.services.create_or_update_github_file",
        mock_create_file,
    ), patch(
        "github_activity_tracker.sync.commits.services.add_commit_file_change",
        mock_add_change,
    ):
        _process_commit_files(mock_repo, mock_commit, files)

    assert mock_create_file.call_count == 5
    # added.txt
    mock_create_file.assert_any_call(mock_repo, "added.txt", is_deleted=False)
    # modified.txt
    mock_create_file.assert_any_call(mock_repo, "modified.txt", is_deleted=False)
    # deleted.txt
    mock_create_file.assert_any_call(mock_repo, "deleted.txt", is_deleted=True)
    # renamed.txt (fallback to previous_filename)
    mock_create_file.assert_any_call(mock_repo, "renamed.txt", is_deleted=False)
    # spaced.txt (trimmed)
    mock_create_file.assert_any_call(mock_repo, "spaced.txt", is_deleted=False)

    assert mock_add_change.call_count == 5
    # added.txt
    mock_add_change.assert_any_call(
        mock_commit,
        mock_github_file_1,
        status="added",
        additions=10,
        deletions=0,
        patch="@@ -0,0 +1,10 @@...",
    )
    # modified.txt
    mock_add_change.assert_any_call(
        mock_commit,
        mock_github_file_2,
        status="modified",
        additions=5,
        deletions=2,
        patch="",
    )
    # deleted.txt
    mock_add_change.assert_any_call(
        mock_commit,
        mock_github_file_3,
        status="removed",
        additions=0,
        deletions=100,
        patch="",
    )
    # renamed.txt
    mock_add_change.assert_any_call(
        mock_commit,
        mock_github_file_4,
        status="renamed",
        additions=0,
        deletions=0,
        patch="",
    )
    # spaced.txt (unknown_status becomes changed)
    mock_add_change.assert_any_call(
        mock_commit,
        mock_github_file_5,
        status=FileChangeStatus.CHANGED,
        additions=0,
        deletions=0,
        patch="",
    )
