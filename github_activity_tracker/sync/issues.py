"""
Sync GitHub issues (comments, assignees, labels) with the database.

Flow:
1. Process existing JSON files in workspace/<owner>/<repo>/issues/*.json (load → DB → remove file).
2. Fetch from GitHub, save each as issues/<number>.json, persist to DB, then remove the file.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from cppa_user_tracker.services import get_or_create_github_account
from github_activity_tracker import fetcher, services
from .raw_source import save_issue_raw_source
from .etag_cache import RedisListETagCache
from github_activity_tracker.workspace import (
    get_issue_json_path,
    iter_existing_issue_jsons,
)
from github_ops import get_github_client
from github_ops.client import ConnectionException, RateLimitException
from github_activity_tracker.sync.utils import (
    normalize_issue_json,
    parse_datetime,
    parse_github_user,
)

if TYPE_CHECKING:
    from github_activity_tracker.models import GitHubRepository

logger = logging.getLogger(__name__)


def _process_issue_data(repo: GitHubRepository, issue_data: dict) -> None:
    """Apply one issue dict (with comments, assignees, labels) to the database.
    Accepts flat or nested { issue_info, comments } format."""
    issue_data = normalize_issue_json(issue_data)
    user_info = parse_github_user(issue_data.get("user"))
    if not user_info["account_id"]:
        logger.warning(
            "Issue #%s: no user account_id; skipping",
            issue_data.get("number", "?"),
        )
        return
    account, _ = get_or_create_github_account(
        github_account_id=user_info["account_id"],
        username=user_info["username"],
        display_name=user_info["display_name"],
        avatar_url=user_info["avatar_url"],
    )

    issue_obj, _ = services.create_or_update_issue(
        repo=repo,
        account=account,
        issue_number=issue_data.get("number"),
        issue_id=issue_data.get("id"),
        title=issue_data.get("title", ""),
        body=issue_data.get("body", ""),
        state=issue_data.get("state", "open"),
        state_reason=issue_data.get("state_reason", ""),
        issue_created_at=parse_datetime(issue_data.get("created_at")),
        issue_updated_at=parse_datetime(issue_data.get("updated_at")),
        issue_closed_at=parse_datetime(issue_data.get("closed_at")),
    )

    for comment_data in issue_data.get("comments", []):
        comment_user_info = parse_github_user(comment_data.get("user"))
        if comment_user_info["account_id"]:
            comment_account, _ = get_or_create_github_account(
                github_account_id=comment_user_info["account_id"],
                username=comment_user_info["username"],
                display_name=comment_user_info["display_name"],
                avatar_url=comment_user_info["avatar_url"],
            )
            services.create_or_update_issue_comment(
                issue=issue_obj,
                account=comment_account,
                issue_comment_id=comment_data.get("id"),
                body=comment_data.get("body", ""),
                issue_comment_created_at=parse_datetime(comment_data.get("created_at")),
                issue_comment_updated_at=parse_datetime(comment_data.get("updated_at")),
            )

    assignee_infos = [parse_github_user(a) for a in issue_data.get("assignees", [])]
    current_assignee_ids = {i["account_id"] for i in assignee_infos if i["account_id"]}
    for assignee_account in issue_obj.assignees.all():
        if assignee_account.github_account_id not in current_assignee_ids:
            services.remove_issue_assignee(issue_obj, assignee_account)
    for assignee_info in assignee_infos:
        if assignee_info["account_id"]:
            assignee_account, _ = get_or_create_github_account(
                github_account_id=assignee_info["account_id"],
                username=assignee_info["username"],
                display_name=assignee_info["display_name"],
                avatar_url=assignee_info["avatar_url"],
            )
            services.add_issue_assignee(issue_obj, assignee_account)

    for label_data in issue_data.get("labels", []):
        label_name = label_data.get("name", "")
        if label_name:
            services.add_issue_label(issue_obj, label_name)

    logger.debug("Issue #%s: saved to DB", issue_data.get("number"))


def _process_existing_issue_jsons(repo: GitHubRepository) -> tuple[int, list[int]]:
    """Load each issues/*.json in workspace for this repo, save to DB, remove file.

    Returns:
        (count, issue_numbers) — count of processed files and their issue numbers.
    """
    owner = repo.owner_account.username
    repo_name = repo.repo_name
    count = 0
    numbers: list[int] = []
    for path in iter_existing_issue_jsons(owner, repo_name):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _process_issue_data(repo, data)
            save_issue_raw_source(owner, repo_name, data)
            path.unlink()
            number = (data.get("issue_info") or {}).get("number") or data.get("number")
            if number is not None:
                numbers.append(number)
            count += 1
        except Exception as e:
            logger.exception("Failed to process %s: %s", path, e)
    return count, numbers


def sync_issues(
    repo: GitHubRepository,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> list[int]:
    """1) Process existing workspace JSONs; 2) Fetch from GitHub, save as JSON, persist to DB, remove file.

    Args:
        repo: Repository to sync.
        start_date: Override start date (default: last issue updated_at + 1s, or None if no issues).
        end_date: Override end date (default: None = no end; stable ETag cache).

    Returns:
        List of issue numbers processed during this sync run.
    """
    logger.info("sync_issues: starting for repo id=%s (%s)", repo.pk, repo.repo_name)

    owner = repo.owner_account.username
    repo_name = repo.repo_name
    processed_numbers: list[int] = []

    try:
        # Phase 1: process existing JSON files
        n_existing, existing_numbers = _process_existing_issue_jsons(repo)
        processed_numbers.extend(existing_numbers)
        if n_existing:
            logger.info("sync_issues: processed %s existing issue JSON(s)", n_existing)

        # Phase 2: fetch from GitHub, write JSON, persist to DB, remove file
        client = get_github_client()
        if start_date is None:
            last_issue = repo.issues.order_by("-issue_updated_at").first()
            if last_issue:
                start_date = last_issue.issue_updated_at + timedelta(seconds=1)
        # Leave end_date as None when not set so ETag cache semantics stay stable.

        count = 0
        etag_cache = RedisListETagCache(repo_id=repo.pk)
        for issue_data in fetcher.fetch_issues_from_github(
            client, owner, repo_name, start_date, end_date, etag_cache=etag_cache
        ):
            issue_number = (issue_data.get("issue_info") or {}).get(
                "number"
            ) or issue_data.get("number")
            if issue_number is None:
                continue
            json_path = get_issue_json_path(owner, repo_name, issue_number)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(issue_data, indent=2, default=str), encoding="utf-8"
            )
            _process_issue_data(repo, issue_data)
            save_issue_raw_source(owner, repo_name, issue_data)
            json_path.unlink()
            processed_numbers.append(issue_number)
            count += 1

        logger.info(
            "sync_issues: finished for repo id=%s; %s existing + %s fetched",
            repo.pk,
            n_existing,
            count,
        )

    except (RateLimitException, ConnectionException) as e:
        logger.error("sync_issues: failed for repo id=%s: %s", repo.pk, e)
        raise
    except Exception as e:
        logger.exception("sync_issues: unexpected error for repo id=%s: %s", repo.pk, e)
        raise

    return processed_numbers
