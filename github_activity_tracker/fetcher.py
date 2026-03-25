"""
Fetch data from GitHub API.
Adapted from BoostDataCollector/github/fetch.py.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator, Optional
from urllib.parse import parse_qs, urlparse

import requests

if TYPE_CHECKING:
    from github_ops.client import GitHubAPIClient

logger = logging.getLogger(__name__)


def _make_aware(dt: datetime) -> datetime:
    """Return dt as UTC-aware; if naive, assume UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _in_date_range(
    dt: datetime,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
) -> bool:
    """Return True if dt falls within [start_time, end_time] (UTC-aware, both inclusive)."""
    if start_time and dt < _make_aware(start_time):
        return False
    if end_time and dt > _make_aware(end_time):
        return False
    return True


def fetch_user_from_github(
    client: GitHubAPIClient,
    username: str = "",
    email: str = "",
    user_id: Optional[int] = None,
) -> Optional[dict]:
    """Fetch user from GitHub by ID, username, or email. Returns user dict or None."""
    if user_id:
        user = client.rest_request(f"/user/{user_id}")
        if user:
            return user
    if username:
        user = client.rest_request(f"/users/{username}")
        if user:
            return user
    if email:
        response = client.rest_request(f"/search/users?q={email}+in:email")
        if len(response.get("items", [])) > 0:
            user = client.rest_request(f"/user/{response['items'][0]['id']}")
            if user:
                return user
    return None


def _is_first_page_url(url: str) -> bool:
    """Return True if the URL's page= query param is 1 or absent (GitHub default)."""
    try:
        pages = parse_qs(urlparse(url).query).get("page")
        return int(pages[0]) == 1 if pages else True
    except (ValueError, IndexError):
        return False


def _yield_commit_with_stats(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    commit: dict,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
) -> Iterator[dict]:
    """Filter a single commit list entry by date range, fetch full stats, and yield."""
    commit_date_str = commit.get("commit", {}).get("author", {}).get(
        "date"
    ) or commit.get("commit", {}).get("committer", {}).get("date")
    if commit_date_str:
        try:
            commit_dt = datetime.fromisoformat(commit_date_str.replace("Z", "+00:00"))
            if not _in_date_range(commit_dt, start_time, end_time):
                return
        except Exception as e:
            logger.debug("Failed to parse commit date '%s': %s", commit_date_str, e)

    try:
        commit_with_stats = client.rest_request(
            f"/repos/{owner}/{repo}/commits/{commit['sha']}"
        )
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code in (502, 503, 504):
            logger.warning(
                "Aborting commit sync at %s for %s/%s after HTTP %s: %s",
                commit["sha"][:7],
                owner,
                repo,
                e.response.status_code,
                e,
            )
            raise
        raise
    yield commit_with_stats


def fetch_commits_from_github(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    etag_cache: Optional[Any] = None,
) -> Iterator[dict]:
    """Fetch commits from GitHub API oldest-to-newest using Link header pagination.

    When GitHub includes rel="last", walks backward (last → prev → … → page 1) so
    commits are yielded oldest-first. When rel="last" is omitted but rel="next"
    is present (e.g. some since/until responses), follows "next" to fetch all
    pages, then yields oldest-first. True single-page responses have neither link.

    The page-1 list response is cached in memory so when backward traversal returns to
    page 1 via the "prev" link, no duplicate request is made.

    If etag_cache is provided, a conditional GET is used for page 1; a 304 means no
    new commits exist in the requested date window and the function returns immediately.
    """
    logger.debug(
        "Fetching commits for %s/%s from %s to %s", owner, repo, start_time, end_time
    )

    per_page = 100
    since_iso = start_time.isoformat() if start_time else ""
    until_iso = end_time.isoformat() if end_time else ""
    endpoint = f"/repos/{owner}/{repo}/commits"

    params: dict = {"per_page": per_page, "page": 1}
    if start_time:
        params["since"] = start_time.isoformat()
    if end_time:
        params["until"] = end_time.isoformat()

    # Fetch page 1 to discover total pages via Link header.
    first_page_etag: Optional[str] = None
    if etag_cache is not None:
        etag = etag_cache.get("commits", 1, since_iso, until_iso)
        first_page_data, first_page_etag, first_page_links = (
            client.rest_request_conditional_with_all_links(
                endpoint, params=params, etag=etag
            )
        )
        if first_page_data is None:
            logger.debug("Commits list page 1: 304 Not Modified, nothing to process")
            return
    else:
        first_page_data, first_page_links = client.rest_request_with_all_links(
            endpoint, params
        )

    if not first_page_data:
        logger.debug("No commits found for %s/%s", owner, repo)
        return

    logger.debug(
        "Fetched %d commits on page 1 for %s/%s", len(first_page_data), owner, repo
    )

    last_url = first_page_links.get("last")
    next_url = first_page_links.get("next")

    if last_url and not _is_first_page_url(last_url):
        # Multiple pages: walk backward from last page to page 1, yielding oldest-first.
        current_url: Optional[str] = last_url
        while current_url is not None:
            if _is_first_page_url(current_url):
                # Reuse the already-fetched page-1 data — no extra API request.
                page_data = first_page_data
                page_links = first_page_links
                logger.debug("Backward traversal reached page 1; using cached data")
            else:
                page_data, page_links = client.rest_request_url_with_all_links(
                    current_url
                )
                logger.debug(
                    "Fetched %d commits (backward traversal) from %s",
                    len(page_data) if page_data else 0,
                    current_url,
                )
                time.sleep(0.2)

            for commit in reversed(page_data or []):
                yield from _yield_commit_with_stats(
                    client, owner, repo, commit, start_time, end_time
                )

            current_url = page_links.get("prev")

        if etag_cache is not None and first_page_etag:
            etag_cache.set("commits", 1, since_iso, until_iso, first_page_etag)
        return

    if next_url:
        # rel="last" omitted but rel="next" is present: fetch remaining pages, oldest-first.
        pages: list[list[dict]] = [first_page_data]
        current_links = first_page_links
        while current_links.get("next"):
            forward_url = current_links["next"]
            page_data, current_links = client.rest_request_url_with_all_links(
                forward_url
            )
            logger.debug(
                "Fetched %d commits (forward pagination) from %s",
                len(page_data) if page_data else 0,
                forward_url,
            )
            time.sleep(0.2)
            pages.append(page_data or [])

        for page_data in reversed(pages):
            for commit in reversed(page_data):
                yield from _yield_commit_with_stats(
                    client, owner, repo, commit, start_time, end_time
                )
        if etag_cache is not None and first_page_etag:
            etag_cache.set("commits", 1, since_iso, until_iso, first_page_etag)
        return

    # No pagination: neither next nor a multi-page last link.
    logger.debug("Single page of commits; processing in reverse order")
    for commit in reversed(first_page_data):
        yield from _yield_commit_with_stats(
            client, owner, repo, commit, start_time, end_time
        )
    if etag_cache is not None and first_page_etag:
        etag_cache.set("commits", 1, since_iso, until_iso, first_page_etag)


def fetch_comments_from_github(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    issue_number: int,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> list[dict]:
    """Fetch comments for an issue/PR from GitHub API (paginated)."""
    logger.debug(
        f"Fetching comments for {owner}/{repo} issue #{issue_number} from {start_time} to {end_time}"
    )

    results: list[dict] = []
    page = 1
    per_page = 100
    while True:
        params = {
            "per_page": per_page,
            "page": page,
            "sort": "created",
            "direction": "asc",
        }
        if start_time:
            params["since"] = start_time.isoformat()

        comments = client.rest_request(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            params,
        )
        if not comments:
            logger.debug(
                f"No more comments found at page {page} for issue #{issue_number}"
            )
            break
        logger.debug(
            f"Fetched {len(comments)} comments from page {page} for issue #{issue_number}"
        )

        for comment in comments:
            created_str = comment.get("created_at")
            if created_str:
                try:
                    c_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    if not _in_date_range(c_dt, start_time, end_time):
                        continue
                except Exception as e:
                    logger.debug(f"Failed to parse comment date '{created_str}': {e}")
                    continue

            results.append(comment)

        if len(comments) < per_page:
            break
        page += 1
        time.sleep(0.1)

    logger.debug(f"Total comments fetched for issue #{issue_number}: {len(results)}")
    return results


def fetch_issues_from_github(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    etag_cache: Optional[Any] = None,
) -> Iterator[dict]:
    """Fetch issues from GitHub API (paginated). Yields issue dicts with comments.
    Uses GitHub's Link header (rel=\"next\") for pagination per API docs.
    If etag_cache is provided, uses conditional GET for the first page when using endpoint+params.
    """
    logger.debug(f"Fetching issues for {owner}/{repo} from {start_time} to {end_time}")
    per_page = 100
    since_iso = start_time.isoformat() if start_time else ""
    endpoint = f"/repos/{owner}/{repo}/issues"
    next_url: Optional[str] = None
    page_num = 1

    while True:
        # Fresh each page: rest_request_url does not return an ETag; do not reuse
        # page N-1's tag when caching page N (conditional path sets this below).
        response_etag: Optional[str] = None
        try:
            if next_url is not None:
                issues, next_url = client.rest_request_url(next_url)
                page_num += 1
            else:
                params = {
                    "state": "all",
                    "per_page": per_page,
                    "page": page_num,
                    "sort": "updated",
                    "direction": "asc",
                }
                if start_time:
                    params["since"] = start_time.isoformat()
                if etag_cache is not None:
                    etag = etag_cache.get("issues", page_num, since_iso, "")
                    data, response_etag, next_url = (
                        client.rest_request_conditional_with_link(
                            endpoint, params=params, etag=etag
                        )
                    )
                    if data is None:
                        logger.debug(
                            "Issues list page %s: 304 Not Modified, skipping",
                            page_num,
                        )
                        page_num += 1
                        time.sleep(0.2)
                        continue
                    issues = data
                else:
                    issues, next_url = client.rest_request_with_link(endpoint, params)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 422:
                logger.debug(
                    "Issues list: 422 Unprocessable Entity, stopping pagination"
                )
                break
            raise

        if not issues:
            logger.debug("No more issues found")
            break

        # Filter out PRs (issues endpoint returns both issues and PRs)
        raw_issues = issues
        issues = [i for i in raw_issues if "pull_request" not in i]
        logger.debug(
            "Fetched %s issues (excluding PRs) from page %s",
            len(issues),
            page_num,
        )

        for issue in issues:
            updated_str = issue.get("updated_at") or issue.get("created_at")
            if not updated_str:
                continue
            try:
                issue_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, TypeError) as e:
                logger.debug(f"Failed to parse issue date '{updated_str}': {e}")
                continue

            if not _in_date_range(issue_dt, start_time, end_time):
                continue

            issue_number = issue.get("number")
            if issue_number is not None:
                # Fetch full issue detail (list endpoint returns summary only)
                try:
                    full_issue = client.rest_request(
                        f"/repos/{owner}/{repo}/issues/{issue_number}"
                    )
                    if full_issue and isinstance(full_issue, dict):
                        issue = full_issue
                except Exception as e:
                    logger.debug("Failed to fetch full issue #%s: %s", issue_number, e)
                logger.debug(f"Fetching comments for issue #{issue_number}")
                comments = fetch_comments_from_github(
                    client, owner, repo, issue_number, start_time, end_time
                )
                logger.debug(
                    f"Found {len(comments)} comments for issue #{issue_number}"
                )
                # Yield nested format: { issue_info: <detail>, comments: [...] }
                yield {"issue_info": issue, "comments": comments}

        if etag_cache is not None and response_etag:
            etag_cache.set("issues", page_num, since_iso, "", response_etag)

        if next_url is None:
            logger.debug('Last page reached (no Link rel="next")')
            break
        time.sleep(0.2)


def fetch_pr_reviews_from_github(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    pr_number: int,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> list[dict]:
    """Fetch reviews/review comments for a PR from GitHub API (paginated)."""
    logger.debug(
        f"Fetching reviews for {owner}/{repo} PR #{pr_number} from {start_time} to {end_time}"
    )
    results: list[dict] = []
    page = 1
    per_page = 100
    while True:
        params = {
            "per_page": per_page,
            "page": page,
        }
        if start_time:
            params["since"] = start_time.isoformat()

        reviews = client.rest_request(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/comments", params
        )
        if not reviews:
            logger.debug(f"No more reviews found at page {page}")
            break

        for review in reviews:
            updated_str = review.get("updated_at") or review.get("created_at")
            if updated_str:
                try:
                    review_dt = datetime.fromisoformat(
                        updated_str.replace("Z", "+00:00")
                    )
                    if not _in_date_range(review_dt, start_time, end_time):
                        continue
                except Exception as e:
                    logger.debug(f"Failed to parse review date '{updated_str}': {e}")
                    continue

            results.append(review)

        if len(reviews) < per_page:
            logger.debug(
                f"Last page reached (got {len(reviews)} reviews, expected {per_page})"
            )
            break
        page += 1
        time.sleep(0.2)

    logger.debug(
        f"Total reviews fetched for {owner}/{repo} PR #{pr_number}: {len(results)}"
    )
    return results


def fetch_issues_and_prs_from_github(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    etag_cache: Optional[Any] = None,
) -> Iterator[dict]:
    """Fetch issues and PRs from GitHub using a single /issues list endpoint.

    GitHub's issues API returns both issues and pull requests; this function routes each
    item by the presence of the "pull_request" key:
      - Issues  → yield {"issue_info": <detail>, "comments": [...]}
      - PRs     → yield {"pr_info": <detail>, "comments": [...], "reviews": [...]}

    Uses Link-header pagination (direction=asc, sort=updated) so items are processed
    oldest-updated-first. If etag_cache is provided, uses conditional GET for the first
    page; a 304 means nothing has changed and the function returns immediately.
    """
    logger.debug(
        "Fetching issues+PRs for %s/%s from %s to %s", owner, repo, start_time, end_time
    )
    per_page = 100
    since_iso = start_time.isoformat() if start_time else ""
    endpoint = f"/repos/{owner}/{repo}/issues"
    next_url: Optional[str] = None
    page_num = 1

    while True:
        response_etag: Optional[str] = None
        try:
            if next_url is not None:
                items, next_url = client.rest_request_url(next_url)
                page_num += 1
            else:
                params: dict = {
                    "state": "all",
                    "per_page": per_page,
                    "page": page_num,
                    "sort": "updated",
                    "direction": "asc",
                }
                if start_time:
                    params["since"] = start_time.isoformat()
                if etag_cache is not None:
                    etag = etag_cache.get("issues_and_prs", page_num, since_iso, "")
                    data, response_etag, next_url = (
                        client.rest_request_conditional_with_link(
                            endpoint, params=params, etag=etag
                        )
                    )
                    if data is None:
                        logger.debug(
                            "Issues+PRs list page %s: 304 Not Modified, skipping",
                            page_num,
                        )
                        page_num += 1
                        time.sleep(0.2)
                        continue
                    items = data
                else:
                    items, next_url = client.rest_request_with_link(endpoint, params)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 422:
                logger.debug(
                    "Issues+PRs list: 422 Unprocessable Entity, stopping pagination"
                )
                break
            raise

        if not items:
            logger.debug("No more issues/PRs found")
            break

        logger.debug(
            "Fetched %d items (issues+PRs combined) from page %s", len(items), page_num
        )

        for item in items:
            updated_str = item.get("updated_at") or item.get("created_at")
            if not updated_str:
                continue
            try:
                item_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, TypeError) as e:
                logger.debug("Failed to parse item date '%s': %s", updated_str, e)
                continue

            if not _in_date_range(item_dt, start_time, end_time):
                continue

            number = item.get("number")
            if number is None:
                continue

            if "pull_request" in item:
                # PR: fetch full detail from /pulls endpoint, then comments + reviews.
                try:
                    full_pr = client.rest_request(
                        f"/repos/{owner}/{repo}/pulls/{number}"
                    )
                    if full_pr and isinstance(full_pr, dict):
                        item = full_pr
                except Exception as e:
                    logger.debug("Failed to fetch full PR #%s: %s", number, e)
                logger.debug("Fetching comments for PR #%s", number)
                comments = fetch_comments_from_github(
                    client, owner, repo, number, start_time, end_time
                )
                time.sleep(0.2)
                logger.debug("Fetching reviews for PR #%s", number)
                reviews = fetch_pr_reviews_from_github(
                    client, owner, repo, number, start_time, end_time
                )
                time.sleep(0.2)
                yield {"pr_info": item, "comments": comments, "reviews": reviews}
            else:
                # Issue: fetch full detail from /issues endpoint, then comments.
                try:
                    full_issue = client.rest_request(
                        f"/repos/{owner}/{repo}/issues/{number}"
                    )
                    if full_issue and isinstance(full_issue, dict):
                        item = full_issue
                except Exception as e:
                    logger.debug("Failed to fetch full issue #%s: %s", number, e)
                logger.debug("Fetching comments for issue #%s", number)
                comments = fetch_comments_from_github(
                    client, owner, repo, number, start_time, end_time
                )
                logger.debug("Found %d comments for issue #%s", len(comments), number)
                yield {"issue_info": item, "comments": comments}

        if etag_cache is not None and response_etag:
            etag_cache.set("issues_and_prs", page_num, since_iso, "", response_etag)

        if next_url is None:
            logger.debug('Last page reached (no Link rel="next")')
            break
        time.sleep(0.2)


def fetch_pull_requests_from_github(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    etag_cache: Optional[Any] = None,
) -> Iterator[dict]:
    """Fetch pull requests from GitHub API (paginated). Yields PR dicts with comments and reviews.
    If etag_cache is provided, uses rest_request_conditional for the list GET.
    """
    logger.debug(f"Fetching PRs for {owner}/{repo} from {start_time} to {end_time}")
    page = 1
    per_page = 100

    while True:
        params = {
            "state": "all",
            "per_page": per_page,
            "page": page,
            "sort": "updated",
            "direction": "desc",
        }
        response_etag = None
        if etag_cache is not None:
            etag = etag_cache.get("pulls", page, "", "")
            data, response_etag = client.rest_request_conditional(
                f"/repos/{owner}/{repo}/pulls", params=params, etag=etag
            )
            if data is None:
                logger.debug("Pulls list page %s: 304 Not Modified, skipping", page)
                page += 1
                time.sleep(0.2)
                continue
            prs = data
        else:
            prs = client.rest_request(f"/repos/{owner}/{repo}/pulls", params)

        if not prs:
            logger.debug(f"No more PRs found at page {page}")
            break

        flag = False
        for pr in prs:
            updated_str = pr.get("updated_at") or pr.get("created_at")
            pr_number = pr.get("number")
            logger.debug("Fetching PR #%s with updated_str: %s", pr_number, updated_str)
            if updated_str:
                try:
                    pr_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                    if start_time and pr_dt < _make_aware(start_time):
                        flag = True
                        break
                    if end_time and pr_dt > _make_aware(end_time):
                        continue
                except Exception as e:
                    logger.debug("Failed to parse PR date '%s': %s", updated_str, e)
                    continue

            if pr_number is None:
                continue

            # Fetch full PR detail (list endpoint returns summary only)
            try:
                full_pr = client.rest_request(
                    f"/repos/{owner}/{repo}/pulls/{pr_number}"
                )
                if full_pr and isinstance(full_pr, dict):
                    pr = full_pr
            except Exception as e:
                logger.debug("Failed to fetch full PR #%s: %s", pr_number, e)

            logger.debug("Fetching comments for PR #%s", pr_number)
            comments = fetch_comments_from_github(
                client, owner, repo, pr_number, start_time, end_time
            )
            time.sleep(0.2)
            logger.debug("Fetching reviews for PR #%s", pr_number)
            reviews = fetch_pr_reviews_from_github(
                client, owner, repo, pr_number, start_time, end_time
            )
            time.sleep(0.2)
            # Yield nested format: { pr_info: <detail>, comments: [...], reviews: [...] }
            yield {"pr_info": pr, "comments": comments, "reviews": reviews}

        if etag_cache is not None and response_etag:
            etag_cache.set("pulls", page, "", "", response_etag)

        if len(prs) < per_page or flag:
            logger.debug(f"Last page reached (got {len(prs)} PRs, expected {per_page})")
            break
        page += 1
        time.sleep(0.2)
