# boost_usage_tracker.services

**Module path:** `boost_usage_tracker.services`
**Description:** External repositories that use Boost, BoostUsage records, and temporary missing-header records. Single place for all writes to boost_usage_tracker models.

**Type notation:** Model types refer to `boost_usage_tracker.models`. Cross-app: `GitHubRepository`, `GitHubFile` are from `github_activity_tracker.models`; `BoostFile` is from `boost_library_tracker.models`.

---

## BoostExternalRepository

| Function                            | Parameter types                                                                                             | Return type                            | Raises |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------- | ------ |
| `get_or_create_boost_external_repo` | `github_repository: GitHubRepository`, `boost_version=""`, `is_boost_embedded=False`, `is_boost_used=False` | `tuple[BoostExternalRepository, bool]` | —      |
| `update_boost_external_repo`        | `ext_repo: BoostExternalRepository`, `boost_version=None`, `is_boost_embedded=None`, `is_boost_used=None`   | `BoostExternalRepository`              | —      |

---

## BoostUsage

| Function                             | Parameter types                                                                     | Return type                                      | Raises |
| ------------------------------------ | ----------------------------------------------------------------------------------- | ------------------------------------------------ | ------ |
| `create_or_update_boost_usage`       | `repo`, `boost_header: BoostFile`, `file_path: GitHubFile`, `last_commit_date=None` | `tuple[BoostUsage, bool]`                        | —      |
| `mark_usage_excepted`                | `usage: BoostUsage`                                                                 | `BoostUsage`                                     | —      |
| `get_active_usages_for_repo`         | `repo: BoostExternalRepository`                                                     | `list[BoostUsage]`                               | —      |
| `get_or_create_missing_header_usage` | `repo`, `file_path: GitHubFile`, `header_name: str`, `last_commit_date=None`        | `tuple[BoostUsage, BoostMissingHeaderTmp, bool]` | —      |

**Note:** `get_or_create_missing_header_usage` creates or reuses a placeholder `BoostUsage` with `boost_header=None` and a `BoostMissingHeaderTmp` row for the unresolved `header_name`. Used when the header is not yet in BoostFile/GitHubFile.

---

## Related docs

- [Schema.md](../Schema.md) – Section 4: Boost Usage Tracker.
- [Contributing.md](../Contributing.md) – Service layer rule.
