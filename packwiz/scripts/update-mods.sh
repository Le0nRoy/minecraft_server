#!/usr/bin/env bash
set -euo pipefail

# update-mods.sh — Refresh and update all packwiz-managed mods
#
# Usage: ./update-mods.sh [--no-commit]
#   --no-commit   Skip the git commit step even if inside a git repo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACK_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PACKWIZ_BIN="packwiz"
PACKWIZ_VERSION="latest"
PACKWIZ_INSTALL_DIR="${HOME}/.local/bin"
PACKWIZ_RELEASES_URL="https://github.com/packwiz/packwiz/releases/latest/download"

NO_COMMIT=false
for arg in "$@"; do
    case "$arg" in
        --no-commit) NO_COMMIT=true ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

# ── Helper functions ──────────────────────────────────────────────────────────

log()  { echo "[update-mods] $*"; }
err()  { echo "[update-mods] ERROR: $*" >&2; exit 1; }

detect_os_arch() {
    local os arch
    case "$(uname -s)" in
        Linux)  os="linux" ;;
        Darwin) os="darwin" ;;
        MINGW*|CYGWIN*|MSYS*) os="windows" ;;
        *) err "Unsupported OS: $(uname -s)" ;;
    esac

    case "$(uname -m)" in
        x86_64|amd64)  arch="amd64" ;;
        aarch64|arm64) arch="arm64" ;;
        *) err "Unsupported architecture: $(uname -m)" ;;
    esac

    echo "${os}_${arch}"
}

# ── Ensure packwiz is available ───────────────────────────────────────────────

ensure_packwiz() {
    if command -v packwiz &>/dev/null; then
        log "packwiz found at: $(command -v packwiz)"
        return 0
    fi

    # Check local install dir
    if [[ -x "${PACKWIZ_INSTALL_DIR}/packwiz" ]]; then
        export PATH="${PACKWIZ_INSTALL_DIR}:${PATH}"
        log "packwiz found at: ${PACKWIZ_INSTALL_DIR}/packwiz"
        return 0
    fi

    log "packwiz not found — downloading..."

    local os_arch
    os_arch="$(detect_os_arch)"

    local ext=""
    [[ "${os_arch}" == windows* ]] && ext=".exe"

    local download_url="${PACKWIZ_RELEASES_URL}/packwiz_${os_arch}${ext}"
    local dest="${PACKWIZ_INSTALL_DIR}/packwiz${ext}"

    mkdir -p "${PACKWIZ_INSTALL_DIR}"

    if command -v curl &>/dev/null; then
        curl -fsSL "${download_url}" -o "${dest}"
    elif command -v wget &>/dev/null; then
        wget -q "${download_url}" -O "${dest}"
    else
        err "Neither curl nor wget found. Please install packwiz manually: https://packwiz.infra.link/"
    fi

    chmod +x "${dest}"
    export PATH="${PACKWIZ_INSTALL_DIR}:${PATH}"
    log "packwiz installed to: ${dest}"
}

# ── Main logic ────────────────────────────────────────────────────────────────

main() {
    ensure_packwiz

    log "Working directory: ${PACK_DIR}"
    cd "${PACK_DIR}"

    # Verify pack.toml exists
    [[ -f "pack.toml" ]] || err "pack.toml not found in ${PACK_DIR}"

    # Step 1: Refresh index (recalculates hashes, detects new/removed mod files)
    log "Running: packwiz refresh"
    packwiz refresh

    # Step 2: Update all mods to their latest versions on Modrinth
    log "Running: packwiz update --all"
    packwiz update --all

    # Step 3: Re-refresh after update to ensure index is consistent
    log "Running: packwiz refresh (post-update)"
    packwiz refresh

    log "Mod update complete."

    # Step 4: Commit changes if inside a git repository
    if [[ "${NO_COMMIT}" == "true" ]]; then
        log "Skipping git commit (--no-commit passed)."
        return 0
    fi

    if git -C "${PACK_DIR}" rev-parse --is-inside-work-tree &>/dev/null; then
        # Check if there are any changes to commit
        if git -C "${PACK_DIR}" diff --quiet && git -C "${PACK_DIR}" diff --cached --quiet; then
            log "No changes to commit — mods are already up to date."
        else
            log "Committing mod updates..."
            git -C "${PACK_DIR}" add \
                "${PACK_DIR}/index.toml" \
                "${PACK_DIR}/mods/"

            local date_str
            date_str="$(date -u '+%Y-%m-%d')"
            git -C "${PACK_DIR}" commit -m "chore(mods): update packwiz mods ${date_str}"
            log "Git commit created."
        fi
    else
        log "Not inside a git repository — skipping git commit."
    fi
}

main "$@"
