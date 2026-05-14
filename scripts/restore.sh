#!/usr/bin/env bash
# restore.sh — Restore a Minecraft server backup.
#
# Usage:
#   ./scripts/restore.sh                      — interactive: list backups, prompt to select
#   ./scripts/restore.sh <backup-file>        — restore the given backup file
#   ./scripts/restore.sh --list               — list available backups and exit
#   ./scripts/restore.sh --force <backup>     — skip all confirmation prompts
#
# Environment variables (sourced from ../.env if present):
#   BACKUP_DIR   — Where backups are stored (default: ./backups)

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

BACKUP_DIR="${BACKUP_DIR:-./backups}"
if [[ "${BACKUP_DIR}" != /* ]]; then
    BACKUP_DIR="${PROJECT_ROOT}/${BACKUP_DIR#./}"
fi

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

LIST_ONLY=false
FORCE=false
BACKUP_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --list)
            LIST_ONLY=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --*)
            error "Unknown option: $1"
            echo "Usage: $0 [--list] [--force] [<backup-file>]" >&2
            exit 1
            ;;
        *)
            if [[ -n "${BACKUP_ARG}" ]]; then
                error "Too many arguments"
                exit 1
            fi
            BACKUP_ARG="$1"
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# List available backups
# ---------------------------------------------------------------------------

list_backups() {
    if [[ ! -d "${BACKUP_DIR}" ]]; then
        error "Backup directory does not exist: ${BACKUP_DIR}"
        exit 1
    fi

    mapfile -t BACKUPS < <(
        find "${BACKUP_DIR}" -maxdepth 1 \( -name "backup_*.tar.zst" -o -name "backup_*.tar.gz" \) \
            -printf "%T@ %p\n" 2>/dev/null \
        | sort -rn \
        | awk '{print $2}'
    )

    if [[ ${#BACKUPS[@]} -eq 0 ]]; then
        warn "No backups found in ${BACKUP_DIR}"
        exit 0
    fi

    echo ""
    echo "Available backups (newest first):"
    echo "-----------------------------------"
    local i=1
    for backup in "${BACKUPS[@]}"; do
        local size
        size="$(du -sh "${backup}" 2>/dev/null | cut -f1)"
        printf "  [%2d] %-50s  %s\n" "${i}" "$(basename "${backup}")" "${size}"
        (( i++ )) || true
    done
    echo ""
}

# Handle --list flag
if [[ "${LIST_ONLY}" == "true" ]]; then
    list_backups
    exit 0
fi

# ---------------------------------------------------------------------------
# Determine which backup to restore
# ---------------------------------------------------------------------------

SELECTED_BACKUP=""

if [[ -n "${BACKUP_ARG}" ]]; then
    # Argument provided: resolve path
    if [[ -f "${BACKUP_ARG}" ]]; then
        SELECTED_BACKUP="$(realpath "${BACKUP_ARG}")"
    elif [[ -f "${BACKUP_DIR}/${BACKUP_ARG}" ]]; then
        SELECTED_BACKUP="${BACKUP_DIR}/${BACKUP_ARG}"
    else
        error "Backup file not found: ${BACKUP_ARG}"
        exit 1
    fi
else
    # Interactive selection
    list_backups

    mapfile -t BACKUPS < <(
        find "${BACKUP_DIR}" -maxdepth 1 \( -name "backup_*.tar.zst" -o -name "backup_*.tar.gz" \) \
            -printf "%T@ %p\n" 2>/dev/null \
        | sort -rn \
        | awk '{print $2}'
    )

    if [[ ${#BACKUPS[@]} -eq 0 ]]; then
        exit 0
    fi

    while true; do
        read -r -p "Enter backup number to restore (or 'q' to quit): " selection
        if [[ "${selection}" == "q" || "${selection}" == "Q" ]]; then
            info "Restore cancelled"
            exit 0
        fi
        if [[ "${selection}" =~ ^[0-9]+$ ]] && (( selection >= 1 && selection <= ${#BACKUPS[@]} )); then
            SELECTED_BACKUP="${BACKUPS[$(( selection - 1 ))]}"
            break
        fi
        echo "  Invalid selection. Enter a number between 1 and ${#BACKUPS[@]}, or 'q' to quit."
    done
fi

info "Selected backup: $(basename "${SELECTED_BACKUP}")"

# ---------------------------------------------------------------------------
# Check if Minecraft container is running
# ---------------------------------------------------------------------------

CONTAINER_RUNNING=false
CONTAINER_NAME=""

if command -v docker &>/dev/null; then
    CONTAINER_NAME="$(docker ps --filter "label=com.minecraft-server.service=minecraft" --format "{{.Names}}" 2>/dev/null | head -1)"
    if [[ -n "${CONTAINER_NAME}" ]]; then
        CONTAINER_RUNNING=true
    fi
fi

if [[ "${CONTAINER_RUNNING}" == "true" ]]; then
    warn "Minecraft container '${CONTAINER_NAME}' is currently running!"
    warn "Restoring while the server is running can corrupt your world."

    if [[ "${FORCE}" == "false" ]]; then
        echo ""
        read -r -p "Type 'yes' to stop the server and continue with restore: " confirm
        if [[ "${confirm}" != "yes" ]]; then
            info "Restore cancelled"
            exit 0
        fi
    else
        info "--force flag set — stopping server without prompt"
    fi
fi

# ---------------------------------------------------------------------------
# Final confirmation (unless --force)
# ---------------------------------------------------------------------------

if [[ "${FORCE}" == "false" ]]; then
    echo ""
    warn "This will overwrite the current world, config, and packwiz directories!"
    read -r -p "Are you sure you want to restore from '$(basename "${SELECTED_BACKUP}")'? Type 'yes' to confirm: " final_confirm
    if [[ "${final_confirm}" != "yes" ]]; then
        info "Restore cancelled"
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Stop the Minecraft container
# ---------------------------------------------------------------------------

if [[ "${CONTAINER_RUNNING}" == "true" ]]; then
    info "Stopping Minecraft container..."
    COMPOSE_FILE="${PROJECT_ROOT}/server/docker-compose.yml"
    if [[ -f "${COMPOSE_FILE}" ]]; then
        (cd "${PROJECT_ROOT}/server" && docker compose down) || \
            docker stop "${CONTAINER_NAME}" || \
            warn "Failed to stop container gracefully"
    else
        docker stop "${CONTAINER_NAME}" || warn "Failed to stop container"
    fi
    info "Container stopped"
fi

# ---------------------------------------------------------------------------
# Create pre-restore safety snapshot
# ---------------------------------------------------------------------------

PRE_RESTORE_TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
PRE_RESTORE_DIR="${BACKUP_DIR}/pre-restore-${PRE_RESTORE_TIMESTAMP}"

info "Creating pre-restore safety snapshot at ${PRE_RESTORE_DIR}..."
mkdir -p "${PRE_RESTORE_DIR}"

SNAPSHOT_SOURCES=()
for src in "server/world" "server/config" "packwiz"; do
    if [[ -e "${PROJECT_ROOT}/${src}" ]]; then
        SNAPSHOT_SOURCES+=("${src}")
    fi
done

if [[ ${#SNAPSHOT_SOURCES[@]} -gt 0 ]]; then
    (
        cd "${PROJECT_ROOT}"
        if command -v zstd &>/dev/null; then
            tar --zstd -cf "${PRE_RESTORE_DIR}/snapshot.tar.zst" "${SNAPSHOT_SOURCES[@]}" 2>/dev/null || \
                warn "Pre-restore snapshot failed (non-fatal)"
        else
            tar -czf "${PRE_RESTORE_DIR}/snapshot.tar.gz" "${SNAPSHOT_SOURCES[@]}" 2>/dev/null || \
                warn "Pre-restore snapshot failed (non-fatal)"
        fi
    )
    info "Safety snapshot created in ${PRE_RESTORE_DIR}"
else
    warn "No existing data found for safety snapshot"
    rmdir "${PRE_RESTORE_DIR}" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# Extract backup to temp directory
# ---------------------------------------------------------------------------

TEMP_EXTRACT_DIR="$(mktemp -d "${BACKUP_DIR}/.restore-tmp-XXXXXX")"
trap 'rm -rf "${TEMP_EXTRACT_DIR}"' EXIT

info "Extracting backup to temporary directory..."

# Determine decompression flags from file extension
case "${SELECTED_BACKUP}" in
    *.tar.zst)  EXTRACT_FLAGS="--zstd" ;;
    *.tar.gz)   EXTRACT_FLAGS="-z" ;;
    *.tar.bz2)  EXTRACT_FLAGS="-j" ;;
    *.tar.xz)   EXTRACT_FLAGS="-J" ;;
    *)
        error "Unrecognised archive format: $(basename "${SELECTED_BACKUP}")"
        exit 1
        ;;
esac

tar ${EXTRACT_FLAGS} -xf "${SELECTED_BACKUP}" -C "${TEMP_EXTRACT_DIR}"
info "Extraction complete"

# ---------------------------------------------------------------------------
# Move extracted files into place
# ---------------------------------------------------------------------------

RESTORE_TARGETS=("server/world" "server/config" "packwiz")

for target in "${RESTORE_TARGETS[@]}"; do
    extracted_path="${TEMP_EXTRACT_DIR}/${target}"
    dest_path="${PROJECT_ROOT}/${target}"

    if [[ -d "${extracted_path}" ]]; then
        info "Restoring ${target}..."
        # Remove existing directory before moving
        rm -rf "${dest_path}"
        mkdir -p "$(dirname "${dest_path}")"
        mv "${extracted_path}" "${dest_path}"
    elif [[ -f "${extracted_path}" ]]; then
        info "Restoring file ${target}..."
        rm -f "${dest_path}"
        mkdir -p "$(dirname "${dest_path}")"
        mv "${extracted_path}" "${dest_path}"
    else
        warn "Path not found in backup archive: ${target} — skipping"
    fi
done

# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------

info "Restore complete!"
echo ""
echo "  Backup restored: $(basename "${SELECTED_BACKUP}")"
echo ""
echo "To restart the Minecraft server, run one of:"
echo "  cd server && docker compose up -d"
echo "  make start   (if Makefile is present)"
echo ""
