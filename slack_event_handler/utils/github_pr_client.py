"""
GitHub PR comment client for the Slack PR bot.
Reads SLACK_PR_BOT_GITHUB_TOKEN and SLACK_PR_BOT_COMMENT_TEMPLATE from Django settings.
"""

import logging
import time

from django.conf import settings
from github import Github
from github.GithubException import GithubException

logger = logging.getLogger(__name__)

_gh: Github | None = None

MAX_RETRIES = 3
RETRY_BASE_DELAY_SEC = 2  # exponential backoff: base * 2^attempt


def _get_client() -> Github:
    global _gh
    if _gh is None:
        token = (getattr(settings, "SLACK_PR_BOT_GITHUB_TOKEN", "") or "").strip()
        if not token:
            raise ValueError(
                "Missing SLACK_PR_BOT_GITHUB_TOKEN in Django settings / .env"
            )
        _gh = Github(token)
    return _gh


def post_pr_comment(owner: str, repo: str, pull_number: int) -> None:
    """
    Posts a comment to a GitHub PR using the configured template.
    Raises on network errors, 404 (not found), 403 (no access), etc.
    """
    template = (
        getattr(settings, "SLACK_PR_BOT_COMMENT_TEMPLATE", "")
        or "Automated comment from Slack bot."
    )
    gh = _get_client()
    repository = gh.get_repo(f"{owner}/{repo}")
    pull = repository.get_pull(pull_number)

    for attempt in range(MAX_RETRIES):
        try:
            pull.create_issue_comment(template)
            logger.debug("Posted PR comment to %s/%s#%d", owner, repo, pull_number)
            return
        except GithubException as e:
            if attempt < MAX_RETRIES - 1:
                delay_sec = RETRY_BASE_DELAY_SEC * (2**attempt)
                logger.warning(
                    "GitHub PR comment failed (attempt %d/%d): %s; retrying in %ds",
                    attempt + 1,
                    MAX_RETRIES,
                    e,
                    delay_sec,
                )
                time.sleep(delay_sec)
            else:
                logger.error(
                    "GitHub PR comment failed after %d attempts: %s",
                    MAX_RETRIES,
                    e,
                )
                raise
