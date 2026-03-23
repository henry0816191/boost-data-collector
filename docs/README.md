# Documentation (per-topic)

Documentation is organized **by topic**, not by app. Each doc covers one cross-cutting concern (workflow, workspace, service API, schema, etc.). To understand a single app, use the relevant topic docs and the per-app service API file.

## Topic index

| Topic | Doc | Purpose |
|-------|-----|---------|
| **Workflow** | [Workflow.md](Workflow.md) | Main application workflow, execution order, and project details. |
| **Operations** | [operations/](operations/README.md) | **Group:** shared I/O (GitHub, Discord, etc.) used by multiple apps. Index in [operations/README.md](operations/README.md). |
| → GitHub | [operations/github.md](operations/github.md) | Clone, push, fetch file, create PR/issue/comment; token use. |
| **Workspace** | [Workspace.md](Workspace.md) | Workspace layout and usage for file processing (`workspace/<app>/...`). |
| **Schema** | [Schema.md](Schema.md) | Database schema and table relationships. |
| **Development** | [Development_guideline.md](Development_guideline.md) | Development setup, app requirements, and step-by-step workflow. |
| **Testing** | [README.md](../README.md#running-tests), [Development_guideline.md](Development_guideline.md#testing-workflow) | How to run tests (pytest), coverage, and when to run them. |
| **Deployment** | [Deployment.md](Deployment.md) | CI/CD pipeline, environment secrets (`SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`; optional `SSH_PORT`), server setup, and deploy script behavior. |
| **Contributing** | [Contributing.md](Contributing.md) | Service layer (single place for writes) and contributor guidelines. |
| **Service API** | [Service_API.md](Service_API.md) | API reference and index for all service layer functions. |
| **Service API (per app)** | [service_api/](service_api/) | Per-app service API docs (name, description, parameters, return types, validation). |

## Operations (shared I/O)

**Operations** = external integrations used by many apps (not the same as **Service API**, which is for DB writes). See **[operations/README.md](operations/README.md)** for the full list and when to add one.

- **GitHub:** [operations/github.md](operations/github.md) — `github_ops` app (clone, push, PR, issue, comment).
- **Discord:** *(add operations/discord.md when you add Discord notifications.)*

## Finding app-specific info

- **Service layer (create/update/delete):** [service_api/](service_api/) → e.g. [github_activity_tracker.md](service_api/github_activity_tracker.md).
- **Operations (GitHub, Discord, …):** [operations/README.md](operations/README.md) and the docs in [operations/](operations/).
- **Workspace (file paths, JSON cache):** [Workspace.md](Workspace.md) — which apps use workspace and the folder layout.
- **Schema (models):** [Schema.md](Schema.md).
- **Workflow (when an app runs):** [Workflow.md](Workflow.md).
