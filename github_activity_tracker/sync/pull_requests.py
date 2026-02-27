"""
Sync GitHub pull requests (reviews, comments, assignees, labels) with the database.

Flow:
1. Process existing JSON files in workspace/<owner>/<repo>/prs/*.json (load → DB → remove file).
2. Fetch from GitHub, save each as prs/<number>.json, persist to DB, then remove the file.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from cppa_user_tracker.services import get_or_create_github_account
from github_activity_tracker import fetcher, services
from .raw_source import save_pr_raw_source
from github_activity_tracker.workspace import (
    get_pr_json_path,
    iter_existing_pr_jsons,
)
from django.utils import timezone
from github_ops import get_github_client
from github_ops.client import ConnectionException, RateLimitException
from github_activity_tracker.sync.utils import (
    normalize_pr_json,
    parse_datetime,
    parse_github_user,
)

if TYPE_CHECKING:
    from github_activity_tracker.models import GitHubRepository

logger = logging.getLogger(__name__)


def _process_pr_data(repo: GitHubRepository, pr_data: dict) -> None:
    """Apply one PR dict (with comments, reviews, assignees, labels) to the database.
    Accepts flat or nested { pr_info, comments, reviews } format."""
    pr_data = normalize_pr_json(pr_data)
    user_info = parse_github_user(pr_data.get("user"))
    if not user_info["account_id"]:
        logger.warning(
            "PR #%s: no user account_id; skipping",
            pr_data.get("number", "?"),
        )
        return
    account, _ = get_or_create_github_account(
        github_account_id=user_info["account_id"],
        username=user_info["username"],
        display_name=user_info["display_name"],
        avatar_url=user_info["avatar_url"],
    )

    pr_obj, _ = services.create_or_update_pull_request(
        repo=repo,
        account=account,
        pr_number=pr_data.get("number"),
        pr_id=pr_data.get("id"),
        title=pr_data.get("title", ""),
        body=pr_data.get("body", ""),
        state=pr_data.get("state", "open"),
        head_hash=pr_data.get("head", {}).get("sha", ""),
        base_hash=pr_data.get("base", {}).get("sha", ""),
        pr_created_at=parse_datetime(pr_data.get("created_at")),
        pr_updated_at=parse_datetime(pr_data.get("updated_at")),
        pr_merged_at=parse_datetime(pr_data.get("merged_at")),
        pr_closed_at=parse_datetime(pr_data.get("closed_at")),
    )

    for comment_data in pr_data.get("comments", []):
        comment_user_info = parse_github_user(comment_data.get("user"))
        if comment_user_info["account_id"]:
            comment_account, _ = get_or_create_github_account(
                github_account_id=comment_user_info["account_id"],
                username=comment_user_info["username"],
                display_name=comment_user_info["display_name"],
                avatar_url=comment_user_info["avatar_url"],
            )
            services.create_or_update_pr_comment(
                pr=pr_obj,
                account=comment_account,
                pr_comment_id=comment_data.get("id"),
                body=comment_data.get("body", ""),
                pr_comment_created_at=parse_datetime(comment_data.get("created_at")),
                pr_comment_updated_at=parse_datetime(comment_data.get("updated_at")),
            )

    for review_data in pr_data.get("reviews", []):
        review_user_info = parse_github_user(review_data.get("user"))
        if review_user_info["account_id"]:
            review_account, _ = get_or_create_github_account(
                github_account_id=review_user_info["account_id"],
                username=review_user_info["username"],
                display_name=review_user_info["display_name"],
                avatar_url=review_user_info["avatar_url"],
            )
            services.create_or_update_pr_review(
                pr=pr_obj,
                account=review_account,
                pr_review_id=review_data.get("id"),
                body=review_data.get("body", ""),
                in_reply_to_id=review_data.get("in_reply_to_id"),
                pr_review_created_at=parse_datetime(review_data.get("created_at")),
                pr_review_updated_at=parse_datetime(review_data.get("updated_at")),
            )

    for assignee_data in pr_data.get("assignees", []):
        assignee_info = parse_github_user(assignee_data)
        if assignee_info["account_id"]:
            assignee_account, _ = get_or_create_github_account(
                github_account_id=assignee_info["account_id"],
                username=assignee_info["username"],
                display_name=assignee_info["display_name"],
                avatar_url=assignee_info["avatar_url"],
            )
            services.add_pr_assignee(pr_obj, assignee_account)

    for label_data in pr_data.get("labels", []):
        label_name = label_data.get("name", "")
        if label_name:
            services.add_pull_request_label(pr_obj, label_name)

    logger.debug("PR #%s: saved to DB", pr_data.get("number"))


def _process_existing_pr_jsons(repo: GitHubRepository) -> int:
    """Load each prs/*.json in workspace for this repo, save to DB, remove file. Returns count processed."""
    owner = repo.owner_account.username
    repo_name = repo.repo_name
    count = 0
    for path in iter_existing_pr_jsons(owner, repo_name):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _process_pr_data(repo, data)
            save_pr_raw_source(owner, repo_name, data)
            path.unlink()
            count += 1
        except Exception as e:
            logger.exception("Failed to process %s: %s", path, e)
    return count


def sync_pull_requests(
    repo: GitHubRepository,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> None:
    """1) Process existing workspace JSONs; 2) Fetch from GitHub, save as JSON, persist to DB, remove file.

    Args:
        repo: Repository to sync.
        start_date: Override start date (default: last PR updated_at + 1s, or None if no PRs).
        end_date: Override end date (default: now).
    """
    logger.info(
        "sync_pull_requests: starting for repo id=%s (%s)",
        repo.pk,
        repo.repo_name,
    )

    owner = repo.owner_account.username
    repo_name = repo.repo_name

    try:
        # Phase 1: process existing JSON files
        n_existing = _process_existing_pr_jsons(repo)
        if n_existing:
            logger.info(
                "sync_pull_requests: processed %s existing PR JSON(s)",
                n_existing,
            )

        # Phase 2: fetch from GitHub, write JSON, persist to DB, remove file
        client = get_github_client()
        if start_date is None:
            last_pr = repo.pull_requests.order_by("-pr_updated_at").first()
            if last_pr:
                start_date = last_pr.pr_updated_at + timedelta(seconds=1)
        if end_date is None:
            end_date = timezone.now()

        count = 0
        for pr_data in fetcher.fetch_pull_requests_from_github(
            client, owner, repo_name, start_date, end_date
        ):
            pr_number = (pr_data.get("pr_info") or {}).get("number") or pr_data.get(
                "number"
            )
            if pr_number is None:
                continue
            json_path = get_pr_json_path(owner, repo_name, pr_number)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(pr_data, indent=2, default=str), encoding="utf-8"
            )
            _process_pr_data(repo, pr_data)
            save_pr_raw_source(owner, repo_name, pr_data)
            json_path.unlink()
            count += 1

        logger.info(
            "sync_pull_requests: finished for repo id=%s; %s existing + %s fetched",
            repo.pk,
            n_existing,
            count,
        )

    except (RateLimitException, ConnectionException) as e:
        logger.error("sync_pull_requests: failed for repo id=%s: %s", repo.pk, e)
        raise
    except Exception as e:
        logger.exception(
            "sync_pull_requests: unexpected error for repo id=%s: %s",
            repo.pk,
            e,
        )
        raise
