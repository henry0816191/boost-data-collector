"""
Backfill ClangGithubIssueItem / ClangGithubCommit from CSV or raw JSON scan.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from clang_github_tracker import services as clang_services
from clang_github_tracker import state_manager as clang_state
from clang_github_tracker.workspace import (
    OWNER,
    REPO,
    default_backfill_csv_path,
    get_raw_repo_dir,
)
from github_activity_tracker.sync.utils import (
    normalize_issue_json,
    normalize_pr_json,
    parse_datetime,
)

logger = logging.getLogger(__name__)

_SHA40 = re.compile(r"^[0-9a-fA-F]{40}$")
_RAW_CHUNK_EVERY = 10_000


def _commit_date_from_json(data: dict):
    """Parse commit author/committer date from a GitHub API-style JSON dict."""
    commit = data.get("commit") or {}
    author = commit.get("author") or commit.get("committer") or {}
    date_str = author.get("date")
    if not date_str:
        return None
    return parse_datetime(date_str) or clang_state.parse_iso(date_str)


class Command(BaseCommand):
    """Load ``ClangGithubIssueItem`` / ``ClangGithubCommit`` from CSV or raw JSON."""

    help = (
        "Backfill clang_github_tracker DB from CSV (--from-csv) or raw JSON dirs (--from-raw). "
        "CSV columns: record_type (issue|pr|commit), number, github_created_at, github_updated_at, "
        "sha, github_committed_at."
    )

    def add_arguments(self, parser):
        """Add mutually exclusive ``--from-csv`` and ``--from-raw`` options."""
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--from-csv",
            nargs="?",
            const="",
            default=None,
            metavar="PATH",
            help=(
                "Import from CSV. If PATH is omitted, use workspace/clang_github_tracker/"
                "clang_github_tracker_backfill.csv"
            ),
        )
        group.add_argument(
            "--from-raw",
            action="store_true",
            help="Scan raw/github_activity_tracker/<owner>/<repo>/commits|issues|prs/*.json",
        )

    def handle(self, *args, **options):
        """Dispatch to CSV or raw-directory backfill."""
        if options.get("from_raw"):
            self._backfill_from_raw()
            return
        csv_arg = options.get("from_csv")
        path = Path(csv_arg) if csv_arg else default_backfill_csv_path()
        self._backfill_from_csv(path)

    def _backfill_from_csv(self, path: Path) -> None:
        """Parse CSV at ``path`` and batch-upsert issues, PRs, and commits."""
        if not path.is_file():
            raise CommandError(f"CSV not found: {path}")
        commit_rows: list[tuple[str, datetime | None]] = []
        issue_rows: list[tuple[int, bool, datetime | None, datetime | None]] = []
        skipped = 0
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row")
            for row in reader:
                rt = (row.get("record_type") or "").strip().lower()
                try:
                    if rt == "issue":
                        num = int((row.get("number") or "").strip())
                        if num <= 0:
                            logger.warning("skip issue row: invalid number %r", num)
                            skipped += 1
                            continue
                        gc = parse_datetime(
                            (row.get("github_created_at") or "").strip()
                        )
                        gu = parse_datetime(
                            (row.get("github_updated_at") or "").strip()
                        )
                        issue_rows.append((num, False, gc, gu))
                    elif rt == "pr":
                        num = int((row.get("number") or "").strip())
                        if num <= 0:
                            logger.warning("skip pr row: invalid number %r", num)
                            skipped += 1
                            continue
                        gc = parse_datetime(
                            (row.get("github_created_at") or "").strip()
                        )
                        gu = parse_datetime(
                            (row.get("github_updated_at") or "").strip()
                        )
                        issue_rows.append((num, True, gc, gu))
                    elif rt == "commit":
                        sha = (row.get("sha") or "").strip()
                        if not _SHA40.match(sha):
                            logger.warning("skip commit row: invalid sha %r", sha)
                            skipped += 1
                            continue
                        gcm = parse_datetime(
                            (row.get("github_committed_at") or "").strip()
                        )
                        commit_rows.append((sha, gcm))
                    else:
                        logger.warning("skip row: unknown record_type %r", rt)
                        skipped += 1
                except (TypeError, ValueError) as e:
                    logger.warning("skip row: %s (row=%r)", e, row)
                    skipped += 1

        ins_i, upd_i = clang_services.upsert_issue_items_batch(issue_rows)
        ins_c, upd_c = clang_services.upsert_commits_batch(commit_rows)
        logger.info(
            "CSV backfill done: issues_prs inserted=%s updated=%s commits inserted=%s "
            "updated=%s skipped=%s path=%s",
            ins_i,
            upd_i,
            ins_c,
            upd_c,
            skipped,
            path,
        )

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
                    commit_rows.append((sha, _commit_date_from_json(data)))
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
