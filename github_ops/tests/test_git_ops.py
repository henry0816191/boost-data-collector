"""Tests for github_ops git_ops (clone, push, pull, fetch_file_content, upload_folder_to_github)."""

from unittest.mock import MagicMock, patch

import requests

from github_ops.git_ops import (
    _create_blob_with_retry,
    _url_with_token,
    clone_repo,
    fetch_file_content,
    pull,
    get_commit_file_changes,
    push,
    upload_folder_to_github,
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
    """push with branch runs git add, git commit, get-url, then git push <url> <branch>."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # add
            MagicMock(returncode=0, stdout="", stderr=""),  # commit
            MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),  # get-url
            MagicMock(),
        ]
        push(tmp_path, "origin", branch="main", token="t")
    assert run_mock.call_count == 4
    push_call = run_mock.call_args_list[3][0][0]
    assert "push" in push_call
    assert "main" in push_call


def test_push_without_branch_does_not_append_branch(tmp_path):
    """push without branch runs git add, git commit, get-url, then git push <url> only."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),
            MagicMock(),
        ]
        push(tmp_path, "origin", token="t")
    push_call = run_mock.call_args_list[3][0][0]
    assert "push" in push_call
    assert push_call[-1] != "main"


def test_push_injects_token_into_push_url(tmp_path):
    """push uses _url_with_token so push URL contains token."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(stdout="https://github.com/owner/repo.git\n", stderr=""),
            MagicMock(),
        ]
        push(tmp_path, "origin", token="secret_token")
    push_call = run_mock.call_args_list[3][0][0]
    push_url = push_call[push_call.index("push") + 1]
    assert "secret_token" in push_url


def test_push_uses_get_github_token_when_token_not_provided(tmp_path):
    """push calls get_github_token(use='push') when token is None."""
    with patch(
        "github_ops.git_ops.get_github_token", return_value="push_token"
    ) as get_token:
        with patch("github_ops.git_ops.subprocess.run") as run_mock:
            run_mock.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),
                MagicMock(),
            ]
            push(tmp_path, "origin")
    get_token.assert_called_once_with(use="push")


def test_push_with_commit_message_runs_add_then_commit_then_push(tmp_path):
    """push with commit_message runs git add, git commit, then get-url and push."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # add
            MagicMock(returncode=0, stdout="", stderr=""),  # commit
            MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),  # get-url
            MagicMock(),  # push
        ]
        push(
            tmp_path,
            "origin",
            branch="main",
            commit_message="Update files",
            token="t",
        )
    assert run_mock.call_count == 4
    add_call = run_mock.call_args_list[0][0][0]
    assert "git" in add_call and "add" in add_call and str(tmp_path) in add_call
    commit_call = run_mock.call_args_list[1][0][0]
    assert "commit" in commit_call and "-m" in commit_call
    assert "Update files" in commit_call
    push_call = run_mock.call_args_list[3][0][0]
    assert "push" in push_call


def test_push_with_commit_message_and_add_paths_passes_paths_to_add(tmp_path):
    """push with commit_message and add_paths runs git add with those paths."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),
            MagicMock(),
        ]
        push(
            tmp_path,
            "origin",
            commit_message="Add report",
            add_paths=["data/report.html", "index.html"],
            token="t",
        )
    add_call = run_mock.call_args_list[0][0][0]
    assert "add" in add_call
    assert "data/report.html" in add_call or "data\\report.html" in add_call
    assert "index.html" in add_call


def test_push_nothing_to_commit_does_not_raise_and_still_pushes(tmp_path):
    """When git commit returns 'nothing to commit', push does not raise and still pushes."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # add
            MagicMock(
                returncode=1,
                stdout="",
                stderr="On branch main\nnothing to commit, working tree clean",
            ),  # commit
            MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),  # get-url
            MagicMock(),  # push
        ]
        push(
            tmp_path,
            "origin",
            branch="main",
            commit_message="Update",
            token="t",
        )
    assert run_mock.call_count == 4
    push_call = run_mock.call_args_list[3][0][0]
    assert "push" in push_call


def test_push_commit_failure_without_nothing_to_commit_raises(tmp_path):
    """When git commit fails and stderr does not contain 'nothing to commit', push raises."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="fatal: some error"),
            MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),
            MagicMock(),
        ]
        try:
            push(
                tmp_path,
                "origin",
                commit_message="Update",
                token="t",
            )
        except Exception as e:
            assert "Process" in type(e).__name__ or "Error" in type(e).__name__
            return
    assert False, "push should have raised on commit failure"


# --- pull ---


def test_pull_with_branch_runs_checkout_then_pull(tmp_path):
    """pull with branch runs git checkout <branch> then git pull <url> <branch>."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(),
            MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),
            MagicMock(),
        ]
        pull(tmp_path, branch="main", token="t")
    assert run_mock.call_count == 3
    calls = [c[0][0] for c in run_mock.call_args_list]
    assert "checkout" in calls[0]
    assert calls[0][-1] == "main"
    assert "pull" in calls[2]
    assert "main" in calls[2]


def test_pull_without_branch_does_not_run_checkout(tmp_path):
    """pull without branch does not run git checkout."""
    with patch("github_ops.git_ops.subprocess.run") as run_mock:
        run_mock.side_effect = [
            MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),
            MagicMock(),
        ]
        pull(tmp_path, token="t")
    calls = [c[0][0] for c in run_mock.call_args_list]
    checkout_calls = [c for c in calls if "checkout" in c]
    assert len(checkout_calls) == 0


def test_pull_uses_get_github_token_when_token_not_provided(tmp_path):
    """pull calls get_github_token(use='push') when token is None."""
    with patch(
        "github_ops.git_ops.get_github_token", return_value="push_tok"
    ) as get_token:
        with patch("github_ops.git_ops.subprocess.run") as run_mock:
            run_mock.side_effect = [
                MagicMock(),
                MagicMock(stdout="https://github.com/o/r.git\n", stderr=""),
                MagicMock(),
            ]
            pull(tmp_path, branch="main")
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


# --- upload_folder_to_github ---


def test_upload_folder_to_github_not_directory_returns_failure():
    """upload_folder_to_github returns success=False when path is not a directory."""
    result = upload_folder_to_github(
        "/nonexistent/path", "owner", "repo", client=MagicMock()
    )
    assert result["success"] is False
    assert "Not a directory" in result["message"]


def test_upload_folder_to_github_calls_create_blob_per_file(tmp_path):
    """upload_folder_to_github invokes _create_blob_with_retry once per file (parallel)."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_bytes(b"c")
    blob_calls = []

    def capture_blob(_base, _token, repo_path, local_path):
        blob_calls.append((repo_path, local_path))
        return (repo_path, "sha_" + repo_path.replace("/", "_"))

    mock_session = MagicMock()
    mock_session.get.side_effect = [
        MagicMock(status_code=200, json=lambda: {"object": {"sha": "commit_sha"}}),
        MagicMock(status_code=200, json=lambda: {"tree": {"sha": "base_tree_sha"}}),
    ]
    mock_session.post.side_effect = [
        MagicMock(status_code=201, json=lambda: {"sha": "new_tree_sha"}),
        MagicMock(status_code=201, json=lambda: {"sha": "new_commit_sha"}),
    ]
    mock_session.patch.return_value = MagicMock(status_code=200)

    mock_client = MagicMock()
    mock_client.rest_base_url = "https://api.github.com"
    mock_client.token = "token"
    mock_client.session = mock_session

    with patch("github_ops.git_ops._create_blob_with_retry", side_effect=capture_blob):
        result = upload_folder_to_github(
            tmp_path, "owner", "repo", branch="main", client=mock_client
        )
    assert result["success"] is True
    assert len(blob_calls) == 3
    paths = {c[0] for c in blob_calls}
    assert paths == {"a.txt", "b.txt", "sub/c.txt"}


def test_upload_folder_to_github_retries_on_403_then_succeeds(tmp_path):
    """upload_folder_to_github retries blob creation on 403 and succeeds on retry."""
    (tmp_path / "single.txt").write_text("content")
    mock_403 = MagicMock()
    mock_403.status_code = 403
    mock_403.headers = {"Retry-After": "1"}
    mock_403.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "403", response=mock_403
    )
    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {"sha": "blob_sha_after_retry"}
    mock_200.raise_for_status = MagicMock()

    mock_main_session = MagicMock()
    mock_main_session.get.side_effect = [
        MagicMock(status_code=200, json=lambda: {"object": {"sha": "commit_sha"}}),
        MagicMock(status_code=200, json=lambda: {"tree": {"sha": "base_tree_sha"}}),
    ]
    mock_main_session.post.side_effect = [
        MagicMock(status_code=201, json=lambda: {"sha": "new_tree_sha"}),
        MagicMock(status_code=201, json=lambda: {"sha": "new_commit_sha"}),
    ]
    mock_main_session.patch.return_value = MagicMock(status_code=200)

    mock_worker_session = MagicMock()
    mock_worker_session.post.side_effect = [mock_403, mock_200]

    mock_client = MagicMock()
    mock_client.rest_base_url = "https://api.github.com"
    mock_client.token = "token"
    mock_client.session = mock_main_session

    with patch(
        "github_ops.git_ops._get_worker_session",
        return_value=mock_worker_session,
    ):
        with patch("github_ops.git_ops.time.sleep"):
            result = upload_folder_to_github(
                tmp_path, "owner", "repo", branch="main", client=mock_client
            )
    assert result["success"] is True
    assert mock_worker_session.post.call_count == 2


def test_upload_folder_to_github_returns_success_with_mock_client(tmp_path):
    """upload_folder_to_github returns success True when all API calls succeed."""
    (tmp_path / "f.txt").write_text("data")
    mock_session = MagicMock()
    mock_session.get.side_effect = [
        MagicMock(status_code=200, json=lambda: {"object": {"sha": "c1"}}),
        MagicMock(status_code=200, json=lambda: {"tree": {"sha": "t1"}}),
    ]
    mock_session.post.side_effect = [
        MagicMock(status_code=201, json=lambda: {"sha": "tree2"}),
        MagicMock(status_code=201, json=lambda: {"sha": "c2"}),
    ]
    mock_session.patch.return_value = MagicMock(status_code=200)
    mock_client = MagicMock()
    mock_client.rest_base_url = "https://api.github.com"
    mock_client.token = "t"
    mock_client.session = mock_session
    with patch(
        "github_ops.git_ops._create_blob_with_retry",
        return_value=("f.txt", "blob_sha"),
    ):
        result = upload_folder_to_github(
            tmp_path,
            "owner",
            "repo",
            commit_message="Upload",
            client=mock_client,
        )
    assert result["success"] is True
    assert "Uploaded" in result["message"]


# --- _create_blob_with_retry ---


def test_create_blob_with_retry_returns_sha_on_success():
    """_create_blob_with_retry returns (repo_path, sha) when POST returns 200."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"sha": "abc123"}
    mock_resp.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    mock_path = MagicMock()
    mock_path.read_bytes.return_value = b"content"
    with patch("github_ops.git_ops._get_worker_session", return_value=mock_session):
        out = _create_blob_with_retry(
            "https://api.github.com/repos/o/r",
            "token",
            "path/file.txt",
            mock_path,
        )
    assert out == ("path/file.txt", "abc123")
    mock_path.read_bytes.assert_called_once()
    mock_session.post.assert_called_once()


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
