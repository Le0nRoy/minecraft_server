#!/usr/bin/env bash
# uninstall.sh — Remove Minecraft server systemd units
set -euo pipefail

# ── Privilege check ───────────────────────────────────────────────────────────
if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    exit 1
fi

SYSTEMD_DIR="/etc/systemd/system"
INSTALL_TARGET="/opt/minecraft-infra"

UNITS=(
    minecraft.service
    minecraft-backup.service
    minecraft-backup.timer
    minecraft-update.service
    minecraft-update.timer
)

# ── Stop and disable units ────────────────────────────────────────────────────
echo "==> Stopping and disabling units"
for unit in "${UNITS[@]}"; do
    if systemctl is-active --quiet "${unit}" 2>/dev/null; then
        echo "    stopping ${unit}"
        systemctl stop "${unit}" || true
    fi
    if systemctl is-enabled --quiet "${unit}" 2>/dev/null; then
        echo "    disabling ${unit}"
        systemctl disable "${unit}" || true
    fi
done

# ── Remove unit files ─────────────────────────────────────────────────────────
echo "==> Removing unit files from ${SYSTEMD_DIR}/"
for unit in "${UNITS[@]}"; do
    unit_path="${SYSTEMD_DIR}/${unit}"
    if [[ -f "${unit_path}" ]]; then
        rm -f "${unit_path}"
        echo "    removed ${unit}"
    fi
done

# ── Reload systemd ────────────────────────────────────────────────────────────
echo "==> Reloading systemd daemon"
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

# ── Optionally remove symlink ─────────────────────────────────────────────────
if [[ -L "${INSTALL_TARGET}" ]]; then
    read -r -p "==> Remove symlink ${INSTALL_TARGET}? [y/N] " remove_link
    if [[ "${remove_link,,}" == "y" ]]; then
        rm -f "${INSTALL_TARGET}"
        echo "==> Removed ${INSTALL_TARGET}"
    else
        echo "==> Kept ${INSTALL_TARGET}"
    fi
fi

echo ""
echo "Uninstall complete. All Minecraft systemd units have been removed."
