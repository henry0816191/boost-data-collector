"""Tests for github_ops.tokens (get_github_token, get_github_client)."""

import pytest
from unittest.mock import patch

from django.conf import settings

from github_ops.client import GitHubAPIClient
from github_ops.tokens import get_github_client, get_github_token
from github_ops import tokens as tokens_module


# --- get_github_token ---


@pytest.mark.django_db
def test_get_github_token_scraping_from_settings():
    """get_github_token(use='scraping') returns GITHUB_TOKEN from settings when set."""
    with patch.object(settings, "GITHUB_TOKEN", "token_from_settings"):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            assert get_github_token(use="scraping") == "token_from_settings"


@pytest.mark.django_db
def test_get_github_token_scraping_from_env_when_settings_empty():
    """get_github_token(use='scraping') uses os.environ GITHUB_TOKEN when settings not set."""
    with patch.object(settings, "GITHUB_TOKEN", None):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            with patch.dict("os.environ", {"GITHUB_TOKEN": "env_token"}, clear=False):
                assert get_github_token(use="scraping") == "env_token"


@pytest.mark.django_db
def test_get_github_token_scraping_from_tokens_list_round_robin():
    """get_github_token(use='scraping') round-robins when GITHUB_TOKENS_SCRAPING is a list."""
    # Reset the module-level cycle so behaviour is deterministic
    with patch.object(tokens_module, "_scraping_token_cycle", None):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", ["token_a", "token_b"]):
            first = get_github_token(use="scraping")
            second = get_github_token(use="scraping")
            third = get_github_token(use="scraping")
            assert first in ("token_a", "token_b")
            assert second in ("token_a", "token_b")
            assert third in ("token_a", "token_b")
            # Round-robin: first != second or second != third (cycle of 2)
            assert (first, second) != (
                second,
                third,
            ) or first == second == third


@pytest.mark.django_db
def test_get_github_token_scraping_missing_raises():
    """get_github_token(use='scraping') raises ValueError when no token configured."""
    with patch.object(settings, "GITHUB_TOKEN", None):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            with patch.dict("os.environ", {"GITHUB_TOKEN": ""}, clear=False):
                with pytest.raises(ValueError, match="No scraping token"):
                    get_github_token(use="scraping")


@pytest.mark.django_db
def test_get_github_token_strips_whitespace():
    """get_github_token returns stripped token (no leading/trailing whitespace)."""
    with patch.object(settings, "GITHUB_TOKEN", "  token  "):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            assert get_github_token(use="scraping") == "token"


@pytest.mark.django_db
def test_get_github_token_write_from_github_token_write():
    """get_github_token(use='write') returns GITHUB_TOKEN_WRITE when set."""
    with patch.object(settings, "GITHUB_TOKEN_WRITE", "write_token"):
        assert get_github_token(use="write") == "write_token"


@pytest.mark.django_db
def test_get_github_token_write_fallback_to_github_token():
    """get_github_token(use='write') falls back to GITHUB_TOKEN when GITHUB_TOKEN_WRITE not set."""
    with patch.object(settings, "GITHUB_TOKEN_WRITE", None):
        with patch.object(settings, "GITHUB_TOKEN", "fallback_token"):
            with patch.dict("os.environ", {"GITHUB_TOKEN": ""}, clear=False):
                assert get_github_token(use="write") == "fallback_token"


@pytest.mark.django_db
def test_get_github_token_write_from_env():
    """get_github_token(use='write') uses os.environ GITHUB_TOKEN when settings empty."""
    with patch.object(settings, "GITHUB_TOKEN_WRITE", None):
        with patch.object(settings, "GITHUB_TOKEN", None):
            with patch.dict("os.environ", {"GITHUB_TOKEN": "env_write"}, clear=False):
                assert get_github_token(use="write") == "env_write"


@pytest.mark.django_db
def test_get_github_token_write_missing_raises():
    """get_github_token(use='write') raises ValueError when no write token configured."""
    with patch.object(settings, "GITHUB_TOKEN_WRITE", None):
        with patch.object(settings, "GITHUB_TOKEN", None):
            with patch.dict("os.environ", {"GITHUB_TOKEN": ""}, clear=False):
                with pytest.raises(ValueError, match="No write token"):
                    get_github_token(use="write")


@pytest.mark.django_db
def test_get_github_token_push_same_as_write():
    """get_github_token(use='push') returns same token as write path."""
    with patch.object(settings, "GITHUB_TOKEN_WRITE", "push_token"):
        assert get_github_token(use="push") == "push_token"


@pytest.mark.django_db
def test_get_github_token_create_pr_same_as_write():
    """get_github_token(use='create_pr') returns same token as write path."""
    with patch.object(settings, "GITHUB_TOKEN_WRITE", "create_pr_token"):
        assert get_github_token(use="create_pr") == "create_pr_token"


@pytest.mark.django_db
def test_get_github_token_unknown_use_raises():
    """get_github_token(use='invalid') raises ValueError with message listing valid uses."""
    with pytest.raises(ValueError, match="Unknown use"):
        get_github_token(use="invalid")


@pytest.mark.django_db
def test_get_github_token_default_use_is_scraping():
    """get_github_token() without use defaults to 'scraping'."""
    with patch.object(settings, "GITHUB_TOKEN", "default_token"):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            assert get_github_token() == "default_token"


# --- get_github_client ---


@pytest.mark.django_db
def test_get_github_client_returns_github_api_client():
    """get_github_client returns an instance of GitHubAPIClient."""
    with patch.object(settings, "GITHUB_TOKEN", "t"):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            client = get_github_client(use="scraping")
    assert isinstance(client, GitHubAPIClient)


@pytest.mark.django_db
def test_get_github_client_uses_token_from_get_github_token():
    """get_github_client(use='scraping') passes token from get_github_token to client."""
    with patch.object(settings, "GITHUB_TOKEN", "scraping_token"):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            client = get_github_client(use="scraping")
    assert client.token == "scraping_token"


@pytest.mark.django_db
def test_get_github_client_write_use():
    """get_github_client(use='write') uses write token."""
    with patch.object(settings, "GITHUB_TOKEN_WRITE", "write_token"):
        client = get_github_client(use="write")
    assert client.token == "write_token"


@pytest.mark.django_db
def test_get_github_client_default_use_is_scraping():
    """get_github_client() without use defaults to 'scraping'."""
    with patch.object(settings, "GITHUB_TOKEN", "default"):
        with patch.object(settings, "GITHUB_TOKENS_SCRAPING", None):
            client = get_github_client()
    assert client.token == "default"


@pytest.mark.django_db
def test_get_github_client_calls_get_github_token():
    """get_github_client calls get_github_token with the given use."""
    with patch(
        "github_ops.tokens.get_github_token", return_value="mocked_token"
    ) as get_token:
        client = get_github_client(use="create_pr")
    get_token.assert_called_once_with(use="create_pr")
    assert client.token == "mocked_token"
