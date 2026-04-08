"""
Backfill ClangGithubIssueItem / ClangGithubCommit from raw JSON scan.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from clang_github_tracker import services as clang_services
from clang_github_tracker.workspace import OWNER, REPO, get_raw_repo_dir
from github_activity_tracker.sync.utils import (
    normalize_issue_json,
    normalize_pr_json,
)

from core.utils.datetime_parsing import parse_iso_datetime as parse_datetime

from clang_github_tracker.sync_raw import commit_date

logger = logging.getLogger(__name__)

_SHA40 = re.compile(r"^[0-9a-fA-F]{40}$")
_RAW_CHUNK_EVERY = 10_000


class Command(BaseCommand):
    """Load ``ClangGithubIssueItem`` / ``ClangGithubCommit`` from raw JSON dirs."""

    help = (
        "Backfill clang_github_tracker DB by scanning "
        "raw/github_activity_tracker/<owner>/<repo>/commits|issues|prs/*.json"
    )

    def handle(self, *args, **options):
        """Scan raw JSON under the configured repo and upsert DB rows."""
        self._backfill_from_raw()

    def _backfill_from_raw(self) -> None:
        """Scan ``commits`` / ``issues`` / ``prs`` JSON under the raw repo dir and upsert."""
        root = get_raw_repo_dir(OWNER, REPO, create=False)
        if not root.is_dir():
            raise CommandError(f"Raw repo dir missing: {root}")

        commits_dir = root / "commits"
        if commits_dir.is_dir():
            commit_rows: list[tuple[str, datetime | None]] = []
            c_skip = 0
            c_ins_total = c_upd_total = 0
            for c_read_n, p in enumerate(sorted(commits_dir.glob("*.json")), start=1):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    sha = (data.get("sha") or "").strip()
                    if not _SHA40.match(sha):
                        c_skip += 1
                        continue
                    commit_rows.append((sha, commit_date(data)))
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("skip commit file %s: %s", p, e)
                    c_skip += 1
                if c_read_n % _RAW_CHUNK_EVERY == 0:
                    if commit_rows:
                        ins_c, upd_c = clang_services.upsert_commits_batch(commit_rows)
                        c_ins_total += ins_c
                        c_upd_total += upd_c
                        commit_rows.clear()
                    logger.info(
                        "raw commits/: read %s JSON files; cumulative "
                        "inserted=%s updated=%s skipped=%s",
                        c_read_n,
                        c_ins_total,
                        c_upd_total,
                        c_skip,
                    )
            if commit_rows:
                ins_c, upd_c = clang_services.upsert_commits_batch(commit_rows)
                c_ins_total += ins_c
                c_upd_total += upd_c
            logger.info(
                "raw commits/: done inserted=%s updated=%s skipped=%s",
                c_ins_total,
                c_upd_total,
                c_skip,
            )

        issue_rows: list[tuple[int, bool, datetime | None, datetime | None]] = []
        i_ins_total = i_upd_total = 0

        issues_dir = root / "issues"
        if issues_dir.is_dir():
            i_skip = 0
            i_ok = 0
            for i_read_n, p in enumerate(sorted(issues_dir.glob("*.json")), start=1):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    flat = normalize_issue_json(data)
                    num = flat.get("number")
                    if not isinstance(num, int) or num <= 0:
                        i_skip += 1
                        continue
                    issue_rows.append(
                        (
                            num,
                            False,
                            parse_datetime(flat.get("created_at")),
                            parse_datetime(flat.get("updated_at")),
                        )
                    )
                    i_ok += 1
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("skip issue file %s: %s", p, e)
                    i_skip += 1
                if i_read_n % _RAW_CHUNK_EVERY == 0:
                    if issue_rows:
                        ins_i, upd_i = clang_services.upsert_issue_items_batch(
                            issue_rows
                        )
                        i_ins_total += ins_i
                        i_upd_total += upd_i
                        issue_rows.clear()
                    logger.info(
                        "raw issues/: read %s JSON files; cumulative "
                        "issues+prs inserted=%s updated=%s",
                        i_read_n,
                        i_ins_total,
                        i_upd_total,
                    )
            if issue_rows:
                ins_i, upd_i = clang_services.upsert_issue_items_batch(issue_rows)
                i_ins_total += ins_i
                i_upd_total += upd_i
                issue_rows.clear()
            logger.info("raw issues/: parsed_ok=%s skipped=%s", i_ok, i_skip)

        prs_dir = root / "prs"
        if prs_dir.is_dir():
            pr_skip = 0
            pr_ok = 0
            for pr_read_n, p in enumerate(sorted(prs_dir.glob("*.json")), start=1):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    flat = normalize_pr_json(data)
                    num = flat.get("number")
                    if not isinstance(num, int) or num <= 0:
                        pr_skip += 1
                        continue
                    issue_rows.append(
                        (
                            num,
                            True,
                            parse_datetime(flat.get("created_at")),
                            parse_datetime(flat.get("updated_at")),
                        )
                    )
                    pr_ok += 1
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("skip pr file %s: %s", p, e)
                    pr_skip += 1
                if pr_read_n % _RAW_CHUNK_EVERY == 0:
                    if issue_rows:
                        ins_i, upd_i = clang_services.upsert_issue_items_batch(
                            issue_rows
                        )
                        i_ins_total += ins_i
                        i_upd_total += upd_i
                        issue_rows.clear()
                    logger.info(
                        "raw prs/: read %s JSON files; cumulative "
                        "issues+prs inserted=%s updated=%s",
                        pr_read_n,
                        i_ins_total,
                        i_upd_total,
                    )
            if issue_rows:
                ins_i, upd_i = clang_services.upsert_issue_items_batch(issue_rows)
                i_ins_total += ins_i
                i_upd_total += upd_i
                issue_rows.clear()
            logger.info("raw prs/: parsed_ok=%s skipped=%s", pr_ok, pr_skip)

        logger.info(
            "raw issues+prs DB total: inserted=%s updated=%s",
            i_ins_total,
            i_upd_total,
        )

        logger.info("raw backfill finished root=%s", root)
