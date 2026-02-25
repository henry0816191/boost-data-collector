# boost_library_tracker.services

**Module path:** `boost_library_tracker.services`
**Description:** Boost libraries, versions, dependencies, categories, and maintainer/author roles. Single place for all writes to boost_library_tracker models.

**Type notation:** Model types refer to `boost_library_tracker.models`. Cross-app: `GitHubRepository`, `GitHubFile` are from `github_activity_tracker.models`; `GitHubAccount` is from `cppa_user_tracker.models`.

---

## BoostLibraryRepository

| Function                        | Parameter types                    | Return type                              | Raises |
| ------------------------------- | ---------------------------------- | ---------------------------------------- | ------ |
| `get_or_create_boost_library_repo` | `github_repository: GitHubRepository` | `tuple[BoostLibraryRepository, bool]`    | —      |

---

## BoostLibrary

| Function                    | Parameter types                          | Return type                   | Raises |
| --------------------------- | ---------------------------------------- | ----------------------------- | ------ |
| `get_or_create_boost_library` | `repo: BoostLibraryRepository`, `name: str` | `tuple[BoostLibrary, bool]`   | `ValueError` if `name` is empty or whitespace-only. |

---

## BoostFile

| Function                  | Parameter types                          | Return type               |
| ------------------------- | ---------------------------------------- | ------------------------- |
| `get_or_create_boost_file` | `github_file: GitHubFile`, `library: BoostLibrary` | `tuple[BoostFile, bool]`  |

---

## BoostVersion

| Function                    | Parameter types                     | Return type                 | Raises |
| --------------------------- | ----------------------------------- | --------------------------- | ------ |
| `get_or_create_boost_version` | `version: str`, `version_created_at=None` | `tuple[BoostVersion, bool]` | `ValueError` if `version` is empty or whitespace-only. |

---

## BoostLibraryVersion

| Function                          | Parameter types                                                       | Return type                         |
| --------------------------------- | --------------------------------------------------------------------- | ----------------------------------- |
| `get_or_create_boost_library_version` | `library: BoostLibrary`, `version: BoostVersion`, `cpp_version=""`, `description=""` | `tuple[BoostLibraryVersion, bool]` |

---

## BoostDependency

| Function            | Parameter types                                              | Return type                    |
| ------------------- | ------------------------------------------------------------ | ------------------------------ |
| `add_boost_dependency` | `client_library: BoostLibrary`, `version: BoostVersion`, `dep_library: BoostLibrary` | `tuple[BoostDependency, bool]` |

---

## DependencyChangeLog

| Function                 | Parameter types                                                    | Return type                           |
| ------------------------ | ------------------------------------------------------------------ | ------------------------------------- |
| `add_dependency_changelog` | `client_library: BoostLibrary`, `dep_library: BoostLibrary`, `is_add: bool`, `created_at` | `tuple[DependencyChangeLog, bool]`     |

---

## BoostLibraryCategory

| Function                          | Parameter types | Return type                             | Raises |
| --------------------------------- | --------------- | --------------------------------------- | ------ |
| `get_or_create_boost_library_category` | `name: str`     | `tuple[BoostLibraryCategory, bool]`     | `ValueError` if `name` is empty or whitespace-only. |

---

## BoostLibraryCategoryRelationship

| Function             | Parameter types                                    | Return type                                   |
| -------------------- | --------------------------------------------------- | --------------------------------------------- |
| `add_library_category` | `library: BoostLibrary`, `category: BoostLibraryCategory` | `tuple[BoostLibraryCategoryRelationship, bool]` |

---

## BoostLibraryRoleRelationship

| Function                | Parameter types                                                                 | Return type                                   |
| ----------------------- | ------------------------------------------------------------------------------- | --------------------------------------------- |
| `add_library_version_role` | `library_version: BoostLibraryVersion`, `account: GitHubAccount`, `is_maintainer=False`, `is_author=False` | `tuple[BoostLibraryRoleRelationship, bool]`   |
