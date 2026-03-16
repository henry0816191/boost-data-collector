"""
GitHub operations: API client, git (clone/push), token resolution, file upload.
Single app for all GitHub I/O; other apps (e.g. github_activity_tracker, cppa_slack_transcript_tracker) use this.
"""

from github_ops.client import (
    ConnectionException,
    GitHubAPIClient,
    RateLimitException,
)
from github_ops.git_ops import (
    clone_repo,
    fetch_file_content,
    get_commit_file_changes,
    get_remote_tree,
    list_remote_directory,
    push,
    upload_file,
    upload_folder_to_github,
)
from github_ops.tokens import get_github_client, get_github_token

__all__ = [
    "ConnectionException",
    "GitHubAPIClient",
    "RateLimitException",
    "clone_repo",
    "fetch_file_content",
    "get_commit_file_changes",
    "get_github_client",
    "get_github_token",
    "get_remote_tree",
    "list_remote_directory",
    "push",
    "upload_file",
    "upload_folder_to_github",
]
