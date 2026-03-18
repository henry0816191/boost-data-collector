"""
Pinecone PR preprocessor for boost_library_tracker.

Wraps github_activity_tracker.preprocessors.github_preprocess.preprocess_all_prs
for all boostorg repos (owner configured via BOOST_GITHUB_OWNER setting, default "boostorg").

Issues and PRs share the namespace "github-boostorg"; they are distinguished in Pinecone
by metadata["type"] = "issue" or "pr".

Usage (via run_cppa_pinecone_sync or run_boost_library_tracker):
    app_type = APP_TYPE  (default: "github-boostorg", override with BOOST_GITHUB_PINECONE_APP_TYPE env)
    namespace = NAMESPACE  ("github-boostorg")
    preprocessor = boost_library_tracker.preprocessors.pr_preprocessor.preprocess_for_pinecone
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from django.conf import settings

from github_activity_tracker.preprocessors.github_preprocess import preprocess_all_prs

NAMESPACE = "github-boostorg"
APP_TYPE = os.getenv("BOOST_GITHUB_PINECONE_APP_TYPE", NAMESPACE)


def preprocess_for_pinecone(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Preprocess Boost GitHub pull requests (all boostorg repos) for Pinecone upsert.

    Args:
        failed_ids: Previously failed ids strings to retry.
        final_sync_at: Last successful sync timestamp; None means first run.

    Returns:
        (documents, is_chunked=False)
    """
    return preprocess_all_prs(
        settings.BOOST_GITHUB_OWNER,
        failed_ids,
        final_sync_at,
    )
