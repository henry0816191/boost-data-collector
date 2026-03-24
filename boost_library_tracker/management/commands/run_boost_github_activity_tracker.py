"""
Management command: run_boost_github_activity_tracker

Runs several tasks in order:
  1. Fetch GitHub activity (main repo boostorg/boost + all submodules)
  2. Export updated issues/PRs as Markdown.
  3. Push markdown files to GitHub repo
  4. Upsert Boost GitHub issues and PRs to Pinecone
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path

import requests
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from core.utils.datetime_parsing import parse_iso_datetime
from cppa_user_tracker.services import get_or_create_owner_account
from github_activity_tracker.services import (
    ensure_repository_owner,
    get_or_create_repository,
)
from github_activity_tracker.sync import sync_github

from boost_library_tracker.services import get_or_create_boost_library_repo
from boost_library_tracker.workspace import get_md_export_dir
from github_ops import (
    get_github_client,
    get_github_token,
    upload_folder_to_github,
)
from github_ops.client import ConnectionException, RateLimitException
from operations.md_ops.github_export import (
    detect_renames_from_dirs,
    write_md_files,
)

logger = logging.getLogger(__name__)

MAIN_OWNER = "boostorg"
MAIN_REPO = "boost"
DEFAULT_MARKDOWN_REPO_BRANCH = "master"
PINECONE_NAMESPACE_ENV_KEY = "BOOST_GITHUB_PINECONE_NAMESPACE"


def _parse_gitmodules_owner_repo(
    gitmodules_content: str,
) -> list[tuple[str, str]]:
    """Parse .gitmodules content and return list of (owner, repo) from each url."""
    result = []
    for line in gitmodules_content.split("\n"):
        line = line.strip()
        if not line.startswith("url ="):
            continue
        url = line.split("=", 1)[1].strip().replace(".git", "").rstrip("/")
        if url.startswith("https://github.com/"):
            parts = url.replace("https://github.com/", "").split("/")
            if len(parts) >= 2:
                result.append((parts[0], parts[1]))
        elif url.startswith("../"):
            result.append((MAIN_OWNER, url.replace("../", "")))
    return result


def _markdown_export_repo_config() -> tuple[str, str, str] | None:
    """Return (owner, repo, branch) for Markdown upload, or None if not configured."""
    owner = getattr(settings, "BOOST_LIBRARY_TRACKER_REPO_OWNER", "").strip()
    repo = getattr(settings, "BOOST_LIBRARY_TRACKER_REPO_NAME", "").strip()
    branch = (
        getattr(
            settings,
            "BOOST_LIBRARY_TRACKER_REPO_BRANCH",
            DEFAULT_MARKDOWN_REPO_BRANCH,
        )
        or DEFAULT_MARKDOWN_REPO_BRANCH
    ).strip()
    if not owner or not repo:
        return None
    return owner, repo, branch


def _generate_markdown_for_synced(
    synced_repos: list,
    md_output_dir: Path,
) -> dict[str, str]:
    """Write Markdown for issues/PRs touched in sync_result; return repo-relative -> local path."""
    all_new_files: dict[str, str] = {}
    for owner, repo_name, _boost_repo, sync_result in synced_repos:
        issue_numbers = sync_result.get("issues") or []
        pr_numbers = sync_result.get("pull_requests") or []
        if not issue_numbers and not pr_numbers:
            logger.debug("No issues/PRs synced for %s/%s; skipping.", owner, repo_name)
            continue
        folder_prefix = "boost" if repo_name == "boost" else f"boost.{repo_name}"
        logger.info(
            "generating MD for %s/%s (%d issues, %d PRs) → %s/",
            owner,
            repo_name,
            len(issue_numbers),
            len(pr_numbers),
            folder_prefix,
        )
        new_files = write_md_files(
            owner=owner,
            repo=repo_name,
            issue_numbers=issue_numbers,
            pr_numbers=pr_numbers,
            output_dir=md_output_dir,
            folder_prefix=folder_prefix,
        )
        all_new_files.update(new_files)
    return all_new_files


def _push_markdown_to_github(
    md_output_dir: Path,
    all_new_files: dict[str, str],
) -> None:
    """Upload generated Markdown to BOOST_LIBRARY_TRACKER_REPO_*; unlink locals on success."""
    if not all_new_files:
        return
    cfg = _markdown_export_repo_config()
    if not cfg:
        logger.error(
            "BOOST_LIBRARY_TRACKER_REPO_OWNER / BOOST_LIBRARY_TRACKER_REPO_NAME "
            "not configured; skipping upload."
        )
        return
    owner, repo, branch = cfg
    logger.info(
        "uploading %d MD file(s) to %s/%s",
        len(all_new_files),
        owner,
        repo,
    )
    token = get_github_token(use="write")
    delete_paths = detect_renames_from_dirs(
        owner,
        repo,
        branch,
        all_new_files,
        token=token,
    )
    if delete_paths:
        for repo_rel in delete_paths:
            stale_local = md_output_dir / repo_rel
            if stale_local.exists():
                stale_local.unlink()
        logger.info("detected %d renamed file(s) to delete", len(delete_paths))

    result = upload_folder_to_github(
        local_folder=md_output_dir,
        owner=owner,
        repo=repo,
        commit_message="chore: update Boost issues/PRs markdown",
        branch=branch,
        delete_paths=delete_paths or None,
    )
    if result.get("success"):
        logger.info("Markdown upload complete")
        for entry in list(md_output_dir.iterdir()):
            if entry.is_file():
                entry.unlink(missing_ok=True)
            else:
                shutil.rmtree(entry)
    else:
        msg = result.get("message") or "Upload failed"
        logger.error("upload MD failed: %s", msg)
        raise CommandError(msg)


def task_fetch_github_activity(
    dry_run: bool = False,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    from_repo: str | None = None,
) -> list:
    """Sync GitHub activity for boostorg/boost and all submodules (DB only; no MD/upload)."""
    logger.info("fetch GitHub activity (main repo + submodules)")
    if start_date:
        logger.info("sync from %s", start_date.isoformat())
    if end_date:
        logger.info("sync to %s", end_date.isoformat())
    elif start_date:
        logger.info("sync to no end (open-ended)")
    if from_repo:
        logger.info("from repo %s (and all after)", from_repo)

    client = get_github_client(use="scraping")

    try:
        owner_account = get_or_create_owner_account(client, MAIN_OWNER)
    except (ConnectionException, RateLimitException) as e:
        logger.exception("Failed to get owner account %s: %s", MAIN_OWNER, e)
        raise

    repos_to_sync = [(MAIN_OWNER, MAIN_REPO)]

    try:
        content, _ = client.get_file_content(MAIN_OWNER, MAIN_REPO, ".gitmodules")
        if content:
            text = content.decode("utf-8")
            submodules = _parse_gitmodules_owner_repo(text)
            for own, repo_name in submodules:
                if (own, repo_name) not in repos_to_sync:
                    repos_to_sync.append((own, repo_name))
            logger.debug(
                "Found %d submodules; total repos to sync: %d",
                len(submodules),
                len(repos_to_sync),
            )
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.debug(
                "No .gitmodules in %s/%s; syncing main repo only",
                MAIN_OWNER,
                MAIN_REPO,
            )
        else:
            raise
    except Exception as e:
        logger.warning("Could not fetch .gitmodules: %s; syncing main repo only", e)

    if from_repo:
        from_name = from_repo.strip()
        idx = None
        for i, (_owner, repo_name) in enumerate(repos_to_sync):
            if repo_name == from_name:
                idx = i
                break
        if idx is None:
            logger.warning(
                "No submodule/repo with name '%s' found in repo list; starting from first (idx=0).",
                from_name,
            )
            idx = 0
        repos_to_sync = repos_to_sync[idx:]
        logger.info(
            "starting from %s/%s (%d repo(s))",
            repos_to_sync[0][0],
            repos_to_sync[0][1],
            len(repos_to_sync),
        )

    if dry_run:
        logger.info(
            "dry-run would sync %d repo(s): %s%s",
            len(repos_to_sync),
            repos_to_sync[:5],
            "..." if len(repos_to_sync) > 5 else "",
        )
        return []

    owner_accounts = {MAIN_OWNER: owner_account}
    synced_repos: list = []

    for own, repo_name in repos_to_sync:
        try:
            logger.debug("Syncing %s/%s", own, repo_name)
            if own not in owner_accounts:
                owner_accounts[own] = get_or_create_owner_account(client, own)
            acc = owner_accounts[own]
            repo, _ = get_or_create_repository(acc, repo_name)
            ensure_repository_owner(repo, acc)
            boost_repo, _ = get_or_create_boost_library_repo(repo)
            sync_result = sync_github(
                boost_repo, start_date=start_date, end_date=end_date
            )
            synced_repos.append((own, repo_name, boost_repo, sync_result))
            logger.info("synced %s/%s", own, repo_name)
        except (ConnectionException, RateLimitException) as e:
            logger.exception("Sync failed for %s/%s: %s", own, repo_name, e)
            raise
        except Exception as e:
            logger.exception("Sync failed for %s/%s: %s", own, repo_name, e)
            raise

    logger.info("GitHub activity synced %d repo(s)", len(synced_repos))
    return synced_repos


def _run_pinecone_sync(
    app_type: str, namespace: str, preprocessor_dotted_path: str
) -> None:
    if not app_type:
        logger.warning(
            "Pinecone sync skipped: BOOST_GITHUB_PINECONE_APP_TYPE is empty (settings/env)."
        )
        return
    if not namespace:
        logger.warning(
            "Pinecone sync skipped: namespace is empty (set %s or Django setting).",
            PINECONE_NAMESPACE_ENV_KEY,
        )
        return
    try:
        call_command(
            "run_cppa_pinecone_sync",
            app_type=app_type,
            namespace=namespace,
            preprocessor=preprocessor_dotted_path,
        )
        logger.info(
            "pinecone sync completed (app_type=%s, namespace=%s)",
            app_type,
            namespace,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Pinecone sync skipped/failed (run_cppa_pinecone_sync unavailable or errored): %s",
            exc,
        )


def task_pinecone_sync(dry_run: bool = False) -> None:
    """Upsert Boost GitHub issues and PRs to Pinecone (app_type / namespace from settings)."""
    logger.info("Pinecone upsert (issues and PRs)")
    if dry_run:
        logger.info("dry-run would run Pinecone sync for issues and PRs")
        return

    from boost_library_tracker.preprocessors.issue_preprocessor import (
        APP_TYPE as ISSUES_APP_TYPE,
        NAMESPACE as ISSUES_NAMESPACE,
    )

    app_type = (settings.BOOST_GITHUB_PINECONE_APP_TYPE or "").strip()
    namespace = (settings.BOOST_GITHUB_PINECONE_NAMESPACE or "").strip()
    effective_app_type = app_type or ISSUES_APP_TYPE
    effective_namespace = namespace or ISSUES_NAMESPACE
    _run_pinecone_sync(
        f"{effective_app_type}-issues",
        effective_namespace,
        "boost_library_tracker.preprocessors.issue_preprocessor.preprocess_for_pinecone",
    )
    _run_pinecone_sync(
        f"{effective_app_type}-prs",
        effective_namespace,
        "boost_library_tracker.preprocessors.pr_preprocessor.preprocess_for_pinecone",
    )


class Command(BaseCommand):
    """Sync Boost GitHub activity, export issues/PRs as Markdown, push to repo, Pinecone upsert."""

    help = (
        "Boost GitHub activity tracker: (1) sync boostorg/boost + submodules; "
        "(2) export updated issues/PRs as Markdown; (3) push to BOOST_LIBRARY_TRACKER_REPO_*; "
        "(4) Pinecone upsert (BOOST_GITHUB_PINECONE_* settings). Use --skip-* to skip steps; default runs all."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No sync, export, push, or Pinecone writes; planned steps are logged at INFO.",
        )
        parser.add_argument(
            "--skip-github-sync",
            action="store_true",
            help="Skip step 1 (no sync_github / API fetch for boostorg/boost and submodules).",
        )
        parser.add_argument(
            "--skip-markdown-export",
            action="store_true",
            help="Skip writing .md files from this run's sync results.",
        )
        parser.add_argument(
            "--skip-remote-push",
            action="store_true",
            help="Skip uploading Markdown to BOOST_LIBRARY_TRACKER_REPO_*.",
        )
        parser.add_argument(
            "--skip-pinecone",
            action="store_true",
            help="Skip run_cppa_pinecone_sync for issues and PRs.",
        )
        parser.add_argument(
            "--since",
            "--from-date",
            "--start-time",
            type=str,
            default=None,
            dest="since",
            help="Sync window start: YYYY-MM-DD or ISO-8601 datetime (UTC offset allowed). "
            "Date-only is midnight that day (naive UTC after normalization). "
            "--from-date is a deprecated alias; --start-time is an alias for --since.",
        )
        parser.add_argument(
            "--until",
            "--to-date",
            "--end-time",
            type=str,
            default=None,
            dest="until",
            help="Sync window end: same formats as --since. "
            "--to-date is a deprecated alias; --end-time is an alias for --until.",
        )
        parser.add_argument(
            "--from-repo",
            "--from-library",
            type=str,
            default=None,
            metavar="NAME",
            dest="from_repo",
            help="Start sync at this repository in the ordered list: `boost` or a submodule name from .gitmodules. "
            "`--from-library` is a deprecated alias.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        skip_github_sync = options["skip_github_sync"]
        skip_markdown_export = options["skip_markdown_export"]
        skip_remote_push = options["skip_remote_push"]
        skip_pinecone = options["skip_pinecone"]
        from_repo = (options.get("from_repo") or "").strip() or None

        try:
            start_date = parse_iso_datetime(options.get("since"))
            end_date = parse_iso_datetime(options.get("until"))
        except ValueError as e:
            raise CommandError(str(e)) from e

        if start_date and end_date and start_date > end_date:
            logger.warning(
                "invalid date range: since (%s) is after until (%s); falling back to defaults",
                start_date.isoformat(),
                end_date.isoformat(),
            )
            start_date = None
            end_date = None

        logger.debug(
            "starting (dry_run=%s, skip_sync=%s, skip_md=%s, skip_push=%s, skip_pinecone=%s, since=%s, until=%s, from_repo=%s)",
            dry_run,
            skip_github_sync,
            skip_markdown_export,
            skip_remote_push,
            skip_pinecone,
            start_date.isoformat() if start_date else "auto",
            end_date.isoformat() if end_date else "none",
            from_repo or "all",
        )

        try:
            if dry_run:
                if not skip_github_sync:
                    task_fetch_github_activity(
                        dry_run=True,
                        start_date=start_date,
                        end_date=end_date,
                        from_repo=from_repo,
                    )
                else:
                    logger.info("dry-run skipping GitHub sync (--skip-github-sync)")
                if not skip_markdown_export:
                    logger.info(
                        "dry-run would export Markdown for issues/PRs touched in sync"
                    )
                if not skip_remote_push:
                    logger.info(
                        "dry-run would push Markdown to BOOST_LIBRARY_TRACKER_REPO_*"
                    )
                if not skip_pinecone:
                    logger.info("dry-run would run Pinecone upsert for issues and PRs")
                logger.info("finished successfully")
                return

            synced_repos: list = []
            if not skip_github_sync:
                synced_repos = task_fetch_github_activity(
                    dry_run=False,
                    start_date=start_date,
                    end_date=end_date,
                    from_repo=from_repo,
                )
            else:
                logger.info("skipping GitHub sync (--skip-github-sync)")

            md_output_dir = get_md_export_dir()
            all_new_files: dict[str, str] = {}

            if not skip_markdown_export:
                logger.info("export updated issues/PRs as Markdown")
                if synced_repos:
                    logger.info("writing MD to %s", md_output_dir)
                    all_new_files = _generate_markdown_for_synced(
                        synced_repos, md_output_dir
                    )
                    if all_new_files:
                        logger.info("generated %d Markdown file(s)", len(all_new_files))
                    else:
                        logger.info(
                            "no Markdown files generated (no issues/PRs in sync results)"
                        )
                elif skip_github_sync:
                    logger.info("skipped Markdown export (no sync in this run)")
                else:
                    logger.info("no repos synced; skipping Markdown export")

            if not skip_remote_push:
                logger.info("push Markdown to configured GitHub repo")
                if not all_new_files:
                    if skip_markdown_export and not skip_github_sync:
                        logger.warning(
                            "nothing new to push (--skip-markdown-export); skipping remote push"
                        )
                    elif skip_github_sync:
                        logger.warning(
                            "nothing to push from this run (sync was skipped)"
                        )
                else:
                    _push_markdown_to_github(md_output_dir, all_new_files)
            else:
                logger.info("skipping remote push (--skip-remote-push)")

            if not skip_pinecone:
                task_pinecone_sync(dry_run=False)
            else:
                logger.info("skipping Pinecone (--skip-pinecone)")

            logger.info("finished successfully")
        except Exception as e:
            logger.exception("command failed: %s", e)
            raise
