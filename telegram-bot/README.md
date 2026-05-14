# Minecraft Server Telegram Bot

A Python Telegram bot that monitors your Minecraft server and provides status commands.
It polls the healthcheck service every 60 seconds and sends proactive notifications
when the server comes online, goes offline, or appears to have crashed.

---

## Setup

### 1. Get a Bot Token from BotFather

1. Open Telegram and search for `@BotFather`.
2. Send `/newbot` and follow the prompts (choose a name and username).
3. BotFather will reply with a token in the format `123456789:ABCdef...`.
4. Save this as `TELEGRAM_BOT_TOKEN`.

### 2. Get your Chat ID

The bot needs to know where to send proactive notifications.

**Option A — personal chat:**
1. Start a conversation with your bot (search for its username and press Start).
2. Send any message to the bot.
3. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
4. Look for `"chat": {"id": <number>}` in the JSON — that number is your chat ID.

**Option B — group chat:**
1. Add the bot to the group.
2. Send a message mentioning the bot (e.g. `/start@yourbotusername`).
3. Use the same `getUpdates` URL above; the chat ID will be a negative number for groups.

Save the ID as `TELEGRAM_CHAT_ID`.

---

## Environment Variables

| Variable            | Required | Default       | Description                                         |
|---------------------|----------|---------------|-----------------------------------------------------|
| `TELEGRAM_BOT_TOKEN`| yes      | —             | Token from BotFather                                |
| `TELEGRAM_CHAT_ID`  | yes      | —             | Chat ID to receive proactive notifications          |
| `HEALTHCHECK_HOST`  | no       | `healthcheck` | Hostname of the healthcheck service                 |
| `HEALTHCHECK_PORT`  | no       | `8080`        | Port of the healthcheck service                     |
| `LOG_LEVEL`         | no       | `INFO`        | Python log level (`DEBUG`, `INFO`, `WARNING`, etc.) |

---

## Available Commands

| Command    | Description                                              |
|------------|----------------------------------------------------------|
| `/start`   | Show welcome message and list available commands         |
| `/status`  | Display server status (online/offline, version, players) |
| `/players` | List currently online players                            |
| `/backup`  | Trigger a server backup via `/scripts/backup.sh`         |

---

## Proactive Notifications

The bot sends automatic notifications when:

- **Server comes online** — `✅ Minecraft server is online! Players can connect.`
- **Server goes offline** — `⚠️ Minecraft server went offline.`
- **Server may have crashed** — `🚨 Minecraft server may have crashed! Check logs.`
- **Backup completed** — `💾 Backup completed: <filename> (<size>)`
- **Backup failed** — `❌ Backup failed: <error>`
- **Bot started** — `🤖 Minecraft bot started and monitoring server.`
- **Bot shutting down** — `🔄 Bot is shutting down`

---

## Running with Docker Compose

Add the following service to your `docker-compose.yml`:

```yaml
telegram-bot:
  build: ./telegram-bot
  restart: unless-stopped
  environment:
    TELEGRAM_BOT_TOKEN: "${TELEGRAM_BOT_TOKEN}"
    TELEGRAM_CHAT_ID: "${TELEGRAM_CHAT_ID}"
    HEALTHCHECK_HOST: healthcheck
    HEALTHCHECK_PORT: "8080"
    LOG_LEVEL: INFO
  volumes:
    - ./scripts:/scripts:ro
  depends_on:
    - healthcheck
```

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your `.env` file.

---

## Building and Running Manually

```bash
cd telegram-bot
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHAT_ID="your-chat-id"
python bot.py
```
