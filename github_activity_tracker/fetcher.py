"""
Fetch data from GitHub API.
Adapted from BoostDataCollector/github/fetch.py.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterator, Optional

import requests

if TYPE_CHECKING:
    from github_ops.client import GitHubAPIClient

logger = logging.getLogger(__name__)


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


def fetch_commits_from_github(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Iterator[dict]:
    """Fetch commits from GitHub API (paginated). Yields commit dicts with stats."""
    logger.debug(f"Fetching commits for {owner}/{repo} from {start_time} to {end_time}")
    page = 1
    per_page = 100
    while True:
        params = {
            "per_page": per_page,
            "page": page,
        }
        if start_time:
            params["since"] = start_time.isoformat()
        if end_time:
            params["until"] = end_time.isoformat()

        commits = client.rest_request(f"/repos/{owner}/{repo}/commits", params)
        if not commits:
            logger.debug(f"No more commits found at page {page}")
            break
        logger.debug(f"Fetched {len(commits)} commits from page {page}")

        for commit in reversed(commits):
            commit_date_str = commit.get("commit", {}).get("author", {}).get(
                "date"
            ) or commit.get("commit", {}).get("committer", {}).get("date")
            if commit_date_str:
                try:
                    commit_dt = datetime.fromisoformat(
                        commit_date_str.replace("Z", "+00:00")
                    )

                    if start_time:
                        start_time_aware = (
                            start_time.replace(tzinfo=timezone.utc)
                            if start_time.tzinfo is None
                            else start_time
                        )
                        if commit_dt < start_time_aware:
                            continue

                    if end_time:
                        end_time_aware = (
                            end_time.replace(tzinfo=timezone.utc)
                            if end_time.tzinfo is None
                            else end_time
                        )
                        if commit_dt > end_time_aware:
                            continue
                except Exception as e:
                    logger.debug(
                        f"Failed to parse commit date '{commit_date_str}': {e}"
                    )

            # Fetch full commit with stats (skip on persistent server errors so sync continues)
            try:
                commit_with_stats = client.rest_request(
                    f"/repos/{owner}/{repo}/commits/{commit['sha']}"
                )
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code in (502, 503, 504):
                    logger.warning(
                        "Skipping commit %s for %s/%s after HTTP %s: %s",
                        commit["sha"][:7],
                        owner,
                        repo,
                        e.response.status_code,
                        e,
                    )
                    continue
                raise
            yield commit_with_stats

        if len(commits) < per_page:
            logger.debug(
                f"Last page reached (got {len(commits)} commits, expected {per_page})"
            )
            break
        page += 1
        time.sleep(0.2)


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

                    if start_time:
                        start_time_aware = (
                            start_time.replace(tzinfo=timezone.utc)
                            if start_time.tzinfo is None
                            else start_time
                        )
                        if c_dt < start_time_aware:
                            continue

                    if end_time:
                        end_time_aware = (
                            end_time.replace(tzinfo=timezone.utc)
                            if end_time.tzinfo is None
                            else end_time
                        )
                        if c_dt > end_time_aware:
                            continue
                except Exception as e:
                    logger.debug(f"Failed to parse comment date '{created_str}': {e}")

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
) -> Iterator[dict]:
    """Fetch issues from GitHub API (paginated). Yields issue dicts with comments."""
    logger.debug(f"Fetching issues for {owner}/{repo} from {start_time} to {end_time}")
    page = 1
    per_page = 100
    while True:
        params = {
            "state": "all",
            "per_page": per_page,
            "page": page,
            "sort": "updated",
            "direction": "asc",
        }
        if start_time:
            params["since"] = start_time.isoformat()

        issues = client.rest_request(f"/repos/{owner}/{repo}/issues", params)
        if not issues:
            logger.debug(f"No more issues found at page {page}")
            break

        # Filter out PRs (issues endpoint returns both issues and PRs)
        issues = [i for i in issues if "pull_request" not in i]
        logger.debug(f"Fetched {len(issues)} issues (excluding PRs) from page {page}")

        for issue in issues:
            updated_str = issue.get("updated_at") or issue.get("created_at")
            if not updated_str:
                continue
            try:
                issue_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, TypeError) as e:
                logger.debug(f"Failed to parse issue date '{updated_str}': {e}")
                continue

            if start_time:
                start_time_aware = (
                    start_time.replace(tzinfo=timezone.utc)
                    if start_time.tzinfo is None
                    else start_time
                )
                if issue_dt < start_time_aware:
                    continue
            if end_time:
                end_time_aware = (
                    end_time.replace(tzinfo=timezone.utc)
                    if end_time.tzinfo is None
                    else end_time
                )
                if issue_dt > end_time_aware:
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

        if len(issues) < per_page:
            logger.debug(
                f"Last page reached (got {len(issues)} issues, expected {per_page})"
            )
            break
        page += 1
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

                    if start_time:
                        start_time_aware = (
                            start_time.replace(tzinfo=timezone.utc)
                            if start_time.tzinfo is None
                            else start_time
                        )
                        if review_dt < start_time_aware:
                            continue

                    if end_time:
                        end_time_aware = (
                            end_time.replace(tzinfo=timezone.utc)
                            if end_time.tzinfo is None
                            else end_time
                        )
                        if review_dt > end_time_aware:
                            continue
                except Exception as e:
                    logger.debug(f"Failed to parse review date '{updated_str}': {e}")

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


def fetch_pull_requests_from_github(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Iterator[dict]:
    """Fetch pull requests from GitHub API (paginated). Yields PR dicts with comments and reviews."""
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

                    if start_time:
                        start_time_aware = (
                            start_time.replace(tzinfo=timezone.utc)
                            if start_time.tzinfo is None
                            else start_time
                        )
                        if pr_dt < start_time_aware:
                            flag = True
                            break

                    if end_time:
                        end_time_aware = (
                            end_time.replace(tzinfo=timezone.utc)
                            if end_time.tzinfo is None
                            else end_time
                        )
                        if pr_dt > end_time_aware:
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

        if len(prs) < per_page or flag:
            logger.debug(f"Last page reached (got {len(prs)} PRs, expected {per_page})")
            break
        page += 1
        time.sleep(0.2)
