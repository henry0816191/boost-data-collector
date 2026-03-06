"""
Slack Web API client. Conversations, users, files, messages.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests
from requests.exceptions import ConnectionError, RequestException, Timeout

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


class SlackAPIClient:
    """Slack Web API client (conversations, users, files, messages)."""

    def __init__(self, bot_token: str):
        self.token = bot_token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
        )
        self.max_retries = 3
        self.retry_delay = 1

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        url = f"{SLACK_API_BASE}/{endpoint}"
        for attempt in range(self.max_retries):
            try:
                if method.upper() == "GET":
                    resp = self.session.get(url, params=params or {}, timeout=timeout)
                else:
                    resp = self.session.post(
                        url, params=params, json=json_data or {}, timeout=timeout
                    )
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 2))
                    logger.warning(
                        "Slack rate limited (429), waiting %s s (Retry-After)",
                        wait,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok") and data.get("error") == "rate_limited":
                    wait = int(resp.headers.get("Retry-After", 2))
                    logger.warning("Slack rate limited (body), waiting %s s", wait)
                    time.sleep(wait)
                    continue
                return data
            except (ConnectionError, Timeout, RequestException) as e:
                if attempt < self.max_retries - 1:
                    wait = self.retry_delay * (2**attempt)
                    logger.warning(
                        "Slack request failed (attempt %s/%s): %s",
                        attempt + 1,
                        self.max_retries,
                        e,
                    )
                    time.sleep(wait)
                else:
                    logger.exception("Slack request failed after retries")
                    raise
        return {"ok": False, "error": "unknown"}

    def conversations_list(
        self,
        types: str = "public_channel",
        exclude_archived: bool = True,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> dict:
        """List channels. types e.g. 'public_channel' or 'public_channel,private_channel'."""
        params = {"types": types, "exclude_archived": exclude_archived, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "conversations.list", params=params)

    def conversations_join(self, channel: str) -> dict:
        """Join a channel by ID."""
        return self._request(
            "POST", "conversations.join", json_data={"channel": channel}
        )

    def conversations_info(self, channel: str) -> dict:
        """Get channel info by ID."""
        return self._request("GET", "conversations.info", params={"channel": channel})

    def conversations_members(
        self,
        channel: str,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> dict:
        """List member IDs in a channel. Returns members array and response_metadata.next_cursor."""
        safe_limit = max(1, min(limit, 1000))
        params = {"channel": channel, "limit": safe_limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "conversations.members", params=params)

    def conversations_history(
        self,
        channel: str,
        limit: int = 100,
        oldest: Optional[str] = None,
        latest: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> dict:
        """Get message history for a channel."""
        safe_limit = max(1, min(limit, 1000))
        params = {"channel": channel, "limit": safe_limit}
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "conversations.history", params=params)

    def users_info(self, user: str) -> dict:
        """Get user info by ID."""
        return self._request("GET", "users.info", params={"user": user})

    def users_list(
        self,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> dict:
        """List users in the workspace. Returns members with profile, etc."""
        safe_limit = max(1, min(limit, 1000))
        params = {"limit": safe_limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "users.list", params=params)

    def team_info(self) -> dict:
        """Get workspace/team info. Returns team dict with id, name, etc. Requires team:read scope."""
        return self._request("GET", "team.info")

    def auth_test(self) -> dict:
        """Check auth and get bot/team info. Returns team (name), team_id, url, etc. No extra scope."""
        return self._request("POST", "auth.test")

    def files_info(
        self,
        file: str,
        timeout: int = 30,
    ) -> dict:
        """Get file info by ID."""
        return self._request(
            "GET", "files.info", params={"file": file}, timeout=timeout
        )
