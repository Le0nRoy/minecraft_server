"""Unit tests for /macmap command in telegram-bot/bot.py."""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing bot
# ---------------------------------------------------------------------------

def _make_module(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

if "aiohttp" not in sys.modules:
    aiohttp_stub = _make_module("aiohttp")
    aiohttp_stub.ClientSession = MagicMock
    aiohttp_stub.ClientTimeout = MagicMock

if "telegram" not in sys.modules:
    tg = _make_module("telegram")
    tg.Bot = MagicMock
    tg.Update = MagicMock
    tg_constants = _make_module("telegram.constants")
    tg_constants.ParseMode = MagicMock
    tg_ext = _make_module("telegram.ext")
    tg_ext.ApplicationBuilder = MagicMock
    tg_ext.CommandHandler = MagicMock
    ContextTypesMock = MagicMock()
    ContextTypesMock.DEFAULT_TYPE = MagicMock
    tg_ext.ContextTypes = ContextTypesMock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")

sys.path.insert(0, os.path.dirname(__file__))
import bot  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_CHAT_ID = bot.CHAT_ID


def _make_update(chat_id: str = ADMIN_CHAT_ID) -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id
    update.message.reply_text = AsyncMock()
    return update


def _make_context(*args: str) -> MagicMock:
    ctx = MagicMock()
    ctx.args = list(args)
    return ctx


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# _normalize_key
# ---------------------------------------------------------------------------

class TestNormalizeKey(unittest.TestCase):
    def test_dashes_to_colons_lowercase(self):
        self.assertEqual(bot._normalize_key("AA-BB-CC-DD-EE-FF"), "aa:bb:cc:dd:ee:ff")

    def test_colons_lowercased(self):
        self.assertEqual(bot._normalize_key("AA:BB:CC:DD:EE:FF"), "aa:bb:cc:dd:ee:ff")

    def test_tailscale_ip_passthrough(self):
        self.assertEqual(bot._normalize_key("100.64.1.2"), "100.64.1.2")


# ---------------------------------------------------------------------------
# _load_mapping_file / _write_mapping_atomic
# ---------------------------------------------------------------------------

class TestMappingFileIO(unittest.TestCase):
    def test_load_missing_returns_empty(self):
        with patch.object(bot, "MAC_MAPPING_FILE", "/nonexistent/mac-mapping.json"):
            result = bot._load_mapping_file()
        self.assertEqual(result, {})

    def test_write_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "mapping.json")
            with patch.object(bot, "MAC_MAPPING_FILE", path):
                bot._write_mapping_atomic({"aa:bb:cc:dd:ee:ff": "Player1"})
                result = bot._load_mapping_file()
        self.assertEqual(result, {"aa:bb:cc:dd:ee:ff": "Player1"})

    def test_load_normalizes_dash_mac_keys(self):
        """Keys with dashes in the file must be normalized to colon form on load."""
        import json as _json
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "mapping.json")
            with open(path, "w") as f:
                _json.dump({"AA-BB-CC-DD-EE-FF": "Player2"}, f)
            with patch.object(bot, "MAC_MAPPING_FILE", path):
                result = bot._load_mapping_file()
        self.assertIn("aa:bb:cc:dd:ee:ff", result)
        self.assertNotIn("AA-BB-CC-DD-EE-FF", result)


# ---------------------------------------------------------------------------
# cmd_macmap — auth
# ---------------------------------------------------------------------------

class TestCmdMacmapAuth(unittest.TestCase):
    def test_non_admin_rejected(self):
        update = _make_update(chat_id="99999")
        ctx = _make_context()
        run(bot.cmd_macmap(update, ctx))
        update.message.reply_text.assert_called_once_with("Not authorised.")

    def test_no_args_shows_usage(self):
        update = _make_update()
        ctx = _make_context()
        run(bot.cmd_macmap(update, ctx))
        call_text = update.message.reply_text.call_args[0][0]
        self.assertIn("Usage", call_text)
        self.assertIn("/macmap list", call_text)

    def test_unknown_subcommand(self):
        update = _make_update()
        ctx = _make_context("foo")
        run(bot.cmd_macmap(update, ctx))
        call_text = update.message.reply_text.call_args[0][0]
        self.assertIn("Unknown subcommand", call_text)


# ---------------------------------------------------------------------------
# cmd_macmap list
# ---------------------------------------------------------------------------

class TestCmdMacmapList(unittest.TestCase):
    def test_empty_mapping(self):
        update = _make_update()
        ctx = _make_context("list")
        with patch.object(bot, "_load_mapping_file", return_value={}):
            run(bot.cmd_macmap(update, ctx))
        update.message.reply_text.assert_called_once_with("MAC/IP mapping is empty.")

    def test_non_empty_mapping(self):
        mapping = {"aa:bb:cc:dd:ee:ff": "Player1", "100.64.1.2": "TsPlayer"}
        update = _make_update()
        ctx = _make_context("list")
        with patch.object(bot, "_load_mapping_file", return_value=mapping):
            run(bot.cmd_macmap(update, ctx))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("2 entries", text)
        self.assertIn("Player1", text)
        self.assertIn("TsPlayer", text)


# ---------------------------------------------------------------------------
# cmd_macmap set
# ---------------------------------------------------------------------------

class TestCmdMacmapSet(unittest.TestCase):
    def test_set_colon_mac(self):
        update = _make_update()
        ctx = _make_context("set", "aa:bb:cc:dd:ee:ff", "Player1")
        written = {}
        with patch.object(bot, "_load_mapping_file", return_value={}), \
             patch.object(bot, "_write_mapping_atomic", side_effect=lambda d: written.update(d)):
            run(bot.cmd_macmap(update, ctx))
        self.assertEqual(written.get("aa:bb:cc:dd:ee:ff"), "Player1")
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Mapped", text)

    def test_set_dash_mac_normalized(self):
        update = _make_update()
        ctx = _make_context("set", "aa-bb-cc-dd-ee-ff", "Player2")
        written = {}
        with patch.object(bot, "_load_mapping_file", return_value={}), \
             patch.object(bot, "_write_mapping_atomic", side_effect=lambda d: written.update(d)):
            run(bot.cmd_macmap(update, ctx))
        self.assertIn("aa:bb:cc:dd:ee:ff", written)

    def test_set_tailscale_ip(self):
        update = _make_update()
        ctx = _make_context("set", "100.64.1.2", "TsPlayer")
        written = {}
        with patch.object(bot, "_load_mapping_file", return_value={}), \
             patch.object(bot, "_write_mapping_atomic", side_effect=lambda d: written.update(d)):
            run(bot.cmd_macmap(update, ctx))
        self.assertEqual(written.get("100.64.1.2"), "TsPlayer")

    def test_set_multi_word_basename(self):
        update = _make_update()
        ctx = _make_context("set", "aa:bb:cc:dd:ee:ff", "Multi", "Word", "Name")
        written = {}
        with patch.object(bot, "_load_mapping_file", return_value={}), \
             patch.object(bot, "_write_mapping_atomic", side_effect=lambda d: written.update(d)):
            run(bot.cmd_macmap(update, ctx))
        self.assertEqual(written.get("aa:bb:cc:dd:ee:ff"), "Multi Word Name")

    def test_set_invalid_key_rejected(self):
        update = _make_update()
        ctx = _make_context("set", "not-a-mac-or-ip", "Player")
        run(bot.cmd_macmap(update, ctx))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Invalid key", text)

    def test_set_missing_args_shows_usage(self):
        update = _make_update()
        ctx = _make_context("set", "aa:bb:cc:dd:ee:ff")
        run(bot.cmd_macmap(update, ctx))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Usage", text)

    def test_set_write_failure_replies_error(self):
        update = _make_update()
        ctx = _make_context("set", "aa:bb:cc:dd:ee:ff", "Player")
        with patch.object(bot, "_load_mapping_file", return_value={}), \
             patch.object(bot, "_write_mapping_atomic", side_effect=OSError("permission denied")):
            run(bot.cmd_macmap(update, ctx))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Write failed", text)


# ---------------------------------------------------------------------------
# cmd_macmap del
# ---------------------------------------------------------------------------

class TestCmdMacmapDel(unittest.TestCase):
    def test_del_existing(self):
        existing = {"aa:bb:cc:dd:ee:ff": "Player1"}
        written = {}
        update = _make_update()
        ctx = _make_context("del", "aa:bb:cc:dd:ee:ff")
        with patch.object(bot, "_load_mapping_file", return_value=dict(existing)), \
             patch.object(bot, "_write_mapping_atomic", side_effect=lambda d: written.update({"_result": d})):
            run(bot.cmd_macmap(update, ctx))
        self.assertNotIn("aa:bb:cc:dd:ee:ff", written.get("_result", {}))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Removed", text)

    def test_del_nonexistent_reports_not_found(self):
        update = _make_update()
        ctx = _make_context("del", "11:22:33:44:55:66")
        with patch.object(bot, "_load_mapping_file", return_value={}):
            run(bot.cmd_macmap(update, ctx))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Not found", text)

    def test_del_write_failure_replies_error(self):
        existing = {"aa:bb:cc:dd:ee:ff": "Player1"}
        update = _make_update()
        ctx = _make_context("del", "aa:bb:cc:dd:ee:ff")
        with patch.object(bot, "_load_mapping_file", return_value=dict(existing)), \
             patch.object(bot, "_write_mapping_atomic", side_effect=OSError("disk full")):
            run(bot.cmd_macmap(update, ctx))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Write failed", text)


# ---------------------------------------------------------------------------
# Atomic write real I/O test
# ---------------------------------------------------------------------------

class TestWriteMappingAtomic(unittest.TestCase):
    def test_file_created_with_correct_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "mapping.json")
            with patch.object(bot, "MAC_MAPPING_FILE", path):
                bot._write_mapping_atomic({"aa:bb:cc:dd:ee:ff": "Player"})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["aa:bb:cc:dd:ee:ff"], "Player")


if __name__ == "__main__":
    unittest.main()
