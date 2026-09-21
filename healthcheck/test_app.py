"""Unit tests for healthcheck/app.py."""

import copy
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Stubs (must come before importing app)
# ---------------------------------------------------------------------------

# Stub mcrcon so the import succeeds without the real package installed
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

import app  # noqa: E402  (must come after stubs)

MCRconException = sys.modules["mcrcon"].MCRconException


# ---------------------------------------------------------------------------
# TestParseListResponse
# ---------------------------------------------------------------------------


class TestParseListResponse(unittest.TestCase):
    def test_vanilla_format(self):
        online, max_p = app._parse_list_response(
            "There are 3 of a max of 20 players online: Steve, Alex"
        )
        self.assertEqual(online, 3)
        self.assertEqual(max_p, 20)

    def test_slash_format(self):
        online, max_p = app._parse_list_response("3/20")
        self.assertEqual(online, 3)
        self.assertEqual(max_p, 20)

    def test_empty_string_fallback(self):
        online, max_p = app._parse_list_response("")
        self.assertEqual(online, 0)
        self.assertEqual(max_p, 20)

    def test_garbage_fallback(self):
        online, max_p = app._parse_list_response("garbage text with no numbers")
        self.assertEqual(online, 0)
        self.assertEqual(max_p, 20)

    def test_large_counts(self):
        online, max_p = app._parse_list_response(
            "There are 150 of a max of 200 players online:"
        )
        self.assertEqual(online, 150)
        self.assertEqual(max_p, 200)


# ---------------------------------------------------------------------------
# TestBuildStatusPayload
# ---------------------------------------------------------------------------


class TestBuildStatusPayload(unittest.TestCase):
    def test_required_keys_present(self):
        result = app._build_status_payload(5, 20, "online")
        for key in ("status", "uptime_seconds", "players", "version", "motd", "timestamp"):
            self.assertIn(key, result)

    def test_nested_players_key(self):
        result = app._build_status_payload(5, 20, "online")
        self.assertIn("players", result)
        self.assertEqual(result["players"]["online"], 5)
        self.assertEqual(result["players"]["max"], 20)

    def test_no_flat_player_keys(self):
        result = app._build_status_payload(5, 20, "online")
        self.assertNotIn("players_online", result)
        self.assertNotIn("players_max", result)

    def test_status_propagates(self):
        for status in ("online", "offline", "starting"):
            with self.subTest(status=status):
                result = app._build_status_payload(0, 20, status)
                self.assertEqual(result["status"], status)

    def test_uptime_non_negative_int(self):
        result = app._build_status_payload(0, 20, "online")
        self.assertIsInstance(result["uptime_seconds"], int)
        self.assertGreaterEqual(result["uptime_seconds"], 0)

    def test_timestamp_format(self):
        result = app._build_status_payload(0, 20, "online")
        try:
            datetime.strptime(result["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            self.fail(f"timestamp {result['timestamp']!r} does not match %Y-%m-%dT%H:%M:%SZ")

    def test_zero_players(self):
        result = app._build_status_payload(0, 0, "offline")
        self.assertEqual(result["players"]["online"], 0)
        self.assertEqual(result["players"]["max"], 0)

    def test_status_field_preserved(self):
        result = app._build_status_payload(3, 20, "online")
        self.assertEqual(result["status"], "online")


# ---------------------------------------------------------------------------
# TestRconCommandWithRetry
# ---------------------------------------------------------------------------


class TestRconCommandWithRetry(unittest.TestCase):
    def test_success_first_attempt_no_sleep(self):
        with patch.object(app, "_rcon_command", return_value="OK"), \
             patch("time.sleep") as mock_sleep:
            result = app._rcon_command_with_retry("list")
        self.assertEqual(result, "OK")
        mock_sleep.assert_not_called()

    def test_success_second_attempt_sleeps_once(self):
        with patch.object(app, "_rcon_command", side_effect=[MCRconException("fail"), "OK"]), \
             patch("time.sleep") as mock_sleep:
            result = app._rcon_command_with_retry("list")
        self.assertEqual(result, "OK")
        mock_sleep.assert_called_once_with(app.RETRY_BACKOFF)

    def test_all_oserror_attempts_raise(self):
        with patch.object(app, "_rcon_command", side_effect=OSError("fail")), \
             patch("time.sleep") as mock_sleep:
            with self.assertRaises(OSError):
                app._rcon_command_with_retry("list")
        self.assertEqual(mock_sleep.call_count, app.RETRY_ATTEMPTS - 1)

    def test_connection_refused_raises(self):
        with patch.object(app, "_rcon_command", side_effect=ConnectionRefusedError("refused")), \
             patch("time.sleep"):
            with self.assertRaises(ConnectionRefusedError):
                app._rcon_command_with_retry("list")

    def test_sleep_called_with_retry_backoff_value(self):
        with patch.object(app, "_rcon_command", side_effect=MCRconException("fail")), \
             patch("time.sleep") as mock_sleep:
            with self.assertRaises(MCRconException):
                app._rcon_command_with_retry("list")
        for call in mock_sleep.call_args_list:
            self.assertEqual(call.args[0], app.RETRY_BACKOFF)


# ---------------------------------------------------------------------------
# TestPollOnce
# ---------------------------------------------------------------------------


class TestPollOnce(unittest.TestCase):
    def setUp(self):
        self._orig_cache = copy.deepcopy(app._cached_status)

    def tearDown(self):
        with app._cache_lock:
            app._cached_status.clear()
            app._cached_status.update(self._orig_cache)

    def test_rcon_success_sets_online(self):
        with patch.object(app, "_rcon_command_with_retry",
                          return_value="There are 3 of a max of 20 players online:"), \
             patch.object(app, "_query_server_tcp", return_value=True):
            app._poll_once()
        self.assertEqual(app._cached_status["status"], "online")
        self.assertEqual(app._cached_status["players"]["online"], 3)
        self.assertEqual(app._cached_status["players"]["max"], 20)

    def test_rcon_failure_tcp_up_sets_starting(self):
        with patch.object(app, "_rcon_command_with_retry", side_effect=OSError("fail")), \
             patch.object(app, "_query_server_tcp", return_value=True):
            app._poll_once()
        self.assertEqual(app._cached_status["status"], "starting")
        self.assertEqual(app._cached_status["players"]["online"], 0)

    def test_rcon_failure_tcp_down_sets_offline(self):
        with patch.object(app, "_rcon_command_with_retry", side_effect=OSError("fail")), \
             patch.object(app, "_query_server_tcp", return_value=False):
            app._poll_once()
        self.assertEqual(app._cached_status["status"], "offline")

    def test_cache_lock_released_after_poll(self):
        with patch.object(app, "_rcon_command_with_retry", side_effect=OSError("fail")), \
             patch.object(app, "_query_server_tcp", return_value=False):
            app._poll_once()
        acquired = app._cache_lock.acquire(blocking=False)
        self.assertTrue(acquired, "cache lock was left locked after _poll_once")
        if acquired:
            app._cache_lock.release()


# ---------------------------------------------------------------------------
# TestHealthEndpoint / TestPingEndpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self._orig_cache = copy.deepcopy(app._cached_status)

    def tearDown(self):
        with app._cache_lock:
            app._cached_status.clear()
            app._cached_status.update(self._orig_cache)

    def test_online_status_returns_200(self):
        with app._cache_lock:
            app._cached_status["status"] = "online"
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)

    def test_offline_status_returns_503(self):
        with app._cache_lock:
            app._cached_status["status"] = "offline"
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 503)

    def test_starting_status_returns_503(self):
        with app._cache_lock:
            app._cached_status["status"] = "starting"
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 503)

    def test_response_json_contains_required_fields(self):
        with app._cache_lock:
            app._cached_status["status"] = "online"
            app._cached_status["players"]["online"] = 5
            app._cached_status["players"]["max"] = 20
        resp = self.client.get("/health")
        data = resp.get_json()
        for key in ("status", "players", "uptime_seconds", "timestamp"):
            self.assertIn(key, data)
        self.assertEqual(data["players"]["online"], 5)
        self.assertEqual(data["players"]["max"], 20)


class TestPingEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_ping_returns_200(self):
        resp = self.client.get("/ping")
        self.assertEqual(resp.status_code, 200)

    def test_ping_returns_alive_true(self):
        resp = self.client.get("/ping")
        data = resp.get_json()
        self.assertEqual(data, {"alive": True})


# ---------------------------------------------------------------------------
# TestCachedStatusInitialState
# ---------------------------------------------------------------------------


class TestCachedStatusInitialState(unittest.TestCase):
    def test_nested_players_key_present(self):
        self.assertIn("players", app._cached_status)
        self.assertIsInstance(app._cached_status["players"]["online"], int)
        self.assertIsInstance(app._cached_status["players"]["max"], int)

    def test_no_flat_player_keys_in_initial_cache(self):
        self.assertNotIn("players_online", app._cached_status)
        self.assertNotIn("players_max", app._cached_status)


if __name__ == "__main__":
    unittest.main()
