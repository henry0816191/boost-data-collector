"""Tests for github_activity_tracker.sync.etag_cache."""

from unittest.mock import MagicMock, patch

from github_activity_tracker.sync.etag_cache import (
    RedisListETagCache,
    KEY_PREFIX,
)


def test_redis_list_etag_cache_key_format():
    """RedisListETagCache builds key with repo_id, list_type, page, since_iso, until_iso."""
    with patch(
        "github_activity_tracker.sync.etag_cache._redis_client", return_value=None
    ):
        cache = RedisListETagCache(repo_id=42)
    assert cache._client is None
    key = cache._key("commits", 1, "2024-01-01", "2024-12-31")
    assert key == f"{KEY_PREFIX}:42:commits:1:2024-01-01:2024-12-31"


def test_redis_list_etag_cache_get_returns_none_when_client_none():
    """When Redis client is unavailable, get returns None."""
    with patch(
        "github_activity_tracker.sync.etag_cache._redis_client", return_value=None
    ):
        cache = RedisListETagCache(repo_id=1)
    assert cache.get("commits", 1) is None
    assert cache.get("issues", 2, "2024-01-01", "") is None


def test_redis_list_etag_cache_set_no_op_when_client_none():
    """When Redis client is unavailable, set is a no-op."""
    with patch(
        "github_activity_tracker.sync.etag_cache._redis_client", return_value=None
    ):
        cache = RedisListETagCache(repo_id=1)
    cache.set("commits", 1, "", "", 'W/"etag"')
    # No exception, no-op


def test_redis_list_etag_cache_set_no_op_when_etag_empty():
    """When etag is empty, set is a no-op."""
    with patch("github_activity_tracker.sync.etag_cache._redis_client") as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value = mock_client
        cache = RedisListETagCache(repo_id=1)
    cache.set("commits", 1, "", "", "")
    mock_client.setex.assert_not_called()


@patch("github_activity_tracker.sync.etag_cache._redis_client")
def test_redis_list_etag_cache_get_set_use_client(mock_redis_client):
    """When Redis client is available, get and set use it."""
    mock_client = MagicMock()
    mock_client.get.return_value = 'W/"stored"'
    mock_redis_client.return_value = mock_client

    cache = RedisListETagCache(repo_id=10)
    assert cache._client is mock_client

    out = cache.get("pulls", 3, "", "")
    assert out == 'W/"stored"'
    mock_client.get.assert_called_once()
    call_key = mock_client.get.call_args[0][0]
    assert call_key == f"{KEY_PREFIX}:10:pulls:3::"

    cache.set("pulls", 3, "", "", "W/new")
    mock_client.setex.assert_called_once()
    args = mock_client.setex.call_args[0]
    assert args[0] == f"{KEY_PREFIX}:10:pulls:3::"
    assert args[1] == cache.ttl
    assert args[2] == "W/new"
