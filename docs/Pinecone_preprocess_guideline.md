# Guideline: Building a preprocess function for Pinecone sync

This document describes how to implement the **preprocess function** that callers pass to `cppa_pinecone_sync.sync.sync_to_pinecone()`. The preprocess function is responsible for turning your app’s data (and sync state) into a list of document dicts that the sync pipeline will upsert to Pinecone.

## When is the preprocess function used?

Other apps call:

```python
from cppa_pinecone_sync.sync import sync_to_pinecone

result = sync_to_pinecone(
    app_type="slack",          # e.g. "slack", "mailing"
    namespace="your_namespace",
    preprocess_fn=your_preprocess_fn,
    # instance defaults to PineconeInstance.PUBLIC; pass PRIVATE to use
    # the private API key (PINECONE_PRIVATE_API_KEY in Django settings).
)
```

To use the **private** API key instead:

```python
from cppa_pinecone_sync.ingestion import PineconeInstance
from cppa_pinecone_sync.sync import sync_to_pinecone

result = sync_to_pinecone(
    app_type="slack",
    namespace="your_namespace",
    preprocess_fn=your_preprocess_fn,
    instance=PineconeInstance.PRIVATE,
)
```

The sync pipeline will:

1. Load **failed IDs** and **last sync time** for this app (by `app_type`) from the database.
2. Call your **preprocess function** with those two inputs.
3. Upsert the documents you return to Pinecone (with chunking and validation as needed).
4. Update the fail list and sync status in the database.

Your preprocess function’s job is step 2: decide _what_ to sync and return it in the required shape.

---

## Signature

```python
def your_preprocess_fn(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    ...
    return (list_of_document_dicts, is_chunked)
```

- **`failed_ids`** — Source record IDs that failed in a previous upsert. You should **include these again** in this run so they can be retried. The sync app will clear and repopulate the fail list after the run based on this run’s failures.
- **`final_sync_at`** — Timestamp of the last successful sync for this app, or `None` if never synced. Use it to fetch only **new or updated** records (e.g. `WHERE updated_at > final_sync_at`) for incremental sync.
- **Return** — A 2-tuple:
  - **`list_of_document_dicts`** — List of raw document dicts (see shape below). Can be empty.
  - **`is_chunked`** — `True` if each dict is already a final chunk (no further splitting). `False` if documents are whole-document and the pipeline should chunk them (e.g. with `RecursiveCharacterTextSplitter`).

---

## Shape of each document dict

Each item in the list must be a dict with at least:

| Key                                       | Location          | Required     | Description                                                                                                                                                                                                     |
| ----------------------------------------- | ----------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `content`                                 | top-level         | Yes          | The text to index (plain string).                                                                                                                                                                               |
| `metadata`                                | top-level         | Yes          | Dict of metadata attached to the document.                                                                                                                                                                      |
| `metadata["doc_id"]` or `metadata["url"]` | inside `metadata` | One required | Stable identifier for the document (e.g. primary key, URL). Used for chunk IDs and for skipping invalid docs.                                                                                                   |
| `metadata["source_ids"]`                  | inside `metadata` | Recommended  | Comma-separated **source record IDs** (e.g. DB primary keys). Used to record failed IDs when an upsert fails so they can be retried next run. If omitted, failed-document tracking for that item will be empty. |

Any other keys in `metadata` (e.g. `title`, `author`, `source`) are passed through to Pinecone and can be used for filtering or display.

### Example minimal document

```python
{
    "content": "The actual text to index for this document or chunk.",
    "metadata": {
        "doc_id": "slack-msg-12345",   # or "url": "https://..."
        "source_ids": "12345",                 # source ID(s) for retry tracking
        "title": "Optional title",
    },
}
```

### Example with multiple source IDs (e.g. one chunk from multiple rows)

If one logical “document” is built from several source records, pass their IDs in `metadata["source_ids"]` as a comma-separated string so that if the upsert fails, all of them are recorded for retry:

```python
"metadata": {
    "doc_id": "thread-abc",
    "source_ids": "101,102,103",
}
```

---

## Implementing the logic

1. **Retry failed first**
   Use `failed_ids` to (e.g.) query your DB or API for those records and add them to the set of documents to return. Without this, failed items would never be retried.

2. **Incremental sync**
   Use `final_sync_at` to restrict to new/updated data (e.g. `updated_at > final_sync_at`). For the first run, `final_sync_at` is `None` — then you can either return a full dump or a bounded window, depending on your app.

3. **Deduplicate**
   If the same record appears both in `failed_ids` and in the “since `final_sync_at`” set, return it once.

4. **Build the list**
   For each record, build one (or more) dicts with `content` and `metadata` as above. If you already produce chunks (e.g. by section), set `is_chunked=True`; otherwise set `is_chunked=False` and let the pipeline chunk by size.

5. **Return**
   Return `(documents, is_chunked)`. You may return `([], False)` if there is nothing to sync; the pipeline will still update sync status.

---

## Chunking and validation

- If **`is_chunked=False`**, the sync pipeline will split each document’s `content` using a text splitter (configurable via Django settings). Chunk size, overlap, and related options are in `cppa_pinecone_sync.ingestion`.
- If **`is_chunked=True`**, no further splitting is done; each dict is treated as one chunk. Ensure each chunk has enough substantive text (see below).
- The ingestion layer **drops** chunks that fail validation (e.g. too short, mostly punctuation or table separators). Defaults include a minimum length and minimum word count. So:
  - Prefer meaningful, contiguous text in `content`.
  - Avoid chunks that are only tables, symbols, or very short snippets.

---

## Choosing public vs private Pinecone instance

The sync pipeline supports two Pinecone API keys: **public** (default) and **private**. Set via:

- **Python API:** Pass `instance=PineconeInstance.PRIVATE` to `sync_to_pinecone()`.
- **Management command:** Use `--pinecone-instance private`:

```bash
python manage.py run_cppa_pinecone_sync \
    --app-type slack \
    --namespace slack-Cpplang \
    --preprocessor myapp.preprocessors.slack_preprocess \
    --pinecone-instance private
```

| Instance  | Django setting read        | `.env` key                 |
| --------- | -------------------------- | -------------------------- |
| `public`  | `PINECONE_API_KEY`         | `PINECONE_API_KEY`         |
| `private` | `PINECONE_PRIVATE_API_KEY` | `PINECONE_PRIVATE_API_KEY` |

If no `instance` is specified, **public** is used.

---

## Summary checklist

- [ ] Signature: `(failed_ids: list[str], final_sync_at: datetime | None) -> tuple[list[dict], bool]`.
- [ ] Each dict has top-level `content` (str) and `metadata` (dict).
- [ ] Each `metadata` has at least one of `doc_id` or `url`.
- [ ] For retry tracking, set `metadata["source_ids"]` to the source record ID(s), comma-separated if multiple.
- [ ] Use `failed_ids` to re-include previously failed records.
- [ ] Use `final_sync_at` for incremental sync when applicable.
- [ ] Return `is_chunked=True` only if you are already emitting final chunks; otherwise `False`.
- [ ] Choose `instance` (public/private) based on which Pinecone project you target.

For the sync API and services (fail list, sync status), see [service_api/cppa_pinecone_sync.md](service_api/cppa_pinecone_sync.md).
