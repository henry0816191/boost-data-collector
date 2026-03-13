"""
GitHub API client with GraphQL and REST support.
Handles rate limiting, retry logic, and connection errors.
"""

from __future__ import annotations

import base64
import logging
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Optional

import requests
from requests.exceptions import ConnectionError, RequestException, Timeout
from urllib3.exceptions import ProtocolError

logger = logging.getLogger(__name__)

MAX_RATE_LIMIT_RETRIES = 5


class RateLimitException(Exception):
    """Raised when rate limit is exceeded."""

    pass


class ConnectionException(Exception):
    """Raised when connection errors occur after retries."""

    pass


class GitHubAPIClient:
    """GitHub API client with GraphQL and REST support."""

    def __init__(self, token: str):
        self.token = token
        self.rest_base_url = "https://api.github.com"
        self.graphql_url = "https://api.github.com/graphql"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )
        self.rate_limit_remaining: Optional[int] = None
        self.rate_limit_reset_time: Optional[int] = None
        self.max_retries = 3
        self.retry_delay = 1  # Initial delay in seconds

    def _check_rate_limit(self):
        """Check current rate limit status with retry logic for connection errors."""
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    f"{self.rest_base_url}/rate_limit", timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    self.rate_limit_remaining = data["resources"]["core"]["remaining"]
                    self.rate_limit_reset_time = data["resources"]["core"]["reset"]

                    if self.rate_limit_remaining == 0:
                        wait_time = max(
                            0, self.rate_limit_reset_time - int(time.time())
                        )
                        if wait_time > 0:
                            raise RateLimitException(
                                f"Rate limit exceeded. Reset at {datetime.fromtimestamp(self.rate_limit_reset_time)}. "
                                f"Wait {wait_time} seconds."
                            )
                return True
            except (ConnectionError, ProtocolError, Timeout) as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2**attempt)  # Exponential backoff
                    logger.warning(
                        f"Connection error checking rate limit (attempt {attempt + 1}/{self.max_retries}): {e}"
                    )
                    logger.debug(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"Failed to check rate limit after {self.max_retries} attempts: {e}"
                    )
                    raise ConnectionException(
                        f"Connection error after {self.max_retries} retries: {e}"
                    )
            except RequestException as e:
                logger.error(f"Request error checking rate limit: {e}")
                raise

    def _parse_rate_limit_wait(self, response: requests.Response) -> Optional[int]:
        """If response is 403/429 with rate limit or Retry-After, return seconds to wait; else None."""
        if response.status_code not in (403, 429):
            return None
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            retry_after = retry_after.strip()
            try:
                return max(0, int(retry_after))
            except ValueError:
                try:
                    dt = parsedate_to_datetime(retry_after)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    wait = (dt - datetime.now(timezone.utc)).total_seconds()
                    return max(0, int(wait))
                except (ValueError, TypeError):
                    pass
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining is None:
            return None
        if int(remaining) != 0:
            return None
        reset = response.headers.get("X-RateLimit-Reset")
        if not reset:
            return None
        wait = max(0, int(reset) - int(time.time()) + 10)
        return wait

    def _update_rate_limit_from_response(self, response: requests.Response) -> None:
        """Update rate limit state from response headers if present."""
        if "X-RateLimit-Remaining" not in response.headers:
            return
        self.rate_limit_remaining = int(response.headers["X-RateLimit-Remaining"])
        self.rate_limit_reset_time = int(response.headers["X-RateLimit-Reset"])

    def _raise_if_error_and_update_rate_limit(
        self, response: requests.Response, request_label: str
    ) -> None:
        """Raise on HTTP/request error; otherwise update rate limit from response. Does not return."""
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.error(
                "HTTP error on %s: %s - %s",
                request_label,
                getattr(e.response, "status_code", None),
                e,
            )
            raise
        except RequestException as e:
            logger.error("Request error on %s: %s", request_label, e)
            raise
        self._update_rate_limit_from_response(response)

    def _do_request(
        self,
        method: str,
        url: str,
        endpoint_for_log: str,
        *,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: int = 30,
        allow_retry: bool = False,
    ) -> requests.Response:
        """Perform one HTTP request. Retries on 429/403 rate limit (wait then retry).
        Retries on 5xx/connection errors only when allow_retry=True.

        Mutating methods (POST, DELETE, GraphQL) must NOT pass allow_retry=True to avoid
        replaying writes that may have succeeded on the server despite a transient failure.
        """
        attempts = self.max_retries if allow_retry else 1
        for rate_limit_attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            rate_limited = False
            rate_limit_resp = None
            for attempt in range(attempts):
                try:
                    resp = self.session.request(
                        method,
                        url,
                        params=params,
                        json=json_data,
                        headers=headers,
                        timeout=timeout,
                    )
                    wait = self._parse_rate_limit_wait(resp)
                    if wait is not None:
                        self._handle_rate_limit(wait)
                        rate_limited = True
                        rate_limit_resp = resp
                        break
                    if allow_retry and resp.status_code in (500, 502, 503, 504):
                        if attempt < attempts - 1:
                            wait_time = self.retry_delay * (2**attempt)
                            logger.warning(
                                "HTTP %s on %s (attempt %s/%s), retrying in %ss...",
                                resp.status_code,
                                endpoint_for_log,
                                attempt + 1,
                                attempts,
                                wait_time,
                            )
                            time.sleep(wait_time)
                            continue
                    return resp
                except (ConnectionError, ProtocolError, Timeout) as e:
                    if allow_retry and attempt < attempts - 1:
                        wait_time = self.retry_delay * (2**attempt)
                        logger.warning(
                            "Connection error on %s (attempt %s/%s): %s",
                            endpoint_for_log,
                            attempt + 1,
                            attempts,
                            e,
                        )
                        time.sleep(wait_time)
                    elif allow_retry:
                        logger.error(
                            "Failed %s after %s retries: %s",
                            endpoint_for_log,
                            self.max_retries,
                            e,
                        )
                        raise ConnectionException(
                            f"Connection error after {self.max_retries} retries for {endpoint_for_log}: {e}"
                        ) from e
                    else:
                        logger.error(
                            "Connection error on %s (no retries): %s",
                            endpoint_for_log,
                            e,
                        )
                        raise ConnectionException(
                            f"Connection error for {endpoint_for_log}: {e}"
                        ) from e
            if rate_limited:
                if rate_limit_attempt < MAX_RATE_LIMIT_RETRIES:
                    continue
                if rate_limit_resp is not None:
                    logger.warning(
                        "Rate limit retries exhausted (%s) for %s, returning last response.",
                        MAX_RATE_LIMIT_RETRIES,
                        endpoint_for_log,
                    )
                    return rate_limit_resp
            raise ConnectionException(
                f"Connection error for {endpoint_for_log}: max retries exceeded"
            )

    def _handle_rate_limit(self, wait_time: int, max_delay: int = 3600) -> None:
        """Handle rate limit by waiting with exponential backoff."""
        wait_time = max(0, wait_time)
        if wait_time > max_delay:
            wait_time = max_delay
        if wait_time > 0:
            logger.warning("Rate limit hit. Waiting %s seconds...", wait_time)
            time.sleep(wait_time)
        self._check_rate_limit()

    def _rest_get(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        etag: Optional[str] = None,
    ) -> tuple[Optional[requests.Response], Optional[str]]:
        """
        Shared GET logic: 403 wait+retry, 304/200 handling.
        _do_request already retries 5xx and connection errors.
        Returns (response, response_etag). On 304 returns (None, response ETag or caller's etag).
        Caller gets response body from response.json() when response is not None.
        """
        url = f"{self.rest_base_url}{endpoint}"
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        response = self._do_request(
            "GET",
            url,
            endpoint,
            params=params,
            headers=headers or None,
            timeout=30,
            allow_retry=True,
        )
        if response.status_code == 304:
            self._update_rate_limit_from_response(response)
            return (None, response.headers.get("ETag", etag))
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.error(
                "HTTP error on %s: %s - %s",
                endpoint,
                e.response.status_code,
                e,
            )
            raise
        self._update_rate_limit_from_response(response)
        return (response, response.headers.get("ETag"))

    def rest_request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make REST API request with rate limit and connection error handling."""
        response, _ = self._rest_get(endpoint, params=params)
        if response is None:
            return {}
        return response.json()

    def rest_request_conditional(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        etag: Optional[str] = None,
    ) -> tuple[Optional[dict], Optional[str]]:
        """Make GET request with optional If-None-Match. Returns (data, etag).
        On 304: (None, response ETag). On 200: (response.json(), response ETag header).
        """
        response, response_etag = self._rest_get(endpoint, params=params, etag=etag)
        if response is None:
            return (None, response_etag)
        return (response.json(), response_etag)

    def rest_post(self, endpoint: str, json_data: Optional[dict] = None) -> dict:
        """POST to REST API with rate limit and connection error handling."""
        url = f"{self.rest_base_url}{endpoint}"
        payload = json_data or {}
        response = self._do_request(
            "POST", url, f"POST {endpoint}", json_data=payload, timeout=30
        )
        self._raise_if_error_and_update_rate_limit(response, f"POST {endpoint}")
        return response.json()

    def rest_put(self, endpoint: str, json_data: Optional[dict] = None) -> dict:
        """PUT to REST API with rate limit and connection error handling."""
        url = f"{self.rest_base_url}{endpoint}"
        payload = json_data or {}
        response = self._do_request(
            "PUT", url, f"PUT {endpoint}", json_data=payload, timeout=30
        )
        self._raise_if_error_and_update_rate_limit(response, f"PUT {endpoint}")
        return response.json()

    def rest_delete(
        self, endpoint: str, json_data: Optional[dict] = None
    ) -> Optional[dict]:
        """DELETE to REST API (JSON body). Returns response JSON or None for 204."""
        url = f"{self.rest_base_url}{endpoint}"
        payload = json_data or {}
        response = self._do_request(
            "DELETE", url, f"DELETE {endpoint}", json_data=payload, timeout=30
        )
        self._raise_if_error_and_update_rate_limit(response, f"DELETE {endpoint}")
        if response.status_code == 204:
            return None
        return response.json()

    def get_file_sha(
        self, owner: str, repo: str, path: str, ref: Optional[str] = None
    ) -> Optional[str]:
        """
        Get the SHA of a file (for update/delete). Returns None if path is a dir or missing.
        """
        params = {} if not ref else {"ref": ref}
        try:
            data = self.rest_request(
                f"/repos/{owner}/{repo}/contents/{path}", params=params
            )
        except requests.exceptions.HTTPError as e:
            if getattr(e.response, "status_code", None) == 404:
                return None
            raise
        if isinstance(data, list):
            return None
        return data.get("sha")

    def create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content_base64: str,
        message: str,
        branch: str = "main",
        sha: Optional[str] = None,
    ) -> dict:
        """
        Create or update a file via Contents API. Use client from get_github_client(use='write').
        """
        payload = {
            "message": message,
            "content": content_base64,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        return self.rest_put(
            f"/repos/{owner}/{repo}/contents/{path}", json_data=payload
        )

    def delete_file(
        self,
        owner: str,
        repo: str,
        path: str,
        message: str,
        branch: str = "main",
    ) -> Optional[dict]:
        """
        Delete a file via Contents API.

        Uses get_file_sha to resolve the blob SHA for the path, then rest_delete
        to perform the delete. Returns the API JSON response on success.

        Returns None in these cases:
        - The target path does not exist or is a directory (get_file_sha
          returns falsy).
        - The Contents API responds with 204 No Content (rest_delete returns
          None in that case).

        Callers cannot distinguish "not found/directory" from "204 no content"
        from the return value alone; both yield None.
        """
        sha = self.get_file_sha(owner, repo, path, ref=branch)
        if not sha:
            return None
        return self.rest_delete(
            f"/repos/{owner}/{repo}/contents/{path}",
            json_data={"message": message, "sha": sha, "branch": branch},
        )

    def list_contents(
        self,
        owner: str,
        repo: str,
        path: str = "",
        ref: Optional[str] = None,
    ):
        """
        List directory contents. Returns API response (list or single file dict).
        ref: branch/tag (default: default branch).
        """
        params = {} if not ref else {"ref": ref}
        return self.rest_request(
            (
                f"/repos/{owner}/{repo}/contents/{path}"
                if path
                else f"/repos/{owner}/{repo}/contents"
            ),
            params=params,
        )

    def get_file_content(
        self, owner: str, repo: str, path: str, ref: Optional[str] = None
    ) -> tuple[bytes, Optional[str]]:
        """
        Fetch one file content via API. Returns (decoded_content_bytes, encoding).
        ref: branch/tag/commit (default: default branch).
        """
        params = {} if not ref else {"ref": ref}
        data = self.rest_request(
            f"/repos/{owner}/{repo}/contents/{path}", params=params
        )
        if isinstance(data, list):
            raise ValueError(f"Path is a directory, not a file: {path}")
        enc = data.get("encoding")
        content_b64 = data.get("content")
        if not content_b64:
            return b"", enc
        return base64.b64decode(content_b64), enc

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
    ) -> dict:
        """Create a pull request. Use client from get_github_client(use='write')."""
        return self.rest_post(
            f"/repos/{owner}/{repo}/pulls",
            json_data={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
            },
        )

    def create_issue(self, owner: str, repo: str, title: str, body: str = "") -> dict:
        """Create an issue. Use client from get_github_client(use='write')."""
        return self.rest_post(
            f"/repos/{owner}/{repo}/issues",
            json_data={"title": title, "body": body},
        )

    def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict:
        """Create a comment on an issue. Use client from get_github_client(use='write')."""
        return self.rest_post(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json_data={"body": body},
        )

    def graphql_request(self, query: str, variables: Optional[dict] = None) -> dict:
        """Make GraphQL API request with rate limit and connection error handling."""
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables
        response = self._do_request(
            "POST",
            self.graphql_url,
            "GraphQL",
            json_data=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        self._raise_if_error_and_update_rate_limit(response, "GraphQL request")
        data = response.json()
        if "errors" in data:
            error_msg = "; ".join(
                e.get("message", "Unknown error") for e in data["errors"]
            )
            raise Exception(f"GraphQL errors: {error_msg}")
        return data

    def get_repository_info(self, owner: str, repo: str) -> dict:
        """Get repository information."""
        return self.rest_request(f"/repos/{owner}/{repo}")

    def get_submodules_from_file(
        self, filepath: str, default_owner: Optional[str] = None
    ) -> list[dict]:
        """Get submodules from a local .gitmodules file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                gitmodules_content = f.read()
        except FileNotFoundError:
            logger.warning(f"Local .gitmodules file not found: {filepath}")
            return []
        except Exception as e:
            logger.error(f"Error reading .gitmodules file {filepath}: {e}")
            return []

        return self._parse_gitmodules(gitmodules_content, default_owner)

    def _parse_gitmodules(
        self,
        gitmodules_content: str,
        default_owner: Optional[str] = None,
        repo_type: str = "boost_org_module",
    ) -> list[dict]:
        """Parse .gitmodules file content."""
        submodules = []
        current_submodule = {}

        for line in gitmodules_content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("[submodule"):
                if current_submodule:
                    submodules.append(current_submodule)
                current_submodule = {
                    "repo_type": repo_type,
                    "owner": default_owner,
                }
            elif line.startswith("path ="):
                continue
            elif line.startswith("url ="):
                url = line.split("=", 1)[1].strip()
                current_submodule["repo_url"] = url.replace(
                    "../", "https://github.com/boostorg/"
                )
                current_submodule["repo_name"] = url.replace("../", "").replace(
                    ".git", ""
                )

        if current_submodule:
            submodules.append(current_submodule)

        return submodules

    def get_submodules(
        self, owner: str, repo: str, local_file: Optional[str] = None
    ) -> list[dict]:
        """Get submodules from .gitmodules file (local file or GitHub API)."""
        if local_file:
            logger.debug(f"Reading submodules from local file: {local_file}")
            submodules = self.get_submodules_from_file(local_file, default_owner=owner)
            if submodules:
                logger.debug(f"Found {len(submodules)} submodule(s) from local file")
                return submodules
            else:
                logger.debug("No submodules found in local file, trying GitHub API...")

        try:
            content = self.rest_request(f"/repos/{owner}/{repo}/contents/.gitmodules")

            if isinstance(content, list):
                logger.warning(
                    f"GitHub API returned a list instead of file object for .gitmodules in {owner}/{repo}"
                )
                return []

            if content.get("type") == "file":
                try:
                    gitmodules_content = base64.b64decode(content["content"]).decode(
                        "utf-8"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to decode .gitmodules content for {owner}/{repo}: {e}"
                    )
                    return []

                submodules = self._parse_gitmodules(
                    gitmodules_content, default_owner=owner
                )
                logger.debug(
                    f"Found {len(submodules)} submodule(s) in {owner}/{repo} via API"
                )
                return submodules
            else:
                logger.warning(
                    f".gitmodules is not a file (type: {content.get('type')}) in {owner}/{repo}"
                )
                return []
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.debug(f"No .gitmodules file found in {owner}/{repo}")
                return []
            else:
                logger.error(
                    f"HTTP error getting .gitmodules for {owner}/{repo}: {e.response.status_code} - {e}"
                )
                raise
        except Exception as e:
            logger.error(f"Error getting submodules for {owner}/{repo}: {e}")
            return []
