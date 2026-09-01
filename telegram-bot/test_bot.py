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
    def __init__(self, host, port, password):
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
    return asyncio.get_event_loop().run_until_complete(coro)


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


if __name__ == "__main__":
    unittest.main()
