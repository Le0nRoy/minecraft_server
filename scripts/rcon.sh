#!/usr/bin/env bash
# rcon.sh — Send a command to the running Minecraft server via RCON.
#
# Usage: ./scripts/rcon.sh <command> [args...]
#
# Environment variables (sourced from ../.env if present):
#   RCON_HOST       — RCON host (default: localhost)
#   RCON_PORT       — RCON port (default: 25575)
#   RCON_PASSWORD   — RCON password (required)
#
# Examples:
#   ./scripts/rcon.sh list
#   ./scripts/rcon.sh "say Hello, world!"
#   ./scripts/rcon.sh "op PlayerName"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
    local level="$1"
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${level}: $*"
}

info()  { log "INFO"  "$@"; }
error() { log "ERROR" "$@" >&2; }

# ---------------------------------------------------------------------------
# Load environment
# ---------------------------------------------------------------------------

ENV_FILE="${PROJECT_ROOT}/.env"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    set -a
    source "${ENV_FILE}"
    set +a
fi

RCON_HOST="${RCON_HOST:-localhost}"
RCON_PORT="${RCON_PORT:-25575}"

# ---------------------------------------------------------------------------
# Validate input
# ---------------------------------------------------------------------------

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 <command> [args...]" >&2
    echo "" >&2
    echo "Examples:" >&2
    echo "  $0 list" >&2
    echo "  $0 \"say Hello, world!\"" >&2
    echo "  $0 \"op PlayerName\"" >&2
    exit 1
fi

if [[ -z "${RCON_PASSWORD:-}" ]]; then
    error "RCON_PASSWORD is not set. Set it in .env or export it before running this script."
    exit 1
fi

# Join all positional arguments into a single command string
RCON_COMMAND="$*"

# ---------------------------------------------------------------------------
# Attempt RCON via mcrcon
# ---------------------------------------------------------------------------

if command -v mcrcon &>/dev/null; then
    info "Using mcrcon to send: ${RCON_COMMAND}"
    exec mcrcon -H "${RCON_HOST}" -P "${RCON_PORT}" -p "${RCON_PASSWORD}" "${RCON_COMMAND}"
fi

# ---------------------------------------------------------------------------
# Attempt RCON via docker exec + rcon-cli
# ---------------------------------------------------------------------------

if command -v docker &>/dev/null; then
    CONTAINER="$(docker ps --filter "label=com.minecraft-server.service=minecraft" --format "{{.Names}}" 2>/dev/null | head -1)"
    if [[ -n "${CONTAINER}" ]]; then
        if docker exec "${CONTAINER}" which rcon-cli &>/dev/null 2>&1; then
            info "Using docker exec rcon-cli in container '${CONTAINER}' to send: ${RCON_COMMAND}"
            exec docker exec "${CONTAINER}" rcon-cli --password "${RCON_PASSWORD}" "${RCON_COMMAND}"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# No RCON method available
# ---------------------------------------------------------------------------

error "No RCON method available."
error "Install mcrcon (https://github.com/Tiiffi/mcrcon) and ensure it is on PATH, or"
error "make sure the Minecraft container is running with rcon-cli available."
exit 1
