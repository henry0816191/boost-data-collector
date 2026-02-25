# discord_activity_tracker.services

**Module path:** `discord_activity_tracker.services`
**Description:** Discord servers, channels, messages, and reactions. Single place for all writes to discord_activity_tracker models. Discord user profiles live in `cppa_user_tracker.DiscordProfile`.

**Type notation:** Model types refer to `discord_activity_tracker.models` unless noted. `DiscordProfile` refers to `cppa_user_tracker.models.DiscordProfile`.

---

## DiscordServer

| Function                     | Parameter types                                  | Return type                 | Description                                    |
| ---------------------------- | ------------------------------------------------ | --------------------------- | ---------------------------------------------- |
| `get_or_create_discord_server` | `server_id: int`, `server_name: str`, `icon_url: str = ""` | `tuple[DiscordServer, bool]` | Get or create server; update name/icon if changed. |

---

## DiscordChannel

| Function                      | Parameter types                                                       | Return type                   | Description                                   |
| ----------------------------- | --------------------------------------------------------------------- | ----------------------------- | --------------------------------------------- |
| `get_or_create_discord_channel` | `server: DiscordServer`, `channel_id: int`, `channel_name: str`, `channel_type: str`, `topic: str = ""`, `position: int = 0` | `tuple[DiscordChannel, bool]` | Get or create channel; update fields if changed. |
| `update_channel_last_activity` | `channel: DiscordChannel`, `last_activity_at: datetime`                | `DiscordChannel`              | Update last_activity_at.                      |
| `update_channel_last_synced`   | `channel: DiscordChannel`, `timestamp: datetime \| None = None`         | `DiscordChannel`              | Update last_synced_at (defaults to now).     |

---

## DiscordMessage

| Function                        | Parameter types                                                                 | Return type                 | Description                    |
| ------------------------------- | -------------------------------------------------------------------------------- | --------------------------- | ------------------------------ |
| `create_or_update_discord_message` | `message_id: int`, `channel: DiscordChannel`, `author: DiscordProfile`, `content: str`, `message_created_at: datetime`, `message_edited_at: datetime \| None = None`, `reply_to_message_id: int \| None = None`, `attachment_urls: list \| None = None` | `tuple[DiscordMessage, bool]` | Create or update message.      |
| `mark_message_deleted`         | `message: DiscordMessage`, `deleted_at: datetime \| None = None`                  | `DiscordMessage`            | Mark message as deleted.       |

---

## DiscordReaction

| Function                 | Parameter types                                | Return type                 | Description             |
| ------------------------ | ---------------------------------------------- | --------------------------- | ----------------------- |
| `add_or_update_reaction` | `message: DiscordMessage`, `emoji: str`, `count: int` | `tuple[DiscordReaction, bool]` | Add or update reaction. |

---

## Query helpers

| Function              | Parameter types                                  | Return type     | Description                          |
| --------------------- | ------------------------------------------------- | --------------- | ------------------------------------ |
| `get_active_channels` | `server: DiscordServer`, `days: int = 30`         | `list`          | Channels with activity in last N days. |

---

## Related

- [Service API index](README.md)
- [Contributing](../Contributing.md)
- [Schema](../Schema.md)
- [Workspace](../Workspace.md) – raw export JSON in `workspace/discord_activity_tracker/raw/`
