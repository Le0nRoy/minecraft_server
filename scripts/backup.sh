#!/usr/bin/env bash
# backup.sh — Create a timestamped backup of the Minecraft server world, config, and mods.
#
# Usage: ./scripts/backup.sh [--dry-run]
#
# Environment variables (sourced from ../.env if present):
#   BACKUP_DIR              — Where to store backups (default: ./backups)
#   BACKUP_RETENTION_DAYS   — How many days to keep backups (default: 14)
#   RCON_PASSWORD           — RCON password for pausing world saves
#   RCON_PORT               — RCON port (default: 25575)
#   TELEGRAM_BOT_TOKEN      — Telegram bot token for failure notifications
#   TELEGRAM_CHAT_ID        — Telegram chat ID for failure notifications

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() {
    local level="$1"
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${level}: $*"
}

info()  { log "INFO"    "$@"; }
warn()  { log "WARNING" "$@"; }
error() { log "ERROR"   "$@" >&2; }

send_telegram() {
    local message="$1"
    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=${message}" \
            -d "parse_mode=Markdown" \
            > /dev/null 2>&1 || true
    fi
}

on_error() {
    local exit_code=$?
    error "Backup failed with exit code ${exit_code}"
    send_telegram "Minecraft backup FAILED on $(hostname) at $(date '+%Y-%m-%d %H:%M:%S') — exit code ${exit_code}"
    exit 1
}

trap 'on_error' ERR

# ---------------------------------------------------------------------------
# Load environment
# ---------------------------------------------------------------------------

ENV_FILE="${PROJECT_ROOT}/.env"
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    set -a
    source "${ENV_FILE}"
    set +a
    info "Loaded environment from ${ENV_FILE}"
fi

# Defaults
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
RCON_PORT="${RCON_PORT:-25575}"
RCON_HOST="${RCON_HOST:-localhost}"

# Resolve BACKUP_DIR relative to project root if not absolute
if [[ "${BACKUP_DIR}" != /* ]]; then
    BACKUP_DIR="${PROJECT_ROOT}/${BACKUP_DIR#./}"
fi

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

DRY_RUN=false
for arg in "$@"; do
    case "${arg}" in
        --dry-run)
            DRY_RUN=true
            info "DRY RUN mode — no files will be written"
            ;;
        *)
            error "Unknown argument: ${arg}"
            echo "Usage: $0 [--dry-run]" >&2
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Determine compression
# ---------------------------------------------------------------------------

TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"

if command -v zstd &>/dev/null; then
    ARCHIVE_EXT="tar.zst"
    COMPRESS_ARGS="--zstd"
    info "Using zstd compression"
else
    ARCHIVE_EXT="tar.gz"
    COMPRESS_ARGS="-z"
    warn "zstd not found — falling back to gzip compression"
fi

BACKUP_FILENAME="backup_${TIMESTAMP}.${ARCHIVE_EXT}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_FILENAME}"

# ---------------------------------------------------------------------------
# Paths to back up (relative to project root)
# ---------------------------------------------------------------------------

BACKUP_SOURCES=(
    "server/world"
    "server/config"
    "packwiz"
    ".env.example"
)

# ---------------------------------------------------------------------------
# RCON helper
# ---------------------------------------------------------------------------

rcon_available=false

send_rcon() {
    local cmd="$1"

    # Try mcrcon first
    if command -v mcrcon &>/dev/null; then
        mcrcon -H "${RCON_HOST}" -P "${RCON_PORT}" -p "${RCON_PASSWORD:-}" "${cmd}" 2>/dev/null && return 0
    fi

    # Try docker exec with rcon-cli inside the container
    if command -v docker &>/dev/null; then
        local container
        container="$(docker ps --filter "label=com.minecraft-server.service=minecraft" --format "{{.Names}}" 2>/dev/null | head -1)"
        if [[ -n "${container}" ]]; then
            docker exec "${container}" rcon-cli --password "${RCON_PASSWORD:-}" "${cmd}" 2>/dev/null && return 0
        fi
    fi

    return 1
}

check_rcon() {
    if [[ -z "${RCON_PASSWORD:-}" ]]; then
        warn "RCON_PASSWORD not set — skipping RCON commands"
        rcon_available=false
        return
    fi

    if send_rcon "list" &>/dev/null 2>&1; then
        rcon_available=true
        info "RCON connection verified"
    else
        rcon_available=false
        warn "RCON not reachable — server may be offline; continuing without save pause"
    fi
}

# ---------------------------------------------------------------------------
# Dry-run: just report what would happen
# ---------------------------------------------------------------------------

if [[ "${DRY_RUN}" == "true" ]]; then
    info "Would create backup: ${BACKUP_PATH}"
    info "Would back up the following paths:"
    for src in "${BACKUP_SOURCES[@]}"; do
        full_path="${PROJECT_ROOT}/${src}"
        if [[ -e "${full_path}" ]]; then
            info "  [EXISTS]  ${full_path}"
        else
            warn "  [MISSING] ${full_path}"
        fi
    done
    info "Would rotate backups older than ${BACKUP_RETENTION_DAYS} days in ${BACKUP_DIR}"
    info "Dry run complete — no files written"
    exit 0
fi

# ---------------------------------------------------------------------------
# Create backup directory
# ---------------------------------------------------------------------------

mkdir -p "${BACKUP_DIR}"

# ---------------------------------------------------------------------------
# Pre-backup: pause world autosave via RCON
# ---------------------------------------------------------------------------

check_rcon

if [[ "${rcon_available}" == "true" ]]; then
    info "Sending save-off to pause autosave..."
    send_rcon "save-off" || warn "save-off command failed — continuing"
    info "Sending save-all to flush world to disk..."
    send_rcon "save-all" || warn "save-all command failed — continuing"
    info "Waiting 5 seconds for world flush..."
    sleep 5
fi

# ---------------------------------------------------------------------------
# Build list of existing sources
# ---------------------------------------------------------------------------

TAR_SOURCES=()
for src in "${BACKUP_SOURCES[@]}"; do
    full_path="${PROJECT_ROOT}/${src}"
    if [[ -e "${full_path}" ]]; then
        TAR_SOURCES+=("${src}")
    else
        warn "Path not found, skipping: ${full_path}"
    fi
done

if [[ ${#TAR_SOURCES[@]} -eq 0 ]]; then
    error "No backup sources exist — aborting"
    exit 1
fi

# ---------------------------------------------------------------------------
# Create archive
# ---------------------------------------------------------------------------

info "Creating backup: ${BACKUP_PATH}"

# Run tar from project root so paths inside archive are relative
(
    cd "${PROJECT_ROOT}"
    tar ${COMPRESS_ARGS} -cf "${BACKUP_PATH}" "${TAR_SOURCES[@]}"
)

# ---------------------------------------------------------------------------
# Post-backup: resume autosave via RCON
# ---------------------------------------------------------------------------

if [[ "${rcon_available}" == "true" ]]; then
    info "Sending save-on to resume autosave..."
    send_rcon "save-on" || warn "save-on command failed — autosave may still be paused; run 'save-on' manually"
fi

# ---------------------------------------------------------------------------
# Rotate old backups
# ---------------------------------------------------------------------------

info "Rotating backups older than ${BACKUP_RETENTION_DAYS} days..."
DELETED_COUNT=0
while IFS= read -r old_backup; do
    info "  Deleting old backup: $(basename "${old_backup}")"
    rm -f "${old_backup}"
    (( DELETED_COUNT++ )) || true
done < <(find "${BACKUP_DIR}" -maxdepth 1 \( -name "backup_*.tar.zst" -o -name "backup_*.tar.gz" \) -mtime "+${BACKUP_RETENTION_DAYS}" 2>/dev/null)

if [[ ${DELETED_COUNT} -gt 0 ]]; then
    info "Rotated ${DELETED_COUNT} old backup(s)"
fi

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

BACKUP_SIZE="$(du -sh "${BACKUP_PATH}" | cut -f1)"
info "Backup complete!"
info "  File : ${BACKUP_PATH}"
info "  Size : ${BACKUP_SIZE}"
