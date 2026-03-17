"""
Pinecone issue preprocessor for clang_github_tracker.

Wraps github_activity_tracker.preprocessors.github_preprocess.preprocess_issues
for the llvm/llvm-project repo (configured via CLANG_GITHUB_OWNER / CLANG_GITHUB_REPO).

Usage (via run_cppa_pinecone_sync or run_clang_github_tracker):
    app_type = APP_TYPE  (default: "github-clang", override with CLANG_GITHUB_PINECONE_APP_TYPE env)
    namespace = NAMESPACE  ("github-clang")
    preprocessor = clang_github_tracker.preprocessors.issue_preprocessor.preprocess_for_pinecone
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from django.conf import settings

from github_activity_tracker.preprocessors.github_preprocess import preprocess_issues

NAMESPACE = "github-clang"
APP_TYPE = os.getenv("CLANG_GITHUB_PINECONE_APP_TYPE", NAMESPACE)


def preprocess_for_pinecone(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Preprocess clang GitHub issues for Pinecone upsert.

    Args:
        failed_ids: Previously failed ids strings to retry.
        final_sync_at: Last successful sync timestamp; None means first run.

    Returns:
        (documents, is_chunked=False)
    """
    return preprocess_issues(
        settings.CLANG_GITHUB_OWNER,
        settings.CLANG_GITHUB_REPO,
        failed_ids,
        final_sync_at,
    )
