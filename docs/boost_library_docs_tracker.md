# boost_library_docs_tracker

Django app that scrapes Boost library documentation by version, writes metadata and content hashes into **BoostDocContent** (extracted text lives in workspace files, not the DB), links pages to library-versions via **BoostLibraryDocumentation**, and upserts to Pinecone. Sync state is tracked on **BoostDocContent** (`is_upserted`). Re-runs when new Boost versions are released; restart logic uses `BoostDocContent.is_upserted` to re-run upserts for failed or new rows.

---

## Overview

| Item | Value |
|---|---|
| Module | `boost_library_docs_tracker` |
| Management command | `run_boost_library_docs_tracker` |
| Workspace subfolder | `workspace/boost_library_docs_tracker/` |
| Models | `BoostDocContent`, `BoostLibraryDocumentation` |
| Service module | `boost_library_docs_tracker.services` |
| Fetcher module | `boost_library_docs_tracker.fetcher` |

---

## Directory structure

```
boost_library_docs_tracker/
├── __init__.py
├── apps.py
├── admin.py
├── models.py
├── services.py
├── fetcher.py
├── html_to_md.py
├── preprocessor.py
├── workspace.py
├── management/
│   ├── __init__.py
│   └── commands/
│       ├── __init__.py
│       └── run_boost_library_docs_tracker.py
├── migrations/
│   ├── __init__.py
│   ├── 0001_initial.py
│   ├── 0002_remove_page_content_and_status_add_is_upserted.py
│   └── 0003_redesign_per_schema_v10.py
└── tests/
    ├── __init__.py
    ├── fixtures.py
    ├── test_models.py
    ├── test_preprocessor.py
    ├── test_services.py
    └── test_fetcher.py
```

---

## Database models

See [Schema.md](Schema.md) section 10 for the full ER diagram. Summary:

**`BoostDocContent`** — One row per unique document content, keyed by `content_hash` (SHA-256 of page text). Stores `url`, `content_hash`, `first_version_id`, `last_version_id`, `is_upserted`, `scraped_at`, `created_at`. Page content is **not** stored in the DB; it is kept in workspace files. The unique key is `content_hash` so the same content is never duplicated; the same URL may produce a new row if content changes. Restart/sync logic: select rows where `is_upserted=False` (or in `failed_ids`) and re-run Pinecone upserts; after success, set `is_upserted=True`.

**`BoostLibraryDocumentation`** — Join table between `BoostLibraryVersion` (section 3 of schema) and `BoostDocContent`. One row per (library-version, doc_content) pair; it only records which pages were found under a given (library, version). No status, page_count, or sync fields; sync state lives on `BoostDocContent`.

---

## Fetcher (`fetcher.py`)

Contains all HTTP and HTML logic. Makes no database writes.

| Function | Description |
|---|---|
| `crawl_library_pages(doc_root_url, max_pages, delay_secs)` | BFS from `doc_root_url`. Only follows links that stay within the same URL prefix (scoped to that library + version). Converts HTML to Markdown via `html_to_md`. Returns `list[tuple[page_url, markdown_text]]`. |
| `walk_library_html(source_root, lib_key, lib_documentation, version, max_pages)` | BFS-walks local HTML files from the extracted Boost source zip. Returns `list[tuple[canonical_url, markdown_text]]`. |
| `download_source_zip(version, dest_dir)` | Downloads the Boost source zip; skips if already present. |
| `extract_source_zip(zip_path, extract_dir)` | Extracts zip; returns top-level extracted directory. Skips if already extracted. |
| `delete_extract_dir(extract_dir)` | Deletes the extracted source tree to free disk space after scraping. |

**Dependencies:** `requests`, `beautifulsoup4`, `lxml`.

**Crawl boundary rule:** Only URLs that begin with `doc_root_url` are followed. This keeps the BFS within one library's documentation tree and prevents leaking into other libraries or external pages.

---

## Management command

**Command name:** `run_boost_library_docs_tracker`

Added to `COLLECTOR_COMMANDS` in `workflow/management/commands/run_all_collectors.py` after `run_boost_library_tracker`.

### Arguments

| Argument | Default | Description |
|---|---|---|
| `--versions VERSION [VERSION ...]` | latest from DB | One or more Boost versions to scrape. Must match `BoostVersion.version` (e.g. `boost-1.85.0` when populated from GitHub tags). |
| `--library LIBRARY` | all | Scrape only one library by name. Useful for debugging. |
| `--dry-run` | off | Fetch and parse pages but do not write to DB or Pinecone. |
| `--skip-pinecone` | off | Write to DB but skip the Pinecone upsert step. |
| `--max-pages N` | 100 | Per-library page cap for the BFS crawl. |
| `--use-local` | off | Download source zip and walk local HTML instead of HTTP crawl. |
| `--cleanup-extract` | off | Delete extracted source tree after each version (only with `--use-local`). |

### Execution steps

1. **Resolve versions** — Use `--versions` if given; otherwise query `BoostVersion` for the latest version with non-null `version_created_at`. Sort old→new.
2. **Discover libraries** — For each version, call `_get_library_list(version)` to read `(library_name, doc_root_url, lib_key, lib_doc)` from `BoostLibraryVersion` and `BoostLibrary`.
3. **Per-library scrape** — For each library (optionally filtered by `--library`): fetch pages via `fetcher.crawl_library_pages` or `fetcher.walk_library_html` (if `--use-local`). For each page: save text to workspace, compute `content_hash`, call `services.get_or_create_doc_content(url, content_hash, version_id=boost_version_id)` → returns `(BoostDocContent, change_type)`. Call `services.link_content_to_library_version(library_version_id, doc_content_id)` to create the **BoostLibraryDocumentation** join row (idempotent).
4. **Pinecone sync** — Unless `--skip-pinecone` or `--dry-run`: run `sync_to_pinecone` with `preprocess_for_pinecone`. The preprocessor selects **BoostDocContent** rows where `is_upserted=False` or in `failed_ids`, loads page content from workspace, builds vectors, and sets `BoostDocContent.is_upserted=True` on success. Failed IDs from the sync result are set back to `is_upserted=False` for retry.
5. **Complete** — Log summary and exit 0.

### Restart and sync logic

- **Scrape:** No per-row “pending” skip; each run (re)scrapes and updates or creates **BoostDocContent** by `content_hash`, and ensures **BoostLibraryDocumentation** join rows exist.
- **Pinecone:** Driven by **BoostDocContent.is_upserted**. Rows with `is_upserted=False` (or in `failed_ids`) are (re)upserted; on success `is_upserted` is set to `True`. On sync failure, failed **BoostDocContent** IDs are set to `is_upserted=False` so the next run retries them.

---

## Pinecone document shape

One Pinecone vector per **BoostDocContent** row. The preprocessor selects rows with `BoostDocContent.is_upserted=False` (or in `failed_ids`), loads page content from the workspace, and builds one document per row. Metadata is taken from **BoostDocContent** (url, content_hash, first_version, last_version) and from the linked **BoostLibraryDocumentation** / **BoostLibraryVersion** for library name.

| Field | Value |
|---|---|
| `metadata.doc_id` | `BoostDocContent.content_hash` |
| `metadata.url` | Page URL |
| `metadata.first_version` / `metadata.last_version` | Version strings from **BoostDocContent** FKs |
| `metadata.library_name` | From a **BoostLibraryDocumentation** relation’s library |
| `metadata.ids` | **BoostDocContent** PK (for failure reporting) |
| `content` | Page text loaded from workspace |

**Upsert logic (driven by BoostDocContent.is_upserted):** Only rows with `is_upserted=False` or in the retry `failed_ids` list are sent to Pinecone. After a successful upsert, `BoostDocContent.is_upserted` is set to `True`. If the sync reports failures, those **BoostDocContent** IDs are set back to `is_upserted=False` so the next run retries them.

---

## Scheduling

The app runs inside the existing daily Celery Beat schedule (1:00 AM Pacific) via `run_all_collectors`. On most days there is no new version and the command finishes quickly; on a release day a full scrape runs for the new version. Pinecone upserts run for any **BoostDocContent** with `is_upserted=False` or in the failure retry list.

For a manual backfill of specific versions, pass values that match **BoostVersion.version** in the database (often the GitHub tag form with a `boost-` prefix):

```bash
python manage.py run_boost_library_docs_tracker --versions boost-1.85.0
python manage.py run_boost_library_docs_tracker --versions boost-1.85.0 boost-1.86.0
```

If your **BoostVersion** rows use bare version strings (e.g. `1.85.0`), use those instead. The command looks up versions with `BoostVersion.objects.get(version=...)`, so the value must match exactly.

---

## Configuration

Settings added to `settings.py` (all via environment variables):

| Setting | Env var | Default | Description |
|---|---|---|---|
| `BOOST_DOCS_MAX_PAGES_PER_LIBRARY` | `BOOST_DOCS_MAX_PAGES_PER_LIBRARY` | `500` | Per-library BFS page cap |
| `BOOST_DOCS_CRAWL_DELAY` | `BOOST_DOCS_CRAWL_DELAY` | `0.5` | Seconds to sleep between page fetches |
| `BOOST_DOCS_PINECONE_API_KEY` | `BOOST_DOCS_PINECONE_API_KEY` | `""` | Pinecone API key |
| `BOOST_DOCS_PINECONE_INDEX` | `BOOST_DOCS_PINECONE_INDEX` | `"boost-docs"` | Pinecone index name |
| `BOOST_DOCS_PINECONE_NAMESPACE` | `BOOST_DOCS_PINECONE_NAMESPACE` | `"boost_docs"` | Pinecone namespace |

GitHub token reuses `settings.GITHUB_TOKENS_SCRAPING` (already configured by the project).

---

## Project integration checklist

When adding this app to the project, do all of the following:

1. Add `"boost_library_docs_tracker"` to `INSTALLED_APPS` in `settings.py`.
2. Add `"boost_library_docs_tracker"` to `_WORKSPACE_APP_SLUGS` in `settings.py`.
3. Add the five `BOOST_DOCS_*` settings to `settings.py` and their env var defaults to `.env.example`.
4. Add `"run_boost_library_docs_tracker"` to `COLLECTOR_COMMANDS` in `workflow/management/commands/run_all_collectors.py` (after `"run_boost_library_tracker"`).
5. Add `beautifulsoup4` and `lxml` to `requirements.txt` (if not already present).
6. Run `python manage.py migrate` to apply the app’s committed migrations.

---

## Related documentation

- [Schema.md](Schema.md) — Database schema (section 10: Boost Library Docs Tracker).
- [Service_API.md](Service_API.md) — Service layer index.
- [service_api/boost_library_docs_tracker.md](service_api/boost_library_docs_tracker.md) — Full service API reference for this app.
- [Workflow.md](Workflow.md) — Execution order (this command runs after `run_boost_library_tracker`).
- [Workspace.md](Workspace.md) — Workspace layout (`workspace/boost_library_docs_tracker/`).
- [Contributing.md](Contributing.md) — Service layer write rules.
