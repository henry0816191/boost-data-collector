"""
GitHub PR URL parser for the Slack PR comment bot.
Extracts and classifies PR URLs from Slack message text.
"""

import re

from django.conf import settings

PR_URL_PATTERN = re.compile(
    r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)", re.IGNORECASE
)


def extract_pr_urls(text: str) -> tuple[list[dict], list[dict]]:
    """
    Extracts all GitHub PR URLs from a Slack message.

    Returns:
        valid       – PRs under the configured org (SLACK_PR_BOT_TEAM)
        invalid_org – PRs detected but belonging to a different org
    """
    allowed_org: str = (getattr(settings, "SLACK_PR_BOT_TEAM", "") or "").strip()
    valid: list[dict] = []
    invalid_org: list[dict] = []

    for match in PR_URL_PATTERN.finditer(text):
        url = match.group(0)
        owner = match.group(1)
        repo = match.group(2)
        pull_number = int(match.group(3))

        if owner.lower() == allowed_org.lower():
            valid.append(
                {"url": url, "owner": owner, "repo": repo, "pull_number": pull_number}
            )
        else:
            invalid_org.append({"url": url, "owner": owner})

    return valid, invalid_org
