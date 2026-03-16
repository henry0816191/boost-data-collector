# boost_library_docs_tracker.services

**Module path:** `boost_library_docs_tracker.services`
**Description:** Boost library docs content storage and (library-version, page) relation tracking with scrape/sync status. Single place for all writes to `boost_library_docs_tracker` models.

**Type notation:** `BoostDocContent` and `BoostLibraryDocumentation` are from `boost_library_docs_tracker.models`. `BoostLibraryVersion` is from `boost_library_tracker.models` (read-only cross-app reference).

---

## BoostDocContent

| Function | Parameter types | Return type | Notes |
|---|---|---|---|
| `get_or_create_doc_content` | `url: str`, `page_content: str`, `content_hash: str` | `tuple[BoostDocContent, str]` | See return values below. `ValueError` if `url` is empty. |

### `get_or_create_doc_content` return values

The second element is a `str` indicating what changed:

| `change_type` | Condition | Side effects |
|---|---|---|
| `"created"` | URL not in DB | Inserts row with `page_content`, `content_hash`, `scraped_at=now()`. |
| `"content_changed"` | URL exists; `content_hash` differs | Updates `page_content`, `content_hash`, `scraped_at=now()`. |
| `"unchanged"` | URL exists; `content_hash` same | Updates `scraped_at=now()` only. |

---

## BoostLibraryDocumentation

| Function | Parameter types | Return type | Notes |
|---|---|---|---|
| `link_content_to_library_version` | `library_version_id: int`, `doc_content_id: int`, `page_count: int` | `tuple[BoostLibraryDocumentation, bool]` | Get or create a row for the (library_version, doc_content) pair. Sets `page_count`. If exists, updates `page_count` if changed. |
| `mark_relation_running` | `doc: BoostLibraryDocumentation` | `BoostLibraryDocumentation` | Sets `status="running"`, `updated_at=now()`. |
| `mark_relation_completed` | `doc: BoostLibraryDocumentation` | `BoostLibraryDocumentation` | Sets `status="completed"`, `updated_at=now()`. |
| `mark_relation_failed` | `doc: BoostLibraryDocumentation` | `BoostLibraryDocumentation` | Sets `status="failed"`, `updated_at=now()`. |
| `get_pending_docs_for_library_version` | `library_version_id: int` | `QuerySet[BoostLibraryDocumentation]` | Returns all rows for this library-version where `status != "completed"`. Empty queryset means the library-version is fully done (skip on restart). |
| `get_docs_pending_sync` | — | `QuerySet[BoostLibraryDocumentation]` | Returns all rows where `status in ("pending", "failed")`. Used by the Pinecone sync step. |
| `mark_doc_synced` | `doc: BoostLibraryDocumentation` | `BoostLibraryDocumentation` | Sets `status="synced"` (or equivalent completed sync state), `updated_at=now()`. |
| `mark_doc_failed` | `doc: BoostLibraryDocumentation` | `BoostLibraryDocumentation` | Sets `status="failed"`, `updated_at=now()`. |
