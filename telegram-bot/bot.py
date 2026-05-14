"""
Minecraft server Telegram bot.

Monitors server health and provides commands to query status,
list players, and trigger backups.
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys

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
