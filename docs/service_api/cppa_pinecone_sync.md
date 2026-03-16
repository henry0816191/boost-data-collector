# cppa_pinecone_sync — Service API

Module: `cppa_pinecone_sync.services`

All creates/updates/deletes for `PineconeFailList` and `PineconeSyncStatus` must go through this module. See [Contributing.md](../Contributing.md).

---

## PineconeFailList

### `get_failed_ids(app_type: str) -> list[str]`

Return all `failed_id` values for the given application.

| Parameter | Type  | Description                          |
| --------- | ----- | ------------------------------------ |
| `app_type`  | `str` | Application type (e.g. `"slack"`). |

**Returns:** `list[str]` of failed_id values.

---

### `clear_failed_ids(app_type: str) -> int`

Delete all `PineconeFailList` records for the given application.

| Parameter | Type  | Description     |
| --------- | ----- | --------------- |
| `app_type`  | `str` | Application type. |

**Returns:** `int` — number of rows deleted.

---

### `record_failed_ids(app_type: str, failed_ids: list[str]) -> list[PineconeFailList]`

Bulk-create `PineconeFailList` entries for each failed ID.

| Parameter    | Type        | Description                            |
| ------------ | ----------- | -------------------------------------- |
| `app_type`   | `str`       | Application type.                      |
| `failed_ids` | `list[str]` | List of source record IDs that failed. |

**Returns:** `list[PineconeFailList]` — created objects. Empty list if `failed_ids` is empty.

---

## PineconeSyncStatus

### `get_final_sync_at(app_type: str) -> datetime | None`

Return `final_sync_at` for the given application, or `None` if no record exists.

| Parameter | Type  | Description     |
| --------- | ----- | --------------- |
| `app_type`  | `str` | Application type. |

**Returns:** `datetime | None`.

---

### `update_sync_status(app_type: str, final_sync_at: datetime | None = None) -> PineconeSyncStatus`

Create or update `PineconeSyncStatus` for the given application. Sets `final_sync_at` to the provided value, or `now()` if not given.

| Parameter       | Type               | Description                              |
| --------------- | ------------------ | ---------------------------------------- |
| `app_type`      | `str`              | Application type.                        |
| `final_sync_at` | `datetime \| None` | Timestamp. Defaults to `timezone.now()`. |

**Returns:** `PineconeSyncStatus` instance.
