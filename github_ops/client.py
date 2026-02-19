"""
GitHub API client with GraphQL and REST support.
Handles rate limiting, retry logic, and connection errors.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime
from typing import Optional

import requests
from requests.exceptions import ConnectionError, RequestException, Timeout
from urllib3.exceptions import ProtocolError

logger = logging.getLogger(__name__)


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
                        wait_time = self.rate_limit_reset_time - int(time.time())
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

    def _handle_rate_limit(self, wait_time: int, max_delay: int = 3600):
        """Handle rate limit by waiting with exponential backoff."""
        if wait_time > max_delay:
            wait_time = max_delay

        logger.warning(f"Rate limit hit. Waiting {wait_time} seconds...")
        logger.debug(f"Resume time: {datetime.fromtimestamp(time.time() + wait_time)}")

        time.sleep(wait_time)
        self._check_rate_limit()

    def rest_request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make REST API request with rate limit and connection error handling."""
        self._check_rate_limit()

        url = f"{self.rest_base_url}{endpoint}"

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=params, timeout=30)

                if response.status_code == 403:
                    if "X-RateLimit-Remaining" in response.headers:
                        remaining = int(response.headers["X-RateLimit-Remaining"])
                        if remaining == 0:
                            reset_time = int(response.headers["X-RateLimit-Reset"])
                            wait_time = reset_time - int(time.time()) + 10  # Add buffer
                            self._handle_rate_limit(wait_time)
                            return self.rest_request(endpoint, params)

                response.raise_for_status()

                if "X-RateLimit-Remaining" in response.headers:
                    self.rate_limit_remaining = int(
                        response.headers["X-RateLimit-Remaining"]
                    )
                    self.rate_limit_reset_time = int(
                        response.headers["X-RateLimit-Reset"]
                    )

                return response.json()

            except (ConnectionError, ProtocolError, Timeout) as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2**attempt)
                    logger.warning(
                        f"Connection error on {endpoint} (attempt {attempt + 1}/{self.max_retries}): {e}"
                    )
                    logger.debug(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"Failed to make request to {endpoint} after {self.max_retries} attempts: {e}"
                    )
                    raise ConnectionException(
                        f"Connection error after {self.max_retries} retries for {endpoint}: {e}"
                    )
            except requests.exceptions.HTTPError as e:
                logger.error(
                    f"HTTP error on {endpoint}: {e.response.status_code} - {e}"
                )
                raise
            except RequestException as e:
                logger.error(f"Request error on {endpoint}: {e}")
                raise

    def rest_post(self, endpoint: str, json_data: Optional[dict] = None) -> dict:
        """POST to REST API with rate limit and connection error handling."""
        self._check_rate_limit()
        url = f"{self.rest_base_url}{endpoint}"
        json_data = json_data or {}

        for attempt in range(self.max_retries):
            try:
                response = self.session.post(url, json=json_data, timeout=30)

                if response.status_code == 403:
                    if "X-RateLimit-Remaining" in response.headers:
                        remaining = int(response.headers["X-RateLimit-Remaining"])
                        if remaining == 0:
                            reset_time = int(response.headers["X-RateLimit-Reset"])
                            wait_time = reset_time - int(time.time()) + 10
                            self._handle_rate_limit(wait_time)
                            return self.rest_post(endpoint, json_data)

                response.raise_for_status()
                if "X-RateLimit-Remaining" in response.headers:
                    self.rate_limit_remaining = int(
                        response.headers["X-RateLimit-Remaining"]
                    )
                    self.rate_limit_reset_time = int(
                        response.headers["X-RateLimit-Reset"]
                    )
                return response.json()

            except (ConnectionError, ProtocolError, Timeout) as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2**attempt)
                    logger.warning(
                        "Connection error on POST %s (attempt %s/%s): %s",
                        endpoint,
                        attempt + 1,
                        self.max_retries,
                        e,
                    )
                    time.sleep(wait_time)
                else:
                    raise ConnectionException(
                        f"Connection error after {self.max_retries} retries for POST {endpoint}: {e}"
                    )
            except requests.exceptions.HTTPError as e:
                logger.error(
                    "HTTP error on POST %s: %s - %s",
                    endpoint,
                    getattr(e.response, "status_code", None),
                    e,
                )
                raise
            except RequestException as e:
                logger.error("Request error on POST %s: %s", endpoint, e)
                raise

    def rest_put(
        self, endpoint: str, json_data: Optional[dict] = None
    ) -> dict:
        """PUT to REST API with rate limit and connection error handling."""
        self._check_rate_limit()
        url = f"{self.rest_base_url}{endpoint}"
        json_data = json_data or {}

        for attempt in range(self.max_retries):
            try:
                response = self.session.put(url, json=json_data, timeout=30)

                if response.status_code == 403:
                    if "X-RateLimit-Remaining" in response.headers:
                        remaining = int(
                            response.headers["X-RateLimit-Remaining"]
                        )
                        if remaining == 0:
                            reset_time = int(
                                response.headers["X-RateLimit-Reset"]
                            )
                            wait_time = (
                                reset_time - int(time.time()) + 10
                            )
                            self._handle_rate_limit(wait_time)
                            return self.rest_put(endpoint, json_data)

                response.raise_for_status()
                if "X-RateLimit-Remaining" in response.headers:
                    self.rate_limit_remaining = int(
                        response.headers["X-RateLimit-Remaining"]
                    )
                    self.rate_limit_reset_time = int(
                        response.headers["X-RateLimit-Reset"]
                    )
                return response.json()

            except (ConnectionError, ProtocolError, Timeout) as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2**attempt)
                    logger.warning(
                        "Connection error on PUT %s (attempt %s/%s): %s",
                        endpoint,
                        attempt + 1,
                        self.max_retries,
                        e,
                    )
                    time.sleep(wait_time)
                else:
                    raise ConnectionException(
                        f"Connection error after {self.max_retries} retries for PUT {endpoint}: {e}"
                    )
            except requests.exceptions.HTTPError as e:
                logger.error(
                    "HTTP error on PUT %s: %s - %s",
                    endpoint,
                    getattr(e.response, "status_code", None),
                    e,
                )
                raise
            except RequestException as e:
                logger.error("Request error on PUT %s: %s", endpoint, e)
                raise

    def rest_delete(
        self, endpoint: str, json_data: Optional[dict] = None
    ) -> Optional[dict]:
        """DELETE to REST API (JSON body). Returns response JSON or None for 204."""
        self._check_rate_limit()
        url = f"{self.rest_base_url}{endpoint}"
        json_data = json_data or {}

        for attempt in range(self.max_retries):
            try:
                response = self.session.delete(
                    url, json=json_data, timeout=30
                )

                if response.status_code == 403:
                    if "X-RateLimit-Remaining" in response.headers:
                        remaining = int(
                            response.headers["X-RateLimit-Remaining"]
                        )
                        if remaining == 0:
                            reset_time = int(
                                response.headers["X-RateLimit-Reset"]
                            )
                            wait_time = (
                                reset_time - int(time.time()) + 10
                            )
                            self._handle_rate_limit(wait_time)
                            return self.rest_delete(endpoint, json_data)

                response.raise_for_status()
                if "X-RateLimit-Remaining" in response.headers:
                    self.rate_limit_remaining = int(
                        response.headers["X-RateLimit-Remaining"]
                    )
                    self.rate_limit_reset_time = int(
                        response.headers["X-RateLimit-Reset"]
                    )
                if response.status_code == 204:
                    return None
                return response.json()

            except (ConnectionError, ProtocolError, Timeout) as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2**attempt)
                    logger.warning(
                        "Connection error on DELETE %s (attempt %s/%s): %s",
                        endpoint,
                        attempt + 1,
                        self.max_retries,
                        e,
                    )
                    time.sleep(wait_time)
                else:
                    raise ConnectionException(
                        f"Connection error after {self.max_retries} retries for DELETE {endpoint}: {e}"
                    )
            except requests.exceptions.HTTPError as e:
                logger.error(
                    "HTTP error on DELETE %s: %s - %s",
                    endpoint,
                    getattr(e.response, "status_code", None),
                    e,
                )
                raise
            except RequestException as e:
                logger.error("Request error on DELETE %s: %s", endpoint, e)
                raise

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
        Delete a file via Contents API. Returns response or None for 204.
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
            f"/repos/{owner}/{repo}/contents/{path}" if path else f"/repos/{owner}/{repo}/contents",
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
        self._check_rate_limit()

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        for attempt in range(self.max_retries):
            try:
                response = self.session.post(
                    self.graphql_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )

                if response.status_code == 403:
                    if "X-RateLimit-Remaining" in response.headers:
                        remaining = int(response.headers["X-RateLimit-Remaining"])
                        if remaining == 0:
                            reset_time = int(response.headers["X-RateLimit-Reset"])
                            wait_time = reset_time - int(time.time()) + 10
                            self._handle_rate_limit(wait_time)
                            return self.graphql_request(query, variables)

                response.raise_for_status()
                data = response.json()

                if "errors" in data:
                    error_msg = "; ".join(
                        [e.get("message", "Unknown error") for e in data["errors"]]
                    )
                    raise Exception(f"GraphQL errors: {error_msg}")

                if "X-RateLimit-Remaining" in response.headers:
                    self.rate_limit_remaining = int(
                        response.headers["X-RateLimit-Remaining"]
                    )
                    self.rate_limit_reset_time = int(
                        response.headers["X-RateLimit-Reset"]
                    )

                return data

            except (ConnectionError, ProtocolError, Timeout) as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2**attempt)
                    logger.warning(
                        f"Connection error on GraphQL request (attempt {attempt + 1}/{self.max_retries}): {e}"
                    )
                    logger.debug(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"Failed GraphQL request after {self.max_retries} attempts: {e}"
                    )
                    raise ConnectionException(
                        f"Connection error after {self.max_retries} retries: {e}"
                    )
            except requests.exceptions.HTTPError as e:
                logger.error(
                    f"HTTP error on GraphQL request: {e.response.status_code} - {e}"
                )
                raise
            except RequestException as e:
                logger.error(f"Request error on GraphQL request: {e}")
                raise

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
