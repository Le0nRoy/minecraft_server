"""Unit tests for auth-sidecar app.py."""

import json
import subprocess
import sys
import tempfile
import types
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

import os

# Ensure `requests` stub exists before importing app
requests_stub = types.ModuleType("requests")
requests_stub.post = MagicMock()
sys.modules.setdefault("requests", requests_stub)

sys.path.insert(0, os.path.dirname(__file__))
import app  # noqa: E402  (local import after sys.path setup)


# ---------------------------------------------------------------------------
# IP classification
# ---------------------------------------------------------------------------


class TestIpClassification(unittest.TestCase):
    def test_tailscale_range_accepted(self):
        self.assertTrue(app.is_tailscale("100.100.1.1"))

    def test_tailscale_range_boundary(self):
        self.assertTrue(app.is_tailscale("100.64.0.1"))

    def test_non_tailscale_rejected(self):
        self.assertFalse(app.is_tailscale("8.8.8.8"))

    def test_local_net_accepted_192168(self):
        self.assertTrue(app.is_local_net("192.168.1.50"))

    def test_local_net_accepted_rfc1918_10(self):
        self.assertTrue(app.is_local_net("10.0.0.1"))

    def test_local_net_accepted_rfc1918_172(self):
        self.assertTrue(app.is_local_net("172.16.0.1"))

    def test_local_net_rejected_external(self):
        self.assertFalse(app.is_local_net("8.8.8.8"))

    def test_invalid_ip_tailscale(self):
        self.assertFalse(app.is_tailscale("not-an-ip"))

    def test_invalid_ip_local(self):
        self.assertFalse(app.is_local_net("not-an-ip"))


# ---------------------------------------------------------------------------
# normalize_key
# ---------------------------------------------------------------------------


class TestNormalizeKey(unittest.TestCase):
    def test_mac_dashes_to_colons_lowercase(self):
        self.assertEqual(app.normalize_key("AA-BB-CC-DD-EE-FF"), "aa:bb:cc:dd:ee:ff")

    def test_mac_colons_already_normalized(self):
        self.assertEqual(app.normalize_key("aa:bb:cc:dd:ee:ff"), "aa:bb:cc:dd:ee:ff")

    def test_mac_uppercase_colons_lowercased(self):
        self.assertEqual(app.normalize_key("AA:BB:CC:DD:EE:FF"), "aa:bb:cc:dd:ee:ff")

    def test_tailscale_ip_passthrough(self):
        self.assertEqual(app.normalize_key("100.64.1.2"), "100.64.1.2")

    def test_external_ip_passthrough(self):
        self.assertEqual(app.normalize_key("8.8.8.8"), "8.8.8.8")


# ---------------------------------------------------------------------------
# load_mapping
# ---------------------------------------------------------------------------


class TestLoadMapping(unittest.TestCase):
    def test_valid_json_normalizes_keys(self):
        data = json.dumps({"AA:BB:CC:DD:EE:FF": "Player1", "100.64.1.2": "TsPlayer"})
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            result = app.load_mapping(path)
            self.assertEqual(result["aa:bb:cc:dd:ee:ff"], "Player1")
            self.assertEqual(result["100.64.1.2"], "TsPlayer")
        finally:
            os.unlink(path)

    def test_file_missing_returns_empty(self):
        result = app.load_mapping("/nonexistent/mac-mapping.json")
        self.assertEqual(result, {})

    def test_malformed_json_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not json {{{")
            path = f.name
        try:
            result = app.load_mapping(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)

    def test_non_dict_json_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write('["list", "not", "dict"]')
            path = f.name
        try:
            result = app.load_mapping(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)

    def test_dash_mac_keys_normalized(self):
        data = json.dumps({"aa-bb-cc-dd-ee-ff": "Player2"})
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            result = app.load_mapping(path)
            self.assertIn("aa:bb:cc:dd:ee:ff", result)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# lookup_basename
# ---------------------------------------------------------------------------


class TestLookupBasename(unittest.TestCase):
    def setUp(self):
        self.mapping = {"aa:bb:cc:dd:ee:ff": "LocalPlayer", "100.64.1.2": "TsPlayer"}

    def test_mac_exact_match(self):
        self.assertEqual(app.lookup_basename("aa:bb:cc:dd:ee:ff", self.mapping), "LocalPlayer")

    def test_mac_uppercase_normalized(self):
        self.assertEqual(app.lookup_basename("AA:BB:CC:DD:EE:FF", self.mapping), "LocalPlayer")

    def test_mac_not_found_returns_none(self):
        self.assertIsNone(app.lookup_basename("11:22:33:44:55:66", self.mapping))

    def test_empty_basename_returns_none(self):
        mapping = {"aa:bb:cc:dd:ee:ff": ""}
        self.assertIsNone(app.lookup_basename("aa:bb:cc:dd:ee:ff", mapping))

    def test_tailscale_ip_match(self):
        self.assertEqual(app.lookup_basename("100.64.1.2", self.mapping), "TsPlayer")


# ---------------------------------------------------------------------------
# Tailscale identity resolution
# ---------------------------------------------------------------------------


class TestTailscaleIdentity(unittest.TestCase):
    def test_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Node: testnode\nLogin: user@example.com\n"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = app.resolve_tailscale_identity("100.100.1.1")
        self.assertIn("testnode", result["tailscale_raw"])

    def test_whois_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error"
        with patch("subprocess.run", return_value=mock_result):
            result = app.resolve_tailscale_identity("100.100.1.1")
        self.assertIn("error", result)

    def test_tailscale_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = app.resolve_tailscale_identity("100.100.1.1")
        self.assertEqual(result["error"], "tailscale not installed")

    def test_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("tailscale", 5)):
            result = app.resolve_tailscale_identity("100.100.1.1")
        self.assertEqual(result["error"], "whois timeout")


# ---------------------------------------------------------------------------
# Local identity resolution helpers
# ---------------------------------------------------------------------------


class TestPingHost(unittest.TestCase):
    def test_reachable(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            self.assertTrue(app.ping_host("192.168.1.1"))

    def test_unreachable(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            self.assertFalse(app.ping_host("192.168.1.1"))

    def test_exception(self):
        with patch("subprocess.run", side_effect=OSError("no ping")):
            self.assertFalse(app.ping_host("192.168.1.1"))


class TestReadArpMac(unittest.TestCase):
    ARP_CONTENT = (
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.1.10     0x1         0x2         aa:bb:cc:dd:ee:ff     *        eth0\n"
        "192.168.1.20     0x1         0x2         11:22:33:44:55:66     *        eth0\n"
    )

    def test_found(self):
        with patch("builtins.open", unittest.mock.mock_open(read_data=self.ARP_CONTENT)):
            mac = app.read_arp_mac("192.168.1.10")
        self.assertEqual(mac, "aa:bb:cc:dd:ee:ff")

    def test_not_found(self):
        with patch("builtins.open", unittest.mock.mock_open(read_data=self.ARP_CONTENT)):
            mac = app.read_arp_mac("192.168.1.99")
        self.assertEqual(mac, "")

    def test_os_error(self):
        with patch("builtins.open", side_effect=OSError("no file")):
            mac = app.read_arp_mac("192.168.1.10")
        self.assertEqual(mac, "")


class TestReverseDns(unittest.TestCase):
    def test_success(self):
        with patch("socket.gethostbyaddr", return_value=("myhost.local", [], ["192.168.1.1"])):
            self.assertEqual(app.reverse_dns("192.168.1.1"), "myhost.local")

    def test_failure(self):
        with patch("socket.gethostbyaddr", side_effect=OSError("nxdomain")):
            self.assertEqual(app.reverse_dns("192.168.1.1"), "")


# ---------------------------------------------------------------------------
# classify_ip integration
# ---------------------------------------------------------------------------


class TestClassifyIp(unittest.TestCase):
    def setUp(self):
        app._notified_macs.clear()

    def test_tailscale_allowed(self):
        with patch.object(app, "resolve_tailscale_identity", return_value={"tailscale_raw": "node"}), \
             patch.object(app, "_mapping_cache", {}):
            decision = app.classify_ip("100.100.1.1")
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["reason"], "tailscale")

    def test_tailscale_with_ip_in_mapping_sets_basename(self):
        ts_ip = "100.64.1.2"
        with patch.object(app, "resolve_tailscale_identity", return_value={"tailscale_raw": "node"}), \
             patch.object(app, "_mapping_cache", {"100.64.1.2": "TsPlayer"}):
            decision = app.classify_ip(ts_ip)
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["identity"].get("basename"), "TsPlayer")

    def test_tailscale_without_mapping_no_basename_no_notification(self):
        with patch.object(app, "resolve_tailscale_identity", return_value={"tailscale_raw": "node"}), \
             patch.object(app, "_mapping_cache", {}), \
             patch.object(app, "send_telegram") as mock_tg:
            decision = app.classify_ip("100.100.1.1")
        self.assertNotIn("basename", decision["identity"])
        mock_tg.assert_not_called()

    def test_local_allowed(self):
        with patch.object(app, "resolve_local_identity", return_value={"reachable": True, "mac": "", "hostname": ""}), \
             patch.object(app, "_mapping_cache", {}):
            decision = app.classify_ip("192.168.1.50")
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["reason"], "local-net")

    def test_local_mac_in_mapping_sets_basename(self):
        with patch.object(app, "resolve_local_identity", return_value={"reachable": True, "mac": "aa:bb:cc:dd:ee:ff", "hostname": "host"}), \
             patch.object(app, "_mapping_cache", {"aa:bb:cc:dd:ee:ff": "LocalPlayer"}), \
             patch.object(app, "send_telegram") as mock_tg:
            decision = app.classify_ip("192.168.1.10")
        self.assertEqual(decision["identity"].get("basename"), "LocalPlayer")
        mock_tg.assert_not_called()

    def test_local_unmapped_mac_sends_telegram_once(self):
        with patch.object(app, "resolve_local_identity", return_value={"reachable": True, "mac": "11:22:33:44:55:66", "hostname": "host"}), \
             patch.object(app, "_mapping_cache", {}), \
             patch.object(app, "send_telegram") as mock_tg:
            app.classify_ip("192.168.1.20")
            app.classify_ip("192.168.1.20")
        mock_tg.assert_called_once()

    def test_local_unmapped_mac_first_seen_notifies(self):
        with patch.object(app, "resolve_local_identity", return_value={"reachable": True, "mac": "aa:11:22:33:44:55", "hostname": ""}), \
             patch.object(app, "_mapping_cache", {}), \
             patch.object(app, "send_telegram") as mock_tg:
            decision = app.classify_ip("192.168.1.30")
        self.assertNotIn("basename", decision["identity"])
        mock_tg.assert_called_once()
        self.assertIn("aa:11:22:33:44:55", app._notified_macs)

    def test_local_unreachable_denied(self):
        with patch.object(app, "resolve_local_identity", return_value={"reachable": False, "mac": "", "hostname": ""}), \
             patch.object(app, "_mapping_cache", {}):
            decision = app.classify_ip("192.168.1.50")
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "local-net-unreachable")

    def test_external_denied(self):
        decision = app.classify_ip("8.8.8.8")
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "denied")


# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------


class TestSendTelegram(unittest.TestCase):
    def test_sends_when_configured(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        with patch.object(app, "TELEGRAM_BOT_TOKEN", "tok"), \
             patch.object(app, "TELEGRAM_CHAT_ID", "cid"), \
             patch("requests.post", return_value=mock_resp) as mock_post:
            app.send_telegram("test msg")
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["text"], "test msg")

    def test_skips_when_not_configured(self):
        with patch.object(app, "TELEGRAM_BOT_TOKEN", ""), \
             patch.object(app, "TELEGRAM_CHAT_ID", ""), \
             patch("requests.post") as mock_post:
            app.send_telegram("test msg")
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class FakeSocket:
    """Minimal socket stub for BaseHTTPRequestHandler."""

    def __init__(self, data: bytes):
        self._data = BytesIO(data)
        self.output = BytesIO()

    def makefile(self, mode, **_kwargs):
        if "r" in mode:
            return self._data
        return self.output

    def sendall(self, data: bytes):
        self.output.write(data)


class TestAuthHandler(unittest.TestCase):
    def _make_handler(self, path: str) -> tuple:
        request_line = f"GET {path} HTTP/1.0\r\n\r\n".encode()
        sock = FakeSocket(request_line)
        handler = app.AuthHandler.__new__(app.AuthHandler)
        handler.rfile = BytesIO(request_line)
        handler.wfile = sock.output
        handler.path = path
        handler.server = MagicMock()
        handler.client_address = ("127.0.0.1", 9999)
        handler.request_version = "HTTP/1.0"
        handler.command = "GET"
        return handler, sock

    def _call_do_get(self, path: str) -> tuple[int, dict]:
        handler, sock = self._make_handler(path)
        responses = []

        def fake_respond(status, body):
            responses.append((status, body))

        handler._respond = fake_respond
        handler.do_GET()
        return responses[0]

    def test_missing_ip_param(self):
        status, body = self._call_do_get("/auth")
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_not_found(self):
        status, body = self._call_do_get("/other")
        self.assertEqual(status, 404)

    def test_denied_sends_telegram(self):
        with patch.object(app, "classify_ip", return_value={"allowed": False, "reason": "denied", "identity": {}}), \
             patch.object(app, "send_telegram") as mock_tg:
            status, body = self._call_do_get("/auth?ip=8.8.8.8")
        self.assertEqual(status, 403)
        mock_tg.assert_called_once()

    def test_allowed_no_telegram(self):
        with patch.object(app, "classify_ip", return_value={"allowed": True, "reason": "tailscale", "identity": {}}), \
             patch.object(app, "send_telegram") as mock_tg:
            status, body = self._call_do_get("/auth?ip=100.100.1.1")
        self.assertEqual(status, 200)
        mock_tg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
