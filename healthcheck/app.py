"""
Minecraft server health check service.

Polls the Minecraft server via RCON every 30 seconds and exposes
cached status over HTTP. Falls back gracefully when RCON is
unavailable (returns status="offline").
"""

import json
import logging
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify
from mcrcon import MCRcon, MCRconException

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RCON_HOST = os.environ.get("RCON_HOST", "localhost")
RCON_PORT = int(os.environ.get("RCON_PORT", "25575"))
RCON_PASSWORD = os.environ.get("RCON_PASSWORD", "")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "25565"))

POLL_INTERVAL = 30  # seconds between RCON polls
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 1.0  # seconds between retries

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("healthcheck")

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------

START_TIME = time.monotonic()
START_WALL = datetime.now(timezone.utc)

_cache_lock = threading.Lock()
_cached_status: dict = {
    "status": "starting",
    "uptime_seconds": 0,
    "players_online": 0,
    "players_max": 20,
    "version": "unknown",
    "motd": "",
    "timestamp": START_WALL.strftime("%Y-%m-%dT%H:%M:%SZ"),
}

# ---------------------------------------------------------------------------
# RCON helpers
# ---------------------------------------------------------------------------


def _rcon_command(command: str) -> str:
    """
    Execute a single RCON command and return the response string.
    Raises MCRconException or OSError on failure.
    """
    with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
        return mcr.command(command)


def _rcon_command_with_retry(command: str) -> str:
    """
    Execute an RCON command with up to RETRY_ATTEMPTS attempts.
    Raises the last exception if all attempts fail.
    """
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return _rcon_command(command)
        except (MCRconException, OSError, ConnectionRefusedError) as exc:
            last_exc = exc
            log.warning(
                "RCON attempt %d/%d failed for command %r: %s",
                attempt,
                RETRY_ATTEMPTS,
                command,
                exc,
            )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF)
    raise last_exc


def _parse_list_response(response: str) -> tuple[int, int]:
    """
    Parse the output of the Minecraft `list` command.

    Vanilla format:
        "There are 3 of a max of 20 players online: ..."
    Paper/Spigot may vary slightly. Returns (players_online, players_max).
    Falls back to (0, 20) on parse failure.
    """
    match = re.search(r"(\d+)\s+of\s+a\s+max\s+(?:of\s+)?(\d+)", response)
    if match:
        return int(match.group(1)), int(match.group(2))
    # Alternative: "There are X/Y players online"
    match = re.search(r"(\d+)/(\d+)", response)
    if match:
        return int(match.group(1)), int(match.group(2))
    log.warning("Could not parse player count from list response: %r", response)
    return 0, 20


def _query_server_tcp() -> bool:
    """Return True if the Minecraft game port is accepting TCP connections."""
    try:
        with socket.create_connection((RCON_HOST, SERVER_PORT), timeout=3):
            return True
    except OSError:
        return False


def _build_status_payload(
    players_online: int,
    players_max: int,
    status: str,
) -> dict:
    now_utc = datetime.now(timezone.utc)
    uptime = int(time.monotonic() - START_TIME)
    return {
        "status": status,
        "uptime_seconds": uptime,
        "players_online": players_online,
        "players_max": players_max,
        "version": "unknown",  # RCON does not expose version; extend via /version if needed
        "motd": "",
        "timestamp": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Background polling thread
# ---------------------------------------------------------------------------


def _poll_loop() -> None:
    """Continuously polls the Minecraft server via RCON and updates the cache."""
    log.info(
        "RCON poller started (host=%s port=%d interval=%ds)",
        RCON_HOST,
        RCON_PORT,
        POLL_INTERVAL,
    )
    while True:
        _poll_once()
        time.sleep(POLL_INTERVAL)


def _poll_once() -> None:
    """Single poll cycle: query RCON, update cache."""
    try:
        response = _rcon_command_with_retry("list")
        players_online, players_max = _parse_list_response(response)
        payload = _build_status_payload(players_online, players_max, status="online")
        log.info(
            "Poll OK: %d/%d players online", players_online, players_max
        )
    except Exception as exc:
        # RCON unavailable — check if the game port is at least reachable
        tcp_up = _query_server_tcp()
        derived_status = "starting" if tcp_up else "offline"
        payload = _build_status_payload(0, 20, status=derived_status)
        log.warning(
            "RCON unavailable (%s); server TCP port %s -> status=%s",
            exc,
            "up" if tcp_up else "down",
            derived_status,
        )

    with _cache_lock:
        _cached_status.update(payload)


def start_poller() -> None:
    """Start the background polling thread (daemon so it exits with the process)."""
    thread = threading.Thread(target=_poll_loop, name="rcon-poller", daemon=True)
    thread.start()
    log.info("Background RCON poller thread started.")


# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health() -> tuple:
    """Return cached Minecraft server status."""
    with _cache_lock:
        snapshot = dict(_cached_status)
    http_status = 200 if snapshot["status"] == "online" else 503
    return jsonify(snapshot), http_status


@app.route("/ping", methods=["GET"])
def ping() -> tuple:
    """Liveness probe — always returns 200 as long as this process is alive."""
    return jsonify({"alive": True}), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info(
        "Minecraft healthcheck service starting (rcon=%s:%d server_port=%d)",
        RCON_HOST,
        RCON_PORT,
        SERVER_PORT,
    )
    # Perform an immediate poll before accepting traffic so the first /health
    # response is not stale.
    _poll_once()
    start_poller()
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)
