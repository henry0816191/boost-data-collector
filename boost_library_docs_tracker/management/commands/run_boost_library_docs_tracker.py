"""
Management command: run_boost_library_docs_tracker

Scrapes Boost library documentation for one or more versions, stores content
in workspace files and BoostDocContent/BoostLibraryDocumentation tables,
then upserts to Pinecone via cppa_pinecone_sync.

Procedure:
  1. Accept list of Boost versions (--versions), sorted old→new.
  2. For each version, load libraries from BoostLibraryVersion + BoostLibrary tables.
  3. For each library, fetch docs and save to workspace:
     - Default (--use-local not set): HTTP BFS crawl per library.
     - --use-local: download source zip once per version, extract, walk local HTML.
       Zip is saved in workspace/raw/boost_library_docs_tracker/ and is not deleted.
       Extract tree is saved in workspace/boost_library_docs_tracker/extracted/.
       Converted page content is saved in workspace/boost_library_docs_tracker/converted/.
       Pass --cleanup-extract to delete the extract tree after all libraries are done.
  4. Fill BoostDocContent and BoostLibraryDocumentation tables (no page_content in DB).
     - New content_hash → create new BoostDocContent row, set first_version and last_version.
     - Same content_hash but different URL → update url and scraped_at, update last_version.
     - Same content_hash and URL → update scraped_at and last_version only.
     - Link BoostDocContent to BoostLibraryVersion via BoostLibraryDocumentation (idempotent).
  5. Call sync_to_pinecone with preprocess_for_pinecone.
  6. Extract failed_ids from the sync result and mark those BoostDocContent
     rows as is_upserted=False.

Usage examples:
  python manage.py run_boost_library_docs_tracker
  python manage.py run_boost_library_docs_tracker --versions 1.86.0 1.87.0
  python manage.py run_boost_library_docs_tracker --library algorithm
  python manage.py run_boost_library_docs_tracker --use-local
  python manage.py run_boost_library_docs_tracker --use-local --cleanup-extract
  python manage.py run_boost_library_docs_tracker --dry-run
  python manage.py run_boost_library_docs_tracker --skip-pinecone
"""

import hashlib
import logging
from pathlib import Path
from urllib.parse import urljoin

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from boost_library_docs_tracker import fetcher, services, workspace
from boost_library_docs_tracker.preprocessor import preprocess_for_pinecone
from boost_library_tracker.models import BoostLibraryVersion, BoostVersion

logger = logging.getLogger(__name__)

APP_TYPE = "boost_library_docs"
PINECONE_NAMESPACE = "boost_library_docs"
DEFAULT_MAX_PAGES = 100


class Command(BaseCommand):
    help = (
        "Scrape Boost library documentation for given versions and upsert to Pinecone."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--versions",
            nargs="*",
            metavar="VERSION",
            default=None,
            help=(
                "One or more Boost versions to scrape (e.g. 1.86.0 1.87.0). "
                "Defaults to latest release from GitHub API."
            ),
        )
        parser.add_argument(
            "--library",
            default=None,
            metavar="LIBRARY",
            help="Scrape only the named library (e.g. algorithm). Default: all libraries.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and parse pages but do not write to DB, workspace, or Pinecone.",
        )
        parser.add_argument(
            "--skip-pinecone",
            action="store_true",
            help="Write to DB and workspace but skip the Pinecone upsert step.",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=DEFAULT_MAX_PAGES,
            metavar="N",
            help=f"Per-library page cap for the BFS crawl (default: {DEFAULT_MAX_PAGES}).",
        )
        parser.add_argument(
            "--use-local",
            action="store_true",
            help=(
                "Download the Boost source zip and walk local HTML instead of HTTP crawling. "
                "Faster and avoids rate-limiting."
            ),
        )
        parser.add_argument(
            "--cleanup-extract",
            action="store_true",
            help=(
                "Delete the extracted source tree after all libraries for a version are "
                "processed (only with --use-local)."
            ),
        )

    def handle(self, *args, **options):
        try:
            self._run(
                versions_arg=options["versions"],
                library_filter=options["library"],
                dry_run=options["dry_run"],
                skip_pinecone=options["skip_pinecone"],
                max_pages=options["max_pages"],
                use_local=options["use_local"],
                cleanup_extract=options["cleanup_extract"],
            )
        except CommandError:
            raise
        except Exception as exc:
            logger.exception("run_boost_library_docs_tracker failed: %s", exc)
            raise CommandError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Top-level flow
    # ------------------------------------------------------------------

    def _run(
        self,
        *,
        versions_arg,
        library_filter,
        dry_run,
        skip_pinecone,
        max_pages,
        use_local,
        cleanup_extract,
    ):
        versions = self._resolve_versions(versions_arg)
        self.stdout.write(
            f"Processing {len(versions)} version(s): {', '.join(versions)}"
        )
        mode = "local-zip" if use_local else "HTTP crawl"
        self.stdout.write(f"Scrape mode: {mode}")

        for version in versions:
            self._process_version(
                version=version,
                library_filter=library_filter,
                dry_run=dry_run,
                max_pages=max_pages,
                use_local=use_local,
                cleanup_extract=cleanup_extract,
            )

        if dry_run or skip_pinecone:
            reason = "dry run" if dry_run else "--skip-pinecone set"
            self.stdout.write(f"Skipping Pinecone sync ({reason}).")
            return

        self._sync_pinecone()

    def _process_version(
        self, *, version, library_filter, dry_run, max_pages, use_local, cleanup_extract
    ):
        self.stdout.write(f"\n[{version}] Discovering libraries...")

        library_list = self._get_library_list(version)
        if library_filter:
            library_list = [
                (n, u, k, d) for n, u, k, d in library_list if n == library_filter
            ]
            if not library_list:
                raise CommandError(
                    f"Library '{library_filter}' not found in Boost {version}."
                )

        self.stdout.write(f"[{version}] {len(library_list)} library/libraries.")

        source_root: Path | None = None

        if use_local:
            source_root = self._prepare_local_source(version=version)

        # Resolve once per version; used to track first/last_version on BoostDocContent.
        boost_version_id = self._resolve_boost_version_id(version)

        total_pages = 0
        for lib_name, doc_root_url, lib_key, lib_doc in library_list:
            pages_count = self._process_library(
                version=version,
                lib_name=lib_name,
                doc_root_url=doc_root_url,
                lib_key=lib_key,
                lib_doc=lib_doc,
                source_root=source_root,
                dry_run=dry_run,
                max_pages=max_pages,
                boost_version_id=boost_version_id,
            )
            total_pages += pages_count

        if use_local and cleanup_extract and source_root is not None:
            fetcher.delete_extract_dir(source_root)

        self.stdout.write(f"[{version}] Done — {total_pages} pages total.")

    def _prepare_local_source(self, *, version: str) -> Path:
        """Download and extract the Boost source zip for a version.

        Returns source_root — the top-level extracted directory.
        """
        zip_dir = workspace.get_zip_dir()
        extract_dir = workspace.get_extract_dir()

        try:
            zip_path = fetcher.download_source_zip(version, zip_dir)
        except Exception as exc:
            raise CommandError(
                f"Failed to download source zip for {version}: {exc}"
            ) from exc

        try:
            source_root = fetcher.extract_source_zip(zip_path, extract_dir)
        except Exception as exc:
            raise CommandError(
                f"Failed to extract source zip for {version}: {exc}"
            ) from exc

        self.stdout.write(f"[{version}] Source ready at {source_root}")
        return source_root

    def _process_library(
        self,
        *,
        version,
        lib_name,
        doc_root_url,
        lib_key,
        lib_doc,
        source_root,
        dry_run,
        max_pages,
        boost_version_id,
    ) -> int:
        effective_max_pages = max_pages if dry_run else None

        if source_root is not None:
            self.stdout.write(
                f"  [{lib_name}] walking local HTML (key={lib_key!r}) ..."
            )
            try:
                pages = fetcher.walk_library_html(
                    source_root=source_root,
                    lib_key=lib_key,
                    lib_documentation=lib_doc,
                    version=version,
                    max_pages=effective_max_pages,
                )
            except Exception as exc:
                logger.error("[%s] local walk failed: %s", lib_name, exc)
                self.stdout.write(
                    self.style.ERROR(f"  [{lib_name}] local walk error: {exc}")
                )
                return 0
        else:
            self.stdout.write(f"  [{lib_name}] crawling {doc_root_url} ...")
            try:
                pages = fetcher.crawl_library_pages(
                    doc_root_url, max_pages=effective_max_pages, delay_secs=0.3
                )
            except Exception as exc:
                logger.error("[%s] crawl failed: %s", lib_name, exc)
                self.stdout.write(
                    self.style.ERROR(f"  [{lib_name}] crawl error: {exc}")
                )
                return 0

        page_count = len(pages)
        self.stdout.write(f"  [{lib_name}] {page_count} pages found.")

        if dry_run:
            return page_count

        lib_version_id = self._resolve_library_version_id(lib_name, version)
        if lib_version_id is None:
            self.stdout.write(
                self.style.WARNING(
                    f"  [{lib_name}] BoostLibraryVersion not found in DB for {version}, skipping DB writes."
                )
            )
            return page_count

        self._save_pages_to_workspace_and_db(
            version=version,
            lib_name=lib_name,
            lib_version_id=lib_version_id,
            boost_version_id=boost_version_id,
            pages=pages,
        )
        return page_count

    # ------------------------------------------------------------------
    # Workspace + DB writes
    # ------------------------------------------------------------------

    def _save_pages_to_workspace_and_db(
        self, *, version, lib_name, lib_version_id, boost_version_id, pages
    ):
        created = changed = unchanged = 0

        for url, page_text in pages:
            content_hash = hashlib.sha256(page_text.encode()).hexdigest()

            try:
                workspace.save_page(version, lib_name, url, page_text)
            except Exception as exc:
                logger.error(
                    "[%s] workspace write failed for %s: %s", lib_name, url, exc
                )
                continue

            try:
                doc_content, change_type = services.get_or_create_doc_content(
                    url, content_hash, version_id=boost_version_id
                )
            except Exception as exc:
                logger.error("[%s] DB write failed for %s: %s", lib_name, url, exc)
                continue

            if change_type == "created":
                created += 1
            elif change_type == "content_changed":
                changed += 1
            else:
                unchanged += 1

            try:
                services.link_content_to_library_version(lib_version_id, doc_content.pk)
            except Exception as exc:
                logger.error(
                    "[%s] link_content_to_library_version failed for %s: %s",
                    lib_name,
                    url,
                    exc,
                )

        self.stdout.write(
            f"  [{lib_name}] created={created}, changed={changed}, unchanged={unchanged}."
        )

    # ------------------------------------------------------------------
    # Pinecone sync
    # ------------------------------------------------------------------

    def _sync_pinecone(self):
        if not apps.is_installed("cppa_pinecone_sync"):
            self.stdout.write(
                self.style.WARNING(
                    "Skipping Pinecone sync: 'cppa_pinecone_sync' is not in INSTALLED_APPS."
                )
            )
            self.stdout.write(
                "Add 'cppa_pinecone_sync' to INSTALLED_APPS or run with --skip-pinecone."
            )
            return

        try:
            from cppa_pinecone_sync.sync import sync_to_pinecone
        except Exception as exc:
            logger.warning("Cannot import cppa_pinecone_sync.sync: %s", exc)
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping Pinecone sync: cannot import cppa_pinecone_sync ({exc})."
                )
            )
            return

        self.stdout.write("\nSyncing to Pinecone...")
        try:
            result = sync_to_pinecone(
                app_type=APP_TYPE,
                namespace=PINECONE_NAMESPACE,
                preprocess_fn=preprocess_for_pinecone,
            )
        except Exception as exc:
            logger.error("Pinecone sync failed: %s", exc)
            self.stdout.write(self.style.ERROR(f"Pinecone sync error: {exc}"))
            return

        successful_ids = result.get("successful_source_ids", [])
        int_successful_ids: list[int] = []
        for sid in successful_ids:
            try:
                int_successful_ids.append(int(sid))
            except (ValueError, TypeError):
                logger.warning("Ignoring non-integer successful_source_id: %r", sid)
        if int_successful_ids:
            services.set_doc_content_upserted_by_ids(int_successful_ids, True)
            logger.info(
                "Marked %d BoostDocContent rows as is_upserted=True "
                "after successful Pinecone upsert.",
                len(int_successful_ids),
            )

        failed_ids = result.get("failed_ids", [])
        int_failed_ids: list[int] = []
        for fid in failed_ids:
            try:
                int_failed_ids.append(int(fid))
            except (ValueError, TypeError):
                logger.warning("Ignoring non-integer failed_id: %r", fid)
        if int_failed_ids:
            services.set_doc_content_upserted_by_ids(int_failed_ids, False)
            logger.warning(
                "Marked %d BoostDocContent rows as is_upserted=False "
                "due to Pinecone failures.",
                len(int_failed_ids),
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Pinecone sync complete — upserted={result.get('upserted', 0)}, "
                f"total={result.get('total', 0)}, "
                f"failed={result.get('failed_count', 0)}."
            )
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_versions(self, versions_arg: list[str] | None) -> list[str]:
        if versions_arg:
            versions = [v.strip() for v in versions_arg if v.strip()]
        else:
            self.stdout.write("Using latest Boost version from BoostVersion table...")
            latest = (
                BoostVersion.objects.filter(version_created_at__isnull=False)
                .order_by("-version_created_at", "-version")
                .first()
            )
            if latest is None:
                raise CommandError(
                    "No BoostVersion in DB. Run boost_library_tracker first."
                )
            self.stdout.write(f"Latest Boost version: {latest.version}")
            versions = [latest.version]

        return _sort_versions_by_db(versions)

    def _get_library_list(self, version: str) -> list[tuple[str, str, str, str]]:
        """Return (library_name, doc_root_url, lib_key, lib_doc) from BoostLibraryVersion and BoostLibrary tables.

        lib_key     - lv.key stripped, falls back to library name.
        lib_doc     - lv.documentation stripped (relative path inside the library tree).
        doc_root_url - canonical HTTP base URL for the library (used when not using local zip).
        """
        try:
            boost_version = BoostVersion.objects.get(version=version)
        except BoostVersion.DoesNotExist:
            raise CommandError(
                f"Boost version '{version}' not found in DB. Run boost_library_tracker first."
            ) from None

        url_version = version.replace(".", "_").replace("boost-", "")
        base = fetcher.BOOST_ORG_BASE

        library_versions = (
            BoostLibraryVersion.objects.filter(version=boost_version)
            .select_related("library")
            .order_by("library__name")
        )
        result = []
        for lv in library_versions:
            lib_name = lv.library.name
            lib_key = lv.key.strip() if lv.key else lib_name
            lib_doc = (lv.documentation or "").strip()
            index_url = f"{base}/doc/libs/{url_version}/libs/{lib_key}"
            doc_root_url = urljoin(index_url, lib_doc) if lib_doc else index_url
            result.append((lib_name, doc_root_url, lib_key, lib_doc))
        return result

    def _resolve_library_version_id(self, lib_name: str, version: str) -> int | None:
        """Resolve BoostLibraryVersion id from DB. Returns None if not found."""
        try:
            lv = BoostLibraryVersion.objects.select_related("library", "version").get(
                library__name=lib_name,
                version__version=version,
            )
            return lv.pk
        except BoostLibraryVersion.DoesNotExist:
            return None
        except BoostLibraryVersion.MultipleObjectsReturned:
            logger.warning(
                "Multiple BoostLibraryVersion rows for lib=%s ver=%s; using first.",
                lib_name,
                version,
            )
            lv = BoostLibraryVersion.objects.filter(
                library__name=lib_name,
                version__version=version,
            ).first()
            return lv.pk if lv is not None else None

    def _resolve_boost_version_id(self, version: str) -> int | None:
        """Resolve BoostVersion PK from the version string. Returns None if not found."""
        try:
            bv = BoostVersion.objects.get(version=version)
            return bv.pk
        except BoostVersion.DoesNotExist:
            return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _sort_versions_by_db(versions: list[str]) -> list[str]:
    """
    Sort version strings from oldest to newest using BoostVersion.version_created_at.
    Versions not in DB are appended last in their original order.
    """
    db_versions = {
        bv.version: bv.version_created_at
        for bv in BoostVersion.objects.filter(version__in=versions).only(
            "version", "version_created_at"
        )
    }

    def _key(v: str):
        created_at = db_versions.get(v)
        return (created_at is None, created_at or "", v)

    return sorted(versions, key=_key)
