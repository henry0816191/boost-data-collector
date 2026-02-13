"""Tests for github_ops git_ops (clone, push, fetch_file_content)."""

from unittest.mock import MagicMock, patch

from github_ops.git_ops import (
    _url_with_token,
    clone_repo,
    fetch_file_content,
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
