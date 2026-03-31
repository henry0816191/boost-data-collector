"""
Backfill ClangGithubIssueItem / ClangGithubCommit from CSV or raw JSON scan.
"""

from __future__ import annotations

import csv
import json
import logging
import re
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


def _commit_date_from_json(data: dict):
    commit = data.get("commit") or {}
    author = commit.get("author") or commit.get("committer") or {}
    date_str = author.get("date")
    if not date_str:
        return None
    return parse_datetime(date_str) or clang_state.parse_iso(date_str)


class Command(BaseCommand):
    help = (
        "Backfill clang_github_tracker DB from CSV (--from-csv) or raw JSON dirs (--from-raw). "
        "CSV columns: record_type (issue|pr|commit), number, github_created_at, github_updated_at, "
        "sha, github_committed_at."
    )

    def add_arguments(self, parser):
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
        if options.get("from_raw"):
            self._backfill_from_raw()
            return
        csv_arg = options.get("from_csv")
        path = Path(csv_arg) if csv_arg else default_backfill_csv_path()
        self._backfill_from_csv(path)

    def _backfill_from_csv(self, path: Path) -> None:
        if not path.is_file():
            raise CommandError(f"CSV not found: {path}")
        inserted = updated = skipped = 0
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row")
            for row in reader:
                rt = (row.get("record_type") or "").strip().lower()
                try:
                    if rt == "issue":
                        num = int((row.get("number") or "").strip())
                        gc = parse_datetime((row.get("github_created_at") or "").strip())
                        gu = parse_datetime((row.get("github_updated_at") or "").strip())
                        _, was_created = clang_services.upsert_issue_item(
                            num,
                            is_pull_request=False,
                            github_created_at=gc,
                            github_updated_at=gu,
                        )
                        inserted += bool(was_created)
                        updated += not was_created
                    elif rt == "pr":
                        num = int((row.get("number") or "").strip())
                        gc = parse_datetime((row.get("github_created_at") or "").strip())
                        gu = parse_datetime((row.get("github_updated_at") or "").strip())
                        _, was_created = clang_services.upsert_issue_item(
                            num,
                            is_pull_request=True,
                            github_created_at=gc,
                            github_updated_at=gu,
                        )
                        inserted += bool(was_created)
                        updated += not was_created
                    elif rt == "commit":
                        sha = (row.get("sha") or "").strip()
                        if not _SHA40.match(sha):
                            logger.warning("skip commit row: invalid sha %r", sha)
                            skipped += 1
                            continue
                        gcm = parse_datetime(
                            (row.get("github_committed_at") or "").strip()
                        )
                        _, was_created = clang_services.upsert_commit(
                            sha, github_committed_at=gcm
                        )
                        inserted += bool(was_created)
                        updated += not was_created
                    else:
                        logger.warning("skip row: unknown record_type %r", rt)
                        skipped += 1
                except (TypeError, ValueError) as e:
                    logger.warning("skip row: %s (row=%r)", e, row)
                    skipped += 1
        logger.info(
            "CSV backfill done: inserted=%s updated=%s skipped=%s path=%s",
            inserted,
            updated,
            skipped,
            path,
        )

    def _backfill_from_raw(self) -> None:
        root = get_raw_repo_dir(OWNER, REPO, create=False)
        if not root.is_dir():
            raise CommandError(f"Raw repo dir missing: {root}")

        commits_dir = root / "commits"
        if commits_dir.is_dir():
            c_ins = c_upd = c_skip = 0
            for p in commits_dir.glob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    sha = (data.get("sha") or "").strip()
                    if not _SHA40.match(sha):
                        c_skip += 1
                        continue
                    dt = _commit_date_from_json(data)
                    _, was_created = clang_services.upsert_commit(
                        sha, github_committed_at=dt
                    )
                    if was_created:
                        c_ins += 1
                    else:
                        c_upd += 1
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("skip commit file %s: %s", p, e)
                    c_skip += 1
            logger.info(
                "raw commits/: inserted=%s updated=%s skipped=%s",
                c_ins,
                c_upd,
                c_skip,
            )

        issues_dir = root / "issues"
        if issues_dir.is_dir():
            i_ins = i_upd = i_skip = 0
            for p in issues_dir.glob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    flat = normalize_issue_json(data)
                    num = flat.get("number")
                    if not isinstance(num, int) or num <= 0:
                        i_skip += 1
                        continue
                    _, was_created = clang_services.upsert_issue_item(
                        num,
                        is_pull_request=False,
                        github_created_at=parse_datetime(flat.get("created_at")),
                        github_updated_at=parse_datetime(flat.get("updated_at")),
                    )
                    if was_created:
                        i_ins += 1
                    else:
                        i_upd += 1
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("skip issue file %s: %s", p, e)
                    i_skip += 1
            logger.info(
                "raw issues/: inserted=%s updated=%s skipped=%s",
                i_ins,
                i_upd,
                i_skip,
            )

        prs_dir = root / "prs"
        if prs_dir.is_dir():
            p_ins = p_upd = p_skip = 0
            for p in prs_dir.glob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    flat = normalize_pr_json(data)
                    num = flat.get("number")
                    if not isinstance(num, int) or num <= 0:
                        p_skip += 1
                        continue
                    _, was_created = clang_services.upsert_issue_item(
                        num,
                        is_pull_request=True,
                        github_created_at=parse_datetime(flat.get("created_at")),
                        github_updated_at=parse_datetime(flat.get("updated_at")),
                    )
                    if was_created:
                        p_ins += 1
                    else:
                        p_upd += 1
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("skip pr file %s: %s", p, e)
                    p_skip += 1
            logger.info(
                "raw prs/: inserted=%s updated=%s skipped=%s",
                p_ins,
                p_upd,
                p_skip,
            )

        logger.info("raw backfill finished root=%s", root)
