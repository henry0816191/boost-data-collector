# Discord Activity Tracker

Archives Discord server chat history to markdown files for LLM consumption.

## Two Sync Methods

| | Bot API | DiscordChatExporter CLI |
|--|---------|------------------------|
| **Command** | `run_discord_activity_tracker` | `run_discord_exporter` |
| **Auth** | Bot token (admin adds bot) | User token (browser DevTools) |
| **TOS** | Compliant | Violates TOS |
| **Setup** | [README below](#bot-method) | [EXPORTER_INTEGRATION.md](EXPORTER_INTEGRATION.md) |

## Setup

### Environment Variables

```bash
# Bot method
DISCORD_TOKEN=bot_token_here

# User token method (alternative)
DISCORD_USER_TOKEN=user_token_here

# Shared
DISCORD_SERVER_ID=331718482485837825
DISCORD_CONTEXT_REPO_PATH=F:\boost\discord-cplusplus-together-context
```

### Migrations

```bash
python manage.py makemigrations discord_activity_tracker
python manage.py migrate
```

## Usage

### Bot Method

```bash
python manage.py run_discord_activity_tracker              # sync + export
python manage.py run_discord_activity_tracker --task sync   # sync only
python manage.py run_discord_activity_tracker --task export  # export only
python manage.py run_discord_activity_tracker --dry-run      # preview
```

### User Token Method

```bash
python manage.py run_discord_exporter                       # sync + export (last 30 days)
python manage.py run_discord_exporter --days-back 15         # sync last 15 days + export
python manage.py run_discord_exporter --task sync            # sync only
python manage.py run_discord_exporter --task export          # export only
python manage.py run_discord_exporter --task import-only     # import pre-exported JSON + export
python manage.py run_discord_exporter --dry-run              # preview
```

#### Full History (first-time setup)

The CLI export for full history takes hours and will timeout via Python subprocess. Run the CLI directly, then import:

```bash
# Step 1: Run CLI manually (no timeout)
# Output goes to workspace/discord_activity_tracker/raw/ (or WORKSPACE_DIR/discord_activity_tracker/raw/)
discord_activity_tracker\tools\DiscordChatExporter.Cli.exe exportguild --token "USER_TOKEN" --guild 331718482485837825 --output "workspace\discord_activity_tracker\raw\" --format Json --parallel 3

# Step 2: Import JSON files to DB + export markdown
python manage.py run_discord_exporter --task import-only --months 120 --active-days 99999
```

## Output

```
YYYY/YYYY-MM/YYYY-MM-channel-name.md
```

Each file: YAML frontmatter (metadata) + messages grouped by date.

## Architecture

| Module | Role |
|--------|------|
| `models.py` | DB schema (Server, User, Channel, Message, Reaction) |
| `services.py` | Service layer for all DB writes |
| `sync/client.py` | Discord bot API wrapper (discord.py) |
| `sync/chat_exporter.py` | DiscordChatExporter CLI wrapper |
| `sync/messages.py` | Message processing + incremental sync |
| `sync/export.py` | Markdown generation + git operations |

## Notes

- **Intended use:** Daily incremental runs. Each run syncs only new messages since the last sync, so runs stay fast (~5–10 sec per channel). Full-historical scrapes are slow; for first-time setup, see [Full History](#full-history-first-time-setup) above.
- Only exports channels active in last 30 days (configurable via `--active-days`)
- Incremental sync via `last_synced_at` per channel
- First run may take 30-60 min; subsequent runs ~5-10 sec per channel
- **Bot messages**: Both sync methods include bot-generated content. DiscordChatExporter exports all messages by default. Bot authors are labeled `(bot)` in the markdown output.
