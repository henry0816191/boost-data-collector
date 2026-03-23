"""
Management command: collect_boost_libraries

Collects Boost versions (releases) from boostorg/boost and library metadata
for each version. Use --release for explicit tag(s), ``all`` / ``new``, or omit
for default API new-only. For each release, fetches .gitmodules to find libs/ submodules,
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
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from boost_library_tracker.models import (
    BoostLibraryRepository,
    BoostVersion,
)
from boost_library_tracker.parsing import (
    parse_gitmodules_lib_submodules,
    parse_libraries_json_full,
)
from boost_library_tracker.release_check import (
    all_boost_versions_from_api,
    new_boost_versions_from_api,
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
from github_ops.tokens import get_github_client

logger = logging.getLogger(__name__)

MAIN_OWNER = "boostorg"
MAIN_REPO = "boost"

RAW_GITMODULES_URL = (
    "https://raw.githubusercontent.com/boostorg/boost/{ref}/.gitmodules"
)
RAW_LIBS_JSON_URL = "https://raw.githubusercontent.com/boostorg/{submodule_name}/{ref}/meta/libraries.json"
FETCH_TIMEOUT = 30

# Full Boost release tags from GitHub, e.g. boost-1.84.0 (major.minor.0)
_BOOST_RELEASE_TAG_RE = re.compile(r"^boost-\d+\.\d+\.0$")


def _normalize_ref(ref: str) -> str:
    """If ref is a numeric short form (e.g. 90), return boost-1.90.0.

    If ref starts with ``boost-``, it must match ``boost-n.m.0`` (digits for n and m).
    """
    s = ref.strip()
    if not s:
        raise ValueError("Empty release ref.")
    if s.isdigit():
        return f"boost-1.{s}.0"
    if s.startswith("boost-"):
        if not _BOOST_RELEASE_TAG_RE.fullmatch(s):
            raise ValueError(
                f"Invalid Boost release tag {s!r}: expected form boost-n.m.0 "
                "(e.g. boost-1.84.0)."
            )
        return s
    raise ValueError(
        f"Invalid release ref {s!r}: expected form boost-n.m.0 "
        "(e.g. boost-1.84.0) or numeric short form (e.g. 90)."
    )


def _parse_boost_version_option(
    boost_version_raw: str | None,
) -> list[str] | None:
    """
    Interpret ``--boost-version``.

    Returns:
        ``None`` — omit / empty: use API, new tags only.
        ``[\"all\"]`` — API, every tag.
        ``[\"new\"]`` — API, new tags only (explicit).
        Otherwise — non-empty list of normalized Boost version strings (explicit only).
    """
    if not boost_version_raw:
        return None
    v = str(boost_version_raw).strip()
    if not v:
        return None
    low = v.lower()
    if low == "all":
        return ["all"]
    if low == "new":
        return ["new"]
    boost_versions_list: list[str] = []
    for part in v.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            boost_versions_list.append(_normalize_ref(p))
        except ValueError as e:
            raise CommandError(str(e)) from e
    if not boost_versions_list:
        raise CommandError(
            "--boost-version must be 'all', 'new', a Boost version, or comma-separated versions."
        )
    return boost_versions_list


def _process_library_data(
    lib_data: dict,
    boost_repo: BoostLibraryRepository,
    boost_version: BoostVersion,
) -> int:
    """Create/update BoostLibraryVersion from one ``libraries.json`` entry and link roles/categories."""
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

    return 1 if created else 0


def _collect_libraries_for_version(
    boost_version,
    ref: str,
    *,
    client: GitHubAPIClient = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Fetch .gitmodules from boostorg/boost at ref, then for each lib submodule
    fetch meta/libraries.json from raw URL and create BoostLibraryVersion records
    with full metadata (description, authors, maintainers, categories, cxxstd).

    When dry_run is True, no DB writes; returns (would_create_count, submodules_processed)
    by checking existing BoostLibraryVersion rows. Otherwise returns (library_versions_created, submodules_processed).

    Returns (library_versions_created, submodules_processed).
    """
    if not client:
        client = get_github_client(use="scraping")
        if not client:
            logger.error("Could not create GitHub Client")
            return 0, 0

    gitmodules_url = RAW_GITMODULES_URL.format(ref=ref)
    content = client.rest_raw_request(gitmodules_url)
    if not content:
        logger.warning("Could not fetch .gitmodules for %s", ref)
        return 0, 0
    try:
        gitmodules_text = content.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Could not decode .gitmodules for %s", ref)
        return 0, 0
    lib_submodules = parse_gitmodules_lib_submodules(gitmodules_text)

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
        try:
            raw = client.rest_raw_request(libs_json_url)
            if not raw:
                logger.warning("Could not fetch libraries.json for %s", libs_json_url)
                continue
        except Exception as e:
            logger.warning(
                "Failed to fetch libraries.json for %s: %s", libs_json_url, e
            )
            continue

        lib_data_list = parse_libraries_json_full(raw, submodule_name)

        for lib_data in lib_data_list:
            created_total += _process_library_data(lib_data, boost_repo, boost_version)

    return created_total, len(lib_submodules)


class Command(BaseCommand):
    """Management command: collect Boost versions and library metadata."""

    help = (
        "Collect Boost versions from boostorg/boost and library metadata "
        "for each version. Creates BoostVersion, BoostLibraryVersion, and related records."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--boost-version",
            type=str,
            default=None,
            help="Which Boost version to collect. Omit or 'new': fetch GitHub releases, "
            "process only tags not yet in BoostVersion (default). "
            "'all': fetch every release from the API. "
            "Otherwise one tag or comma-separated tags (e.g. boost-1.84.0, 90,89). "
            "Reserved words: all, new (case-insensitive).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="When using API mode (no explicit tags): cap how many releases to process (newest first).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and report what would be done; no DB writes.",
        )

    def handle(self, *_args, **options):

        dry_run = options.get("dry_run", False)
        limit = options.get("limit")

        try:
            boost_versions_list = _parse_boost_version_option(
                options.get("boost_version")
            )
        except CommandError as e:
            logger.error("Error parsing --boost-version: %s", e)
            return

        target_releases: list[tuple[str, str]] = []

        if boost_versions_list and "all" == boost_versions_list[0]:
            target_releases = all_boost_versions_from_api()
        elif boost_versions_list and "new" not in boost_versions_list:
            target_releases = [(ref, None) for ref in boost_versions_list]
        elif not boost_versions_list or "new" in boost_versions_list:
            target_releases = new_boost_versions_from_api()

        if not target_releases:
            logger.warning("No releases to process")
            return

        if limit:
            target_releases = target_releases[:limit]
            logger.info("Processing first %s releases", limit)

        self._process_refs(target_releases, dry_run=dry_run)

    def _process_refs(
        self,
        target_releases: list[tuple[str, str | None]],
        *,
        dry_run: bool = False,
    ) -> None:
        """Process (ref, published_at) pairs; each ref in its own transaction.

        ``published_at`` is set when refs came from the GitHub releases API; use None
        for explicit ``--release`` tags. BoostVersion is committed only after library
        collection succeeds, so a failed run leaves no version row and can be retried.
        """
        if dry_run:
            logger.info("Dry run: no DB writes.")
            logger.info("Would process %s releases", len(target_releases))
            return
        total_versions_created = 0
        total_lib_versions_created = 0

        client = get_github_client(use="scraping")
        if not client:
            logger.error("Could not create GitHub Client")
            return

        for tag, sha in target_releases:
            if not sha:
                sha = client.get_tag_sha(MAIN_OWNER, MAIN_REPO, tag)
                if not sha:
                    logger.error("Could not get SHA for tag %s", tag)
                    continue
            published_at = client.get_tag_published_at(MAIN_OWNER, MAIN_REPO, sha)
            logger.info("Collecting libraries for tag: %s, sha: %s", tag, sha)
            try:
                with transaction.atomic():
                    version_obj, created = get_or_create_boost_version(
                        tag, version_created_at=published_at
                    )
                    if created:
                        total_versions_created += 1
                        logger.info("Created BoostVersion: %s", tag)
                    lib_created, submodules = _collect_libraries_for_version(
                        version_obj, tag, client=client
                    )
                    total_lib_versions_created += lib_created
                    logger.info(
                        "  %s: %s library versions from %s submodules",
                        tag,
                        lib_created,
                        submodules,
                    )
            except Exception as e:
                logger.exception("Failed to process ref %s", tag)
                logger.error(
                    "%s: failed (rolled back; retry or use --release new): %s",
                    tag,
                    e,
                )
                continue
        logger.info(
            "Done: %s versions, %s library versions created.",
            total_versions_created,
            total_lib_versions_created,
        )
