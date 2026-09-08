"""Unit and integration tests for bot.py admin/RCON features."""

import asyncio
import logging
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stubs so bot.py can be imported without real credentials or mcrcon
# ---------------------------------------------------------------------------

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
os.environ.setdefault("ADMIN_USER_IDS", "100,200")

# Stub mcrcon before importing bot so the import succeeds without the package
mcrcon_stub = types.ModuleType("mcrcon")


class _MCRcon:
    def __init__(self, host, password, port=25575):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def command(self, cmd):
        return ""


class _MCRconException(Exception):
    pass


mcrcon_stub.MCRcon = _MCRcon
mcrcon_stub.MCRconException = _MCRconException
sys.modules["mcrcon"] = mcrcon_stub

import bot  # noqa: E402  (must come after stubs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_update(user_id: int, username: str = "tester") -> MagicMock:
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def _make_context(*args) -> MagicMock:
    ctx = MagicMock()
    ctx.args = list(args)
    ctx.bot = MagicMock()
    return ctx


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# _parse_admin_ids
# ---------------------------------------------------------------------------

class TestParseAdminIds(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(bot._parse_admin_ids(""), [])

    def test_single_id(self):
        self.assertEqual(bot._parse_admin_ids("123"), [123])

    def test_multiple_ids(self):
        self.assertEqual(bot._parse_admin_ids("123,456"), [123, 456])

    def test_whitespace_ignored(self):
        self.assertEqual(bot._parse_admin_ids(" 123 , 456 "), [123, 456])

    def test_non_numeric_skipped_with_warning(self):
        with self.assertLogs("minecraft-bot", level="WARNING") as cm:
            result = bot._parse_admin_ids("123,abc,456")
        self.assertEqual(result, [123, 456])
        self.assertTrue(any("abc" in line for line in cm.output))

    def test_trailing_comma(self):
        self.assertEqual(bot._parse_admin_ids("123,"), [123])


# ---------------------------------------------------------------------------
# require_admin decorator
# ---------------------------------------------------------------------------

class TestRequireAdmin(unittest.TestCase):
    def setUp(self):
        # Patch ADMIN_USER_IDS so tests are independent of env
        self._orig = bot.ADMIN_USER_IDS
        bot.ADMIN_USER_IDS = [100, 200]

    def tearDown(self):
        bot.ADMIN_USER_IDS = self._orig

    def test_admin_user_calls_wrapped_function(self):
        called = []

        @bot.require_admin
        async def handler(update, context):
            called.append(True)

        update = _make_update(100)
        run(handler(update, MagicMock()))
        self.assertEqual(called, [True])

    def test_non_admin_user_gets_rejection_reply(self):
        @bot.require_admin
        async def handler(update, context):
            pass  # should not be called

        update = _make_update(999)
        run(handler(update, MagicMock()))
        update.message.reply_text.assert_called_once_with("⛔ Not authorised.")

    def test_non_admin_does_not_call_wrapped_function(self):
        called = []

        @bot.require_admin
        async def handler(update, context):
            called.append(True)

        update = _make_update(999)
        run(handler(update, MagicMock()))
        self.assertEqual(called, [])


# ---------------------------------------------------------------------------
# _rcon_command
# ---------------------------------------------------------------------------

class TestRconCommand(unittest.TestCase):
    def test_calls_mcr_command_and_returns_result(self):
        fake_mcr = MagicMock()
        fake_mcr.__enter__ = MagicMock(return_value=fake_mcr)
        fake_mcr.__exit__ = MagicMock(return_value=False)
        fake_mcr.command.return_value = "Player opped"

        with patch.object(bot, "MCRcon", return_value=fake_mcr):
            result = run(bot._rcon_command("host", 25575, "pass", "op Steve"))

        fake_mcr.command.assert_called_once_with("op Steve")
        self.assertEqual(result, "Player opped")

    def test_propagates_exception(self):
        fake_mcr = MagicMock()
        fake_mcr.__enter__ = MagicMock(side_effect=OSError("refused"))
        fake_mcr.__exit__ = MagicMock(return_value=False)

        with patch.object(bot, "MCRcon", return_value=fake_mcr):
            with self.assertRaises(OSError):
                run(bot._rcon_command("host", 25575, "pass", "op Steve"))


# ---------------------------------------------------------------------------
# Integration tests for admin command handlers (mock _rcon_command + _notify)
# ---------------------------------------------------------------------------

ADMIN_ID = 100
NON_ADMIN_ID = 999


class TestAdminHandlers(unittest.TestCase):
    def setUp(self):
        self._orig_admins = bot.ADMIN_USER_IDS
        bot.ADMIN_USER_IDS = [ADMIN_ID]

    def tearDown(self):
        bot.ADMIN_USER_IDS = self._orig_admins

    # -- /op --

    def test_op_no_args_returns_usage(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        run(bot.cmd_op(update, ctx))
        update.message.reply_text.assert_called_once_with("Usage: /op <player>")

    def test_op_calls_rcon_and_notifies(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock(return_value="opped")) as mock_rcon, \
             patch.object(bot, "_notify", new=AsyncMock()) as mock_notify:
            run(bot.cmd_op(update, ctx))

        mock_rcon.assert_called_once_with(bot.RCON_HOST, bot.RCON_PORT, bot.RCON_PASSWORD, "op Steve")
        mock_notify.assert_called_once()
        update.message.reply_text.assert_called_once()

    def test_op_rcon_error_replies_error_no_notify(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock(side_effect=OSError("refused"))), \
             patch.object(bot, "_notify", new=AsyncMock()) as mock_notify:
            run(bot.cmd_op(update, ctx))

        mock_notify.assert_not_called()
        call_args = update.message.reply_text.call_args[0][0]
        self.assertIn("❌ RCON error", call_args)

    def test_op_non_admin_rejected(self):
        update = _make_update(NON_ADMIN_ID)
        ctx = _make_context("Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock()) as mock_rcon:
            run(bot.cmd_op(update, ctx))

        mock_rcon.assert_not_called()
        update.message.reply_text.assert_called_once_with("⛔ Not authorised.")

    # -- /kick --

    def test_kick_calls_rcon(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("Alex")

        with patch.object(bot, "_rcon_command", new=AsyncMock(return_value="")) as mock_rcon, \
             patch.object(bot, "_notify", new=AsyncMock()):
            run(bot.cmd_kick(update, ctx))

        mock_rcon.assert_called_once_with(bot.RCON_HOST, bot.RCON_PORT, bot.RCON_PASSWORD, "kick Alex")

    def test_kick_rcon_error_replies_error(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("Alex")

        with patch.object(bot, "_rcon_command", new=AsyncMock(side_effect=OSError("refused"))), \
             patch.object(bot, "_notify", new=AsyncMock()) as mock_notify:
            run(bot.cmd_kick(update, ctx))

        mock_notify.assert_not_called()
        self.assertIn("❌ RCON error", update.message.reply_text.call_args[0][0])

    # -- /deop --

    def test_deop_no_args_returns_usage(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        run(bot.cmd_deop(update, ctx))
        update.message.reply_text.assert_called_once_with("Usage: /deop <player>")

    def test_deop_calls_rcon_and_notifies(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock(return_value="deopped")) as mock_rcon, \
             patch.object(bot, "_notify", new=AsyncMock()) as mock_notify:
            run(bot.cmd_deop(update, ctx))

        mock_rcon.assert_called_once_with(bot.RCON_HOST, bot.RCON_PORT, bot.RCON_PASSWORD, "deop Steve")
        mock_notify.assert_called_once()

    def test_deop_rcon_error_replies_error_no_notify(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock(side_effect=OSError("refused"))), \
             patch.object(bot, "_notify", new=AsyncMock()) as mock_notify:
            run(bot.cmd_deop(update, ctx))

        mock_notify.assert_not_called()
        self.assertIn("❌ RCON error", update.message.reply_text.call_args[0][0])

    def test_deop_non_admin_rejected(self):
        update = _make_update(NON_ADMIN_ID)
        ctx = _make_context("Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock()) as mock_rcon:
            run(bot.cmd_deop(update, ctx))

        mock_rcon.assert_not_called()
        update.message.reply_text.assert_called_once_with("⛔ Not authorised.")

    # -- /ban --

    def test_ban_no_args_returns_usage(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        run(bot.cmd_ban(update, ctx))
        update.message.reply_text.assert_called_once_with("Usage: /ban <player>")

    def test_ban_calls_rcon_and_notifies(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("Griefer")

        with patch.object(bot, "_rcon_command", new=AsyncMock(return_value="banned")) as mock_rcon, \
             patch.object(bot, "_notify", new=AsyncMock()) as mock_notify:
            run(bot.cmd_ban(update, ctx))

        mock_rcon.assert_called_once_with(bot.RCON_HOST, bot.RCON_PORT, bot.RCON_PASSWORD, "ban Griefer")
        mock_notify.assert_called_once()

    def test_ban_rcon_error_replies_error_no_notify(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("Griefer")

        with patch.object(bot, "_rcon_command", new=AsyncMock(side_effect=OSError("refused"))), \
             patch.object(bot, "_notify", new=AsyncMock()) as mock_notify:
            run(bot.cmd_ban(update, ctx))

        mock_notify.assert_not_called()
        self.assertIn("❌ RCON error", update.message.reply_text.call_args[0][0])

    def test_ban_non_admin_rejected(self):
        update = _make_update(NON_ADMIN_ID)
        ctx = _make_context("Griefer")

        with patch.object(bot, "_rcon_command", new=AsyncMock()) as mock_rcon:
            run(bot.cmd_ban(update, ctx))

        mock_rcon.assert_not_called()
        update.message.reply_text.assert_called_once_with("⛔ Not authorised.")

    # -- /pardon --

    def test_pardon_no_args_returns_usage(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        run(bot.cmd_pardon(update, ctx))
        update.message.reply_text.assert_called_once_with("Usage: /pardon <player>")

    def test_pardon_calls_rcon_and_notifies(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock(return_value="pardoned")) as mock_rcon, \
             patch.object(bot, "_notify", new=AsyncMock()) as mock_notify:
            run(bot.cmd_pardon(update, ctx))

        mock_rcon.assert_called_once_with(bot.RCON_HOST, bot.RCON_PORT, bot.RCON_PASSWORD, "pardon Steve")
        mock_notify.assert_called_once()

    def test_pardon_rcon_error_replies_error_no_notify(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock(side_effect=OSError("refused"))), \
             patch.object(bot, "_notify", new=AsyncMock()) as mock_notify:
            run(bot.cmd_pardon(update, ctx))

        mock_notify.assert_not_called()
        self.assertIn("❌ RCON error", update.message.reply_text.call_args[0][0])

    def test_pardon_non_admin_rejected(self):
        update = _make_update(NON_ADMIN_ID)
        ctx = _make_context("Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock()) as mock_rcon:
            run(bot.cmd_pardon(update, ctx))

        mock_rcon.assert_not_called()
        update.message.reply_text.assert_called_once_with("⛔ Not authorised.")

    # -- /whitelist --

    def test_whitelist_add_player(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("add", "Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock(return_value="")) as mock_rcon, \
             patch.object(bot, "_notify", new=AsyncMock()):
            run(bot.cmd_whitelist(update, ctx))

        mock_rcon.assert_called_once_with(bot.RCON_HOST, bot.RCON_PORT, bot.RCON_PASSWORD, "whitelist add Steve")

    def test_whitelist_remove_player(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("remove", "Steve")

        with patch.object(bot, "_rcon_command", new=AsyncMock(return_value="")) as mock_rcon, \
             patch.object(bot, "_notify", new=AsyncMock()):
            run(bot.cmd_whitelist(update, ctx))

        mock_rcon.assert_called_once_with(bot.RCON_HOST, bot.RCON_PORT, bot.RCON_PASSWORD, "whitelist remove Steve")

    def test_whitelist_bad_subcommand_returns_usage(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("badverb", "Steve")
        run(bot.cmd_whitelist(update, ctx))
        update.message.reply_text.assert_called_once_with("Usage: /whitelist <add|remove> <player>")

    def test_whitelist_missing_player_returns_usage(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("add")
        run(bot.cmd_whitelist(update, ctx))
        update.message.reply_text.assert_called_once_with("Usage: /whitelist <add|remove> <player>")

    # -- /rcon --

    def test_rcon_no_args_returns_usage(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        run(bot.cmd_rcon(update, ctx))
        update.message.reply_text.assert_called_once_with("Usage: /rcon <minecraft command>")

    def test_rcon_strips_leading_slash(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("/say", "hello")

        with patch.object(bot, "_rcon_command", new=AsyncMock(return_value="")) as mock_rcon, \
             patch.object(bot, "_notify", new=AsyncMock()):
            run(bot.cmd_rcon(update, ctx))

        mock_rcon.assert_called_once_with(bot.RCON_HOST, bot.RCON_PORT, bot.RCON_PASSWORD, "say hello")

    def test_rcon_no_leading_slash_passthrough(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("say", "hello")

        with patch.object(bot, "_rcon_command", new=AsyncMock(return_value="")) as mock_rcon, \
             patch.object(bot, "_notify", new=AsyncMock()):
            run(bot.cmd_rcon(update, ctx))

        mock_rcon.assert_called_once_with(bot.RCON_HOST, bot.RCON_PORT, bot.RCON_PASSWORD, "say hello")

    # -- /start admin block --

    def test_start_admin_sees_admin_block(self):
        update = _make_update(ADMIN_ID)
        ctx = MagicMock()
        run(bot.cmd_start(update, ctx))
        call_text = update.message.reply_text.call_args[0][0]
        self.assertIn("Admin commands", call_text)

    def test_start_non_admin_no_admin_block(self):
        update = _make_update(NON_ADMIN_ID)
        ctx = MagicMock()
        run(bot.cmd_start(update, ctx))
        call_text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("Admin commands", call_text)


# ---------------------------------------------------------------------------
# /wipe command
# ---------------------------------------------------------------------------


class TestCmdWipe(unittest.TestCase):
    def setUp(self):
        self._orig_admins = bot.ADMIN_USER_IDS
        bot.ADMIN_USER_IDS = [ADMIN_ID]
        # Reset pending wipe state before each test
        bot._wipe_pending.clear()

    def tearDown(self):
        bot.ADMIN_USER_IDS = self._orig_admins
        bot._wipe_pending.clear()

    # -- non-admin blocked --

    def test_wipe_non_admin_rejected(self):
        update = _make_update(NON_ADMIN_ID)
        ctx = _make_context()
        run(bot.cmd_wipe(update, ctx))
        update.message.reply_text.assert_called_once_with("⛔ Not authorised.")
        self.assertEqual(bot._wipe_pending, {})

    # -- first /wipe (no args, no pending) → issues token --

    def test_wipe_no_pending_issues_token(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        run(bot.cmd_wipe(update, ctx))
        self.assertIn(ADMIN_ID, bot._wipe_pending)
        token, expiry = bot._wipe_pending[ADMIN_ID]
        import time
        self.assertGreater(expiry, time.time())
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn(token, reply_text)

    # -- second /wipe with no args → refreshes token --

    def test_wipe_existing_pending_refreshes_token(self):
        import time
        # Pre-populate with an old token
        bot._wipe_pending[ADMIN_ID] = ("old-token", time.time() + 30)
        update = _make_update(ADMIN_ID)
        ctx = _make_context()
        run(bot.cmd_wipe(update, ctx))
        token, expiry = bot._wipe_pending[ADMIN_ID]
        self.assertNotEqual(token, "old-token")
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn(token, reply_text)

    # -- /wipe <token> with valid token → runs script --

    def test_wipe_valid_token_runs_script(self):
        import time
        token = "abc123"
        bot._wipe_pending[ADMIN_ID] = (token, time.time() + 60)
        update = _make_update(ADMIN_ID)
        ctx = _make_context(token)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Wipe complete"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch.object(bot, "_notify", new=AsyncMock()) as mock_notify:
            run(bot.cmd_wipe(update, ctx))

        mock_run.assert_called_once()
        mock_notify.assert_called_once()
        notify_text = mock_notify.call_args[0][1]
        self.assertIn("wipe", notify_text.lower())
        # Token consumed
        self.assertNotIn(ADMIN_ID, bot._wipe_pending)

    # -- /wipe <token> with expired token → error, removes pending --

    def test_wipe_expired_token_returns_error(self):
        import time
        token = "expiredtoken"
        bot._wipe_pending[ADMIN_ID] = (token, time.time() - 1)
        update = _make_update(ADMIN_ID)
        ctx = _make_context(token)

        with patch("subprocess.run") as mock_run:
            run(bot.cmd_wipe(update, ctx))

        mock_run.assert_not_called()
        self.assertNotIn(ADMIN_ID, bot._wipe_pending)
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("expired", reply_text.lower())

    # -- /wipe <wrong-token> → error, pending unchanged --

    def test_wipe_wrong_token_returns_invalid(self):
        import time
        bot._wipe_pending[ADMIN_ID] = ("correcttoken", time.time() + 60)
        update = _make_update(ADMIN_ID)
        ctx = _make_context("wrongtoken")

        with patch("subprocess.run") as mock_run:
            run(bot.cmd_wipe(update, ctx))

        mock_run.assert_not_called()
        self.assertIn(ADMIN_ID, bot._wipe_pending)
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("invalid", reply_text.lower())

    # -- /wipe <token> with no pending → no pending wipe message --

    def test_wipe_token_arg_no_pending_returns_no_pending(self):
        update = _make_update(ADMIN_ID)
        ctx = _make_context("sometoken")

        with patch("subprocess.run") as mock_run:
            run(bot.cmd_wipe(update, ctx))

        mock_run.assert_not_called()
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("no pending", reply_text.lower())

    # -- script FileNotFoundError --

    def test_wipe_script_not_found(self):
        import time
        token = "tok"
        bot._wipe_pending[ADMIN_ID] = (token, time.time() + 60)
        update = _make_update(ADMIN_ID)
        ctx = _make_context(token)

        with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
            run(bot.cmd_wipe(update, ctx))

        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("not found", reply_text.lower())

    # -- script TimeoutExpired --

    def test_wipe_script_timeout(self):
        import subprocess
        import time
        token = "tok"
        bot._wipe_pending[ADMIN_ID] = (token, time.time() + 60)
        update = _make_update(ADMIN_ID)
        ctx = _make_context(token)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="wipe.sh", timeout=300)):
            run(bot.cmd_wipe(update, ctx))

        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("timed out", reply_text.lower())

    # -- script non-zero exit --

    def test_wipe_script_nonzero_exit(self):
        import time
        token = "tok"
        bot._wipe_pending[ADMIN_ID] = (token, time.time() + 60)
        update = _make_update(ADMIN_ID)
        ctx = _make_context(token)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "docker: permission denied"
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            run(bot.cmd_wipe(update, ctx))

        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply_text)

    # -- /start shows /wipe for admin --

    def test_start_admin_sees_wipe_command(self):
        update = _make_update(ADMIN_ID)
        ctx = MagicMock()
        run(bot.cmd_start(update, ctx))
        call_text = update.message.reply_text.call_args[0][0]
        self.assertIn("/wipe", call_text)

    # -- unexpected OSError propagation (e.g. PermissionError) --

    def test_wipe_script_unexpected_error(self):
        import time
        token = "tok"
        bot._wipe_pending[ADMIN_ID] = (token, time.time() + 60)
        update = _make_update(ADMIN_ID)
        ctx = _make_context(token)

        with patch("subprocess.run", side_effect=PermissionError("permission denied")):
            run(bot.cmd_wipe(update, ctx))

        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply_text)
        self.assertIn("Wipe failed", reply_text)

    # -- two admins get independent tokens --

    def test_two_admins_independent_tokens(self):
        import time
        ADMIN_ID_2 = 200
        self._orig_admins2 = bot.ADMIN_USER_IDS
        bot.ADMIN_USER_IDS = [ADMIN_ID, ADMIN_ID_2]

        try:
            update1 = _make_update(ADMIN_ID)
            update2 = _make_update(ADMIN_ID_2)
            run(bot.cmd_wipe(update1, _make_context()))
            run(bot.cmd_wipe(update2, _make_context()))

            self.assertIn(ADMIN_ID, bot._wipe_pending)
            self.assertIn(ADMIN_ID_2, bot._wipe_pending)
            token1 = bot._wipe_pending[ADMIN_ID][0]
            token2 = bot._wipe_pending[ADMIN_ID_2][0]
            self.assertNotEqual(token1, token2)
        finally:
            bot.ADMIN_USER_IDS = self._orig_admins2


# ---------------------------------------------------------------------------
# _format_players — verifies bot reads nested players dict correctly
# ---------------------------------------------------------------------------


class TestFormatPlayers(unittest.TestCase):
    def test_shows_count(self):
        result = bot._format_players({"players": {"online": 5, "max": 20}})
        self.assertIn("5/20", result)

    def test_zero_count(self):
        result = bot._format_players({"players": {"online": 0, "max": 0}})
        self.assertIn("0/0", result)

    def test_missing_players_key_no_crash(self):
        result = bot._format_players({})
        self.assertIn("0/0", result)

    def test_sample_names_listed(self):
        data = {
            "players": {
                "online": 2,
                "max": 20,
                "sample": [{"name": "Alice"}, {"name": "Bob"}],
            }
        }
        result = bot._format_players(data)
        self.assertIn("Alice", result)
        self.assertIn("Bob", result)


# ---------------------------------------------------------------------------
# _format_status — verifies icon and nested players dict for /status
# ---------------------------------------------------------------------------


class TestFormatStatus(unittest.TestCase):
    def test_online_shows_checkmark(self):
        msg = bot._format_status({"status": "online"})
        self.assertTrue(msg.startswith("✅"), f"Expected ✅ prefix, got: {msg!r}")

    def test_offline_shows_cross(self):
        msg = bot._format_status({"status": "offline"})
        self.assertTrue(msg.startswith("❌"), f"Expected ❌ prefix, got: {msg!r}")

    def test_starting_shows_cross(self):
        msg = bot._format_status({"status": "starting"})
        self.assertTrue(msg.startswith("❌"), f"Expected ❌ prefix, got: {msg!r}")

    def test_unknown_shows_cross(self):
        msg = bot._format_status({})
        self.assertTrue(msg.startswith("❌"), f"Expected ❌ prefix, got: {msg!r}")

    def test_shows_player_count(self):
        data = {"status": "online", "players": {"online": 3, "max": 20}}
        result = bot._format_status(data)
        self.assertIn("3/20", result)

    def test_missing_players_key_shows_zero(self):
        result = bot._format_status({"status": "online"})
        self.assertIn("0/0", result)


# ---------------------------------------------------------------------------
# health_poll_loop — ServerState transition logic
# ---------------------------------------------------------------------------


class TestHealthPollLoop(unittest.IsolatedAsyncioTestCase):
    async def _run_loop_iterations(self, fetch_side_effect):
        """Run health_poll_loop for N iterations via side_effect list, return notify calls."""
        mock_bot = MagicMock()
        notify_calls = []

        # Append a sentinel CancelledError so the loop stops after exhausting the list
        fetch_responses = list(fetch_side_effect) + [asyncio.CancelledError()]

        call_idx = [0]

        async def fake_fetch(session):
            resp = fetch_responses[call_idx[0]]
            call_idx[0] += 1
            if isinstance(resp, type) and issubclass(resp, BaseException):
                raise resp()
            if isinstance(resp, BaseException):
                raise resp
            return resp

        async def fake_notify(b, msg):
            notify_calls.append(msg)

        with patch.object(bot, "fetch_health", new=fake_fetch), \
             patch.object(bot, "_notify", new=fake_notify), \
             patch.object(bot, "POLL_INTERVAL", 0):
            try:
                await bot.health_poll_loop(mock_bot)
            except asyncio.CancelledError:
                pass

        return notify_calls

    async def test_offline_then_online_triggers_online_notify(self):
        # ServerState skips notification on first poll (UNKNOWN state); must go offline→online
        notify_calls = await self._run_loop_iterations([
            {"status": "offline"},   # poll 1: UNKNOWN→OFFLINE, no notify
            {"status": "online"},    # poll 2: OFFLINE→ONLINE, fires "online" notify
        ])
        online_msgs = [m for m in notify_calls if "online" in m.lower()]
        self.assertTrue(online_msgs, f"Expected an 'online' notification, got: {notify_calls}")

    async def test_offline_status_does_not_trigger_online_notify(self):
        notify_calls = await self._run_loop_iterations([
            {"status": "offline"},   # poll 1: UNKNOWN→OFFLINE, no notify
            {"status": "offline"},   # poll 2: no change, no notify
        ])
        for msg in notify_calls:
            self.assertNotIn("online", msg.lower(), f"Unexpected online notify: {msg!r}")

    async def test_none_fetch_does_not_trigger_online_notify(self):
        notify_calls = await self._run_loop_iterations([
            None,   # poll 1: fetch failed, no notify
            None,   # poll 2: still failed, no notify
        ])
        for msg in notify_calls:
            self.assertNotIn("online", msg.lower(), f"Unexpected online notify: {msg!r}")


if __name__ == "__main__":
    unittest.main()
