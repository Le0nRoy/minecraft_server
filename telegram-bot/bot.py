"""
Minecraft server Telegram bot.

Monitors server health and provides commands to query status,
list players, and trigger backups.
"""

import asyncio
import functools
import logging
import os
import secrets
import signal
import subprocess
import sys
import time

import aiohttp
from mcrcon import MCRcon, MCRconException
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
WIPE_SCRIPT: str = os.environ.get("WIPE_SCRIPT", "/scripts/wipe.sh")
WIPE_TOKEN_TTL: int = 60  # seconds a wipe confirmation token stays valid

RCON_HOST: str = os.environ.get("RCON_HOST", "minecraft")
RCON_PORT: int = int(os.environ.get("RCON_PORT", "25575"))
RCON_PASSWORD: str = os.environ.get("RCON_PASSWORD", "")


def _parse_admin_ids(raw: str) -> list[int]:
    result = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            result.append(int(entry))
        except ValueError:
            logger.warning("ADMIN_USER_IDS: ignoring non-numeric entry %r", entry)
    return result


ADMIN_USER_IDS: list[int] = _parse_admin_ids(os.environ.get("ADMIN_USER_IDS", ""))

# ---------------------------------------------------------------------------
# Wipe confirmation state
# ---------------------------------------------------------------------------

# Maps user_id → (token, expiry_timestamp).  Single-process; no DB needed.
_wipe_pending: dict[int, tuple[str, float]] = {}

# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------

def require_admin(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in ADMIN_USER_IDS:
            await update.message.reply_text("⛔ Not authorised.")
            return
        return await func(update, context)
    return wrapper


async def _rcon_command(host: str, port: int, password: str, cmd: str) -> str:
    def _sync() -> str:
        with MCRcon(host, port, password) as mcr:
            return mcr.command(cmd)
    return await asyncio.to_thread(_sync)


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
    if update.effective_user.id in ADMIN_USER_IDS:
        text += (
            "\n*Admin commands:*\n"
            "/op /deop /kick /ban /pardon — player management\n"
            "/whitelist <add|remove> <player>\n"
            "/rcon <command> — raw RCON passthrough\n"
            "/wipe — wipe world data (requires token confirmation)\n"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@require_admin
async def cmd_op(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /op <player>")
        return
    player = context.args[0]
    user = update.effective_user
    try:
        result = await _rcon_command(RCON_HOST, RCON_PORT, RCON_PASSWORD, f"op {player}")
    except Exception as exc:
        await update.message.reply_text(f"❌ RCON error: {exc}")
        return
    logger.info("ADMIN cmd user_id=%d user=%s rcon=%r result=%r", user.id, user.username, f"op {player}", result)
    await update.message.reply_text(f"✅ `op {player}`: {result or 'done'}", parse_mode=ParseMode.MARKDOWN)
    await _notify(context.bot, f"🔧 {user.username or user.id} ran: op {player}")


@require_admin
async def cmd_deop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /deop <player>")
        return
    player = context.args[0]
    user = update.effective_user
    try:
        result = await _rcon_command(RCON_HOST, RCON_PORT, RCON_PASSWORD, f"deop {player}")
    except Exception as exc:
        await update.message.reply_text(f"❌ RCON error: {exc}")
        return
    logger.info("ADMIN cmd user_id=%d user=%s rcon=%r result=%r", user.id, user.username, f"deop {player}", result)
    await update.message.reply_text(f"✅ `deop {player}`: {result or 'done'}", parse_mode=ParseMode.MARKDOWN)
    await _notify(context.bot, f"🔧 {user.username or user.id} ran: deop {player}")


@require_admin
async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /kick <player>")
        return
    player = context.args[0]
    user = update.effective_user
    try:
        result = await _rcon_command(RCON_HOST, RCON_PORT, RCON_PASSWORD, f"kick {player}")
    except Exception as exc:
        await update.message.reply_text(f"❌ RCON error: {exc}")
        return
    logger.info("ADMIN cmd user_id=%d user=%s rcon=%r result=%r", user.id, user.username, f"kick {player}", result)
    await update.message.reply_text(f"✅ `kick {player}`: {result or 'done'}", parse_mode=ParseMode.MARKDOWN)
    await _notify(context.bot, f"🔧 {user.username or user.id} ran: kick {player}")


@require_admin
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /ban <player>")
        return
    player = context.args[0]
    user = update.effective_user
    try:
        result = await _rcon_command(RCON_HOST, RCON_PORT, RCON_PASSWORD, f"ban {player}")
    except Exception as exc:
        await update.message.reply_text(f"❌ RCON error: {exc}")
        return
    logger.info("ADMIN cmd user_id=%d user=%s rcon=%r result=%r", user.id, user.username, f"ban {player}", result)
    await update.message.reply_text(f"✅ `ban {player}`: {result or 'done'}", parse_mode=ParseMode.MARKDOWN)
    await _notify(context.bot, f"🔧 {user.username or user.id} ran: ban {player}")


@require_admin
async def cmd_pardon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /pardon <player>")
        return
    player = context.args[0]
    user = update.effective_user
    try:
        result = await _rcon_command(RCON_HOST, RCON_PORT, RCON_PASSWORD, f"pardon {player}")
    except Exception as exc:
        await update.message.reply_text(f"❌ RCON error: {exc}")
        return
    logger.info("ADMIN cmd user_id=%d user=%s rcon=%r result=%r", user.id, user.username, f"pardon {player}", result)
    await update.message.reply_text(f"✅ `pardon {player}`: {result or 'done'}", parse_mode=ParseMode.MARKDOWN)
    await _notify(context.bot, f"🔧 {user.username or user.id} ran: pardon {player}")


@require_admin
async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2 or context.args[0] not in ("add", "remove"):
        await update.message.reply_text("Usage: /whitelist <add|remove> <player>")
        return
    sub, player = context.args
    user = update.effective_user
    rcon_cmd = f"whitelist {sub} {player}"
    try:
        result = await _rcon_command(RCON_HOST, RCON_PORT, RCON_PASSWORD, rcon_cmd)
    except Exception as exc:
        await update.message.reply_text(f"❌ RCON error: {exc}")
        return
    logger.info("ADMIN cmd user_id=%d user=%s rcon=%r result=%r", user.id, user.username, rcon_cmd, result)
    await update.message.reply_text(f"✅ `{rcon_cmd}`: {result or 'done'}", parse_mode=ParseMode.MARKDOWN)
    await _notify(context.bot, f"🔧 {user.username or user.id} ran: {rcon_cmd}")


@require_admin
async def cmd_rcon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /rcon <minecraft command>")
        return
    raw = " ".join(context.args).lstrip("/")
    user = update.effective_user
    try:
        result = await _rcon_command(RCON_HOST, RCON_PORT, RCON_PASSWORD, raw)
    except Exception as exc:
        await update.message.reply_text(f"❌ RCON error: {exc}")
        return
    logger.info("ADMIN cmd user_id=%d user=%s rcon=%r result=%r", user.id, user.username, raw, result)
    await update.message.reply_text(f"✅ `{raw}`: {result or 'done'}", parse_mode=ParseMode.MARKDOWN)
    await _notify(context.bot, f"🔧 {user.username or user.id} ran: {raw}")


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


@require_admin
async def cmd_wipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Two-step world wipe: first call issues a token, second call with that token executes."""
    user = update.effective_user

    if not context.args:
        # Issue (or refresh) a confirmation token
        token = secrets.token_hex(8)
        expiry = time.time() + WIPE_TOKEN_TTL
        action = "refreshed" if user.id in _wipe_pending else "issued"
        _wipe_pending[user.id] = (token, expiry)
        logger.info("WIPE token %s user_id=%d user=%s", action, user.id, user.username)
        await update.message.reply_text(
            f"⚠️ *World wipe requested.*\n\n"
            f"To confirm, send within {WIPE_TOKEN_TTL}s:\n"
            f"`/wipe {token}`\n\n"
            f"This will delete all world data and restart the server.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Token provided — validate
    provided_token = context.args[0]
    pending = _wipe_pending.get(user.id)

    if pending is None:
        await update.message.reply_text("❌ No pending wipe. Run /wipe first to get a token.")
        return

    stored_token, expiry = pending

    if time.time() >= expiry:
        del _wipe_pending[user.id]
        logger.warning("WIPE token expired user_id=%d user=%s", user.id, user.username)
        await update.message.reply_text("❌ Wipe token expired. Run /wipe again.")
        return

    if provided_token != stored_token:
        logger.warning("WIPE invalid token user_id=%d user=%s", user.id, user.username)
        await update.message.reply_text("❌ Invalid wipe token.")
        return

    # Token valid — execute wipe
    del _wipe_pending[user.id]
    logger.info("WIPE initiated user_id=%d user=%s", user.id, user.username)
    await update.message.reply_text("🗑️ Wipe confirmed — starting wipe script…")

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [WIPE_SCRIPT],
                capture_output=True,
                text=True,
                timeout=300,
            ),
        )
    except FileNotFoundError:
        msg = f"❌ Wipe script not found at `{WIPE_SCRIPT}`."
        logger.error("WIPE failed user_id=%d script not found", user.id)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return
    except subprocess.TimeoutExpired:
        logger.error("WIPE failed user_id=%d timed out", user.id)
        await update.message.reply_text("❌ Wipe timed out after 5 minutes.")
        return

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "Unknown error").strip()[:400]
        logger.error(
            "WIPE failed user_id=%d user=%s returncode=%d stderr=%r",
            user.id, user.username, result.returncode, stderr,
        )
        await update.message.reply_text(
            f"❌ Wipe failed (exit {result.returncode}):\n```\n{stderr}\n```",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    logger.info("WIPE completed user_id=%d user=%s", user.id, user.username)
    actor = user.username or str(user.id)
    success_msg = f"🗑️ World wipe completed by {actor}. Server is restarting."
    await update.message.reply_text(success_msg)
    await _notify(context.bot, success_msg)


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
    application.add_handler(CommandHandler("op", cmd_op))
    application.add_handler(CommandHandler("deop", cmd_deop))
    application.add_handler(CommandHandler("kick", cmd_kick))
    application.add_handler(CommandHandler("ban", cmd_ban))
    application.add_handler(CommandHandler("pardon", cmd_pardon))
    application.add_handler(CommandHandler("whitelist", cmd_whitelist))
    application.add_handler(CommandHandler("rcon", cmd_rcon))
    application.add_handler(CommandHandler("wipe", cmd_wipe))

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
