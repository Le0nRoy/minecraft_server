"""
Minecraft server Telegram bot.

Monitors server health and provides commands to query status,
list players, and trigger backups.
"""

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile

import aiohttp
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("minecraft-bot")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID: str = os.environ["TELEGRAM_CHAT_ID"]
HEALTHCHECK_HOST: str = os.environ.get("HEALTHCHECK_HOST", "healthcheck")
HEALTHCHECK_PORT: str = os.environ.get("HEALTHCHECK_PORT", "8080")
HEALTH_URL: str = f"http://{HEALTHCHECK_HOST}:{HEALTHCHECK_PORT}/health"
POLL_INTERVAL: int = 60  # seconds between health polls
BACKUP_SCRIPT: str = "/scripts/backup.sh"
MAC_MAPPING_FILE: str = os.environ.get("MAC_MAPPING_FILE", "/data/mac-mapping.json")

# ---------------------------------------------------------------------------
# Server state machine
# ---------------------------------------------------------------------------

class ServerState:
    """Tracks the last known state of the Minecraft server."""

    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"

    def __init__(self) -> None:
        self.state: str = self.UNKNOWN
        # True when the previous poll succeeded (server was reachable + healthy)
        self._was_online: bool = False

    def transition(self, is_online: bool) -> str | None:
        """
        Update state given a new poll result.

        Returns a notification key if a notable transition occurred,
        otherwise None.
        """
        previous = self.state

        if is_online:
            self.state = self.ONLINE
        else:
            self.state = self.OFFLINE

        if previous == self.UNKNOWN:
            # First poll — don't spam a notification, just record state.
            self._was_online = is_online
            return None

        if not self._was_online and is_online:
            self._was_online = True
            return "online"

        if self._was_online and not is_online:
            self._was_online = False
            return "crashed"  # was online, now offline → possible crash

        return None


# ---------------------------------------------------------------------------
# Health fetching
# ---------------------------------------------------------------------------

async def fetch_health(session: aiohttp.ClientSession) -> dict | None:
    """
    Query the healthcheck service.

    Returns the parsed JSON dict on success, None on any error.
    """
    try:
        async with session.get(HEALTH_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json()
            logger.warning("Health endpoint returned HTTP %s", resp.status)
            return None
    except Exception as exc:
        logger.debug("Health query failed: %s", exc)
        return None


def _format_status(data: dict) -> str:
    """Format a health response into a human-readable message."""
    status = data.get("status", "unknown")
    icon = "✅" if status == "healthy" else "❌"

    lines = [f"{icon} *Server status:* `{status}`"]

    if "version" in data:
        lines.append(f"*Version:* `{data['version']}`")

    players = data.get("players", {})
    online = players.get("online", 0)
    max_players = players.get("max", 0)
    if online is not None:
        lines.append(f"*Players:* {online}/{max_players}")

    if "motd" in data:
        motd = data["motd"]
        if isinstance(motd, dict):
            motd = motd.get("clean", motd.get("raw", ""))
        if motd:
            lines.append(f"*MOTD:* {motd}")

    if "latency" in data:
        lines.append(f"*Latency:* {data['latency']} ms")

    return "\n".join(lines)


def _format_players(data: dict) -> str:
    """Format the player list from a health response."""
    players = data.get("players", {})
    online = players.get("online", 0)
    max_players = players.get("max", 0)
    sample = players.get("sample", [])

    if online == 0:
        return f"*Players online:* 0/{max_players}\nNo players currently online."

    lines = [f"*Players online:* {online}/{max_players}"]
    if sample:
        names = [p.get("name", "Unknown") for p in sample]
        lines.append("*Player list:*")
        for name in names:
            lines.append(f"  • {name}")
        if online > len(sample):
            lines.append(f"  _… and {online - len(sample)} more_")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MAC/IP mapping helpers
# ---------------------------------------------------------------------------

_MAC_RE = re.compile(r'^([0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}$')
_MAC_OR_IP_RE = re.compile(
    r'^([0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}$'
    r'|^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}$'
)


def _normalize_key(key: str) -> str:
    if _MAC_RE.match(key):
        return key.replace("-", ":").lower()
    return key


def _load_mapping_file() -> dict:
    try:
        with open(MAC_MAPPING_FILE) as f:
            data = json.load(f)
        return {_normalize_key(k): v for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load mapping file: %s", exc)
        return {}


def _write_mapping_atomic(data: dict) -> None:
    dir_ = os.path.dirname(MAC_MAPPING_FILE) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_, suffix=".tmp", delete=False) as f:
        json.dump(data, f, indent=2)
        tmp = f.name
    os.replace(tmp, MAC_MAPPING_FILE)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message listing available commands."""
    text = (
        "👋 *Minecraft Server Bot*\n\n"
        "Available commands:\n"
        "/status — Show current server status\n"
        "/players — List online players\n"
        "/backup — Trigger a server backup\n"
        "/macmap — Manage MAC/IP → basename mappings\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Query the healthcheck service and reply with server status."""
    async with aiohttp.ClientSession() as session:
        data = await fetch_health(session)

    if data is None:
        await update.message.reply_text(
            "❌ *Server status:* unreachable\n"
            "The healthcheck service did not respond.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(_format_status(data), parse_mode=ParseMode.MARKDOWN)


async def cmd_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Query the healthcheck service and reply with the player list."""
    async with aiohttp.ClientSession() as session:
        data = await fetch_health(session)

    if data is None:
        await update.message.reply_text(
            "❌ Unable to retrieve player list — healthcheck service unreachable.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(_format_players(data), parse_mode=ParseMode.MARKDOWN)


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger a backup by running the backup script."""
    await update.message.reply_text("💾 Starting backup, please wait…")

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [BACKUP_SCRIPT],
                capture_output=True,
                text=True,
                timeout=300,
            ),
        )
    except FileNotFoundError:
        msg = f"❌ Backup script not found at `{BACKUP_SCRIPT}`."
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return
    except subprocess.TimeoutExpired:
        await update.message.reply_text("❌ Backup timed out after 5 minutes.")
        return
    except Exception as exc:
        await update.message.reply_text(f"❌ Backup failed: {exc}")
        return

    if result.returncode == 0:
        output = result.stdout.strip()
        # Try to extract filename / size from script output (best effort)
        filename = ""
        size = ""
        for line in output.splitlines():
            line_lower = line.lower()
            if "backup" in line_lower and ("/" in line or ".tar" in line or ".zip" in line):
                filename = line.strip()
            if "size" in line_lower or "bytes" in line_lower or "mb" in line_lower:
                size = line.strip()

        if filename:
            detail = filename + (f" ({size})" if size else "")
            msg = f"💾 Backup completed: {detail}"
        else:
            msg = "💾 Backup completed successfully."
            if output:
                msg += f"\n```\n{output[:400]}\n```"

        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

        # Also send proactive notification to the configured chat
        bot: Bot = context.bot
        await bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        error = (result.stderr or result.stdout or "Unknown error").strip()[:400]
        msg = f"❌ Backup failed:\n```\n{error}\n```"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

        bot: Bot = context.bot
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"❌ Backup failed: {error[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def cmd_macmap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage MAC/Tailscale-IP → basename mappings. Admin-only."""
    if str(update.effective_chat.id) != CHAT_ID:
        await update.message.reply_text("Not authorised.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "/macmap list\n"
            "/macmap set <mac-or-tailscale-ip> <basename>\n"
            "/macmap del <mac-or-tailscale-ip>"
        )
        return

    subcommand = args[0].lower()

    if subcommand == "list":
        mapping = _load_mapping_file()
        if not mapping:
            await update.message.reply_text("MAC/IP mapping is empty.")
            return
        lines = [f"MAC/IP mapping ({len(mapping)} entries):"]
        for k, v in mapping.items():
            lines.append(f"• {k} → {v}")
        await update.message.reply_text("\n".join(lines))

    elif subcommand == "set":
        if len(args) < 3:
            await update.message.reply_text("Usage: /macmap set <mac-or-ip> <basename>")
            return
        raw_key = args[1]
        if not _MAC_OR_IP_RE.match(raw_key):
            await update.message.reply_text(
                f"Invalid key: {raw_key!r}. "
                "Expected MAC (aa:bb:cc:dd:ee:ff or aa-bb-cc-dd-ee-ff) or Tailscale IP."
            )
            return
        key = _normalize_key(raw_key)
        basename = " ".join(args[2:])
        mapping = _load_mapping_file()
        mapping[key] = basename
        try:
            _write_mapping_atomic(mapping)
            logger.info("macmap set: %s → %s", key, basename)
            await update.message.reply_text(f"Mapped {key} → {basename}")
        except OSError as exc:
            logger.error("macmap set write failed: %s", exc)
            await update.message.reply_text(f"Write failed: {exc}")

    elif subcommand == "del":
        if len(args) < 2:
            await update.message.reply_text("Usage: /macmap del <mac-or-ip>")
            return
        raw_key = args[1]
        key = _normalize_key(raw_key)
        mapping = _load_mapping_file()
        if key not in mapping:
            await update.message.reply_text(f"Not found: {key}")
            return
        del mapping[key]
        try:
            _write_mapping_atomic(mapping)
            logger.info("macmap del: %s", key)
            await update.message.reply_text(f"Removed mapping for {key}")
        except OSError as exc:
            logger.error("macmap del write failed: %s", exc)
            await update.message.reply_text(f"Write failed: {exc}")

    else:
        await update.message.reply_text(
            f"Unknown subcommand: {subcommand!r}. Use list, set, or del."
        )


# ---------------------------------------------------------------------------
# Background health polling
# ---------------------------------------------------------------------------

async def health_poll_loop(bot: Bot) -> None:
    """
    Poll the healthcheck service every POLL_INTERVAL seconds and send
    proactive notifications when the server state changes.
    """
    state = ServerState()
    logger.info("Health polling started (interval=%ds, url=%s)", POLL_INTERVAL, HEALTH_URL)

    async with aiohttp.ClientSession() as session:
        while True:
            data = await fetch_health(session)
            is_online = data is not None and data.get("status") == "healthy"

            transition = state.transition(is_online)

            if transition == "online":
                logger.info("Server came online")
                await _notify(bot, "✅ Minecraft server is online! Players can connect.")
            elif transition == "crashed":
                logger.warning("Server went offline (possible crash)")
                await _notify(bot, "🚨 Minecraft server may have crashed! Check logs.")
            elif transition == "offline":
                logger.info("Server went offline (clean shutdown)")
                await _notify(bot, "⚠️ Minecraft server went offline.")

            await asyncio.sleep(POLL_INTERVAL)


async def _notify(bot: Bot, text: str) -> None:
    """Send a message to the configured chat ID, logging errors instead of crashing."""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
        logger.info("Notification sent: %s", text)
    except Exception as exc:
        logger.error("Failed to send notification: %s", exc)


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

async def post_init(application) -> None:
    """Called after the application is initialised — send startup notification and start poller."""
    logger.info("Bot started, sending startup notification")
    await _notify(application.bot, "🤖 Minecraft bot started and monitoring server.")

    # Launch the health poller as a background task
    loop = asyncio.get_event_loop()
    task = loop.create_task(health_poll_loop(application.bot))
    application.bot_data["poll_task"] = task
    logger.info("Health poll task scheduled")


async def post_shutdown(application) -> None:
    """Called during shutdown — cancel the poller and send goodbye."""
    task = application.bot_data.get("poll_task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Health poll task cancelled")

    logger.info("Bot shutting down, sending notification")
    try:
        await application.bot.send_message(
            chat_id=CHAT_ID,
            text="🔄 Bot is shutting down",
        )
    except Exception as exc:
        logger.warning("Could not send shutdown notification: %s", exc)


def handle_sigterm(application) -> None:
    """Schedule graceful shutdown on SIGTERM."""
    logger.info("SIGTERM received, initiating shutdown")
    application.stop_running()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)
    if not CHAT_ID:
        logger.critical("TELEGRAM_CHAT_ID is not set")
        sys.exit(1)

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("players", cmd_players))
    application.add_handler(CommandHandler("backup", cmd_backup))
    application.add_handler(CommandHandler("macmap", cmd_macmap))

    # Register SIGTERM handler for graceful Docker shutdown
    signal.signal(signal.SIGTERM, lambda *_: handle_sigterm(application))

    logger.info(
        "Starting bot (healthcheck=%s, chat_id=%s)",
        HEALTH_URL,
        CHAT_ID,
    )
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
