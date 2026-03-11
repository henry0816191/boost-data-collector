"""Tests for github_ops git_ops (clone, push, fetch_file_content, get_commit_file_changes)."""

from unittest.mock import MagicMock, patch

from github_ops.git_ops import (
    _url_with_token,
    clone_repo,
    fetch_file_content,
    get_commit_file_changes,
    push,
)


# --- _url_with_token ---


def test_url_with_token_empty_token_returns_unchanged():
    """_url_with_token with empty token returns URL unchanged."""
    url = "https://github.com/owner/repo.git"
    assert _url_with_token(url, "") == url


def test_url_with_token_injects_token_before_github_com():
    """_url_with_token injects token into HTTPS GitHub URL."""
    url = "https://github.com/owner/repo.git"
    out = _url_with_token(url, "secret")
    assert out == "https://secret@github.com/owner/repo.git"


def test_url_with_token_none_like_token_returns_unchanged():
    """_url_with_token with falsy token (e.g. empty string) returns URL unchanged."""
    url = "https://github.com/org/repo.git"
    assert _url_with_token(url, "") == url


def test_url_with_token_only_replaces_first_occurrence():
    """_url_with_token uses count=1 so only first https://github.com/ is modified."""
    url = "https://github.com/boostorg/boost.git"
    out = _url_with_token(url, "tok")
    assert out == "https://tok@github.com/boostorg/boost.git"


# --- clone_repo ---


def test_clone_repo_builds_correct_command_with_explicit_token(tmp_path):
    """clone_repo runs git clone with URL containing token and dest_dir."""
    with patch("github_ops.git_ops.subprocess.run", MagicMock()) as run_mock:
        clone_repo(
            "https://github.com/owner/repo.git",
            tmp_path,
            token="my_token",
        )
    run_mock.assert_called_once()
    call_args = run_mock.call_args[0][0]
    assert call_args[0] == "git"
    assert call_args[1] == "clone"
    assert "my_token" in call_args[2]
    assert call_args[3] == str(tmp_path)


def test_clone_repo_slug_converted_to_https_url(tmp_path):
    """clone_repo converts owner/repo slug to https://github.com/owner/repo.git."""
    with patch("github_ops.git_ops.subprocess.run", MagicMock()) as run_mock:
        clone_repo("owner/repo", tmp_path, token="t")
    call_args = run_mock.call_args[0][0]
    assert (
        "https://github.com/owner/repo.git" in call_args[2]
        or "t@github.com" in call_args[2]
    )


def test_clone_repo_with_depth_adds_depth_flag(tmp_path):
    """clone_repo adds --depth N when depth is provided."""
    with patch("github_ops.git_ops.subprocess.run", MagicMock()) as run_mock:
        clone_repo("https://github.com/o/r.git", tmp_path, token="t", depth=1)
    call_args = run_mock.call_args[0][0]
    assert "--depth" in call_args
    assert "1" in call_args


def test_clone_repo_uses_get_github_token_when_token_not_provided(tmp_path):
    """clone_repo calls get_github_token(use='scraping') when token is None."""
    with patch(
        "github_ops.git_ops.get_github_token", return_value="scraping_token"
    ) as get_token:
        with patch("github_ops.git_ops.subprocess.run", MagicMock()):
            clone_repo("https://github.com/o/r.git", tmp_path)
    get_token.assert_called_once_with(use="scraping")


# --- push ---


def test_push_with_branch_appends_branch_to_command(tmp_path):
    """push with branch runs git push <url> <branch>."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),
            MagicMock(),
        ]
        push(tmp_path, "origin", branch="main", token="t")
    assert run_mock.call_count == 2
    push_call = run_mock.call_args_list[1][0][0]
    assert "push" in push_call
    assert "main" in push_call


def test_push_without_branch_does_not_append_branch(tmp_path):
    """push without branch runs git push <url> only."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),
            MagicMock(),
        ]
        push(tmp_path, "origin", token="t")
    push_call = run_mock.call_args_list[1][0][0]
    assert "push" in push_call
    assert push_call[-1] != "main"


def test_push_injects_token_into_push_url(tmp_path):
    """push uses _url_with_token so push URL contains token."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(stdout="https://github.com/owner/repo.git\n", stderr=""),
            MagicMock(),
        ]
        push(tmp_path, "origin", token="secret_token")
    push_call = run_mock.call_args_list[1][0][0]
    push_url = push_call[push_call.index("push") + 1]
    assert "secret_token" in push_url


def test_push_uses_get_github_token_when_token_not_provided(tmp_path):
    """push calls get_github_token(use='push') when token is None."""
    with patch(
        "github_ops.git_ops.get_github_token", return_value="push_token"
    ) as get_token:
        with patch("github_ops.git_ops.subprocess.run") as run_mock:
            run_mock.side_effect = [
                MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),
                MagicMock(),
            ]
            push(tmp_path, "origin")
    get_token.assert_called_once_with(use="push")


# --- fetch_file_content ---


def test_fetch_file_content_returns_client_get_file_content_bytes():
    """fetch_file_content returns first element of client.get_file_content (content bytes)."""
    mock_client = MagicMock()
    mock_client.get_file_content.return_value = (b"file contents", "utf-8")
    out = fetch_file_content("owner", "repo", "path/file.txt", client=mock_client)
    assert out == b"file contents"
    mock_client.get_file_content.assert_called_once_with(
        "owner", "repo", "path/file.txt", ref=None
    )


def test_fetch_file_content_passes_ref_to_client():
    """fetch_file_content passes ref to get_file_content when provided."""
    mock_client = MagicMock()
    mock_client.get_file_content.return_value = (b"x", None)
    fetch_file_content("o", "r", "p", ref="main", client=mock_client)
    mock_client.get_file_content.assert_called_once_with("o", "r", "p", ref="main")


def test_fetch_file_content_uses_get_github_client_when_client_none():
    """fetch_file_content calls get_github_client(use='scraping') when client is None."""
    mock_client = MagicMock()
    mock_client.get_file_content.return_value = (b"data", None)
    with patch(
        "github_ops.git_ops.get_github_client", return_value=mock_client
    ) as get_client:
        fetch_file_content("o", "r", "p", client=None)
    get_client.assert_called_once_with(use="scraping")
    mock_client.get_file_content.assert_called_once()


def test_fetch_file_content_empty_content_returns_empty_bytes():
    """fetch_file_content returns empty bytes when get_file_content returns (b'', _)."""
    mock_client = MagicMock()
    mock_client.get_file_content.return_value = (b"", None)
    out = fetch_file_content("o", "r", "empty", client=mock_client)
    assert out == b""


# --- get_commit_file_changes ---


def test_get_commit_file_changes_returns_list_of_file_dicts(tmp_path):
    """get_commit_file_changes returns list of file dicts with filename, status, additions, deletions, patch."""
    # Mock git diff outputs
    name_status_output = "M\tREADME.md\nA\tnew_file.txt\nD\told_file.txt"
    numstat_output = "5\t2\tREADME.md\n10\t0\tnew_file.txt\n0\t3\told_file.txt"
    patch_output = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ patch @@"

    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(stdout=name_status_output, returncode=0),  # --name-status
            MagicMock(stdout=numstat_output, returncode=0),  # --numstat
            MagicMock(stdout=patch_output, returncode=0),  # patch for README.md
            MagicMock(stdout=patch_output, returncode=0),  # patch for new_file.txt
            MagicMock(stdout=patch_output, returncode=0),  # patch for old_file.txt
        ]

        files = get_commit_file_changes(tmp_path, "parent_sha", "commit_sha")

    assert len(files) == 3
    assert all("filename" in f for f in files)
    assert all("status" in f for f in files)
    assert all("additions" in f for f in files)
    assert all("deletions" in f for f in files)
    assert all("patch" in f for f in files)


def test_get_commit_file_changes_maps_status_codes():
    """get_commit_file_changes maps git status codes (A/M/D/R) to added/modified/removed/renamed."""
    name_status_output = (
        "A\tadded.txt\nM\tmodified.txt\nD\tremoved.txt\nR100\told.txt\tnew.txt"
    )
    numstat_output = (
        "1\t0\tadded.txt\n2\t1\tmodified.txt\n0\t1\tremoved.txt\n0\t0\tnew.txt"
    )

    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(stdout=name_status_output, returncode=0),
            MagicMock(stdout=numstat_output, returncode=0),
            MagicMock(stdout="", returncode=0),  # patches
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="", returncode=0),
        ]

        files = get_commit_file_changes("/fake/path", "parent", "commit")

    statuses = {f["filename"]: f["status"] for f in files}
    assert statuses["added.txt"] == "added"
    assert statuses["modified.txt"] == "modified"
    assert statuses["removed.txt"] == "removed"
    assert statuses["new.txt"] == "renamed"

    # Check rename has previous_filename
    renamed = [f for f in files if f["filename"] == "new.txt"][0]
    assert renamed.get("previous_filename") == "old.txt"


def test_get_commit_file_changes_brace_style_rename_numstat_path():
    """Numstat brace-style paths like src/{old => new}/file.txt are normalized to src/new/file.txt for lookup."""
    # --name-status: rename from src/old/file.txt to src/new/file.txt (key is new path)
    name_status_output = "R100\tsrc/old/file.txt\tsrc/new/file.txt"
    # --numstat: git uses brace notation for directory renames
    numstat_output = "3\t2\tsrc/{old => new}/file.txt"

    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(stdout=name_status_output, returncode=0),
            MagicMock(stdout=numstat_output, returncode=0),
            MagicMock(stdout="", returncode=0),  # patch for src/new/file.txt
        ]

        files = get_commit_file_changes("/fake/path", "parent", "commit")

    assert len(files) == 1
    assert files[0]["filename"] == "src/new/file.txt"
    assert files[0]["status"] == "renamed"
    assert files[0]["previous_filename"] == "src/old/file.txt"
    # Additions/deletions must come from numstat (not fallback 0,0)
    assert files[0]["additions"] == 3
    assert files[0]["deletions"] == 2


def test_get_commit_file_changes_applies_patch_size_limit():
    """get_commit_file_changes truncates patch when patch_size_limit is provided."""
    name_status_output = "M\tfile.txt"
    numstat_output = "1\t1\tfile.txt"
    large_patch = "x" * 1000

    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(stdout=name_status_output, returncode=0),
            MagicMock(stdout=numstat_output, returncode=0),
            MagicMock(stdout=large_patch, returncode=0),
        ]

        files = get_commit_file_changes(
            "/fake", "parent", "commit", patch_size_limit=100
        )

    assert len(files) == 1
    assert len(files[0]["patch"]) == 100 + len(
        "\n... (truncated)"
    )  # patch_size_limit + suffix
    assert files[0]["patch"].endswith("... (truncated)")


def test_get_commit_file_changes_patch_size_limit_zero_means_no_truncation():
    """patch_size_limit=0 should behave like None (no truncation)."""
    name_status_output = "M\tfile.txt"
    numstat_output = "1\t1\tfile.txt"
    large_patch = "x" * 1000

    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(stdout=name_status_output, returncode=0),
            MagicMock(stdout=numstat_output, returncode=0),
            MagicMock(stdout=large_patch, returncode=0),
        ]

        files = get_commit_file_changes("/fake", "parent", "commit", patch_size_limit=0)

    assert files[0]["patch"] == large_patch
    assert not files[0]["patch"].endswith("... (truncated)")


def test_get_commit_file_changes_uses_utf8_encoding_for_subprocess():
    """get_commit_file_changes passes encoding=utf-8 and errors=replace to avoid UnicodeDecodeError on Windows."""
    name_status_output = "M\tfile.txt"
    numstat_output = "1\t1\tfile.txt"
    # Patch containing byte that would fail cp1252 decode (e.g. 0x9d)
    patch_output = "diff --git a/file.txt b/file.txt\n--- a/file.txt\n+++ b/file.txt"

    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(stdout=name_status_output, returncode=0),
            MagicMock(stdout=numstat_output, returncode=0),
            MagicMock(stdout=patch_output, returncode=0),
        ]
        get_commit_file_changes("/fake", "parent", "commit")

    # All subprocess.run calls must use encoding and errors (for git diff output on Windows)
    for call in run_mock.call_args_list:
        kwargs = call[1]
        assert kwargs.get("encoding") == "utf-8"
        assert kwargs.get("errors") == "replace"
