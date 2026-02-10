# DiscordChatExporter Integration

User token method via DiscordChatExporter CLI — alternative to the bot API when server admins deny bot access.

> **Warning:** Using a user token violates Discord TOS. Risks: account ban, server ban. Use a disposable account if possible.

## Setup

1. Download [DiscordChatExporter CLI](https://github.com/Tyrrrz/DiscordChatExporter/releases) to `discord_activity_tracker/tools/`
2. Extract user token (see [tools/README.md](tools/README.md))
3. Configure `.env`:

```bash
DISCORD_USER_TOKEN=your_token_here
DISCORD_SERVER_ID=331718482485837825
DISCORD_CONTEXT_REPO_PATH=F:\boost\discord-cplusplus-together-context
```

## Pipeline

```
Discord ──> DiscordChatExporter CLI ──> JSON ──> Django DB ──> Markdown
               (subprocess)           (temp)    (shared)     (context repo)
```

## Modules

| File | Role |
|------|------|
| `sync/chat_exporter.py` | Python wrapper for CLI (export, parse, convert) |
| `management/commands/run_discord_exporter.py` | Django management command |
| `tools/DiscordChatExporter.Cli.exe` | CLI binary (not in git, see [tools/README.md](tools/README.md)) |

For commands and usage, see [README.md](README.md#user-token-method).

## Troubleshooting

| Error | Fix |
|-------|-----|
| CLI not found | Download from [releases](https://github.com/Tyrrrz/DiscordChatExporter/releases) to `tools/` |
| 401 Unauthorized | Token expired — extract a new one |
| HTTP 429 rate limit | Already handled; reduce `--parallel` if needed |
| Proxy errors | Unset `HTTP_PROXY` / `HTTPS_PROXY` before running |
| Empty results | Check `--days-back` value; try `--full-sync` |
