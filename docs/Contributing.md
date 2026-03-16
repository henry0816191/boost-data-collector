# Contributing to Boost Data Collector

This document describes how to contribute to the project, with emphasis on the **service layer** and data-write rules.

## Service layer: single place for writes

Each Django app that has **models** provides a **`services.py`** module. This is the **only** place where code should create, update, or delete rows for that app’s models.

### Rule

- **All** inserts/updates/deletes for an app’s models must go through functions in that app’s **`services.py`**.
- Do **not** call `Model.objects.create()`, `model.save()`, or `model.delete()` from outside `services.py` (e.g. from management commands, views, other apps, or tests that are not testing the service layer itself).

### Why

- **Single place for write logic:** Validation, defaults, and side effects live in one module.
- **Easier to change:** Schema or business rules can be updated in one place.
- **Clear API:** Contributors know where to look and what to call.

### Which apps have a service layer

| App                       | File                                  | Notes                                         |
| ------------------------- | ------------------------------------- | --------------------------------------------- |
| `cppa_user_tracker`       | `cppa_user_tracker/services.py`       | Identity, profiles, emails, staging.     |
| `github_activity_tracker` | `github_activity_tracker/services.py` | Repos, languages, licenses, issues, PRs. |
| `boost_library_tracker`   | `boost_library_tracker/services.py`   | Boost libraries, versions, dependencies, categories, roles. |
| `boost_library_docs_tracker` | `boost_library_docs_tracker/services.py` | BoostDocContent and BoostLibraryDocumentation (doc scrape and sync status). |
| `boost_usage_tracker`     | `boost_usage_tracker/services.py`     | External repos, Boost usage, missing-header tmp. |
| `cppa_pinecone_sync`       | `cppa_pinecone_sync/services.py`       | Pinecone fail list and sync status writes.                  |
| `discord_activity_tracker` | `discord_activity_tracker/services.py` | Servers, users, channels, messages, reactions.              |

For a full list of functions, parameter/return types, and validation (e.g. empty `name` raises `ValueError`), see **[Service_API.md](Service_API.md)** and the per-app docs in **[service_api/](service_api/)** (index: [service_api/README.md](service_api/README.md)).

### How to use

1. **From management commands or other apps:** Import and call the service functions.

   ```python
   from cppa_user_tracker.services import create_identity, add_email
   from github_activity_tracker.services import get_or_create_language, add_pull_request_label

   identity = create_identity(display_name="Jane")
   add_email(identity.profiles.first(), "jane@example.com")
   lang, _ = get_or_create_language("Python")
   add_pull_request_label(pr, "bug")
   ```

2. **Adding new write behavior:** Add a new function in the app’s `services.py` (and optionally a helper in the same module). Do not add new writes by calling the model or manager directly from outside `services.py`.

3. **Reading data:** No restriction. Use the ORM as usual: `Model.objects.filter(...)`, `model.related_set.all()`, etc.

### Testing

- **Running tests:** From the project root, install dev deps (`pip install -r requirements-dev.txt`) and run `python -m pytest`. See [README.md](../README.md#running-tests) and [Development_guideline.md](Development_guideline.md#testing-workflow) for full commands and options.
- **Unit tests for `services.py`:** Call the service functions and assert on the database (or mocks) as needed.
- **Other tests:** Prefer service functions when setting up data. If you must create models directly for tests, keep it in test code (e.g. fixtures or test helpers) and avoid doing the same in production code.

## Other guidelines

- **Branching:** Create feature branches from `develop`. Open pull requests against `develop`. See [Development_guideline.md](Development_guideline.md).
- **Code style:** Use Python 3.11+ and follow Django and project conventions. Use the project’s logging (`logging.getLogger(__name__)`).
- **Database:** Use the Django ORM and migrations. Writes only through the service layer as above.
- **Docs:** Update this doc (and app `services.py` docstrings) when adding new apps or changing the write rules.

## Related documentation

- [Service_API.md](Service_API.md) – API reference for all service layer functions.
- [Development_guideline.md](Development_guideline.md) – Setup, workflow, adding apps.
- [Workflow.md](Workflow.md) – Execution order and collectors.
- [Schema.md](Schema.md) – Database schema.
