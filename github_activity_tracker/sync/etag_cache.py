"""
ETag cache for GitHub list endpoints (commits, issues, pulls).
Stores only ETag strings; used for conditional GET (If-None-Match).
Uses Redis. Enable Redis persistence (RDB or AOF) in your Redis server so the cache survives restarts.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

KEY_PREFIX = "github_etag"
# Optional TTL in seconds (default 7 days) to limit key growth
DEFAULT_TTL = 7 * 24 * 3600

# Module-level cache: avoid repeated Redis probes during bulk sync.
_CACHED_REDIS_CLIENT = None
_REDIS_CLIENT_CHECKED_AT = 0.0
# Re-check Redis availability after this many seconds if last check failed.
_REDIS_RETRY_INTERVAL_SEC = 60.0


def _redis_client():
    """Return Redis client or None if unavailable. Memoized at module scope."""
    global _CACHED_REDIS_CLIENT, _REDIS_CLIENT_CHECKED_AT

    # Return cached client if already connected.
    if _CACHED_REDIS_CLIENT is not None:
        return _CACHED_REDIS_CLIENT

    # If we recently checked and failed, don't retry yet (avoid repeated 5s timeouts).
    now = time.time()
    if (
        _REDIS_CLIENT_CHECKED_AT > 0
        and (now - _REDIS_CLIENT_CHECKED_AT) < _REDIS_RETRY_INTERVAL_SEC
    ):
        return None

    _REDIS_CLIENT_CHECKED_AT = now
    try:
        import redis

        url = getattr(settings, "GITHUB_ETAG_REDIS_URL", "redis://localhost:6379/1")
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.ping()
        _CACHED_REDIS_CLIENT = client
        logger.info("ETag cache Redis connected.")
        return client
    except Exception as e:
        logger.debug("ETag cache Redis unavailable: %s", e)
        return None


class RedisListETagCache:
    """Cache adapter for list ETags: get/set by repo_id, list_type, page, since_iso, until_iso."""

    def __init__(self, repo_id: int, ttl: Optional[int] = DEFAULT_TTL):
        self.repo_id = repo_id
        self.ttl = ttl
        self._client = _redis_client()

    def _key(
        self,
        list_type: str,
        page: int,
        since_iso: str = "",
        until_iso: str = "",
    ) -> str:
        return f"{KEY_PREFIX}:{self.repo_id}:{list_type}:{page}:{since_iso}:{until_iso}"

    def get(
        self,
        list_type: str,
        page: int,
        since_iso: str = "",
        until_iso: str = "",
    ) -> Optional[str]:
        """Return stored ETag or None."""
        if self._client is None:
            return None
        try:
            key = self._key(list_type, page, since_iso, until_iso)
            value = self._client.get(key)
            return value if value else None
        except Exception as e:
            logger.debug("ETag cache get failed: %s", e)
            return None

    def set(
        self,
        list_type: str,
        page: int,
        since_iso: str,
        until_iso: str,
        etag: str,
    ) -> None:
        """Store ETag. No-op if Redis unavailable or etag empty."""
        if not etag or self._client is None:
            return
        try:
            key = self._key(list_type, page, since_iso, until_iso)
            if self.ttl is not None:
                self._client.setex(key, self.ttl, etag)
            else:
                self._client.set(key, etag)
        except Exception as e:
            logger.debug("ETag cache set failed: %s", e)
