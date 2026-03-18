"""Tests for github_ops client and tokens (smoke / no-network where possible)."""

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

from github_ops.client import (
    ConnectionException,
    GitHubAPIClient,
)
from github_ops.tokens import get_github_client, get_github_token


# --- get_github_token ---


def test_import_get_github_token():
    """github_ops.get_github_token is importable."""
    assert callable(get_github_token)


@pytest.mark.django_db
def test_get_github_token_and_client_from_mock_github_token(mock_github_token):
    """With mock_github_token (env set), get_github_token returns env value and get_github_client builds client with it (no network)."""
    with patch.object(settings, "GITHUB_TOKEN", None):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            token = get_github_token(use="scraping")
    assert token == "ghp_test_fake_for_tests"
    with patch.object(settings, "GITHUB_TOKEN", None):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            client = get_github_client(use="scraping")
    assert isinstance(client, GitHubAPIClient)
    assert client.token == "ghp_test_fake_for_tests"


@pytest.mark.django_db
def test_get_github_token_scraping_from_settings():
    """get_github_token(use='scraping') returns GITHUB_TOKEN when set in settings."""
    with patch.object(settings, "GITHUB_TOKEN", "token_from_settings"):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            assert get_github_token(use="scraping") == "token_from_settings"


@pytest.mark.django_db
def test_get_github_token_write_from_settings():
    """get_github_token(use='write') returns GITHUB_TOKEN_WRITE when set."""
    with patch.object(settings, "GITHUB_TOKEN_WRITE", "write_token"):
        assert get_github_token(use="write") == "write_token"


@pytest.mark.django_db
def test_get_github_token_unknown_use_raises():
    """get_github_token(use='invalid') raises ValueError."""
    with pytest.raises(ValueError, match="Unknown use"):
        get_github_token(use="invalid")


@pytest.mark.django_db
def test_get_github_token_scraping_missing_raises():
    """get_github_token(use='scraping') raises when no token configured."""
    with patch.object(settings, "GITHUB_TOKEN", None):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            with patch.dict("os.environ", {"GITHUB_TOKEN": ""}, clear=False):
                with pytest.raises(ValueError, match="No scraping token"):
                    get_github_token(use="scraping")


# --- get_github_client ---


def test_import_get_github_client():
    """github_ops.get_github_client is importable."""
    assert callable(get_github_client)


@pytest.mark.django_db
def test_get_github_client_returns_client_with_scraping_token():
    """get_github_client(use='scraping') returns GitHubAPIClient with token from settings."""
    with patch.object(settings, "GITHUB_TOKEN", "scraping_token"):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            client = get_github_client(use="scraping")
    assert isinstance(client, GitHubAPIClient)
    assert client.token == "scraping_token"


@pytest.mark.django_db
def test_get_github_client_returns_client_with_write_token():
    """get_github_client(use='write') returns GitHubAPIClient with write token."""
    with patch.object(settings, "GITHUB_TOKEN_WRITE", "write_token"):
        client = get_github_client(use="write")
    assert isinstance(client, GitHubAPIClient)
    assert client.token == "write_token"


@pytest.mark.django_db
def test_get_github_client_create_pr_uses_write_token():
    """get_github_client(use='create_pr') uses same token as write."""
    with patch.object(settings, "GITHUB_TOKEN_WRITE", "create_pr_token"):
        client = get_github_client(use="create_pr")
    assert client.token == "create_pr_token"


# --- GitHubAPIClient.__init__ ---


def test_client_init_sets_token_and_urls():
    """GitHubAPIClient.__init__ sets token, rest_base_url, graphql_url."""
    c = GitHubAPIClient("my_token")
    assert c.token == "my_token"
    assert c.rest_base_url == "https://api.github.com"
    assert c.graphql_url == "https://api.github.com/graphql"


def test_client_init_session_has_auth_header():
    """GitHubAPIClient session includes Authorization header."""
    c = GitHubAPIClient("secret")
    assert "Authorization" in c.session.headers
    assert "secret" in c.session.headers["Authorization"]


def test_client_init_default_retry_settings():
    """GitHubAPIClient has default max_retries and retry_delay."""
    c = GitHubAPIClient("t")
    assert c.max_retries == 3
    assert c.retry_delay == 1


# --- rest_request ---


def _make_resp(status_code=200, json_data=None, headers=None):
    """Build a MagicMock response for use with session.request mocks."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json = MagicMock(return_value=json_data if json_data is not None else {})
    resp.raise_for_status = MagicMock()
    return resp


def test_rest_request_success_returns_json():
    """rest_request returns JSON when GET returns 200."""
    client = GitHubAPIClient("token")
    client.session.request = MagicMock(return_value=_make_resp(200, {"id": 1}))
    out = client.rest_request("/repos/foo/bar")
    assert out == {"id": 1}
    client.session.request.assert_called_once()
    assert client.session.request.call_args[0][0] == "GET"


def test_rest_request_updates_rate_limit_headers():
    """rest_request updates rate_limit_remaining and rate_limit_reset_time from headers."""
    client = GitHubAPIClient("token")
    client.session.request = MagicMock(
        return_value=_make_resp(
            200,
            {},
            {"X-RateLimit-Remaining": "99", "X-RateLimit-Reset": "12345"},
        )
    )
    client.rest_request("/repos/foo/bar")
    assert client.rate_limit_remaining == 99
    assert client.rate_limit_reset_time == 12345


def test_rest_request_connection_error_after_retries_raises():
    """rest_request raises ConnectionException after max retries on connection error."""
    from requests.exceptions import ConnectionError as ReqConnectionError

    client = GitHubAPIClient("token")
    client.session.request = MagicMock(side_effect=ReqConnectionError("network down"))
    with pytest.raises(ConnectionException, match="retries"):
        client.rest_request("/repos/foo/bar")


def test_rest_request_retries_on_502_then_succeeds():
    """rest_request retries on 502/503/504 and returns JSON when a later attempt succeeds."""
    client = GitHubAPIClient("token")
    resp_502 = _make_resp(502)
    resp_200 = _make_resp(200, {"id": 1})
    client.session.request = MagicMock(side_effect=[resp_502, resp_200])
    with patch("github_ops.client.time.sleep"):
        out = client.rest_request("/repos/foo/bar")
    assert out == {"id": 1}
    assert client.session.request.call_count == 2


def test_rest_request_502_after_max_retries_raises():
    """rest_request raises after max retries when all attempts return 502."""
    import requests as req

    client = GitHubAPIClient("token")
    client.max_retries = 2
    resp_502 = _make_resp(502)
    resp_502.raise_for_status = MagicMock(
        side_effect=req.exceptions.HTTPError("Bad Gateway", response=resp_502)
    )
    client.session.request = MagicMock(return_value=resp_502)
    with patch("github_ops.client.time.sleep"):
        with pytest.raises(req.exceptions.HTTPError):
            client.rest_request("/repos/foo/bar")
    assert client.session.request.call_count == 2


# --- rest_request_conditional ---


def test_rest_request_conditional_200_returns_data_and_etag():
    """rest_request_conditional returns (data, response_etag) when GET returns 200."""
    client = GitHubAPIClient("token")
    client.session.request = MagicMock(
        return_value=_make_resp(
            200,
            {"items": [1, 2]},
            {"ETag": 'W/"abc123"'},
        )
    )
    data, etag = client.rest_request_conditional("/repos/foo/bar/commits", etag=None)
    assert data == {"items": [1, 2]}
    assert etag == 'W/"abc123"'


def test_rest_request_conditional_304_returns_none_and_etag():
    """rest_request_conditional returns (None, etag) when GET returns 304."""
    client = GitHubAPIClient("token")
    client.session.request = MagicMock(return_value=_make_resp(304, None, {}))
    data, etag = client.rest_request_conditional(
        "/repos/foo/bar/commits", etag='W/"cached"'
    )
    assert data is None
    assert etag == 'W/"cached"'


def test_rest_request_conditional_sends_if_none_match_when_etag_provided():
    """rest_request_conditional sends If-None-Match header when etag is provided."""
    client = GitHubAPIClient("token")
    client.session.request = MagicMock(
        return_value=_make_resp(200, {}, {"ETag": "new"})
    )
    client.rest_request_conditional("/repos/x/y/commits", etag='W/"old"')
    call_kwargs = client.session.request.call_args[1]
    assert "headers" in call_kwargs
    assert call_kwargs["headers"]["If-None-Match"] == 'W/"old"'


def test_rest_request_conditional_no_etag_behaves_like_normal_get():
    """rest_request_conditional with etag=None returns (data, response_etag) on 200."""
    client = GitHubAPIClient("token")
    client.session.request = MagicMock(
        return_value=_make_resp(200, {"data": 1}, {"ETag": "xyz"})
    )
    data, response_etag = client.rest_request_conditional("/repos/a/b/issues")
    assert data == {"data": 1}
    assert response_etag == "xyz"
    call_kwargs = client.session.request.call_args[1]
    assert call_kwargs.get("headers") is None or "If-None-Match" not in (
        call_kwargs.get("headers") or {}
    )


# --- rest_post ---


def test_rest_post_success_returns_json():
    """rest_post returns JSON when POST returns 200."""
    client = GitHubAPIClient("token")
    client.session.request = MagicMock(return_value=_make_resp(200, {"number": 42}))
    out = client.rest_post("/repos/foo/bar/issues", json_data={"title": "Hi"})
    assert out == {"number": 42}


def test_rest_post_sends_json_data():
    """rest_post sends given json_data in request body."""
    client = GitHubAPIClient("token")
    post_mock = MagicMock(return_value=_make_resp(200, {}))
    client.session.request = post_mock
    client.rest_post("/repos/a/b/issues", json_data={"title": "T", "body": "B"})
    post_mock.assert_called_once()
    call_kw = post_mock.call_args[1]
    assert call_kw["json"] == {"title": "T", "body": "B"}
    assert post_mock.call_args[0][0] == "POST"


def test_rest_post_connection_error_raises_without_retry():
    """rest_post raises ConnectionException immediately on connection error (no retries for mutating methods)."""
    from requests.exceptions import ConnectionError as ReqConnectionError

    client = GitHubAPIClient("token")
    client.session.request = MagicMock(side_effect=ReqConnectionError("fail"))
    with pytest.raises(ConnectionException):
        client.rest_post("/repos/foo/bar/issues", json_data={"title": "x"})
    assert client.session.request.call_count == 1


# --- get_file_content ---


def test_get_file_content_returns_decoded_bytes_and_encoding():
    """get_file_content returns (decoded_bytes, encoding) for valid file."""
    import base64

    client = GitHubAPIClient("token")
    client.rest_request = MagicMock(
        return_value={
            "content": base64.b64encode(b"hello").decode("ascii"),
            "encoding": "base64",
        }
    )
    content, enc = client.get_file_content("o", "r", "path/file.txt")
    assert content == b"hello"
    assert enc == "base64"


def test_get_file_content_directory_raises_value_error():
    """get_file_content raises ValueError when path is a directory (API returns list)."""
    client = GitHubAPIClient("token")
    client.rest_request = MagicMock(return_value=[{"name": "subdir"}])
    with pytest.raises(ValueError, match="directory, not a file"):
        client.get_file_content("o", "r", "path/")


def test_get_file_content_empty_content_returns_empty_bytes():
    """get_file_content returns (b'', enc) when content is missing."""
    client = GitHubAPIClient("token")
    client.rest_request = MagicMock(return_value={"encoding": "base64"})
    content, enc = client.get_file_content("o", "r", "empty.txt")
    assert content == b""
    assert enc == "base64"


def test_get_file_content_passes_ref_as_param():
    """get_file_content passes ref to rest_request when provided."""
    client = GitHubAPIClient("token")
    client.rest_request = MagicMock(return_value={"content": "", "encoding": None})
    client.get_file_content("o", "r", "f", ref="main")
    client.rest_request.assert_called_once()
    assert client.rest_request.call_args[1]["params"] == {"ref": "main"}


# --- create_pull_request ---


def test_create_pull_request_calls_rest_post_with_correct_endpoint():
    """create_pull_request calls rest_post with /repos/owner/repo/pulls."""
    client = GitHubAPIClient("token")
    client.rest_post = MagicMock(return_value={"number": 1})
    client.create_pull_request("o", "r", "Title", "head", "base", body="Body")
    client.rest_post.assert_called_once()
    assert "/repos/o/r/pulls" in client.rest_post.call_args[0][0]


def test_create_pull_request_sends_title_head_base_body():
    """create_pull_request sends title, head, base, body in json_data."""
    client = GitHubAPIClient("token")
    client.rest_post = MagicMock(return_value={})
    client.create_pull_request(
        "owner", "repo", "PR Title", "feature", "main", body="Desc"
    )
    call_kw = client.rest_post.call_args[1]
    assert call_kw["json_data"]["title"] == "PR Title"
    assert call_kw["json_data"]["head"] == "feature"
    assert call_kw["json_data"]["base"] == "main"
    assert call_kw["json_data"]["body"] == "Desc"


def test_create_pull_request_returns_rest_post_response():
    """create_pull_request returns the dict returned by rest_post."""
    client = GitHubAPIClient("token")
    client.rest_post = MagicMock(return_value={"number": 42, "html_url": "https://..."})
    out = client.create_pull_request("o", "r", "T", "h", "b")
    assert out["number"] == 42
    assert out["html_url"] == "https://..."


# --- create_issue ---


def test_create_issue_calls_rest_post_with_correct_endpoint():
    """create_issue calls rest_post with /repos/owner/repo/issues."""
    client = GitHubAPIClient("token")
    client.rest_post = MagicMock(return_value={"number": 1})
    client.create_issue("o", "r", "Issue Title", body="Body")
    client.rest_post.assert_called_once()
    assert "/repos/o/r/issues" in client.rest_post.call_args[0][0]


def test_create_issue_sends_title_and_body():
    """create_issue sends title and body in json_data."""
    client = GitHubAPIClient("token")
    client.rest_post = MagicMock(return_value={})
    client.create_issue("owner", "repo", "Title", body="Body text")
    call_kw = client.rest_post.call_args[1]
    assert call_kw["json_data"]["title"] == "Title"
    assert call_kw["json_data"]["body"] == "Body text"


def test_create_issue_empty_body_default():
    """create_issue sends empty string body when body not provided."""
    client = GitHubAPIClient("token")
    client.rest_post = MagicMock(return_value={})
    client.create_issue("o", "r", "Title")
    assert client.rest_post.call_args[1]["json_data"]["body"] == ""


# --- create_issue_comment ---


def test_create_issue_comment_calls_rest_post_with_correct_endpoint():
    """create_issue_comment calls rest_post with .../issues/{number}/comments."""
    client = GitHubAPIClient("token")
    client.rest_post = MagicMock(return_value={"id": 1})
    client.create_issue_comment("o", "r", 123, "Comment body")
    client.rest_post.assert_called_once()
    assert "/repos/o/r/issues/123/comments" in client.rest_post.call_args[0][0]


def test_create_issue_comment_sends_body():
    """create_issue_comment sends body in json_data."""
    client = GitHubAPIClient("token")
    client.rest_post = MagicMock(return_value={})
    client.create_issue_comment("o", "r", 5, "My comment")
    assert client.rest_post.call_args[1]["json_data"]["body"] == "My comment"


def test_create_issue_comment_returns_rest_post_response():
    """create_issue_comment returns the dict returned by rest_post."""
    client = GitHubAPIClient("token")
    client.rest_post = MagicMock(return_value={"id": 999})
    out = client.create_issue_comment("o", "r", 1, "x")
    assert out == {"id": 999}


# --- graphql_request ---


def test_graphql_request_success_returns_data():
    """graphql_request returns data when response has no errors."""
    client = GitHubAPIClient("token")
    client.session.request = MagicMock(
        return_value=_make_resp(200, {"data": {"repository": {"name": "r"}}})
    )
    out = client.graphql_request("query { x }")
    assert out["data"]["repository"]["name"] == "r"


def test_graphql_request_errors_in_response_raises():
    """graphql_request raises Exception when response contains 'errors'."""
    client = GitHubAPIClient("token")
    client.session.request = MagicMock(
        return_value=_make_resp(
            200,
            {"errors": [{"message": "Something went wrong"}]},
        )
    )
    with pytest.raises(Exception, match="GraphQL errors"):
        client.graphql_request("query { x }")


def test_graphql_request_sends_query_and_variables():
    """graphql_request sends query and optional variables in payload."""
    client = GitHubAPIClient("token")
    post_mock = MagicMock(return_value=_make_resp(200, {"data": {}}))
    client.session.request = post_mock
    client.graphql_request("query Q($x: Int) { f(x: $x) }", variables={"x": 1})
    call_kw = post_mock.call_args[1]
    assert call_kw["json"]["query"] == "query Q($x: Int) { f(x: $x) }"
    assert call_kw["json"]["variables"] == {"x": 1}
    assert post_mock.call_args[0][0] == "POST"


def test_graphql_request_connection_error_retries_then_raises():
    """graphql_request retries on connection error, then raises ConnectionException after retries exhausted."""
    from requests.exceptions import ConnectionError as ReqConnectionError

    client = GitHubAPIClient("token")
    client.session.request = MagicMock(side_effect=ReqConnectionError("fail"))
    with patch("github_ops.client.time.sleep"), pytest.raises(ConnectionException):
        client.graphql_request("query { x }")
    assert client.session.request.call_count == client.max_retries


# --- get_repository_info ---


def test_get_repository_info_calls_rest_request_with_repos_path():
    """get_repository_info calls rest_request with /repos/owner/repo."""
    client = GitHubAPIClient("token")
    client.rest_request = MagicMock(return_value={"full_name": "owner/repo"})
    client.get_repository_info("owner", "repo")
    client.rest_request.assert_called_once_with("/repos/owner/repo")


def test_get_repository_info_returns_rest_request_response():
    """get_repository_info returns the dict from rest_request."""
    client = GitHubAPIClient("token")
    client.rest_request = MagicMock(return_value={"id": 1, "name": "repo"})
    out = client.get_repository_info("o", "r")
    assert out == {"id": 1, "name": "repo"}


def test_get_repository_info_passes_owner_repo_in_path():
    """get_repository_info builds path with given owner and repo."""
    client = GitHubAPIClient("token")
    client.rest_request = MagicMock(return_value={})
    client.get_repository_info("boostorg", "boost")
    assert client.rest_request.call_args[0][0] == "/repos/boostorg/boost"


# --- get_submodules_from_file ---


def test_get_submodules_from_file_not_found_returns_empty_list(tmp_path):
    """get_submodules_from_file returns [] when file does not exist."""
    client = GitHubAPIClient("token")
    out = client.get_submodules_from_file(str(tmp_path / "nonexistent.gitmodules"))
    assert out == []


def test_get_submodules_from_file_valid_returns_parsed_list(tmp_path):
    """get_submodules_from_file returns parsed submodules from valid .gitmodules."""
    f = tmp_path / ".gitmodules"
    f.write_text('[submodule "libs/foo"]\n' "path = libs/foo\n" "url = ../foo.git\n")
    client = GitHubAPIClient("token")
    out = client.get_submodules_from_file(str(f), default_owner="boostorg")
    assert len(out) == 1
    assert "repo_name" in out[0]
    assert "repo_url" in out[0]
    assert "boostorg" in out[0].get("repo_url", "") or out[0].get("owner") == "boostorg"


def test_get_submodules_from_file_empty_file_returns_empty_list(tmp_path):
    """get_submodules_from_file returns [] for empty or comment-only file."""
    f = tmp_path / ".gitmodules"
    f.write_text("# comment only\n\n")
    client = GitHubAPIClient("token")
    out = client.get_submodules_from_file(str(f))
    assert out == []


# --- _parse_gitmodules ---


def test_parse_gitmodules_empty_returns_empty_list():
    """_parse_gitmodules returns [] for empty content."""
    client = GitHubAPIClient("token")
    out = client._parse_gitmodules("")
    assert out == []


def test_parse_gitmodules_single_submodule():
    """_parse_gitmodules parses one submodule with url and repo_name."""
    client = GitHubAPIClient("token")
    content = '[submodule "libs/x"]\npath = libs/x\nurl = ../x.git\n'
    out = client._parse_gitmodules(content, default_owner="boostorg")
    assert len(out) == 1
    assert out[0]["repo_name"] == "x" or "x" in out[0]["repo_name"]
    assert "boostorg" in out[0]["repo_url"] or out[0].get("owner") == "boostorg"


def test_parse_gitmodules_multiple_submodules():
    """_parse_gitmodules parses multiple submodules."""
    client = GitHubAPIClient("token")
    content = (
        '[submodule "a"]\npath = a\nurl = ../a.git\n'
        '[submodule "b"]\npath = b\nurl = ../b.git\n'
    )
    out = client._parse_gitmodules(content, default_owner="boostorg")
    assert len(out) == 2


def test_parse_gitmodules_skips_comments_and_blank_lines():
    """_parse_gitmodules ignores # comments and blank lines."""
    client = GitHubAPIClient("token")
    content = '# comment\n\n[submodule "x"]\nurl = ../x.git\n'
    out = client._parse_gitmodules(content)
    assert len(out) == 1


# --- get_submodules ---


def test_get_submodules_with_local_file_uses_file(tmp_path):
    """get_submodules with local_file uses file content when file exists and has submodules."""
    f = tmp_path / ".gitmodules"
    f.write_text('[submodule "x"]\npath = x\nurl = ../x.git\n')
    client = GitHubAPIClient("token")
    client.rest_request = MagicMock()
    out = client.get_submodules("owner", "repo", local_file=str(f))
    assert len(out) >= 1
    client.rest_request.assert_not_called()


def test_get_submodules_with_local_file_empty_falls_back_to_api(tmp_path):
    """get_submodules with local_file that has no submodules falls back to API."""
    f = tmp_path / ".gitmodules"
    f.write_text("# empty\n")
    client = GitHubAPIClient("token")
    client.rest_request = MagicMock(return_value={"type": "file", "content": ""})
    out = client.get_submodules("owner", "repo", local_file=str(f))
    assert isinstance(out, list)
    client.rest_request.assert_called_once_with(
        "/repos/owner/repo/contents/.gitmodules"
    )


def test_get_submodules_from_api_returns_parsed_list():
    """get_submodules without local_file fetches .gitmodules via API and parses it."""
    import base64

    client = GitHubAPIClient("token")
    content_b64 = base64.b64encode(
        b'[submodule "x"]\npath = x\nurl = ../x.git\n'
    ).decode("ascii")
    client.rest_request = MagicMock(
        return_value={
            "type": "file",
            "content": content_b64,
        }
    )
    out = client.get_submodules("owner", "repo")
    assert len(out) == 1
    client.rest_request.assert_called_with("/repos/owner/repo/contents/.gitmodules")


def test_get_submodules_api_404_returns_empty_list():
    """get_submodules returns [] when .gitmodules is 404."""
    import requests

    client = GitHubAPIClient("token")
    err = requests.exceptions.HTTPError()
    err.response = MagicMock()
    err.response.status_code = 404
    client.rest_request = MagicMock(side_effect=err)
    out = client.get_submodules("owner", "repo")
    assert out == []
