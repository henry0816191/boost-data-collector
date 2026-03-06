# boost_library_docs_tracker

Django app that scrapes all Boost library documentation by version, stores the extracted text in the database, and upserts to Pinecone. Re-runs automatically when a new Boost version is released.

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
├── management/
│   ├── __init__.py
│   └── commands/
│       ├── __init__.py
│       └── run_boost_library_docs_tracker.py
├── migrations/
│   ├── __init__.py
│   └── 0001_initial.py
└── tests/
    ├── __init__.py
    ├── fixtures.py
    ├── test_models.py
    ├── test_services.py
    └── test_fetcher.py
```

---

## Database models

See [Schema.md](Schema.md) section 10 for the full ER diagram. Summary:

**`BoostDocContent`** — One globally unique row per URL, shared across all versions and libraries. Stores `page_content`, `content_hash` (SHA-256), and `scraped_at`. Content is updated in place when the hash changes on a re-scrape. Because pages are global, unchanged content is never duplicated even when the same URL appears in a new version.

**`BoostLibraryDocumentation`** — Join table between `BoostLibraryVersion` (section 3 of schema) and `BoostDocContent`. One row per (library-version, page) pair. Tracks `status` (`pending` / `running` / `completed` / `failed`) and `page_count` (total pages discovered for that library-version). Restart logic: skip any (library-version, page) pair whose status is already `completed`.

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
| `--version VERSION` | auto-detect | Force a specific Boost version instead of querying GitHub API. |
| `--library LIBRARY` | all | Scrape only one library by name. Useful for debugging. |
| `--dry-run` | off | Fetch and parse pages but do not write to DB or Pinecone. |
| `--skip-pinecone` | off | Write to DB but skip the Pinecone upsert step. |
| `--max-pages N` | 500 | Per-library page cap for the BFS crawl. |

### Execution steps

1. **Detect version** — Use `--version` if given; otherwise query `BoostVersion` in the DB for the latest version with a non-null `version_created_at`.
2. **Discover libraries** — Call `_get_library_list(version)` to read all `(library_name, doc_root_url, lib_key, lib_doc)` tuples from `BoostLibraryVersion` and `BoostLibrary` tables (no HTTP required).
3. **Per-library scrape loop** — For each `BoostLibraryVersion` (filtered by `--library` if given):
   - Call `services.get_pending_docs_for_library_version(library_version_id)` — if all docs are already `completed`, skip this library (restart logic).
   - Call `fetcher.crawl_library_pages(doc_root_url)`, compute `content_hash = sha256(page_text)` for each URL.
   - For each page: call `services.get_or_create_doc_content(url, page_content, content_hash)` → returns `(BoostDocContent, change_type)`.
   - Call `services.link_content_to_library_version(library_version_id, doc_content_id, page_count)` to record the relation.
4. **Pinecone sync** — Unless `--skip-pinecone` or `--dry-run`: call `services.get_docs_pending_sync()`, upsert each page's content to Pinecone (or metadata-only if content unchanged), call `services.mark_doc_synced(doc)` or `services.mark_doc_failed(doc)`.
5. **Complete** — Log summary and exit 0. On unhandled exception, log and exit non-zero.

### Restart and resume logic

- **Library-version level:** `services.get_pending_docs_for_library_version()` returns only rows not yet `completed`; libraries already fully scraped are skipped.
- **Page level:** `get_or_create_doc_content` is idempotent — if the URL exists and the hash is the same, only `scraped_at` is updated; no duplicate rows.
- **Pinecone level:** `get_docs_pending_sync()` returns only rows with `status in (pending, failed)`; already-synced rows are skipped automatically.

---

## Pinecone document shape

One Pinecone vector per `BoostDocContent` row. The vector ID is the page URL (deterministic, used for dedup and update-in-place). Metadata is populated from the `BoostLibraryDocumentation` row and its linked `BoostLibraryVersion`.

| Field | Value |
|---|---|
| `id` | Page URL |
| `page_content` | Extracted plain text (embedded) |
| `metadata.url` | Page URL |
| `metadata.library_name` | Library name from linked `BoostLibrary` |
| `metadata.boost_version` | Version string from linked `BoostVersion` |
| `metadata.content_hash` | SHA-256 of `page_content` |

**Upsert logic (driven by `BoostLibraryDocumentation.status`):**

| `change_type` from `get_or_create_doc_content` | Pinecone action |
|---|---|
| `"created"` or `"content_changed"` | Re-embed `page_content` and full upsert |
| `"unchanged"` | No Pinecone action needed (content identical) |

Relations with `status == "failed"` are retried on the next run.

---

## Scheduling

The app runs inside the existing daily Celery Beat schedule (1:00 AM Pacific) via `run_all_collectors`. On most days the target version is already `completed` and the command exits in seconds. On a release day a full scrape runs for the new version.

For a manual backfill of older versions:

```bash
python manage.py run_boost_library_docs_tracker --version 1.85.0
python manage.py run_boost_library_docs_tracker --version 1.86.0
```

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
6. Run `python manage.py makemigrations boost_library_docs_tracker` and `python manage.py migrate`.

---

## Related documentation

- [Schema.md](Schema.md) — Database schema (section 10: Boost Library Docs Tracker).
- [Service_API.md](Service_API.md) — Service layer index.
- [service_api/boost_library_docs_tracker.md](service_api/boost_library_docs_tracker.md) — Full service API reference for this app.
- [Workflow.md](Workflow.md) — Execution order (this command runs after `run_boost_library_tracker`).
- [Workspace.md](Workspace.md) — Workspace layout (`workspace/boost_library_docs_tracker/`).
- [Contributing.md](Contributing.md) — Service layer write rules.
