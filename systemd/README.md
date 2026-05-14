# Systemd Units

This directory contains systemd unit files for managing the Minecraft server and its supporting services as a proper system service.

## Units overview

| Unit | Type | Purpose |
|------|------|---------|
| `minecraft.service` | Service | Manages the Docker Compose stack (start / stop / restart) |
| `minecraft-backup.service` | Service (oneshot) | Runs `scripts/backup.sh` on demand or via timer |
| `minecraft-backup.timer` | Timer | Triggers `minecraft-backup.service` daily at 04:00 |
| `minecraft-update.service` | Service (oneshot) | Runs `packwiz/scripts/update-mods.sh` |
| `minecraft-update.timer` | Timer | Triggers `minecraft-update.service` every Monday at 03:00 |

---

## Installation

Run the install script as root from the project directory:

```bash
sudo bash systemd/install.sh
```

The script will:
1. Create a symlink `/opt/minecraft-infra` pointing to your project directory.
2. Copy all `.service` and `.timer` files to `/etc/systemd/system/`.
3. Reload the systemd daemon.
4. Enable `minecraft.service`, `minecraft-backup.timer`, and `minecraft-update.timer`.
5. Start both timers immediately.
6. Optionally start `minecraft.service` right away.

### Prerequisites

- Docker and the `docker compose` plugin installed.
- An `/opt/minecraft-infra/.env` file (or the symlink from step 1 will make the project `.env` available there).

---

## Uninstallation

```bash
sudo bash systemd/uninstall.sh
```

This stops and disables all units, removes the unit files from `/etc/systemd/system/`, reloads the daemon, and optionally removes the `/opt/minecraft-infra` symlink.

---

## Common operations

### Check service status

```bash
systemctl status minecraft.service
```

### Follow live logs

```bash
# Main server logs
journalctl -u minecraft.service -f

# Backup logs
journalctl -u minecraft-backup.service -f

# Mod update logs
journalctl -u minecraft-update.service -f
```

### Start / stop the server

```bash
systemctl start minecraft.service
systemctl stop minecraft.service
systemctl restart minecraft.service
```

### Trigger a manual backup

```bash
systemctl start minecraft-backup.service
```

Check the result:

```bash
journalctl -u minecraft-backup.service --since "5 minutes ago"
```

### Trigger a manual mod update check

```bash
systemctl start minecraft-update.service
```

---

## Timer management

### List all active timers

```bash
systemctl list-timers --all | grep minecraft
```

### Show next scheduled run

```bash
systemctl status minecraft-backup.timer
systemctl status minecraft-update.timer
```

### Disable a timer without uninstalling

```bash
systemctl stop  minecraft-backup.timer
systemctl disable minecraft-backup.timer
```

Re-enable:

```bash
systemctl enable --now minecraft-backup.timer
```

---

## Logs retention

Logs are written to the systemd journal via `SyslogIdentifier`. To search historical logs:

```bash
# All minecraft-related entries from the last 24 hours
journalctl -u minecraft.service -u minecraft-backup.service -u minecraft-update.service --since "24 hours ago"

# Errors only
journalctl -u minecraft.service -p err
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Service fails to start | `journalctl -u minecraft.service -n 50` |
| Docker Compose errors | `journalctl -u minecraft.service -n 50 --no-pager` |
| `.env` not found | Verify `/opt/minecraft-infra/.env` exists (or the symlink is correct) |
| Backup not running | `systemctl status minecraft-backup.timer` and check `Persistent=true` |
| Timer not firing | Ensure `systemctl start minecraft-backup.timer` has been run after install |
