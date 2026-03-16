"""
GitHub PR URL parser for the Slack PR comment bot.
Extracts PR URLs from Slack message text and splits by allowed org.
"""

import re
from typing import Optional

PR_URL_PATTERN = re.compile(
    r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)", re.IGNORECASE
)


def extract_pr_urls(
    text: str, allowed_org: Optional[str] = None
) -> tuple[list[dict], list[dict]]:
    """
    Extract all GitHub PR URLs from a Slack message and split by allowed org.

    Args:
        text: Raw message text (may contain one or more GitHub PR URLs).
        allowed_org: If set, PRs under this owner are returned as "valid";
            PRs under other owners are returned as "invalid_org". If empty/None,
            all found PRs are valid and invalid_org is empty.

    Returns:
        (valid, invalid_org): Each is a list of dicts with keys url, owner, repo, pull_number.
        valid = PRs that are under allowed_org (or all if allowed_org not set).
        invalid_org = PRs that are under a different org (only when allowed_org is set).
    """
    allowed = (allowed_org or "").strip().lower()
    all_entries: list[dict] = []
    for match in PR_URL_PATTERN.finditer(text):
        url = match.group(0)
        owner = match.group(1)
        repo = match.group(2)
        pull_number = int(match.group(3))
        all_entries.append(
            {"url": url, "owner": owner, "repo": repo, "pull_number": pull_number}
        )

    if not allowed:
        return (all_entries, [])

    valid = [e for e in all_entries if (e["owner"] or "").strip().lower() == allowed]
    invalid_org = [
        e for e in all_entries if (e["owner"] or "").strip().lower() != allowed
    ]
    return (valid, invalid_org)
