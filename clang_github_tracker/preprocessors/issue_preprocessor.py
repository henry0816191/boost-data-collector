"""
Pinecone issue preprocessor for clang_github_tracker.

Selects candidate issue numbers from DB (updated_at vs final_sync_at) plus failed_ids retries,
then builds documents from raw JSON via github_preprocess.build_issue_document.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from django.conf import settings
from django.utils import timezone

from clang_github_tracker.models import ClangGithubIssueItem
from github_activity_tracker.preprocessors.github_preprocess import build_issue_document
from github_activity_tracker.workspace import get_raw_source_issue_path

logger = logging.getLogger(__name__)

_ISSUE_ID_SUFFIX = re.compile(r":issue:(\d+)$")

NAMESPACE = "github-clang"
APP_TYPE = os.getenv("CLANG_GITHUB_PINECONE_APP_TYPE", NAMESPACE)


def preprocess_for_pinecone(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Preprocess clang GitHub issues for Pinecone upsert."""
    owner = settings.CLANG_GITHUB_OWNER
    repo = settings.CLANG_GITHUB_REPO

    if final_sync_at is None:
        qs = ClangGithubIssueItem.objects.filter(is_pull_request=False).values_list(
            "number", flat=True
        )
    else:
        fs = final_sync_at
        if timezone.is_naive(fs):
            fs = timezone.make_aware(fs, timezone.utc)
        qs = ClangGithubIssueItem.objects.filter(
            is_pull_request=False, updated_at__gt=fs
        ).values_list("number", flat=True)

    numbers: set[int] = set(int(n) for n in qs)

    for fid in failed_ids:
        m = _ISSUE_ID_SUFFIX.search(fid or "")
        if m:
            numbers.add(int(m.group(1)))

    documents: list[dict[str, Any]] = []
    for number in sorted(numbers):
        path = get_raw_source_issue_path(owner, repo, number)
        if not path.is_file():
            logger.debug("preprocess issue #%s: raw missing %s", number, path)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("preprocess issue #%s: read failed %s", number, e)
            continue
        doc = build_issue_document(path, data, repo)
        if doc:
            documents.append(doc)

    return documents, False
