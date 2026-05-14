# minecraft-infra — Modded Fabric Server Infrastructure

A fully automated, Docker-based Minecraft server infrastructure for a modded Fabric 1.20.1 pack. Includes server orchestration, automated backups, client installation helpers, health monitoring, and Telegram notifications — all wired together through a single Makefile.

![Minecraft 1.20.1](https://img.shields.io/badge/Minecraft-1.20.1-brightgreen)
![Fabric 0.15.11](https://img.shields.io/badge/Fabric-0.15.11-blue)
![Docker](https://img.shields.io/badge/Docker-Compose%20v2-2496ED)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Server Host                            │
│                                                                 │
│  systemd (minecraft.service)                                    │
│    └── docker compose  (server/docker-compose.yml)             │
│          ├── minecraft  (itzg/minecraft-server, Fabric 1.20.1) │
│          │     ├── :25565  game port (exposed to players)       │
│          │     └── RCON :25575  (internal only)                 │
│          ├── healthcheck-sidecar  :8080                         │
│          │     └── GET /health → JSON status (RCON-backed)      │
│          └── telegram-bot  (docker profile: telegram)           │
│                └── polls healthcheck every 60 s                 │
│                      sends alerts on state transitions          │
│                      responds to /status /players /backup       │
│                                                                 │
│  backups/ ← scripts/backup.sh                                  │
│               triggered by minecraft-backup.timer (04:00 daily)│
│               14-day rolling retention                          │
│                                                                 │
│  minecraft-update.timer → packwiz refresh (Mon 03:00)          │
└─────────────────────────────────────────────────────────────────┘
        ↕ :25565                       ↕ Telegram API
┌──────────────────────┐     ┌──────────────────────────────────┐
│   Minecraft Client   │     │   Telegram (phone / desktop)     │
│   Prism Launcher     │     │   /status  /players  /backup     │
│   packwiz auto-sync  │     └──────────────────────────────────┘
│   (Linux/Win/macOS)  │
└──────────────────────┘
```

### Component summary

| Component | Image / source | Purpose |
|-----------|---------------|---------|
| `minecraft` | `itzg/minecraft-server` | Runs the Fabric server |
| `healthcheck-sidecar` | `healthcheck/` | HTTP `/health` endpoint backed by RCON |
| `telegram-bot` | `telegram-bot/` | Proactive alerts + bot commands |
| `backup.sh` | `scripts/` | World backup with RCON save-pause |
| `restore.sh` | `scripts/` | Interactive or scripted restore |
| packwiz | `packwiz/` | Mod pack definition synced to clients |

---

## Prerequisites

### Server
- Linux host with systemd (for autostart)
- Docker 24+ and Docker Compose v2 (`docker compose` subcommand)
- Git

### Clients (players)
- [Prism Launcher](https://prismlauncher.org) (any platform)
- Java 17 or newer

---

## Quick Start — Server

```bash
# 1. Clone the repository
git clone <repo-url> minecraft-infra
cd minecraft-infra

# 2. Create your .env from the template and fill in secrets
make setup
$EDITOR .env

# 3. Start the server stack
make up

# 4. Verify the server is healthy
make health

# 5. (Optional) Install systemd autostart units
make install-systemd
```

The server will be reachable at `<host-ip>:25565`.

---

## Quick Start — Client

### Linux

```bash
bash scripts/install-client-linux.sh
```

The script detects or installs Prism Launcher (Flatpak, Snap, or native), verifies Java 17+, and creates a pre-configured Fabric 1.20.1 instance. On first launch packwiz automatically downloads all mods.

### Windows

Right-click `scripts/install-client-windows.ps1` and choose **Run with PowerShell**.  
If execution policy blocks it, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-client-windows.ps1
```

A folder-picker dialog asks where to install the instance. Prism Launcher is detected or downloaded automatically. Java 17 is verified; a link to Adoptium Temurin is offered if it is missing.

### macOS

```bash
bash scripts/install-client-macos.sh
```

The script opens a native macOS folder picker (via `osascript`), verifies Prism Launcher in `~/Applications` or `/Applications`, checks Java 17 via `/usr/libexec/java_home`, and creates the instance. A macOS notification confirms completion.

After any platform install:
1. Open Prism Launcher.
2. Find the instance named **Minecraft Infra Pack 1.20.1**.
3. Click **Launch** — packwiz fetches all mod JARs on first run.

---

## Configuration (.env)

Copy `.env.example` to `.env` (`make setup`) and edit the values below.

| Variable | Default | Description |
|----------|---------|-------------|
| `MINECRAFT_VERSION` | `1.20.1` | Minecraft release version |
| `FABRIC_LOADER_VERSION` | `0.15.11` | Fabric loader version |
| `FABRIC_INSTALLER_VERSION` | `1.0.1` | Fabric installer version |
| `SERVER_MEMORY_MIN` | `2G` | JVM minimum heap (`-Xms`) |
| `SERVER_MEMORY_MAX` | `8G` | JVM maximum heap (`-Xmx`) |
| `SERVER_PORT` | `25565` | Minecraft game port (host-facing) |
| `RCON_PORT` | `25575` | RCON port (host-facing) |
| `RCON_PASSWORD` | `change_me_rcon_pass` | RCON password — **change this** |
| `HEALTHCHECK_PORT` | `8080` | Health endpoint port (host-facing) |
| `TELEGRAM_BOT_TOKEN` | _(empty)_ | Token from @BotFather |
| `TELEGRAM_CHAT_ID` | _(empty)_ | Chat/group ID for notifications |
| `BACKUP_RETENTION_DAYS` | `14` | Days to keep backup archives |
| `BACKUP_DIR` | `./backups` | Directory for backup archives |
| `TZ` | `UTC` | Container timezone |
| `COMPOSE_PROJECT_NAME` | `minecraft-server` | Docker Compose project name |
| `ENABLE_TELEGRAM` | `true` | Reserved flag (use `COMPOSE_PROFILES`) |
| `ENABLE_MONITORING` | `false` | Reserved flag for future monitoring |

> **Never commit `.env` to version control.** It is listed in `.gitignore`.

---

## Makefile Reference

Run `make help` to print all targets with descriptions.

| Target | Description |
|--------|-------------|
| `make up` | Start the server stack in detached mode |
| `make down` | Stop and remove containers |
| `make restart` | Restart all containers |
| `make logs` | Follow the `minecraft` container logs |
| `make logs-all` | Follow logs for all containers |
| `make status` | Show container status and health URL |
| `make pull` | Pull latest Docker images |
| `make backup` | Create a timestamped world backup |
| `make restore` | Interactive backup picker and restore |
| `make restore BACKUP=<file>` | Restore a specific backup file |
| `make health` | Query the healthcheck endpoint (pretty-printed JSON) |
| `make rcon CMD="<cmd>"` | Send an RCON command, e.g. `make rcon CMD="say hello"` |
| `make shell` | Open a bash shell inside the `minecraft` container |
| `make update-mods` | Run the packwiz mod update script |
| `make packwiz-refresh` | Refresh the packwiz index only |
| `make setup` | Copy `.env.example` → `.env` if absent, print next steps |
| `make install-systemd` | Install systemd service and timer units (requires sudo) |
| `make install-client-linux` | Run the Linux client installer |
| `make build` | Rebuild Docker images without cache |
| `make deploy` | `pull` → `down` → `up` → tail logs 10 s (full redeploy) |
| `make clean` | Remove stopped containers and prune unused images |
| `make clean-backups` | Delete backups older than `BACKUP_RETENTION_DAYS` |
| `make help` | Show this target list |

---

## Mod Management

Mods are defined in `packwiz/mods/*.pw.toml`. The packwiz index (`packwiz/index.toml`) tracks all mod files. Clients receive mod updates automatically on every Prism Launcher launch via the packwiz bootstrap hook.

### Adding a mod

1. Find the mod on [Modrinth](https://modrinth.com) and note the `mod-id` and `version` slug.
2. Create `packwiz/mods/<modname>.pw.toml`:

```toml
name = "Mod Display Name"
filename = "mod-filename-1.0.0-fabric.jar"
side = "both"   # or "client" or "server"

[download]
url = "https://cdn.modrinth.com/data/<mod-id>/versions/<version>/<filename>"
hash-format = "sha256"
hash = "<sha256-of-jar>"

[update]
[update.modrinth]
    mod-id = "<mod-id>"
    version = "<version>"
```

3. Run `make packwiz-refresh` (updates `index.toml`).
4. Commit both the new `.pw.toml` and the updated `index.toml`.

### Removing a mod

1. Delete the corresponding `.pw.toml` file from `packwiz/mods/`.
2. Run `make packwiz-refresh`.
3. Commit the deletions and updated `index.toml`.

### Updating all mods

```bash
make update-mods
```

This runs `packwiz/scripts/update-mods.sh`, which calls `packwiz update --all` and refreshes the index. Review and commit the changes.

### Mod list

| Mod Name | Side | Purpose | Modrinth ID |
|----------|------|---------|-------------|
| Fabric API | both | Core Fabric mod library | `P7dR8mSH` |
| Architectury API | both | Cross-loader API layer | `lhGA9TYQ` |
| Cloth Config API | both | Configuration screen library | `9s6osm5g` |
| Modern Industrialization | both | Tech/industrial progression | `IEPAK5x6` |
| Create Fabric | both | Rotational mechanics and contraptions | `Xbc0uyRg` |
| Create: Steam 'n' Rails | both | Train and rail expansion for Create | `ZzjhlDgM` |
| Applied Energistics 2 | both | Item storage and autocrafting network | `XxWD5pD3` |
| Pipez | both | Item, fluid, and energy pipes | `e6UzDPNM` |
| Integrated Dynamics | both | Logic and automation network | `E4mKHD0r` |
| MineColonies | both | NPC colony builder | `UELeoord` |
| Structurize | both | Structure placement library (MineColonies dep) | `Ln1mcrOm` |
| Chipped | both | Decorative block variants | `oZ7KFGip` |
| Supplementaries | both | Functional decorative blocks | `jwdMSMnm` |
| Macaw's Bridges | both | Buildable bridge blocks | `BckMi1LP` |
| Macaw's Furniture | both | Furniture blocks | `9IQrlCmU` |
| Macaw's Windows | both | Decorative windows | `uh5ynCnb` |
| Macaw's Doors | both | Decorative door variants | `PQ3Mocy9` |
| Farmer's Delight (Fabric) | both | Farming and cooking expansion | `MXAnMBkQ` |
| Terralith | both | World-gen overhaul with new biomes | `8oi3bsk5` |
| Roughly Enough Items (REI) | both | In-game item/recipe browser | `nfn13YXA` |
| JourneyMap | both | In-game minimap and full-screen map | `lfHFW1mp` |
| Inventory Profiles Next | both | Inventory sorting and management | `O7RBXm3n` |
| Mouse Tweaks | both | Improved mouse interactions in inventory | `aC3cM3Vq` |
| Sodium | client | High-performance rendering engine | `AANobbMI` |
| Iris Shaders | client | Shader support (works with Sodium) | `YL57xq9U` |
| Litematica | client | Schematic viewer and builder | `dMEFMghe` |
| WorldEdit CUI | client | Visual overlay for WorldEdit selections | `HEi11K9s` |
| Effortless Building | client | Extended placement tools | `7oc4vlUz` |

---

## Backup & Restore Guide

### Automatic backups

The `minecraft-backup.timer` systemd unit runs `scripts/backup.sh` daily at **04:00** with up to 5 minutes of random jitter. Backups are stored in `backups/` (gitignored) and rotated after `BACKUP_RETENTION_DAYS` days (default 14).

The script:
1. Sends `save-off` and `save-all` via RCON to flush the world to disk cleanly.
2. Archives `server/world`, `server/config`, and `packwiz/` using zstd (falls back to gzip).
3. Resumes autosave with `save-on`.
4. Deletes archives older than the retention window.

### Manual backup

```bash
make backup
# or directly:
./scripts/backup.sh
# dry-run (prints what would happen, writes nothing):
./scripts/backup.sh --dry-run
```

### Listing backups

```bash
./scripts/restore.sh --list
```

### Restoring a backup

```bash
# Interactive picker (shows numbered list, prompts for confirmation):
make restore

# Restore a specific archive:
make restore BACKUP=backups/backup_2024-01-15_04-00-00.tar.zst

# Skip all prompts (for scripted use):
./scripts/restore.sh --force backups/backup_2024-01-15_04-00-00.tar.zst
```

The restore script:
1. Stops the running Minecraft container if one is detected.
2. Creates a pre-restore safety snapshot of the current world.
3. Extracts the chosen archive to a temp directory.
4. Moves `server/world`, `server/config`, and `packwiz/` into place.

After restoring, start the server again with `make up`.

---

## Telegram Bot Setup

The Telegram bot is an optional Docker Compose profile (`telegram`). It polls the healthcheck service every 60 seconds and sends proactive alerts when the server comes online or goes offline.

**Available bot commands:**

| Command | Description |
|---------|-------------|
| `/start` | Show help and available commands |
| `/status` | Current server status (online/offline, player count) |
| `/players` | List currently online players |
| `/backup` | Trigger a world backup from Telegram |

**Setup steps:**

1. Open Telegram and message **@BotFather**. Send `/newbot` and follow the prompts. Copy the API token.
2. Get your chat ID: message **@userinfobot** — it replies with your numeric user or group ID.
3. Add both values to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456789:ABCDEFabcdef...
   TELEGRAM_CHAT_ID=-1001234567890
   ```
4. Start the stack with the `telegram` profile enabled:
   ```bash
   COMPOSE_PROFILES=telegram make up
   ```

The bot sends a startup notification when its container starts and a shutdown notification when it stops gracefully.

---

## Health Endpoint

The `healthcheck-sidecar` container exposes two HTTP endpoints:

### `GET /health`

Returns cached server status. HTTP 200 when online, HTTP 503 when offline or starting.

```bash
curl http://localhost:8080/health
```

Example response:

```json
{
  "status": "online",
  "uptime_seconds": 3742,
  "players_online": 3,
  "players_max": 20,
  "version": "unknown",
  "motd": "",
  "timestamp": "2024-01-15T09:42:00Z"
}
```

`status` values:
- `online` — RCON responding, server accepting players
- `starting` — game port reachable but RCON not yet available
- `offline` — game port unreachable

### `GET /ping`

Liveness probe, always returns HTTP 200 as long as the sidecar process is alive:

```json
{"alive": true}
```

The sidecar polls the Minecraft server via RCON every 30 seconds. It retries failed RCON calls up to 3 times before marking the server as `offline` or `starting`.

---

## Systemd Integration

The `systemd/` directory contains units that manage the Docker Compose stack as a system service. The repo is symlinked to `/opt/minecraft-infra` by the installer.

### Install

```bash
make install-systemd
# equivalent to: sudo systemd/install.sh
```

The install script:
1. Creates `/opt/minecraft-infra` → `<project-dir>` symlink.
2. Copies all `.service` and `.timer` files to `/etc/systemd/system/`.
3. Runs `systemctl daemon-reload`.
4. Enables and starts `minecraft.service`, `minecraft-backup.timer`, and `minecraft-update.timer`.
5. Prompts whether to start `minecraft.service` immediately.

### Uninstall

```bash
sudo systemd/uninstall.sh
```

Stops and disables all units, removes unit files, reloads systemd.

### Installed units

| Unit | Type | Schedule / trigger |
|------|------|--------------------|
| `minecraft.service` | Service | Started by systemd on boot; manages `docker compose up/down` |
| `minecraft-backup.service` | Service | Oneshot — runs `scripts/backup.sh` |
| `minecraft-backup.timer` | Timer | Daily at 04:00 (± up to 5 min jitter) |
| `minecraft-update.service` | Service | Oneshot — runs packwiz mod update |
| `minecraft-update.timer` | Timer | Every Monday at 03:00 (± up to 10 min jitter) |

### Useful commands

```bash
# Service status
systemctl status minecraft.service

# Follow service logs
journalctl -u minecraft.service -f

# Trigger a backup immediately
systemctl start minecraft-backup.service

# Follow backup logs
journalctl -u minecraft-backup.service -f

# List active timers
systemctl list-timers --all | grep minecraft

# Stop the server
systemctl stop minecraft.service

# Prevent autostart on boot
systemctl disable minecraft.service
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Server containers won't start | Missing `.env` or Docker not running | Run `make setup`; verify `docker info` works |
| Server uses too much memory / OOM killed | `SERVER_MEMORY_MAX` too high for the host | Lower `SERVER_MEMORY_MAX` in `.env` |
| Mods not loading on client | packwiz bootstrap not configured in instance | Re-run the client installer for your platform |
| RCON connection refused | Wrong `RCON_PASSWORD` or RCON port not open | Verify `RCON_PASSWORD` in `.env` matches the container; check `SERVER_PORT`/`RCON_PORT` |
| `make health` returns 503 | Server is starting up or offline | Wait for the start period (up to 2 minutes); check `make logs` |
| Backup fails with permission error | `BACKUP_DIR` not writable | `mkdir -p backups && chmod 755 backups` |
| Telegram bot sends no messages | Wrong token/chat ID, or `telegram` profile not active | Verify `.env` values; start with `COMPOSE_PROFILES=telegram make up` |
| Restore leaves world corrupted | Server was still running during restore | Always stop the server first; the restore script warns and prompts |
| `make install-systemd` fails | Not running as root | Run with `sudo` or use `make install-systemd` which prepends `sudo` automatically |
| Weekly mod update breaks the pack | A mod incompatibility after `packwiz update --all` | Roll back `packwiz/mods/*.pw.toml` via git; pin the offending mod version |

---

## Security Considerations

- **Never commit `.env`** — it contains your RCON password and Telegram token. It is in `.gitignore`.
- **Change `RCON_PASSWORD`** from the default (`change_me_rcon_pass`) before first launch.
- **Restrict the RCON port** (25575) at the firewall level so it is only reachable from `localhost`. The game port (25565) is the only port that needs to be publicly accessible.
- **Do not expose the healthcheck port** (8080) publicly in production unless it is behind authentication. It reveals player counts and server uptime.
- The `telegram-bot` container has access to the RCON password. Treat the Telegram bot token with the same care as a password.
- Backup archives may contain world data; restrict read access to `backups/` accordingly (`chmod 700 backups/`).

---

## Repository Layout

```
minecraft-infra/
├── packwiz/            # Mod pack definition (packwiz format)
│   ├── pack.toml       # Pack metadata (name, MC version, Fabric version)
│   ├── index.toml      # File index with SHA-256 hashes
│   └── mods/           # One .pw.toml per mod
├── server/             # Docker Compose stack
│   ├── docker-compose.yml
│   └── config/         # Server config files copied into /data on startup
├── scripts/            # Shell / PowerShell automation
│   ├── backup.sh
│   ├── restore.sh
│   ├── rcon.sh
│   ├── install-client-linux.sh
│   ├── install-client-macos.sh
│   └── install-client-windows.ps1
├── systemd/            # Systemd unit files and install/uninstall scripts
│   ├── minecraft.service
│   ├── minecraft-backup.service / .timer
│   ├── minecraft-update.service / .timer
│   ├── install.sh
│   └── uninstall.sh
├── telegram-bot/       # Python Telegram notification bot
│   ├── bot.py
│   ├── Dockerfile
│   └── requirements.txt
├── healthcheck/        # Flask HTTP health endpoint
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── backups/            # Backup archives (gitignored)
├── Makefile            # Orchestration layer
├── .env.example        # Configuration template
├── .gitignore
└── AGENTS.md           # AI agent file ownership map
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
