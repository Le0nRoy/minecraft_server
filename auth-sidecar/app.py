"""
Auth identity sidecar service.

Exposes GET /auth?ip=<ip> and classifies connecting IPs:
  - Tailscale (100.x.x.x): allowed, identity resolved via `tailscale whois`
  - Local-net (RFC 1918 private): allowed if reachable, identity from ARP + rDNS
  - All others: denied + Telegram notification sent
"""

import concurrent.futures
import ipaddress
import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LISTEN_PORT = int(os.environ.get("AUTH_SIDECAR_PORT", "8181"))
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")
MAPPING_FILE: str = os.environ.get("MAC_MAPPING_FILE", "/data/mac-mapping.json")
MAPPING_RELOAD_INTERVAL: int = int(os.environ.get("MAPPING_RELOAD_INTERVAL", "30"))
ALLOWLIST_FILE: str = os.environ.get("ALLOWLIST_FILE", "/data/allowlist.json")
DENYLIST_FILE: str = os.environ.get("DENYLIST_FILE", "/data/denylist.json")

TAILSCALE_PREFIX = ipaddress.ip_network("100.64.0.0/10")

PING_TIMEOUT_SECONDS = 2
WHOIS_TIMEOUT_SECONDS = 5
RDNS_TIMEOUT_SECONDS = 2
TELEGRAM_TIMEOUT_SECONDS = 10

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("auth-sidecar")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_mapping_cache: dict[str, str] = {}
# in-memory per-session dedup; intentionally reset on restart (owner decision 2026-09-09)
_notified_macs: set[str] = set()
_notified_ips: set[str] = set()
_allowlist_cache: set[str] = set()
_denylist_cache: set[str] = set()

# ---------------------------------------------------------------------------
# IP classification
# ---------------------------------------------------------------------------


def is_tailscale(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in TAILSCALE_PREFIX
    except ValueError:
        return False


def is_local_net(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# MAC / key normalization and mapping
# ---------------------------------------------------------------------------

_MAC_RE = re.compile(r'^([0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}$')


def normalize_key(key: str) -> str:
    """Normalize mapping key: MACs get dash→colon + lowercase; IPs pass through."""
    if _MAC_RE.match(key):
        return key.replace("-", ":").lower()
    return key


def load_mapping(path: str = MAPPING_FILE) -> dict[str, str]:
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            log.error("Mapping file is not a JSON object: %s", path)
            return {}
        return {normalize_key(k): v for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Failed to load mapping file %s: %s", path, exc)
        return {}


def lookup_basename(key: str, mapping: dict[str, str]) -> str | None:
    return mapping.get(normalize_key(key)) or None


def load_list(path: str) -> set[str]:
    """Load a JSON array list file into a normalized set. Returns empty set on missing/malformed file."""
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, list):
            log.error("List file is not a JSON array: %s", path)
            return set()
        return {normalize_key(entry) for entry in data if isinstance(entry, str)}
    except FileNotFoundError:
        return set()
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Failed to load list file %s: %s", path, exc)
        return set()


def _append_to_denylist(key: str) -> None:
    """Append a key to the denylist file atomically. No-op if already present."""
    normalized = normalize_key(key)
    current = load_list(DENYLIST_FILE)
    if normalized in current:
        log.debug("Key %s already in denylist — skipped", normalized)
        return
    current.add(normalized)
    dir_ = os.path.dirname(DENYLIST_FILE) or "."
    try:
        with tempfile.NamedTemporaryFile("w", dir=dir_, suffix=".tmp", delete=False) as f:
            json.dump(sorted(current), f)
            tmp = f.name
        os.replace(tmp, DENYLIST_FILE)
        log.info("Auto-denylisted: %s", normalized)
    except OSError as exc:
        log.error("Failed to write denylist file %s: %s", DENYLIST_FILE, exc)


def _mapping_reload_loop() -> None:
    while True:
        time.sleep(MAPPING_RELOAD_INTERVAL)
        global _mapping_cache, _allowlist_cache, _denylist_cache
        _mapping_cache = load_mapping()
        _allowlist_cache = load_list(ALLOWLIST_FILE)
        _denylist_cache = load_list(DENYLIST_FILE)
        log.debug("Mapping reloaded: %d entries", len(_mapping_cache))
        log.debug("Lists reloaded: allowlist=%d denylist=%d", len(_allowlist_cache), len(_denylist_cache))


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


def resolve_tailscale_identity(ip: str) -> dict:
    """Run `tailscale whois <ip>` and parse the output."""
    try:
        result = subprocess.run(
            ["tailscale", "whois", ip],
            capture_output=True,
            text=True,
            timeout=WHOIS_TIMEOUT_SECONDS,
        )
        raw = result.stdout.strip()
        if result.returncode != 0:
            log.warning("tailscale whois exited %d: %s", result.returncode, result.stderr.strip())
            return {"tailscale_raw": "", "error": "whois failed"}
        return {"tailscale_raw": raw}
    except FileNotFoundError:
        log.error("tailscale binary not found")
        return {"tailscale_raw": "", "error": "tailscale not installed"}
    except subprocess.TimeoutExpired:
        log.warning("tailscale whois timed out for %s", ip)
        return {"tailscale_raw": "", "error": "whois timeout"}


def ping_host(ip: str) -> bool:
    """Return True if the host responds to a single ICMP ping."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(PING_TIMEOUT_SECONDS), ip],
            capture_output=True,
            timeout=PING_TIMEOUT_SECONDS + 1,
        )
        return result.returncode == 0
    except Exception as exc:
        log.debug("ping %s failed: %s", ip, exc)
        return False


def read_arp_mac(ip: str) -> str:
    """Read MAC address from /proc/net/arp for a given IP."""
    try:
        with open("/proc/net/arp") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip:
                    return parts[3]
    except OSError as exc:
        log.debug("ARP read failed: %s", exc)
    return ""


def reverse_dns(ip: str) -> str:
    """Perform reverse DNS lookup; return empty string on failure or timeout."""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(socket.gethostbyaddr, ip)
            return future.result(timeout=RDNS_TIMEOUT_SECONDS)[0]
    except Exception:
        return ""


def resolve_local_identity(ip: str) -> dict:
    reachable = ping_host(ip)
    mac = read_arp_mac(ip) if reachable else ""
    hostname = reverse_dns(ip)
    return {"reachable": reachable, "mac": mac, "hostname": hostname}


# ---------------------------------------------------------------------------
# Telegram notifications
# ---------------------------------------------------------------------------


def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured; skipping notification")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        resp = requests.post(url, json=payload, timeout=TELEGRAM_TIMEOUT_SECONDS)
        if not resp.ok:
            log.warning("Telegram API returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.error("Telegram notification failed: %s", exc)


def send_telegram_with_keyboard(text: str, key: str) -> None:
    """Send a Telegram message with allowlist/denylist inline keyboard buttons."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured; skipping notification")
        return
    keyboard = {"inline_keyboard": [[
        {"text": "✅ Allowlist", "callback_data": f"allow|{key}"},
        {"text": "🚫 Denylist", "callback_data": f"deny|{key}"},
    ]]}
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "reply_markup": json.dumps(keyboard),
    }
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json=payload, timeout=TELEGRAM_TIMEOUT_SECONDS)
        if not resp.ok:
            log.warning("Telegram keyboard API returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.error("Telegram keyboard notification failed: %s", exc)


# ---------------------------------------------------------------------------
# Auth decision
# ---------------------------------------------------------------------------


def classify_ip(ip: str) -> dict:
    """
    Classify an IP and return a decision dict:
      {allowed, reason, identity}

    Priority: denylist → allowlist → tailscale → local-net → external deny.
    """
    if ip in _denylist_cache:
        log.info("DENIED ip=%s reason=denylisted", ip)
        return {"allowed": False, "reason": "denylisted", "identity": {}}

    if ip in _allowlist_cache:
        log.info("ALLOWED ip=%s reason=allowlisted", ip)
        return {"allowed": True, "reason": "allowlisted", "identity": {}}

    if is_tailscale(ip):
        identity = resolve_tailscale_identity(ip)
        basename = lookup_basename(ip, _mapping_cache)
        if basename:
            log.info("Tailscale IP %s mapped to basename %s", ip, basename)
            identity["basename"] = basename
        return {"allowed": True, "reason": "tailscale", "identity": identity}

    if is_local_net(ip):
        identity = resolve_local_identity(ip)
        mac = identity.get("mac", "")
        if mac:
            if mac in _denylist_cache:
                log.info("DENIED ip=%s mac=%s reason=denylisted", ip, mac)
                return {"allowed": False, "reason": "denylisted", "identity": identity}
            if mac in _allowlist_cache:
                log.info("ALLOWED ip=%s mac=%s reason=allowlisted", ip, mac)
                return {"allowed": True, "reason": "allowlisted", "identity": identity}
            basename = lookup_basename(mac, _mapping_cache)
            if basename:
                log.info("MAC %s mapped to basename %s", mac, basename)
                identity["basename"] = basename
            elif mac not in _notified_macs:
                _notified_macs.add(mac)
                log.info("Unknown MAC %s — notifying Telegram", mac)
                send_telegram_with_keyboard(
                    f"[auth-sidecar] Unknown client: MAC={mac} "
                    f"hostname={identity.get('hostname') or 'unknown'} ip={ip}",
                    mac,
                )
        if not identity["reachable"]:
            return {"allowed": False, "reason": "local-net-unreachable", "identity": identity}
        return {"allowed": True, "reason": "local-net", "identity": identity}

    return {"allowed": False, "reason": "denied", "identity": {}}


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class AuthHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence default access log; use our logger
        log.debug("HTTP %s", fmt % args)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/auth":
            self._respond(404, {"error": "not found"})
            return

        params = parse_qs(parsed.query)
        ip_list = params.get("ip", [])
        if not ip_list:
            self._respond(400, {"error": "ip parameter required"})
            return

        ip = ip_list[0]
        log.info("Auth request for ip=%s", ip)

        decision = classify_ip(ip)

        if not decision["allowed"]:
            reason = decision["reason"]
            if reason == "denied" and ip not in _notified_ips:
                _notified_ips.add(ip)
                _append_to_denylist(ip)
                _denylist_cache.add(normalize_key(ip))
                log.warning("DENIED external ip=%s — auto-denylisted and notified", ip)
                send_telegram_with_keyboard(
                    f"[auth-sidecar] DENIED: connection from unknown IP {ip}", ip
                )
            elif reason == "denylisted":
                log.info("DENIED ip=%s reason=denylisted (silent)", ip)
            elif reason == "local-net-unreachable":
                log.warning("DENIED ip=%s reason=local-net-unreachable", ip)
                send_telegram(f"[auth-sidecar] DENIED: local-net IP {ip} unreachable")
            else:
                log.warning("DENIED ip=%s reason=%s (unhandled)", ip, reason)
            self._respond(403, decision)
            return

        log.info("ALLOWED ip=%s reason=%s", ip, decision["reason"])
        self._respond(200, decision)

    def _respond(self, status: int, body: dict) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    global _mapping_cache, _allowlist_cache, _denylist_cache
    _mapping_cache = load_mapping()
    _allowlist_cache = load_list(ALLOWLIST_FILE)
    _denylist_cache = load_list(DENYLIST_FILE)
    log.info("Loaded %d mapping entries from %s", len(_mapping_cache), MAPPING_FILE)
    log.info("Loaded %d allowlist, %d denylist entries", len(_allowlist_cache), len(_denylist_cache))

    t = threading.Thread(target=_mapping_reload_loop, daemon=True)
    t.start()

    log.info("Auth sidecar starting on port %d", LISTEN_PORT)
    server = HTTPServer(("0.0.0.0", LISTEN_PORT), AuthHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
