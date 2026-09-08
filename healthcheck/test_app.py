"""Unit tests for healthcheck/app.py."""

import sys
import types
import unittest

# Stub flask before importing app so the import succeeds without the package
flask_stub = types.ModuleType("flask")


class _Flask:
    def __init__(self, *args, **kwargs):
        pass

    def route(self, *args, **kwargs):
        return lambda f: f

    def run(self, *args, **kwargs):
        pass


flask_stub.Flask = _Flask
flask_stub.jsonify = lambda x: x
sys.modules["flask"] = flask_stub

# Stub mcrcon before importing app so the import succeeds without the package
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


# ---------------------------------------------------------------------------
# _build_status_payload
# ---------------------------------------------------------------------------


class TestBuildStatusPayload(unittest.TestCase):
    def test_nested_players_key(self):
        result = app._build_status_payload(5, 20, "online")
        self.assertIn("players", result)
        self.assertEqual(result["players"]["online"], 5)
        self.assertEqual(result["players"]["max"], 20)

    def test_no_flat_player_keys(self):
        result = app._build_status_payload(5, 20, "online")
        self.assertNotIn("players_online", result)
        self.assertNotIn("players_max", result)

    def test_zero_players(self):
        result = app._build_status_payload(0, 0, "offline")
        self.assertEqual(result["players"]["online"], 0)
        self.assertEqual(result["players"]["max"], 0)

    def test_status_field_preserved(self):
        result = app._build_status_payload(3, 20, "online")
        self.assertEqual(result["status"], "online")


# ---------------------------------------------------------------------------
# _cached_status initial state
# ---------------------------------------------------------------------------


class TestCachedStatusInitialState(unittest.TestCase):
    def test_nested_players_key_present(self):
        self.assertIn("players", app._cached_status)
        self.assertEqual(app._cached_status["players"]["online"], 0)
        self.assertEqual(app._cached_status["players"]["max"], 20)

    def test_no_flat_player_keys_in_initial_cache(self):
        self.assertNotIn("players_online", app._cached_status)
        self.assertNotIn("players_max", app._cached_status)


if __name__ == "__main__":
    unittest.main()
