"""
GitHub API client with GraphQL and REST support.
Handles rate limiting, retry logic, and connection errors.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Optional, Union
from urllib.parse import urlparse

import requests
from requests.exceptions import ConnectionError, RequestException, Timeout
from urllib3.exceptions import ProtocolError

from core.utils.datetime_parsing import parse_iso_datetime

logger = logging.getLogger(__name__)

MAX_RATE_LIMIT_RETRIES = 15
# Extra seconds added to API reset-based wait so we don't retry before the window opens.
RATE_LIMIT_WAIT_SAFETY_MARGIN_SEC = 10


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
        """If response is 403/429 with rate limit or Retry-After, return seconds to wait; else None.

        Also handles HTTP 200 GraphQL throttle responses, which GitHub returns with
        X-RateLimit-Remaining: 0 / X-RateLimit-Reset headers or an "errors" key in the body.
        """
        if response.status_code not in (403, 429):
            if response.status_code == 200:
                # GraphQL rate-limit: only indicated by "errors" key in response body.
                # X-RateLimit-Remaining: 0 on HTTP 200 means the request succeeded and
                # consumed the last token, not that it was throttled.
                try:
                    body = response.json()
                    body_throttled = isinstance(body, dict) and "errors" in body
                except (ValueError, KeyError):
                    body_throttled = False
                if not body_throttled:
                    return None
            else:
                return None
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            retry_after = retry_after.strip()
            try:
                retry_secs = int(retry_after)
                if retry_secs > 0:
                    return retry_secs
            except ValueError:
                try:
                    dt = parsedate_to_datetime(retry_after)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    wait = (dt - datetime.now(timezone.utc)).total_seconds()
                    if wait > 0:
                        return wait
                except (ValueError, TypeError):
                    pass
        # Retry-After missing or did not yield a positive delay; try X-RateLimit-*.
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining is None:
            return None
        try:
            remaining_int = int(remaining)
        except (TypeError, ValueError):
            return None
        if remaining_int != 0:
            return None
        reset = response.headers.get("X-RateLimit-Reset")
        if not reset:
            return None
        try:
            reset_int = int(reset)
        except (TypeError, ValueError):
            return None
        wait = max(0, reset_int - int(time.time()) + RATE_LIMIT_WAIT_SAFETY_MARGIN_SEC)
        return wait

    def _update_rate_limit_from_response(self, response: requests.Response) -> None:
        """Update rate limit state from response headers if present."""
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining is None or reset is None:
            return
        try:
            self.rate_limit_remaining = int(remaining)
            self.rate_limit_reset_time = int(reset)
        except (TypeError, ValueError):
            logger.debug(
                "Invalid rate-limit headers received; skipping local state update."
            )

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
        allow_retry_on_5xx: bool = False,
        allow_retry_on_connection_errors: bool = False,
    ) -> requests.Response:
        """Perform one HTTP request. Retries on 429/403 rate limit (wait then retry).
        Retries on 5xx only when allow_retry_on_5xx=True; retries on connection errors
        only when allow_retry_on_connection_errors=True. Mutating methods (e.g. REST POST/DELETE)
        should not pass allow_retry_on_connection_errors=True to avoid replaying writes that
        may have succeeded on the server despite a transient failure. GraphQL is retried
        because this client uses it only for read-only queries (e.g. file content).
        """
        attempts_5xx = self.max_retries if allow_retry_on_5xx else 1
        attempts_conn = self.max_retries if allow_retry_on_connection_errors else 1
        for rate_limit_attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            rate_limited = False
            attempt_5xx = 0
            attempt_conn = 0
            while True:
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
                        if rate_limit_attempt >= MAX_RATE_LIMIT_RETRIES:
                            raise RateLimitException(
                                f"Rate limit retries exhausted for {endpoint_for_log}"
                            )
                        rate_limited = True
                        self._handle_rate_limit(wait)
                        break
                    if resp.status_code in (500, 502, 503, 504):
                        if allow_retry_on_5xx and attempt_5xx < attempts_5xx - 1:
                            wait_time = self.retry_delay * (2**attempt_5xx)
                            logger.warning(
                                "HTTP %s on %s (attempt %s/%s), retrying in %ss...",
                                resp.status_code,
                                endpoint_for_log,
                                attempt_5xx + 1,
                                attempts_5xx,
                                wait_time,
                            )
                            time.sleep(wait_time)
                            attempt_5xx += 1
                            continue
                    return resp
                except (ConnectionError, ProtocolError, Timeout) as e:
                    if (
                        allow_retry_on_connection_errors
                        and attempt_conn < attempts_conn - 1
                    ):
                        wait_time = self.retry_delay * (2**attempt_conn)
                        logger.warning(
                            "Connection error on %s (attempt %s/%s): %s",
                            endpoint_for_log,
                            attempt_conn + 1,
                            attempts_conn,
                            e,
                        )
                        time.sleep(wait_time)
                        attempt_conn += 1
                        continue
                    if allow_retry_on_connection_errors:
                        logger.error(
                            "Failed %s after %s retries: %s",
                            endpoint_for_log,
                            self.max_retries,
                            e,
                        )
                        raise ConnectionException(
                            f"Connection error after {self.max_retries} retries for {endpoint_for_log}: {e}"
                        ) from e
                    logger.error(
                        "Connection error on %s (no retries): %s",
                        endpoint_for_log,
                        e,
                    )
                    raise ConnectionException(
                        f"Connection error for {endpoint_for_log}: {e}"
                    ) from e
            if rate_limited:
                time.sleep(2 * rate_limit_attempt)
                continue
            raise ConnectionException(
                f"Connection error for {endpoint_for_log}: max retries exceeded"
            )

    def _handle_rate_limit(
        self, wait_time: int, max_delay: Optional[int] = 3600
    ) -> None:
        """Handle rate limit by waiting. Does not cap below (max_delay + safety margin)."""
        wait_time = max(0, wait_time)
        if max_delay is not None:
            cap = max_delay + RATE_LIMIT_WAIT_SAFETY_MARGIN_SEC
            if wait_time > cap:
                wait_time = cap
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
        _do_request retries 5xx and connection errors when the corresponding flags are set.
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
            allow_retry_on_5xx=True,
            allow_retry_on_connection_errors=True,
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

    def rest_raw_request(
        self, url: str, params: Optional[dict] = None
    ) -> Optional[bytes] | None:
        """Make raw request to REST API with rate limit and connection error handling."""
        response = self._do_request(
            "GET",
            url,
            "raw",
            params=params,
            timeout=30,
            allow_retry_on_5xx=True,
            allow_retry_on_connection_errors=True,
            headers={"Accept": "application/vnd.github.raw"},
        )
        if response is None:
            return None
        return response.content

    def rest_request_conditional_with_link(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        etag: Optional[str] = None,
    ) -> tuple[Optional[dict], Optional[str], Optional[str]]:
        """Like rest_request_conditional but also returns next_page_url from Link header.
        Returns (data, response_etag, next_page_url). On 304: (None, etag, None).
        """
        response, response_etag = self._rest_get(endpoint, params=params, etag=etag)
        if response is None:
            return (None, response_etag, None)
        next_url = self._parse_link_next(response.headers.get("Link"))
        return (response.json(), response_etag, next_url)

    @staticmethod
    def _parse_link_next(link_header: Optional[str]) -> Optional[str]:
        """Parse GitHub Link response header; return URL for rel=\"next\" or None.
        See: https://docs.github.com/en/rest/guides/using-pagination-in-the-rest-api
        """
        if not link_header or 'rel="next"' not in link_header:
            return None
        match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        return match.group(1) if match else None

    def rest_request_with_link(
        self, endpoint: str, params: Optional[dict] = None
    ) -> tuple[Union[list, dict], Optional[str]]:
        """GET request that returns (data, next_page_url) using the Link header.
        next_page_url is None when there is no next page. Use rest_request_url(next_page_url) for the next page.
        """
        response, _ = self._rest_get(endpoint, params=params)
        if response is None:
            return ({}, None)
        data = response.json()
        next_url = self._parse_link_next(response.headers.get("Link"))
        return (data, next_url)

    def rest_request_url(
        self, full_url: str
    ) -> tuple[Union[list, dict], Optional[str]]:
        """GET full_url (e.g. from Link rel=\"next\"). Returns (data, next_page_url).
        Uses same session (auth, rate limit). next_page_url is None when no more pages.
        """
        response = self._rest_get_url(full_url)
        data = response.json()
        next_url = self._parse_link_next(response.headers.get("Link"))
        return (data, next_url)

    def _validate_rest_pagination_url(self, full_url: str) -> None:
        """Ensure full_url is same origin as rest_base_url so the auth token is not sent elsewhere."""
        expected = urlparse(self.rest_base_url)
        if not expected.scheme or not expected.netloc:
            raise ValueError(
                "GitHubAPIClient.rest_base_url must be an absolute URL with host"
            )
        target = urlparse(full_url)
        if not target.netloc:
            raise ValueError(
                "Refusing relative or invalid pagination URL (missing host)"
            )
        if target.scheme.lower() != "https":
            raise ValueError(
                f"Refusing pagination URL with scheme {target.scheme!r}; only https is allowed"
            )
        if (target.scheme.lower(), target.netloc.lower()) != (
            expected.scheme.lower(),
            expected.netloc.lower(),
        ):
            raise ValueError(
                f"Refusing to follow pagination URL outside {expected.netloc}"
            )

    def _rest_get_url(self, full_url: str) -> requests.Response:
        """GET by full URL (e.g. from Link rel=\"next\"). For pagination only."""
        self._validate_rest_pagination_url(full_url)
        response = self._do_request(
            "GET",
            full_url,
            "GET (paginated)",
            params=None,
            headers=None,
            timeout=30,
            allow_retry_on_5xx=True,
            allow_retry_on_connection_errors=True,
        )
        response.raise_for_status()
        self._update_rate_limit_from_response(response)
        return response

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
        """Make GraphQL API request with rate limit and connection error handling.
        Connection errors are retried (used for read-only queries only).
        """
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
            allow_retry_on_5xx=True,
            allow_retry_on_connection_errors=True,
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

    def get_tag_sha(self, owner: str, repo: str, tag: str) -> Optional[str]:
        """Get the SHA of a tag."""
        response = self.rest_request(f"/repos/{owner}/{repo}/git/ref/tags/{tag}")
        if not response:
            return None
        return response.get("object", {}).get("sha")

    def get_tag_published_at(
        self, owner: str, repo: str, sha: str
    ) -> Optional[datetime]:
        """Get the published at date of a tag."""
        response = self.rest_request(f"/repos/{owner}/{repo}/git/commits/{sha}")
        if not response:
            return None
        author = response.get("author", {}) or response.get("committer", {})
        if not author:
            return None
        date_str = author.get("date") or ""
        return parse_iso_datetime(date_str) or datetime.now(timezone.utc)
