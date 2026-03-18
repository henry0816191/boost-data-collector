"""
Management command: run_boost_library_tracker

Runs several tasks in order:
  1. Fetch GitHub activity (main repo boostorg/boost + all submodules)
  2. Export updated issues/PRs as Markdown and push to private GitHub repo
  3. If new version releases exist: collect_boost_libraries (--new-only) and import_boost_dependencies for each new version
  4. Library tracker (stub; to be implemented)
  5. Upsert Boost GitHub issues and PRs to Pinecone (if --pinecone-app-type / env is set)
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from cppa_user_tracker.services import get_or_create_owner_account
from github_activity_tracker.services import (
    ensure_repository_owner,
    get_or_create_repository,
)
from github_activity_tracker.sync import sync_github

from boost_library_tracker.models import BoostVersion
from boost_library_tracker.services import get_or_create_boost_library_repo
from boost_library_tracker.workspace import (
    get_workspace_root as get_boost_workspace_root,
)
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
DEFAULT_PRIVATE_MD_BRANCH = "master"
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
        # e.g. https://github.com/boostorg/algorithm or ../algorithm
        if url.startswith("https://github.com/"):
            parts = url.replace("https://github.com/", "").split("/")
            if len(parts) >= 2:
                result.append((parts[0], parts[1]))
        elif url.startswith("../"):
            # relative: ../algorithm -> boostorg/algorithm
            result.append((MAIN_OWNER, url.replace("../", "")))
    return result


def task_fetch_github_activity(
    self,
    dry_run: bool = False,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    from_library: str | None = None,
    no_upload: bool = False,
) -> list:
    """Fetch GitHub activity for boostorg/boost and all its submodules.

    When no_upload is False: creates MD per repo inside the sync loop, then
    uploads all MD files to the private repo once when sync ends.

    Args:
        dry_run: If True, only show what would be done.
        start_date: Start date for sync (default: auto from DB).
        end_date: End date for sync (default: None = no end; fetcher uses stable cache key).
        from_library: If set, start at this repo (including main when 'boost') and sync it and all after.
            Use 'boost' for main repo or a submodule name (e.g. 'build', 'algorithm'). Default: sync all.
        no_upload: If True, do not generate MD or upload; only sync. If False, generate MD per repo and upload when sync ends.
    """
    self.stdout.write("Task 1: Fetch GitHub activity (main repo + submodules)...")
    if start_date:
        self.stdout.write(f"  From: {start_date.isoformat()}")
    if end_date:
        self.stdout.write(f"  To: {end_date.isoformat()}")
    elif start_date:
        self.stdout.write("  To: no end (open-ended)")
    if from_library:
        self.stdout.write(f"  From library: {from_library} (and all after)")

    client = get_github_client(use="scraping")

    # Resolve owner account for main repo (boostorg)
    try:
        owner_account = get_or_create_owner_account(client, MAIN_OWNER)
    except (ConnectionException, RateLimitException) as e:
        logger.exception("Failed to get owner account %s: %s", MAIN_OWNER, e)
        raise

    # Build list: main repo + submodules (owner, repo_name)
    repos_to_sync = [(MAIN_OWNER, MAIN_REPO)]

    try:
        content, _ = client.get_file_content(MAIN_OWNER, MAIN_REPO, ".gitmodules")
        if content:
            text = content.decode("utf-8")
            submodules = _parse_gitmodules_owner_repo(text)
            for owner, repo_name in submodules:
                if (owner, repo_name) not in repos_to_sync:
                    repos_to_sync.append((owner, repo_name))
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

    # If --from-library is set, start at this repo (including main if NAME is 'boost') and all after
    if from_library:
        from_name = from_library.strip()
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
        self.stdout.write(
            f"  Starting from {repos_to_sync[0][0]}/{repos_to_sync[0][1]} ({len(repos_to_sync)} repo(s))"
        )

    if dry_run:
        self.stdout.write(
            f"  Would sync {len(repos_to_sync)} repo(s): {repos_to_sync[:5]}{'...' if len(repos_to_sync) > 5 else ''}"
        )
        return []

    owner_accounts = {MAIN_OWNER: owner_account}
    synced_repos: list = []
    md_output_dir = None
    all_new_files: dict[str, str] = {}
    if not no_upload:
        md_output_dir = get_boost_workspace_root() / "md_export"
        md_output_dir.mkdir(parents=True, exist_ok=True)
        self.stdout.write(f"  Writing MD to {md_output_dir}")

    for owner, repo_name in repos_to_sync:
        try:
            logger.debug("Syncing %s/%s", owner, repo_name)
            if owner not in owner_accounts:
                owner_accounts[owner] = get_or_create_owner_account(client, owner)
            acc = owner_accounts[owner]
            repo, _ = get_or_create_repository(acc, repo_name)
            ensure_repository_owner(repo, acc)
            boost_repo, _ = get_or_create_boost_library_repo(repo)
            sync_result = sync_github(
                boost_repo, start_date=start_date, end_date=end_date
            )
            synced_repos.append((owner, repo_name, boost_repo, sync_result))
            self.stdout.write(self.style.SUCCESS(f"  Synced {owner}/{repo_name}"))

            # Create MD per repo when no_upload is False
            if md_output_dir is not None:
                issue_numbers = sync_result.get("issues") or []
                pr_numbers = sync_result.get("pull_requests") or []
                if issue_numbers or pr_numbers:
                    folder_prefix = (
                        "boost" if repo_name == "boost" else f"boost.{repo_name}"
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
        except (ConnectionException, RateLimitException) as e:
            logger.exception("Sync failed for %s/%s: %s", owner, repo_name, e)
            raise
        except Exception as e:
            logger.exception("Sync failed for %s/%s: %s", owner, repo_name, e)
            raise

    self.stdout.write(
        self.style.SUCCESS(f"  GitHub activity: synced {len(synced_repos)} repo(s).")
    )

    # When sync ended and we have MD files, upload once to the private repo
    if md_output_dir is not None and all_new_files:
        private_owner = getattr(
            settings, "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_OWNER", ""
        ).strip()
        private_repo = getattr(
            settings, "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_NAME", ""
        ).strip()
        private_branch = (
            getattr(
                settings,
                "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_BRANCH",
                DEFAULT_PRIVATE_MD_BRANCH,
            )
            or DEFAULT_PRIVATE_MD_BRANCH
        ).strip()

        if private_owner and private_repo:
            self.stdout.write(
                f"  Uploading {len(all_new_files)} MD file(s) to private repo..."
            )
            token = get_github_token(use="write")
            delete_paths = detect_renames_from_dirs(
                private_owner,
                private_repo,
                private_branch,
                all_new_files,
                token=token,
            )
            if delete_paths:
                self.stdout.write(
                    f"  Detected {len(delete_paths)} renamed file(s) to delete."
                )
            result = upload_folder_to_github(
                local_folder=md_output_dir,
                owner=private_owner,
                repo=private_repo,
                commit_message="chore: update Boost issues/PRs markdown",
                branch=private_branch,
                delete_paths=delete_paths or None,
            )
            if result.get("success"):
                self.stdout.write(self.style.SUCCESS("  Upload complete."))
                for local_path in all_new_files.values():
                    Path(local_path).unlink(missing_ok=True)
            else:
                msg = result.get("message") or "Upload failed"
                self.stdout.write(self.style.ERROR(f"  Upload failed: {msg}"))
                logger.error("Upload MD failed: %s", msg)
                raise CommandError(msg)
        else:
            logger.error(
                "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_OWNER / _NAME not configured; skipping upload."
            )
    return synced_repos


def task_generate_and_upload_md(
    self,
    synced_repos: list,
    dry_run: bool = False,
    no_upload: bool = False,
) -> None:
    """Convert synced issues/PRs to Markdown and push to private GitHub repo."""
    self.stdout.write("Task 2: Generate Markdown and upload to private repo...")

    if dry_run:
        self.stdout.write("  Dry run: skipping MD generation and upload.")
        return

    if not synced_repos:
        self.stdout.write("  No repos synced; skipping MD generation.")
        return

    md_output_dir = get_boost_workspace_root() / "md_export"
    md_output_dir.mkdir(parents=True, exist_ok=True)
    self.stdout.write(f"  Writing MD to {md_output_dir}")

    all_new_files: dict[str, str] = {}

    for owner, repo_name, _boost_repo, sync_result in synced_repos:
        issue_numbers = sync_result.get("issues") or []
        pr_numbers = sync_result.get("pull_requests") or []

        if not issue_numbers and not pr_numbers:
            logger.debug("No issues/PRs synced for %s/%s; skipping.", owner, repo_name)
            continue

        folder_prefix = "boost" if repo_name == "boost" else f"boost.{repo_name}"
        self.stdout.write(
            f"  Generating MD for {owner}/{repo_name} "
            f"({len(issue_numbers)} issues, {len(pr_numbers)} PRs) → {folder_prefix}/"
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

    if not all_new_files:
        self.stdout.write("  No Markdown files generated; nothing to upload.")
        return

    self.stdout.write(f"  Generated {len(all_new_files)} file(s).")

    if no_upload:
        self.stdout.write("  --no-upload set; skipping GitHub push.")
        return

    private_owner = getattr(
        settings, "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_OWNER", ""
    ).strip()
    private_repo = getattr(
        settings, "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_NAME", ""
    ).strip()
    private_branch = (
        getattr(
            settings,
            "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_BRANCH",
            DEFAULT_PRIVATE_MD_BRANCH,
        )
        or DEFAULT_PRIVATE_MD_BRANCH
    ).strip()
    if not private_owner or not private_repo:
        logger.error(
            "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_OWNER / "
            "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_NAME not configured; skipping upload."
        )
        return

    token = get_github_token(use="write")
    delete_paths = detect_renames_from_dirs(
        private_owner,
        private_repo,
        private_branch,
        all_new_files,
        token=token,
    )
    if delete_paths:
        self.stdout.write(f"  Detected {len(delete_paths)} renamed file(s) to delete.")

    result = upload_folder_to_github(
        local_folder=md_output_dir,
        owner=private_owner,
        repo=private_repo,
        commit_message="chore: update Boost issues/PRs markdown",
        branch=private_branch,
        delete_paths=delete_paths or None,
    )

    if result.get("success"):
        self.stdout.write(self.style.SUCCESS("  Upload complete."))
        for local_path in all_new_files.values():
            Path(local_path).unlink(missing_ok=True)
    else:
        msg = result.get("message") or "Upload failed"
        self.stdout.write(self.style.ERROR(f"  Upload failed: {msg}"))
        logger.error("task_generate_and_upload_md upload failed: %s", msg)
        raise CommandError(msg)


def task_upload_md_only(self, dry_run: bool = False) -> None:
    """Upload existing MD files from workspace/boost_library_tracker/md_export to the private repo (no sync, no generation)."""
    self.stdout.write("Task: Upload existing MD files to private repo...")

    if dry_run:
        self.stdout.write("  Dry run: skipping upload.")
        return

    md_output_dir = get_boost_workspace_root() / "md_export"
    if not md_output_dir.is_dir():
        self.stdout.write(
            self.style.WARNING(
                f"  No md_export folder at {md_output_dir}; nothing to upload."
            )
        )
        return

    all_new_files: dict[str, str] = {}
    for root, _dirs, files in os.walk(md_output_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = Path(root) / name
            repo_rel = path.relative_to(md_output_dir).as_posix()
            all_new_files[repo_rel] = str(path)

    if not all_new_files:
        self.stdout.write(
            self.style.WARNING("  No .md files in md_export; nothing to upload.")
        )
        return

    self.stdout.write(f"  Found {len(all_new_files)} .md file(s) in {md_output_dir}")

    private_owner = getattr(
        settings, "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_OWNER", ""
    ).strip()
    private_repo = getattr(
        settings, "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_NAME", ""
    ).strip()
    private_branch = (
        getattr(
            settings,
            "BOOST_LIBRARY_TRACKER_PRIVATE_REPO_BRANCH",
            DEFAULT_PRIVATE_MD_BRANCH,
        )
        or DEFAULT_PRIVATE_MD_BRANCH
    ).strip()

    if not private_owner or not private_repo:
        logger.error("BOOST_LIBRARY_TRACKER_PRIVATE_REPO_OWNER / _NAME not configured.")
        self.stdout.write(
            self.style.ERROR(
                "  Private repo not configured; set BOOST_LIBRARY_TRACKER_PRIVATE_REPO_OWNER and _NAME."
            )
        )
        return

    token = get_github_token(use="write")
    delete_paths = detect_renames_from_dirs(
        private_owner,
        private_repo,
        private_branch,
        all_new_files,
        token=token,
    )
    if delete_paths:
        self.stdout.write(f"  Detected {len(delete_paths)} renamed file(s) to delete.")

    result = upload_folder_to_github(
        local_folder=md_output_dir,
        owner=private_owner,
        repo=private_repo,
        commit_message="chore: update Boost issues/PRs markdown",
        branch=private_branch,
        delete_paths=delete_paths or None,
    )

    if result.get("success"):
        self.stdout.write(self.style.SUCCESS("  Upload complete."))
        for local_path in all_new_files.values():
            Path(local_path).unlink(missing_ok=True)
    else:
        msg = result.get("message") or "Upload failed"
        self.stdout.write(self.style.ERROR(f"  Upload failed: {msg}"))
        logger.error("task_upload_md_only failed: %s", msg)
        raise CommandError(msg)


def task_collect_libraries(self, ref: str, dry_run: bool = False) -> None:
    """Collect all Boost libraries from .gitmodules + meta/libraries.json per lib submodule."""
    self.stdout.write("Task 3: Collect all Boost libraries...")
    if dry_run:
        call_command(
            "collect_boost_libraries",
            ref=ref,
            dry_run=True,
            stdout=self.stdout,
            stderr=self.stderr,
        )
        return
    call_command(
        "collect_boost_libraries",
        ref=ref,
        stdout=self.stdout,
        stderr=self.stderr,
    )


def task_collect_and_import_if_new_releases(self, dry_run: bool = False) -> None:
    """
    If there are new releases (not in BoostVersion): run collect_boost_libraries --new-only,
    then import_boost_dependencies for each new version.
    """
    self.stdout.write(
        "Checking for new releases and running collect + import if any..."
    )
    if dry_run:
        self.stdout.write(
            "  Would run collect_boost_libraries (new-only) then import_boost_dependencies for new versions."
        )
        return

    existing_versions = set(BoostVersion.objects.values_list("version", flat=True))
    call_command(
        "collect_boost_libraries",
        new_only=True,
        stdout=self.stdout,
        stderr=self.stderr,
    )
    current_versions = set(BoostVersion.objects.values_list("version", flat=True))
    new_versions = sorted(current_versions - existing_versions)

    if not new_versions:
        self.stdout.write(
            self.style.SUCCESS("No new releases; skipping import_boost_dependencies.")
        )
        return

    self.stdout.write(
        self.style.SUCCESS(
            f"New version(s): {len(new_versions)}. Running import_boost_dependencies for each."
        )
    )
    for tag in new_versions:
        self.stdout.write(f"  Importing dependencies for {tag}...")
        call_command(
            "import_boost_dependencies",
            boost_version=tag,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def task_library_tracker(self, dry_run: bool = False) -> None:
    """Library tracker (versions, dependencies, etc.). Stub for now."""
    self.stdout.write("Task 4: Library tracker (stub)...")
    if not dry_run:
        pass  # TODO: implement


def _run_pinecone_sync(
    app_type: str, namespace: str, preprocessor_dotted_path: str
) -> None:
    """Trigger run_cppa_pinecone_sync if app_type and namespace are both set."""
    if not app_type:
        logger.warning("Pinecone sync skipped: --pinecone-app-type is empty.")
        return
    if not namespace:
        logger.warning(
            "Pinecone sync skipped: namespace is empty (set --pinecone-namespace or %s).",
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
            "run_boost_library_tracker: pinecone sync completed (app_type=%s, namespace=%s)",
            app_type,
            namespace,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Pinecone sync skipped/failed (run_cppa_pinecone_sync unavailable or errored): %s",
            exc,
        )


def task_pinecone_sync(
    self, app_type: str, namespace: str, dry_run: bool = False
) -> None:
    """Upsert Boost GitHub issues and PRs to Pinecone."""
    self.stdout.write("Task 4: Upsert Boost GitHub issues and PRs to Pinecone...")
    if dry_run:
        self.stdout.write("  Would run Pinecone sync for issues and PRs.")
        return

    from boost_library_tracker.preprocessors.issue_preprocessor import (
        APP_TYPE as ISSUES_APP_TYPE,
        NAMESPACE as ISSUES_NAMESPACE,
    )

    effective_app_type = app_type or ISSUES_APP_TYPE
    effective_namespace = namespace or ISSUES_NAMESPACE
    _run_pinecone_sync(
        effective_app_type,
        effective_namespace,
        "boost_library_tracker.preprocessors.issue_preprocessor.preprocess_for_pinecone",
    )
    _run_pinecone_sync(
        effective_app_type,
        effective_namespace,
        "boost_library_tracker.preprocessors.pr_preprocessor.preprocess_for_pinecone",
    )


class Command(BaseCommand):
    """Run the Boost Library Tracker pipeline: GitHub sync, collect/import if new releases, library tracker."""

    help = (
        "Run Boost Library Tracker: (1) GitHub activity for boostorg/boost + submodules; "
        "(2) if new releases exist, collect_boost_libraries and import_boost_dependencies; "
        "(3) library tracker stub, etc."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show what would be done (e.g. repo list); do not sync.",
        )
        parser.add_argument(
            "--ref",
            type=str,
            default="develop",
            help="Ref for task collect_libraries (.gitmodules and meta/libraries.json). Default: develop.",
        )
        parser.add_argument(
            "--task",
            type=str,
            default=None,
            help=(
                "Run only this task: 'github_activity', 'upload_md' (upload existing MD only), "
                "'collect_and_import_if_new', 'collect_libraries', 'library_tracker', or 'pinecone_sync'. Default: run all."
            ),
        )
        parser.add_argument(
            "--from-date",
            type=str,
            default=None,
            help="Start date for sync (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). Default: auto from DB.",
        )
        parser.add_argument(
            "--to-date",
            type=str,
            default=None,
            help="End date for sync (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). Default: None (no end; fetcher uses stable cache key).",
        )
        parser.add_argument(
            "--from-library",
            type=str,
            default=None,
            metavar="NAME",
            help="Start at this repo (including the main repo when NAME is 'boost') and sync it and all after. "
            "Use 'boost' for main repo or a submodule name (e.g. 'build', 'algorithm'). Default: sync all.",
        )
        parser.add_argument(
            "--no-upload",
            action="store_true",
            help="Generate Markdown files but skip pushing to GitHub (useful for inspection).",
        )
        parser.add_argument(
            "--pinecone-app-type",
            type=str,
            default=settings.BOOST_GITHUB_PINECONE_APP_TYPE,
            help="App type passed to run_cppa_pinecone_sync. Default from env BOOST_GITHUB_PINECONE_APP_TYPE.",
        )
        parser.add_argument(
            "--pinecone-namespace",
            type=str,
            default=settings.BOOST_GITHUB_PINECONE_NAMESPACE,
            help=f"Pinecone namespace for sync. Default from env {PINECONE_NAMESPACE_ENV_KEY}.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        ref = (options.get("ref") or "develop").strip()
        task_filter = (options["task"] or "").strip().lower()
        no_upload = options.get("no_upload", False)
        pinecone_app_type = (
            options.get("pinecone_app_type") or ""
        ).strip() or settings.BOOST_GITHUB_PINECONE_APP_TYPE
        pinecone_namespace = (
            options.get("pinecone_namespace") or ""
        ).strip() or settings.BOOST_GITHUB_PINECONE_NAMESPACE

        valid_tasks = {
            "",
            "upload_md",
            "github_activity",
            "collect_and_import_if_new",
            "collect_libraries",
            "library_tracker",
            "pinecone_sync",
        }
        if task_filter not in valid_tasks:
            self.stderr.write(
                self.style.ERROR(
                    "Invalid --task. Use one of: github_activity, upload_md, "
                    "collect_and_import_if_new, collect_libraries, library_tracker, pinecone_sync."
                )
            )
            return

        # Parse date arguments
        start_date = None
        end_date = None
        if options.get("from_date"):
            try:
                start_date = datetime.fromisoformat(options["from_date"])
            except ValueError as e:
                self.stderr.write(
                    self.style.WARNING(f"Invalid --from-date format: {e}")
                )
                start_date = None
        if options.get("to_date"):
            try:
                end_date = datetime.fromisoformat(options["to_date"])
            except ValueError as e:
                self.stderr.write(self.style.WARNING(f"Invalid --to-date format: {e}"))
                end_date = None

        # Normalize to UTC-naive so comparison never mixes aware and naive
        if start_date and start_date.tzinfo:
            start_date = start_date.astimezone(timezone.utc).replace(tzinfo=None)
        if end_date and end_date.tzinfo:
            end_date = end_date.astimezone(timezone.utc).replace(tzinfo=None)

        if start_date and end_date and start_date > end_date:
            self.stderr.write(
                self.style.WARNING(
                    f"Invalid date range: start_date ({start_date.isoformat()}) is after "
                    f"end_date ({end_date.isoformat()}); falling back to defaults."
                )
            )
            start_date = None
            end_date = None

        from_library = (options.get("from_library") or "").strip() or None
        logger.debug(
            "run_boost_library_tracker: starting (dry_run=%s, ref=%s, task=%s, from=%s, to=%s, from_library=%s)",
            dry_run,
            ref,
            task_filter or "all",
            start_date.isoformat() if start_date else "auto",
            end_date.isoformat() if end_date else "none",
            from_library or "all",
        )

        try:
            synced_repos = []
            if task_filter == "upload_md":
                task_upload_md_only(self, dry_run=dry_run)
                self.stdout.write(
                    self.style.SUCCESS(
                        "run_boost_library_tracker: finished successfully"
                    )
                )
                return
            if not task_filter or task_filter == "github_activity":
                synced_repos = task_fetch_github_activity(
                    self,
                    dry_run=dry_run,
                    start_date=start_date,
                    end_date=end_date,
                    from_library=from_library,
                    no_upload=no_upload,
                )
            # When no_upload is True, generate MD to a temp dir for inspection (upload already skipped in task_fetch_github_activity)
            if (
                (not task_filter or task_filter in ("github_activity", "upload_md"))
                and no_upload
                and synced_repos
            ):
                task_generate_and_upload_md(
                    self,
                    synced_repos=synced_repos,
                    dry_run=dry_run,
                    no_upload=True,
                )
            if not task_filter or task_filter == "collect_and_import_if_new":
                task_collect_and_import_if_new_releases(self, dry_run=dry_run)
            if task_filter == "collect_libraries":
                task_collect_libraries(self, ref=ref, dry_run=dry_run)
            if not task_filter or task_filter == "library_tracker":
                task_library_tracker(self, dry_run=dry_run)
            if not task_filter or task_filter == "pinecone_sync":
                task_pinecone_sync(
                    self,
                    app_type=pinecone_app_type,
                    namespace=pinecone_namespace,
                    dry_run=dry_run,
                )

            self.stdout.write(
                self.style.SUCCESS("run_boost_library_tracker: finished successfully")
            )
            logger.debug("run_boost_library_tracker: finished successfully")
        except Exception as e:
            logger.exception("run_boost_library_tracker failed: %s", e)
            raise
