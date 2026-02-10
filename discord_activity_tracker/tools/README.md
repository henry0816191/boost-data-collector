# DiscordChatExporter CLI

v2.46.0 for Windows. Download from [GitHub](https://github.com/Tyrrrz/DiscordChatExporter/releases) if missing.

> **Warning:** Using a user token violates Discord TOS. Use at your own risk.

## Get Discord User Token

| Method | Steps |
|--------|-------|
| **Network Monitor** (recommended) | DevTools (`Ctrl+Shift+I`) > Network > reload (`F5`) > filter "messages" > click any request > copy `authorization` header |
| **Browser Console** | DevTools > Console > paste snippet below > copy token |
| **Storage Inspector** | DevTools > Application > Local Storage > `discord.com` > search "token" |

Console snippet:
```javascript
let m;webpackChunkdiscord_app.push([[Math.random()],{},e=>{for(let i in e.c){let x=e.c[i];if(x?.exports?.$8&&x.exports.LP&&x.exports.gK){m=x;break}}}]);m&&console.log("Token:",m.exports.LP());
```

## CLI Usage

```bash
# Check version
./DiscordChatExporter.Cli.exe --version

# Export guild to JSON
./DiscordChatExporter.Cli.exe exportguild -t "TOKEN" -g SERVER_ID -f Json --after "2026-02-09"

# Export single channel
./DiscordChatExporter.Cli.exe export -t "TOKEN" -c CHANNEL_ID -f Json
```
