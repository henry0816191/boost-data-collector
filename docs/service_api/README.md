# Service API index

Index of all app service modules. All writes to app models must go through the service layer.

**Import pattern:** `from <app>.services import <function>`

| Service module | App | Short description |
|----------------|-----|-------------------|
| [cppa_user_tracker.services](cppa_user_tracker.md) | cppa_user_tracker | Identity, profiles, emails, and staging (TmpIdentity, TempProfileIdentityRelation). |
| [github_activity_tracker.services](github_activity_tracker.md) | github_activity_tracker | Repos, languages, licenses, issues, pull requests, assignees, labels. |
| [boost_library_tracker.services](boost_library_tracker.md) | boost_library_tracker | Boost libraries, versions, dependencies, categories, maintainers/authors. |
| [boost_library_docs_tracker.services](boost_library_docs_tracker.md) | boost_library_docs_tracker | BoostDocContent (per-content metadata and sync state: is_upserted, first/last_version); BoostLibraryDocumentation (join row linking library-version to doc content only). |
| [cppa_pinecone_sync.services](cppa_pinecone_sync.md)           | cppa_pinecone_sync      | Pinecone fail list and sync status (failure tracking, last-sync bookkeeping). |
| [boost_usage_tracker.services](boost_usage_tracker.md)           | boost_usage_tracker     | External repos, Boost usage, missing-header tmp. |
| [discord_activity_tracker.services](discord_activity_tracker.md) | discord_activity_tracker | Servers, channels, messages, reactions (user profiles in cppa_user_tracker). |
| [cppa_youtube_script_tracker.services](cppa_youtube_script_tracker.md) | cppa_youtube_script_tracker | YouTube channels, videos, transcript state, and speaker links for C++ conference talks. |
| [clang_github_tracker.services](clang_github_tracker.md) | clang_github_tracker | Upsert llvm issue/PR/commit rows; DB watermarks for API fetch windows. |

---

## Quick reference

- **cppa_user_tracker** – Create/update Identity, TmpIdentity, BaseProfile–TmpIdentity relations, and Email.
- **github_activity_tracker** – Get-or-create Language/License/Repository; add repo languages/licenses; manage issue and PR assignees and labels.
- **boost_library_tracker** – Get-or-create BoostLibraryRepository, BoostLibrary, BoostVersion, BoostLibraryVersion; add dependencies, categories, and role relationships.
- **boost_library_docs_tracker** – Get-or-create BoostDocContent (by content_hash; holds url, first/last_version, is_upserted); link to BoostLibraryVersion via BoostLibraryDocumentation (join row only); Pinecone sync driven by BoostDocContent.is_upserted.
- **boost_usage_tracker** – Get-or-create BoostExternalRepository, create/update BoostUsage, record missing headers (BoostMissingHeaderTmp).
- **discord_activity_tracker** – Get-or-create DiscordServer, DiscordChannel; create/update DiscordMessage, DiscordReaction. Discord user profiles in cppa_user_tracker.
- **cppa_youtube_script_tracker** – Get-or-create YouTubeChannel, YouTubeVideo; update transcript state; link speakers to videos. Speaker profiles (`YoutubeSpeaker`) in cppa_user_tracker.
- **cppa_pinecone_sync** – Get/clear/record failed IDs in PineconeFailList; get/update PineconeSyncStatus.
- **clang_github_tracker** – Upsert `ClangGithubIssueItem` / `ClangGithubCommit` during sync or backfill; read `Max(github_updated_at)` / `Max(github_committed_at)` for fetch cursors.

See [Contributing.md](../Contributing.md) for the rule that all writes go through the service layer.
