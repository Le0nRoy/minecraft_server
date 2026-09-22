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
    tg_ext.CallbackQueryHandler = MagicMock
    ContextTypesMock = MagicMock()
    ContextTypesMock.DEFAULT_TYPE = MagicMock
    tg_ext.ContextTypes = ContextTypesMock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
os.environ.setdefault("ADMIN_USER_IDS", "100")

sys.path.insert(0, os.path.dirname(__file__))
import bot  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_USER_ID = 100
NON_ADMIN_USER_ID = 99999


def _make_update(user_id: int = ADMIN_USER_ID) -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = int(bot.CHAT_ID)
    update.effective_user.id = user_id
    update.message.reply_text = AsyncMock()
    return update


def _make_context(*args: str) -> MagicMock:
    ctx = MagicMock()
    ctx.args = list(args)
    return ctx


def run(coro):
    return asyncio.run(coro)


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
    def setUp(self):
        self._orig = bot.ADMIN_USER_IDS
        bot.ADMIN_USER_IDS = [ADMIN_USER_ID]

    def tearDown(self):
        bot.ADMIN_USER_IDS = self._orig

    def test_non_admin_rejected(self):
        update = _make_update(user_id=NON_ADMIN_USER_ID)
        ctx = _make_context()
        run(bot.cmd_macmap(update, ctx))
        update.message.reply_text.assert_called_once_with("⛔ Not authorised.")

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
    def setUp(self):
        self._orig = bot.ADMIN_USER_IDS
        bot.ADMIN_USER_IDS = [ADMIN_USER_ID]

    def tearDown(self):
        bot.ADMIN_USER_IDS = self._orig

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
    def setUp(self):
        self._orig = bot.ADMIN_USER_IDS
        bot.ADMIN_USER_IDS = [ADMIN_USER_ID]

    def tearDown(self):
        bot.ADMIN_USER_IDS = self._orig

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
    def setUp(self):
        self._orig = bot.ADMIN_USER_IDS
        bot.ADMIN_USER_IDS = [ADMIN_USER_ID]

    def tearDown(self):
        bot.ADMIN_USER_IDS = self._orig

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


# ---------------------------------------------------------------------------
# _append_to_list
# ---------------------------------------------------------------------------


class TestAppendToList(unittest.TestCase):
    def test_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "allowlist.json")
            bot._append_to_list(path, "1.2.3.4")
            with open(path) as f:
                data = json.load(f)
            self.assertIn("1.2.3.4", data)

    def test_appends_new_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "list.json")
            with open(path, "w") as f:
                json.dump(["10.0.0.1"], f)
            bot._append_to_list(path, "1.2.3.4")
            with open(path) as f:
                data = json.load(f)
            self.assertIn("1.2.3.4", data)
            self.assertIn("10.0.0.1", data)

    def test_skips_duplicate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "list.json")
            with open(path, "w") as f:
                json.dump(["1.2.3.4"], f)
            bot._append_to_list(path, "1.2.3.4")
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data.count("1.2.3.4"), 1)

    def test_normalizes_mac_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "list.json")
            bot._append_to_list(path, "AA:BB:CC:DD:EE:FF")
            with open(path) as f:
                data = json.load(f)
            self.assertIn("aa:bb:cc:dd:ee:ff", data)

    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "list.json")
            bot._append_to_list(path, "1.2.3.4")
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# handle_list_action
# ---------------------------------------------------------------------------


def _make_callback_query(user_id: int = ADMIN_USER_ID, data: str = "allow|1.2.3.4") -> MagicMock:
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message = MagicMock()
    query.message.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_chat.id = int(bot.CHAT_ID)
    update.effective_user.id = user_id
    update.callback_query = query
    ctx = MagicMock()
    return update, ctx


class TestHandleListAction(unittest.TestCase):
    def setUp(self):
        self._orig = bot.ADMIN_USER_IDS
        bot.ADMIN_USER_IDS = [ADMIN_USER_ID]

    def tearDown(self):
        bot.ADMIN_USER_IDS = self._orig

    def test_unauthorized_user_ignored(self):
        update, ctx = _make_callback_query(user_id=NON_ADMIN_USER_ID, data="allow|1.2.3.4")
        with patch.object(bot, "_append_to_list") as mock_append:
            run(bot.handle_list_action(update, ctx))
        mock_append.assert_not_called()

    def test_unauthorized_chat_callback_ignored(self):
        update, ctx = _make_callback_query(user_id=ADMIN_USER_ID, data="allow|1.2.3.4")
        update.effective_chat.id = int(bot.CHAT_ID) + 1  # valid user, wrong chat
        with patch.object(bot, "_append_to_list") as mock_append:
            run(bot.handle_list_action(update, ctx))
        mock_append.assert_not_called()

    def test_allow_action_writes_to_allowlist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            allowlist_path = os.path.join(tmpdir, "allowlist.json")
            update, ctx = _make_callback_query(data="allow|1.2.3.4")
            with patch.object(bot, "ALLOWLIST_FILE", allowlist_path), \
                 patch.object(bot, "DENYLIST_FILE", os.path.join(tmpdir, "denylist.json")):
                run(bot.handle_list_action(update, ctx))
            with open(allowlist_path) as f:
                data = json.load(f)
            self.assertIn("1.2.3.4", data)

    def test_deny_action_writes_to_denylist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            denylist_path = os.path.join(tmpdir, "denylist.json")
            update, ctx = _make_callback_query(data="deny|aa:bb:cc:dd:ee:ff")
            with patch.object(bot, "ALLOWLIST_FILE", os.path.join(tmpdir, "allowlist.json")), \
                 patch.object(bot, "DENYLIST_FILE", denylist_path):
                run(bot.handle_list_action(update, ctx))
            with open(denylist_path) as f:
                data = json.load(f)
            self.assertIn("aa:bb:cc:dd:ee:ff", data)

    def test_malformed_callback_data_no_crash(self):
        update, ctx = _make_callback_query(data="malformed-no-pipe")
        with patch.object(bot, "_append_to_list") as mock_append:
            run(bot.handle_list_action(update, ctx))
        mock_append.assert_not_called()

    def test_buttons_removed_after_action(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            update, ctx = _make_callback_query(data="allow|1.2.3.4")
            with patch.object(bot, "ALLOWLIST_FILE", os.path.join(tmpdir, "allowlist.json")), \
                 patch.object(bot, "DENYLIST_FILE", os.path.join(tmpdir, "denylist.json")):
                run(bot.handle_list_action(update, ctx))
        update.callback_query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)

    def test_confirmation_reply_sent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            update, ctx = _make_callback_query(data="deny|1.2.3.4")
            with patch.object(bot, "ALLOWLIST_FILE", os.path.join(tmpdir, "allowlist.json")), \
                 patch.object(bot, "DENYLIST_FILE", os.path.join(tmpdir, "denylist.json")):
                run(bot.handle_list_action(update, ctx))
        update.callback_query.message.reply_text.assert_called_once()

    def test_duplicate_key_graceful(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            allowlist_path = os.path.join(tmpdir, "allowlist.json")
            with open(allowlist_path, "w") as f:
                json.dump(["1.2.3.4"], f)
            update, ctx = _make_callback_query(data="allow|1.2.3.4")
            with patch.object(bot, "ALLOWLIST_FILE", allowlist_path), \
                 patch.object(bot, "DENYLIST_FILE", os.path.join(tmpdir, "denylist.json")):
                run(bot.handle_list_action(update, ctx))
            with open(allowlist_path) as f:
                data = json.load(f)
            self.assertEqual(data.count("1.2.3.4"), 1)
            update.callback_query.message.reply_text.assert_called_once()


if __name__ == "__main__":
    unittest.main()
