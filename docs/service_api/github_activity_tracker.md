# github_activity_tracker.services

**Module path:** `github_activity_tracker.services`
**Description:** Repos, languages, licenses, issues, pull requests, assignees, and labels. Single place for all writes to github_activity_tracker models.

**Type notation:** Model types refer to `github_activity_tracker.models`. Cross-app: `GitHubAccount` is `cppa_user_tracker.models.GitHubAccount`.

---

## Language

| Function                 | Parameter types | Return type          | Description                       | Raises |
| ------------------------ | --------------- | -------------------- | --------------------------------- | ------ |
| `get_or_create_language` | `name: str`     | `tuple[Language, bool]` | Get or create a Language by name. | `ValueError` if `name` is empty or whitespace-only. |

---

## License

| Function                | Parameter types                     | Return type         | Description                      | Raises |
| ----------------------- | ----------------------------------- | ------------------- | -------------------------------- | ------ |
| `get_or_create_license` | `name: str`, `spdx_id: str = ""`, `url: str = ""` | `tuple[License, bool]` | Get or create a License by name. | `ValueError` if `name` is empty or whitespace-only. |

---

## GitHubRepository

| Function                   | Parameter types                                 | Return type                       | Description                                                                                                                     |
| -------------------------- | ----------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `get_or_create_repository` | `owner_account: GitHubAccount`, `repo_name: str`, `**defaults: Any` | `tuple[GitHubRepository, bool]`   | Get or create a repo by owner and name. `defaults` used when creating (e.g. `stars`, `forks`, `description`, `repo_pushed_at`). |
| `add_repo_license`         | `repo: GitHubRepository`, `license_obj: License` | `None`                            | Add a License to a repo (M2M). Idempotent.                                                                                      |
| `remove_repo_license`      | `repo: GitHubRepository`, `license_obj: License` | `None`                            | Remove a License from a repo.                                                                                                   |

---

## RepoLanguage

| Function                          | Parameter types                         | Return type                   | Description                                             |
| --------------------------------- | --------------------------------------- | ----------------------------- | ------------------------------------------------------- |
| `add_repo_language`               | `repo: GitHubRepository`, `language: Language`, `line_count: int = 0` | `tuple[RepoLanguage, bool]`    | Add or get repo–language link with `line_count`.        |
| `update_repo_language_line_count` | `repo: GitHubRepository`, `language: Language`, `line_count: int` | `RepoLanguage`                 | Update `line_count` for an existing repo–language link. |

---

## Issue (assignees and labels)

| Function                | Parameter types            | Return type                 | Description                                    |
| ----------------------- | -------------------------- | --------------------------- | ---------------------------------------------- |
| `add_issue_assignee`    | `issue: Issue`, `account: GitHubAccount` | `None`                       | Add an assignee to an issue (M2M). Idempotent. |
| `remove_issue_assignee` | `issue: Issue`, `account: GitHubAccount` | `None`                       | Remove an assignee from an issue.              |
| `add_issue_label`       | `issue: Issue`, `label_name: str` | `tuple[IssueLabel, bool]`    | Add a label to an issue.                       |
| `remove_issue_label`    | `issue: Issue`, `label_name: str` | `None`                       | Remove a label from an issue.                  |

---

## Pull request (assignees and labels)

| Function                    | Parameter types         | Return type                       | Description                                |
| --------------------------- | ----------------------- | --------------------------------- | ------------------------------------------ |
| `add_pr_assignee`           | `pr: PullRequest`, `account: GitHubAccount` | `None`                             | Add an assignee to a PR (M2M). Idempotent. |
| `remove_pr_assignee`        | `pr: PullRequest`, `account: GitHubAccount` | `None`                             | Remove an assignee from a PR.              |
| `add_pull_request_label`   | `pr: PullRequest`, `label_name: str` | `tuple[PullRequestLabel, bool]`    | Add a label to a pull request.             |
| `remove_pull_request_label` | `pr: PullRequest`, `label_name: str` | `None`                             | Remove a label from a pull request.        |

---

## Not yet in API

- GitCommit, GitHubFile, GitCommitFileChange: add `create_commit`, `create_github_file`, `add_commit_file_change` when needed.
- IssueComment, PullRequestReview, PullRequestComment: add `create_issue_comment`, `create_pr_review`, `create_pr_comment` when needed.

---

## Sync / orchestration (not a service)

To sync a repo from GitHub (read last updated from DB, fetch from GitHub, save via the services above), use the **sync** package—it is orchestration, not a write:

| Entry point | Parameter types | Return type | Description |
|-------------|-----------------|-------------|-------------|
| `sync_github(repo)` | `repo: GitHubRepository` | `None` | Run full sync for one repo: repos (metadata), then commits, issues, pull requests. Accepts `GitHubRepository` or a subclass (e.g. `BoostLibraryRepository`). Raises `ValueError` if `repo` is `None`. |

**Module:** `github_activity_tracker.sync`
**Usage:** `from github_activity_tracker.sync import sync_github` then `sync_github(repo)`.

---

## Related

- [Service API index](README.md)
- [Contributing](../Contributing.md)
- [Schema](../Schema.md)
