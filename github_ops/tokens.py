"""
GitHub token resolution: get token or API client by use case (scraping, push, write).
"""

from __future__ import annotations

import itertools
import logging
import os
from typing import Literal, Optional

from django.conf import settings

from github_ops.client import GitHubAPIClient

logger = logging.getLogger(__name__)

_scraping_token_cycle: Optional[itertools.cycle] = None


def get_github_token(
    use: Literal["scraping", "push", "create_pr", "write"] = "scraping",
) -> str:
    """
    Return the appropriate GitHub token for the given use case.

    - scraping: one of GITHUB_TOKENS_SCRAPING (round-robin) or GITHUB_TOKEN fallback
    - push: same as write (GITHUB_TOKEN_WRITE or GITHUB_TOKEN)
    - create_pr: same as write (GITHUB_TOKEN_WRITE or GITHUB_TOKEN)
    - write: GITHUB_TOKEN_WRITE (create PR, issues, comments, git push) or GITHUB_TOKEN
    """
    if use == "scraping":
        tokens = getattr(settings, "GITHUB_TOKENS_SCRAPING", None) or []
        if not tokens:
            token = getattr(settings, "GITHUB_TOKEN", None) or os.environ.get(
                "GITHUB_TOKEN", ""
            )
            if not token:
                raise ValueError(
                    "No scraping token: set GITHUB_TOKENS_SCRAPING or GITHUB_TOKEN."
                )
            return (token or "").strip()
        global _scraping_token_cycle
        if _scraping_token_cycle is None:
            _scraping_token_cycle = itertools.cycle(tokens)
        return next(_scraping_token_cycle)
    if use in ("push", "create_pr", "write"):
        token = getattr(settings, "GITHUB_TOKEN_WRITE", None) or ""
        if not token:
            token = getattr(settings, "GITHUB_TOKEN", None) or os.environ.get(
                "GITHUB_TOKEN", ""
            )
        if not token:
            raise ValueError("No write token: set GITHUB_TOKEN_WRITE or GITHUB_TOKEN.")
        return (token or "").strip()
    raise ValueError(
        f"Unknown use: {use!r}. Use 'scraping', 'push', 'create_pr', or 'write'."
    )


def get_github_client(
    use: Literal["scraping", "push", "create_pr", "write"] = "scraping",
) -> GitHubAPIClient:
    """
    Get a GitHub API client with the token for the given use case.
    """
    token = get_github_token(use=use)
    logger.debug("Creating GitHub API client (use=%s)", use)
    return GitHubAPIClient(token)
