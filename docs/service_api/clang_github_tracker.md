# clang_github_tracker.services

**Module path:** `clang_github_tracker.services`
**Description:** Upserts for `ClangGithubIssueItem` and `ClangGithubCommit` (no FKs to other apps). Used by `sync_clang_github_activity`, `backfill_clang_github_tracker`, and date resolution watermarks.

**Type notation:** Models live in `clang_github_tracker.models`.

---

## Upserts

| Function | Parameters | Return | Raises |
| -------- | ---------- | ------ | ------ |
| `upsert_issue_item` | `number: int`, `*, is_pull_request: bool`, `github_created_at`, `github_updated_at` | `tuple[ClangGithubIssueItem, bool]` (instance, created) | — |
| `upsert_commit` | `sha: str`, `*, github_committed_at` | `tuple[ClangGithubCommit, bool]` | `ValueError` if `sha` is not 40 hex chars |

---

## API fetch watermarks

| Function | Return | Notes |
| -------- | ------ | ----- |
| `get_issue_item_watermark` | `datetime \| None` | `Max(github_updated_at)` over all issue/PR rows (unified issues+PR stream). |
| `get_commit_watermark` | `datetime \| None` | `Max(github_committed_at)` over commits. |
| `start_after_watermark` | `datetime \| None` | `max_dt + timedelta(milliseconds=1)` or `None` if `max_dt` is `None`. |

Used by `clang_github_tracker.state_manager.resolve_start_end_dates` (with optional CLI `--since` / `--until` bounds).

---

## Related docs

- [Schema.md](../Schema.md) – Section 2b: Clang GitHub Tracker.
- [Workspace.md](../Workspace.md) – `workspace/raw/github_activity_tracker/`, `workspace/clang_github_tracker/`.
- [Contributing.md](../Contributing.md) – Service layer rule.
