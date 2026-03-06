"""
Management command: collect_boost_libraries

Collects Boost versions (releases) from boostorg/boost and library metadata
for each version. For each release, fetches .gitmodules to find libs/ submodules,
then meta/libraries.json from each submodule to collect library names, descriptions,
authors, maintainers, categories, and C++ standard requirements.

Creates:
- BoostVersion rows for each release
- BoostLibrary rows for each library (if not exists)
- BoostLibraryVersion rows with full metadata
- BoostLibraryRoleRelationship for authors/maintainers
- BoostLibraryCategoryRelationship for categories
"""

import logging
from datetime import datetime

import requests
from django.core.management.base import BaseCommand
from django.db import transaction

from boost_library_tracker.models import (
    BoostLibrary,
    BoostLibraryRepository,
    BoostLibraryVersion,
    BoostVersion,
)
from boost_library_tracker.parsing import (
    parse_gitmodules_lib_submodules,
    parse_libraries_json_full,
)
from boost_library_tracker.services import (
    add_library_category,
    add_library_version_role,
    get_or_create_account_from_name,
    get_or_create_boost_library,
    get_or_create_boost_library_category,
    get_or_create_boost_library_version,
    get_or_create_boost_version,
)
from github_ops.client import GitHubAPIClient
from github_ops.tokens import get_github_token

logger = logging.getLogger(__name__)

MAIN_OWNER = "boostorg"
MAIN_REPO = "boost"

RAW_GITMODULES_URL = (
    "https://raw.githubusercontent.com/boostorg/boost/{ref}/.gitmodules"
)
RAW_LIBS_JSON_URL = "https://raw.githubusercontent.com/boostorg/{submodule_name}/{ref}/meta/libraries.json"
FETCH_TIMEOUT = 30


def _normalize_ref(ref: str) -> str:
    """If ref is a numeric short form (e.g. 90, 89), return boost-1.90.0, boost-1.89.0."""
    if ref.isdigit():
        return f"boost-1.{ref}.0"
    return ref


def _fetch_raw_url(url: str) -> bytes | None:
    """Fetch URL and return response body, or None on failure."""
    try:
        resp = requests.get(url, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as e:
        logger.warning("Fetch failed %s: %s", url, e)
        return None


def _fetch_releases(client: GitHubAPIClient) -> list[dict]:
    """Fetch all releases from boostorg/boost using GitHub API."""
    releases = []
    page = 1
    per_page = 100

    while True:
        try:
            page_releases = client.rest_request(
                f"/repos/{MAIN_OWNER}/{MAIN_REPO}/releases",
                params={"per_page": per_page, "page": page},
            )
            if not page_releases:
                break
            releases.extend(page_releases)
            if len(page_releases) < per_page:
                break
            page += 1
        except Exception as e:
            logger.error(f"Failed to fetch releases page {page}: {e}")
            break

    return releases


def _collect_libraries_for_version(
    boost_version, ref: str, *, dry_run: bool = False
) -> tuple[int, int]:
    """
    Fetch .gitmodules from boostorg/boost at ref, then for each lib submodule
    fetch meta/libraries.json from raw URL and create BoostLibraryVersion records
    with full metadata (description, authors, maintainers, categories, cxxstd).

    When dry_run is True, no DB writes; returns (would_create_count, submodules_processed)
    by checking existing BoostLibraryVersion rows. Otherwise returns (library_versions_created, submodules_processed).

    Returns (library_versions_created, submodules_processed).
    """
    gitmodules_url = RAW_GITMODULES_URL.format(ref=ref)
    content = _fetch_raw_url(gitmodules_url)
    if not content:
        logger.warning(f"Could not fetch .gitmodules for {ref}")
        return 0, 0
    try:
        gitmodules_text = content.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Could not decode .gitmodules for %s", ref)
        return 0, 0
    lib_submodules = parse_gitmodules_lib_submodules(gitmodules_text)

    version_obj = BoostVersion.objects.filter(version=ref).first() if dry_run else None
    created_total = 0
    for submodule_name, _path_in_boost in lib_submodules:
        boost_repo = BoostLibraryRepository.objects.filter(
            owner_account__username=MAIN_OWNER,
            repo_name=submodule_name,
        ).first()
        if not boost_repo:
            logger.debug(
                "Skipping submodule %s: no BoostLibraryRepository",
                submodule_name,
            )
            continue

        libs_json_url = RAW_LIBS_JSON_URL.format(submodule_name=submodule_name, ref=ref)
        raw = _fetch_raw_url(libs_json_url)
        if not raw:
            continue

        lib_data_list = parse_libraries_json_full(raw, submodule_name)

        for lib_data in lib_data_list:
            if dry_run:
                lib_name = lib_data["name"]
                library = BoostLibrary.objects.filter(
                    repo=boost_repo, name=lib_name
                ).first()
                if version_obj is None:
                    created_total += 1
                elif library is None:
                    created_total += 1
                elif not BoostLibraryVersion.objects.filter(
                    library=library, version=version_obj
                ).exists():
                    created_total += 1
                continue
            lib_name = lib_data["name"]
            description = lib_data["description"]
            key = lib_data.get("key", "")
            documentation = lib_data.get("documentation", "")
            cxxstd = lib_data["cxxstd"]
            authors = lib_data["authors"]
            maintainers = lib_data["maintainers"]
            categories = lib_data["category"]

            boost_library, _ = get_or_create_boost_library(boost_repo, lib_name)

            lib_version, created = get_or_create_boost_library_version(
                library=boost_library,
                version=boost_version,
                cpp_version=cxxstd,
                description=description,
                key=key,
                documentation=documentation,
            )
            if created:
                created_total += 1

            for author_name in authors:
                account = get_or_create_account_from_name(author_name)
                add_library_version_role(
                    library_version=lib_version,
                    account=account,
                    is_author=True,
                )

            for maintainer_name in maintainers:
                account = get_or_create_account_from_name(maintainer_name)
                add_library_version_role(
                    library_version=lib_version,
                    account=account,
                    is_maintainer=True,
                )

            for category_name in categories:
                category, _ = get_or_create_boost_library_category(category_name)
                add_library_category(boost_library, category)

    return created_total, len(lib_submodules)


class Command(BaseCommand):
    """Management command: collect Boost versions and library metadata."""

    help = (
        "Collect Boost versions (releases) from boostorg/boost and library metadata "
        "for each version. Creates BoostVersion, BoostLibraryVersion, and related records."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--ref",
            type=str,
            help="Collect libraries for a single ref (e.g., boost-1.84.0)",
        )
        parser.add_argument(
            "--refs",
            type=str,
            help="Comma-separated refs to process (e.g. 90,89 or boost-1.90.0,boost-1.89.0)",
        )
        parser.add_argument(
            "--new-only",
            action="store_true",
            help="Only process releases not yet in BoostVersion (default when no --ref/--refs)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="process_all",
            help="Process all releases from API (default without this is new-only)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit number of versions to process (processes newest first)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and report what would be done; no DB writes.",
        )

    def handle(self, *_args, **options):
        try:
            token = get_github_token(use="scraping")
        except ValueError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return
        if not token:
            self.stdout.write(self.style.ERROR("No GitHub token available"))
            return

        dry_run = options.get("dry_run", False)
        if dry_run:
            self.stdout.write("Dry run: no DB writes.")

        client = GitHubAPIClient(token)
        limit = options.get("limit")
        refs_arg = options.get("refs")
        ref_arg = options.get("ref")
        process_all = options.get("process_all", False)
        new_only_flag = options.get("new_only", False)
        if process_all and new_only_flag:
            self.stdout.write(
                self.style.ERROR("Use either --all or --new-only, not both.")
            )
            return

        refs_list = None
        if refs_arg:
            refs_list = [
                _normalize_ref(r.strip()) for r in refs_arg.split(",") if r.strip()
            ]
        elif ref_arg:
            refs_list = [_normalize_ref(ref_arg.strip())]

        if refs_list:
            self._process_refs(refs_list, dry_run=dry_run)
            return

        new_only = new_only_flag or not process_all
        self.stdout.write("Fetching all releases from boostorg/boost...")
        releases = _fetch_releases(client)
        if not releases:
            self.stdout.write(self.style.WARNING("No releases found"))
            return

        if new_only:
            existing_versions = set(
                BoostVersion.objects.values_list("version", flat=True)
            )
            releases = [
                r for r in releases if r.get("tag_name") not in existing_versions
            ]
            self.stdout.write(
                f"Processing {len(releases)} new release(s) (not in BoostVersion)"
            )
        else:
            self.stdout.write(f"Found {len(releases)} releases")

        if limit:
            releases = releases[:limit]
            self.stdout.write(f"Processing first {limit} releases")

        total_versions_created = 0
        total_lib_versions_created = 0
        for release in releases:
            tag_name = release.get("tag_name", "")
            if not tag_name:
                continue
            published_at_str = release.get("published_at")
            published_at = None
            if published_at_str:
                try:
                    published_at = datetime.fromisoformat(
                        published_at_str.replace("Z", "+00:00")
                    )
                except Exception as e:
                    logger.warning(f"Could not parse date {published_at_str}: {e}")

            if dry_run:
                lib_created, submodules = _collect_libraries_for_version(
                    None, tag_name, dry_run=True
                )
                total_lib_versions_created += lib_created
                version_exists = BoostVersion.objects.filter(version=tag_name).exists()
                if not version_exists:
                    total_versions_created += 1
                    self.stdout.write(f"Would create BoostVersion: {tag_name}")
                self.stdout.write(
                    f"  {tag_name}: {lib_created} library version(s) would be created from {submodules} submodules"
                )
                continue
            try:
                with transaction.atomic():
                    version_obj, created = get_or_create_boost_version(
                        version=tag_name,
                        version_created_at=published_at,
                    )
                    if created:
                        total_versions_created += 1
                        self.stdout.write(f"Created BoostVersion: {tag_name}")
                    lib_created, submodules = _collect_libraries_for_version(
                        version_obj, tag_name
                    )
                    total_lib_versions_created += lib_created
                    self.stdout.write(
                        f"  {tag_name}: {lib_created} library versions from {submodules} submodules"
                    )
            except Exception as e:
                logger.exception("Failed to process release %s", tag_name)
                self.stdout.write(
                    self.style.ERROR(
                        f"  {tag_name}: failed (rolled back, retry with --new-only): {e}"
                    )
                )

        summary = (
            f"\nDone: {total_versions_created} versions, "
            f"{total_lib_versions_created} library versions created."
        )
        if dry_run:
            summary = (
                f"\nDone (dry run): {total_versions_created} version row(s) would be created, "
                f"{total_lib_versions_created} library version(s) would be created."
            )
        self.stdout.write(self.style.SUCCESS(summary))

    def _process_refs(self, refs_list: list[str], *, dry_run: bool = False) -> None:
        """Process a list of refs; each ref in its own transaction. BoostVersion is
        committed only after library collection succeeds, so a failed run leaves no
        version row and can be retried.
        """
        total_versions_created = 0
        total_lib_versions_created = 0
        for ref in refs_list:
            self.stdout.write(f"Collecting libraries for ref: {ref}")
            if dry_run:
                lib_created, submodules = _collect_libraries_for_version(
                    None, ref, dry_run=True
                )
                total_lib_versions_created += lib_created
                version_exists = BoostVersion.objects.filter(version=ref).exists()
                if not version_exists:
                    total_versions_created += 1
                    self.stdout.write(f"Would create BoostVersion: {ref}")
                self.stdout.write(
                    f"  {ref}: {lib_created} library version(s) would be created from {submodules} submodules"
                )
                continue
            try:
                with transaction.atomic():
                    version_obj, created = get_or_create_boost_version(ref)
                    if created:
                        total_versions_created += 1
                        self.stdout.write(f"Created BoostVersion: {ref}")
                    lib_created, submodules = _collect_libraries_for_version(
                        version_obj, ref
                    )
                    total_lib_versions_created += lib_created
                    self.stdout.write(
                        f"  {ref}: {lib_created} library versions from {submodules} submodules"
                    )
            except Exception as e:
                logger.exception("Failed to process ref %s", ref)
                self.stdout.write(
                    self.style.ERROR(
                        f"Failed ref {ref} (rolled back, retry later): {e}"
                    )
                )
                continue
        summary = (
            f"\nDone: {total_versions_created} versions, "
            f"{total_lib_versions_created} library versions created."
        )
        if dry_run:
            summary = (
                f"\nDone (dry run): {total_versions_created} version row(s) would be created, "
                f"{total_lib_versions_created} library version(s) would be created."
            )
        self.stdout.write(self.style.SUCCESS(summary))
