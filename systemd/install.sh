#!/usr/bin/env bash
# install.sh — Install Minecraft server systemd units
set -euo pipefail

# ── Privilege check ───────────────────────────────────────────────────────────
if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    exit 1
fi

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_TARGET="/opt/minecraft-infra"
SYSTEMD_DIR="/etc/systemd/system"

echo "==> Project directory: ${PROJECT_DIR}"
echo "==> Install target:    ${INSTALL_TARGET}"

# ── Create /opt/minecraft-infra symlink ───────────────────────────────────────
if [[ -L "${INSTALL_TARGET}" ]]; then
    echo "==> Updating existing symlink ${INSTALL_TARGET} -> ${PROJECT_DIR}"
    ln -sfn "${PROJECT_DIR}" "${INSTALL_TARGET}"
elif [[ -e "${INSTALL_TARGET}" ]]; then
    echo "WARNING: ${INSTALL_TARGET} exists and is not a symlink." >&2
    read -r -p "Remove it and create a symlink? [y/N] " confirm
    if [[ "${confirm,,}" == "y" ]]; then
        rm -rf "${INSTALL_TARGET}"
        ln -s "${PROJECT_DIR}" "${INSTALL_TARGET}"
        echo "==> Created symlink ${INSTALL_TARGET} -> ${PROJECT_DIR}"
    else
        echo "Skipping symlink creation. Unit files will still be installed."
    fi
else
    ln -s "${PROJECT_DIR}" "${INSTALL_TARGET}"
    echo "==> Created symlink ${INSTALL_TARGET} -> ${PROJECT_DIR}"
fi

# ── Copy unit files ───────────────────────────────────────────────────────────
echo "==> Copying unit files to ${SYSTEMD_DIR}/"
for unit_file in "${SCRIPT_DIR}"/*.service "${SCRIPT_DIR}"/*.timer; do
    [[ -f "${unit_file}" ]] || continue
    unit_name="$(basename "${unit_file}")"
    cp "${unit_file}" "${SYSTEMD_DIR}/${unit_name}"
    chmod 644 "${SYSTEMD_DIR}/${unit_name}"
    echo "    installed ${unit_name}"
done

# ── Reload systemd ────────────────────────────────────────────────────────────
echo "==> Reloading systemd daemon"
systemctl daemon-reload

# ── Enable units ──────────────────────────────────────────────────────────────
echo "==> Enabling units"
systemctl enable minecraft.service
systemctl enable minecraft-backup.timer
systemctl enable minecraft-update.timer

# Start timers immediately so they are active without a reboot
systemctl start minecraft-backup.timer
systemctl start minecraft-update.timer

# ── Optionally start the main service ─────────────────────────────────────────
read -r -p "==> Start minecraft.service now? [y/N] " start_now
if [[ "${start_now,,}" == "y" ]]; then
    echo "==> Starting minecraft.service …"
    systemctl start minecraft.service
    systemctl status minecraft.service --no-pager
else
    echo "==> Skipped. Start later with: systemctl start minecraft.service"
fi

# ── Post-install instructions ─────────────────────────────────────────────────
cat <<'EOF'

Installation complete.

Useful commands
---------------
  Check service status:   systemctl status minecraft.service
  Follow service logs:    journalctl -u minecraft.service -f
  Trigger backup now:     systemctl start minecraft-backup.service
  Follow backup logs:     journalctl -u minecraft-backup.service -f
  List active timers:     systemctl list-timers --all | grep minecraft
  Stop the server:        systemctl stop minecraft.service
  Disable autostart:      systemctl disable minecraft.service

EOF
