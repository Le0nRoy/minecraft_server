# minecraft-infra — Modded NeoForge Server Infrastructure

A fully automated, Docker-based Minecraft server infrastructure for a modded NeoForge 1.21.1 pack. Includes server orchestration, automated backups, client installation helpers, health monitoring, and Telegram notifications — all wired together through a single Makefile.

![Minecraft 1.21.1](https://img.shields.io/badge/Minecraft-1.21.1-brightgreen)
![NeoForge 21.1.244](https://img.shields.io/badge/NeoForge-21.1.244-blue)
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
│          ├── minecraft  (itzg/minecraft-server, NeoForge 1.21.1)│
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
| `minecraft` | `itzg/minecraft-server` | Runs the NeoForge server |
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
- Java 21 or newer

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

The pack targets **NeoForge 1.21.1** and needs **Java 21+** on the client (not 17 — NeoForge 21.1.x requires 21). Prism Launcher is required.

All three installer scripts now:
- Detect Prism Launcher, or offer to install it automatically if missing.
- Detect Java 21+, or offer to install it automatically if missing/too old (via the official Adoptium Temurin installer on Windows/macOS, or your system package manager on Linux).
- Locate Prism Launcher's **real** instances directory and create the instance directly inside it — no manual folder picking, no zip import, no copying files around. A folder picker only appears as a last-resort fallback if the instances directory genuinely can't be determined.

### Don't have the repo cloned? You don't need it.

All three installer scripts are self-contained (every URL inside them is absolute), so anyone can run them straight from GitHub without cloning anything.

**Windows** — pick whichever you prefer:

- **One-liner**: open PowerShell and run:
  ```powershell
  iex (irm https://raw.githubusercontent.com/Le0nRoy/minecraft_server/neoforge-1.21.1-migration/scripts/install-client-windows.ps1)
  ```
  This downloads and runs the script entirely in memory — nothing is saved to disk, so there's no risk of the "access denied" error you'd get trying to save a file into a protected folder like `C:\Windows\System32`.
- **Double-click**: download [`install-client-windows.bat`](scripts/install-client-windows.bat) and double-click it. Explorer normally can't run `.ps1` files directly — double-clicking one (or using "Run with PowerShell") skips the `-ExecutionPolicy Bypass` flag, hits the default Restricted execution policy, and the window closes instantly with an error before you can read it. This `.bat` fetches `install-client-windows.ps1` fresh from GitHub and runs it with the right flags, keeping the window open.

**Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/Le0nRoy/minecraft_server/neoforge-1.21.1-migration/scripts/install-client-linux.sh | bash
```

**macOS**
```bash
curl -fsSL https://raw.githubusercontent.com/Le0nRoy/minecraft_server/neoforge-1.21.1-migration/scripts/install-client-macos.sh | bash
```

### If you do have the repo

Linux:
```bash
bash scripts/install-client-linux.sh
```
Detects or installs Prism Launcher (Flatpak, Snap, or native); detects or installs Java 21+ via `apt`/`dnf`/`pacman`/Flatpak (asks for `sudo` where needed); creates the instance directly inside Prism's detected data directory. On first launch packwiz automatically downloads all mods.

Windows — double-click `scripts/install-client-windows.bat`, or from a PowerShell prompt:
```powershell
powershell -NoExit -ExecutionPolicy Bypass -File scripts\install-client-windows.ps1
```
Detects or installs Prism Launcher; detects or installs Java 21 (downloads the latest Temurin MSI from Adoptium and runs it silently, with your confirmation first); locates `%APPDATA%\PrismLauncher\instances` (or the portable install's own `instances/` folder, if detected) and creates the instance there directly.

macOS:
```bash
bash scripts/install-client-macos.sh
```
Detects or installs Prism Launcher (via Homebrew if available, or points you to the download page); detects or installs Java 21 (Homebrew cask, or the official Adoptium `.pkg` installer via `sudo installer`); locates `~/Library/Application Support/PrismLauncher/instances` and creates the instance there directly. A macOS notification confirms completion.

### If the instances directory can't be auto-detected

This is a fallback path, not the normal one — all three scripts should locate Prism's real instances directory on their own. If it ever fails, you'll be asked to pick a folder yourself; in that case, **don't** use "Add Instance → Import from zip or folder" on the result (that dialog expects a zip archive and will just show an empty result). Instead:

1. Open Prism Launcher.
2. In the main window, open the folder view for your instances — click the **Instances** icon on the top toolbar, then **View Instance Folder** (localized builds: **"Экземпляры"** → **"Папки"**). This opens the real instances directory in your file browser.
3. Copy the whole folder the script created (e.g. `minecraft-infra-pack`) into that instances directory.
4. Restart Prism Launcher (or just refresh) — the instance appears in the list on its own.
5. Select it and click **Launch**. `.minecraft` will look empty right up until this point — that's normal, packwiz populates `mods/` automatically as part of launching, right before Minecraft itself starts.

### Uninstalling (Windows)

The Windows installer writes `uninstall.bat` and `uninstall.ps1` directly into the instance folder it creates. Double-click `uninstall.bat` inside that folder to remove the modpack:

- Asks for confirmation before deleting anything.
- Separately asks (in Russian, matching the rest of the installer's target audience) whether to also uninstall the Java 21 (Eclipse Temurin) that was installed for this modpack — answer no if Java is used by anything else on the machine.
- Deletes the whole instance folder (world saves, configs, mods — everything).

If you installed before this feature existed, grab both files from the repo and save them — with these exact names — inside your existing instance folder:
```powershell
$dir = "$env:APPDATA\PrismLauncher\instances\minecraft-infra-pack"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/Le0nRoy/minecraft_server/neoforge-1.21.1-migration/scripts/uninstall-windows.ps1" -OutFile "$dir\uninstall.ps1"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/Le0nRoy/minecraft_server/neoforge-1.21.1-migration/scripts/uninstall-windows.bat" -OutFile "$dir\uninstall.bat"
```

---

## Configuration (.env)

Copy `.env.example` to `.env` (`make setup`) and edit the values below.

| Variable | Default | Description |
|----------|---------|-------------|
| `MINECRAFT_VERSION` | `1.21.1` | Minecraft release version |
| `NEOFORGE_VERSION` | `21.1.244` | NeoForge loader version |
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

40 mods total. Generated from `packwiz/mods/*.pw.toml` — regenerate this table from there if it drifts, don't hand-edit it back out of sync.

| Mod Name | Side | Purpose | Source | ID |
|----------|------|---------|--------|-----|
| Applied Energistics 2 | both | Item storage and autocrafting network | Modrinth | `XxWD5pD3` |
| Architectury API | both | Cross-loader API layer | Modrinth | `lhGA9TYQ` |
| Athena | both | Connected textures library (Chipped dep) | Modrinth | `b1ZV3DIJ` |
| BlockUI | both | UI library (MineColonies dep) | CurseForge | `522992` |
| Chipped | both | Decorative block variants | Modrinth | `BAscRYKm` |
| Cloth Config API | both | Configuration screen library | Modrinth | `9s6osm5g` |
| Common Capabilities | both | Capability library (Integrated Dynamics dep) | Modrinth | `oFXrCkDI` |
| Create | both | Rotational mechanics and contraptions | Modrinth | `LNytGWDc` |
| Cyclops Core | both | Core library (Integrated Dynamics dep) | Modrinth | `Z9DM0LJ4` |
| Domum Ornamentum | both | Building block library (MineColonies dep) | CurseForge | `527361` |
| Effortless Building | client | Extended placement tools | Modrinth | `DYtfQEYj` |
| Farmer's Delight | both | Farming and cooking expansion | Modrinth | `R2OftAxM` |
| GuideME | both | In-game guidebook library (AE2 / Modern Industrialization dep) | Modrinth | `Ck4E7v7R` |
| Integrated Dynamics | both | Logic and automation network | Modrinth | `yYzdQHJI` |
| Inventory Profiles Next | both | Inventory sorting and management | Modrinth | `O7RBXm3n` |
| Iris Shaders | client | Shader support (works with Sodium) | Modrinth | `YL57xq9U` |
| JourneyMap | both | In-game minimap and full-screen map | Modrinth | `lfHFW1mp` |
| Kotlin for Forge | both | Kotlin runtime library (Inventory Profiles Next dep) | Modrinth | `ordsPcFz` |
| Lithostitched | both | World-gen datapack library (Terralith dep) | Modrinth | `XaDC71GB` |
| Macaw's Bridges | both | Buildable bridge blocks | Modrinth | `GURcjz8O` |
| Macaw's Doors | both | Decorative door variants | Modrinth | `kNxa8z3e` |
| Macaw's Furniture | both | Furniture blocks | Modrinth | `dtWC90iB` |
| Macaw's Windows | both | Decorative windows | Modrinth | `C7I0BCni` |
| MineColonies | both | NPC colony builder | CurseForge | `245506` |
| Modern Industrialization | both | Tech/industrial progression | Modrinth | `Gov5Dboq` |
| Moonlight Lib | both | Shared library (Supplementaries dep) | Modrinth | `twkfQtEc` |
| Mouse Tweaks | both | Improved mouse interactions in inventory | Modrinth | `aC3cM3Vq` |
| Multi Piston | both | Piston extension library (MineColonies dep) | CurseForge | `303278` |
| Pipez | both | Item, fluid, and energy pipes | Modrinth | `iRmWy6ga` |
| Resourceful Lib | both | Shared library (Chipped dep) | Modrinth | `G1hIVOrD` |
| Roughly Enough Items (REI) | both | In-game item/recipe browser | Modrinth | `nfn13YXA` |
| Sodium | client | High-performance rendering engine | Modrinth | `AANobbMI` |
| Sodium Dynamic Lights | client | Dynamic light sources from held/dropped items | Modrinth | `PxQSWIcD` |
| Sodium Extra | client | Additional Sodium video options and QoL | Modrinth | `PtjYWJkn` |
| Structurize | both | Structure placement library (MineColonies dep) | CurseForge | `298744` |
| Supplementaries | both | Functional decorative blocks | Modrinth | `fFEIiSDQ` |
| Terralith | both | World-gen overhaul with new biomes | Modrinth | `8oi3bsk5` |
| WorldEdit | both | World editing tool for builders | Modrinth | `1u6JkXh5` |
| WorldEdit CUI (Unofficial Forge Port) | client | Visual overlay for WorldEdit selections | Modrinth | `lOELapP1` |
| libIPN | both | Library for Inventory Profiles Next | Modrinth | `onSQdWhM` |

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
│   ├── pack.toml       # Pack metadata (name, MC version, NeoForge version)
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
│   ├── install-client-windows.ps1
│   └── install-client-windows.bat
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
