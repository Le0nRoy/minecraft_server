#!/usr/bin/env bash
# Wipe Minecraft world data from the mounted volume and restart the server.
#
# Environment variables:
#   MINECRAFT_DATA_PATH  Path where minecraft_data volume is mounted (default: /minecraft_data)
#   LEVEL                World folder name (default: world)
#   RCON_HOST            RCON hostname (default: minecraft)
#   RCON_PORT            RCON port (default: 25575)
#   RCON_PASSWORD        RCON password
#   RCON_WARN_DELAY      Seconds to wait after warning before stopping (default: 10)

set -euo pipefail

MINECRAFT_DATA_PATH="${MINECRAFT_DATA_PATH:-/minecraft_data}"
LEVEL_NAME="${LEVEL:-world}"
RCON_WARN_DELAY="${RCON_WARN_DELAY:-10}"
RCON_HOST="${RCON_HOST:-minecraft}"
RCON_PORT="${RCON_PORT:-25575}"
RCON_PASSWORD="${RCON_PASSWORD:-}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

find_container() {
    docker ps --filter "label=com.minecraft-server.service=minecraft" \
        --format "{{.Names}}" 2>/dev/null | head -1
}

send_rcon_warn() {
    # Direct TCP RCON — bypasses docker exec (blocked by socket-proxy POST=0)
    if rcon-cli --host "${RCON_HOST}" --port "${RCON_PORT}" --password "${RCON_PASSWORD}" \
            "say §cServer wipe in ${RCON_WARN_DELAY}s — world data will be erased!" \
            2>/dev/null; then
        return 0
    fi
    log "WARNING: RCON warn failed — continuing"
    return 0
}

CONTAINER="$(find_container)"

# 1. RCON warning + wait if server is running
if [[ -n "$CONTAINER" ]]; then
    log "INFO: Server running ($CONTAINER) — sending RCON warning"
    send_rcon_warn "$CONTAINER"
    sleep "${RCON_WARN_DELAY}"

    # 2. Stop container
    log "INFO: Stopping $CONTAINER"
    docker stop "$CONTAINER"
else
    log "INFO: Server not running — skipping RCON warning and stop"
fi

# 3. Delete world folders directly from the mounted volume
for world_dir in "${LEVEL_NAME}" "${LEVEL_NAME}_nether" "${LEVEL_NAME}_the_end"; do
    target="${MINECRAFT_DATA_PATH}/${world_dir}"
    if [[ -d "$target" ]]; then
        log "INFO: Deleting $target"
        rm -rf "$target"
    else
        log "WARNING: $target not found — skipping"
    fi
done

# 4. Start the container (use the name found earlier, or fall back to label lookup)
START_TARGET="${CONTAINER:-}"
if [[ -z "$START_TARGET" ]]; then
    # Server was already stopped; find it including stopped containers
    START_TARGET="$(docker ps -a --filter "label=com.minecraft-server.service=minecraft" \
        --format "{{.Names}}" | head -1)"
fi

if [[ -z "$START_TARGET" ]]; then
    log "ERROR: Could not find Minecraft container to restart"
    exit 1
fi

log "INFO: Starting $START_TARGET"
docker start "$START_TARGET"
log "INFO: Wipe complete"
