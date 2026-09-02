"""
Auth identity sidecar service.

Exposes GET /auth?ip=<ip> and classifies connecting IPs:
  - Tailscale (100.x.x.x): allowed, identity resolved via `tailscale whois`
  - Local-net (192.168.x.x): allowed if reachable, identity from ARP + rDNS
  - All others: denied + Telegram notification sent
"""

import ipaddress
import json
import logging
import os
import socket
import subprocess
import sys
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

TAILSCALE_PREFIX = ipaddress.ip_network("100.64.0.0/10")
LOCAL_NET_PREFIX = ipaddress.ip_network("192.168.0.0/16")

PING_TIMEOUT_SECONDS = 2
WHOIS_TIMEOUT_SECONDS = 5
RDNS_TIMEOUT_SECONDS = 2

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
# IP classification
# ---------------------------------------------------------------------------


def is_tailscale(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in TAILSCALE_PREFIX
    except ValueError:
        return False


def is_local_net(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in LOCAL_NET_PREFIX
    except ValueError:
        return False


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
    """Perform reverse DNS lookup; return empty string on failure."""
    try:
        return socket.gethostbyaddr(ip)[0]
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
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            log.warning("Telegram API returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.error("Telegram notification failed: %s", exc)


# ---------------------------------------------------------------------------
# Auth decision
# ---------------------------------------------------------------------------


def classify_ip(ip: str) -> dict:
    """
    Classify an IP and return a decision dict:
      {allowed, reason, identity}
    """
    if is_tailscale(ip):
        identity = resolve_tailscale_identity(ip)
        return {
            "allowed": True,
            "reason": "tailscale",
            "identity": identity,
        }

    if is_local_net(ip):
        identity = resolve_local_identity(ip)
        return {
            "allowed": True,
            "reason": "local-net",
            "identity": identity,
        }

    return {
        "allowed": False,
        "reason": "denied",
        "identity": {},
    }


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
            msg = f"[auth-sidecar] DENIED: connection from unknown IP {ip}"
            log.warning(msg)
            send_telegram(msg)
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
    log.info("Auth sidecar starting on port %d", LISTEN_PORT)
    server = HTTPServer(("0.0.0.0", LISTEN_PORT), AuthHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
