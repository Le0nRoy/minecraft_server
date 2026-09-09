# scripts/

Utility scripts for managing the Minecraft server and setting up clients.

## backup.sh

Creates a timestamped, compressed backup of the server world, configuration, and mod definitions.

**What is backed up:**
- `server/world/` — the live Minecraft world
- `server/config/` — server configuration files
- `packwiz/` — mod pack definitions
- `.env.example` — environment variable template

**Usage:**

```bash
# Normal backup
./scripts/backup.sh

# Show what would be backed up without writing anything
./scripts/backup.sh --dry-run
```

**Environment variables** (set in `.env` or exported):

| Variable | Default | Description |
|---|---|---|
| `BACKUP_DIR` | `./backups` | Directory where backups are stored |
| `BACKUP_RETENTION_DAYS` | `14` | Delete backups older than this many days |
| `RCON_PASSWORD` | — | RCON password (enables save-off/save-all before backup) |
| `RCON_PORT` | `25575` | RCON port |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token for failure alerts |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID for failure alerts |

**Backup naming:** `backup_YYYY-MM-DD_HH-MM-SS.tar.zst` (falls back to `.tar.gz` if `zstd` is not installed).

**RCON behaviour:** If RCON is reachable, the script sends `save-off` and `save-all` before archiving, waits 5 seconds for the flush, then sends `save-on` after the archive is complete. If RCON is not available the backup still runs — it just does not pause autosave first.

---

## restore.sh

Restores a backup to the project directory, with safety checks.

**Usage:**

```bash
# List available backups
./scripts/restore.sh --list

# Interactive restore (select from numbered list)
./scripts/restore.sh

# Restore a specific backup file
./scripts/restore.sh backups/backup_2024-01-01_12-00-00.tar.zst

# Skip all confirmation prompts (for automation)
./scripts/restore.sh --force backups/backup_2024-01-01_12-00-00.tar.zst
```

**What the script does:**

1. Lists available backups (newest first).
2. If the Minecraft container is running, warns the user and asks for confirmation before stopping it.
3. Creates a pre-restore safety snapshot of the current world in `backups/pre-restore-TIMESTAMP/`.
4. Extracts the selected backup to a temporary directory.
5. Moves `world/`, `config/`, and `packwiz/` from the extracted archive into their correct locations.
6. Prints instructions to restart the server.

**Flags:**

| Flag | Description |
|---|---|
| `--list` | List available backups and exit |
| `--force` | Skip all `yes`/`no` confirmation prompts |

---

## rcon.sh

Thin helper to send a single RCON command to the running server.

**Usage:**

```bash
./scripts/rcon.sh list
./scripts/rcon.sh "say Server restarting in 5 minutes"
./scripts/rcon.sh "op PlayerName"
./scripts/rcon.sh "whitelist add PlayerName"
```

**Requires** `RCON_PASSWORD` to be set (in `.env` or as an environment variable).

**Method priority:**

1. `mcrcon` CLI — if installed and on `PATH`
2. `docker exec <container> rcon-cli` — if Docker is running and the Minecraft container is up

If neither is available the script exits with an error and prints installation hints.

---

## install-client-linux.sh / install-client-macos.sh / install-client-windows.ps1

One-shot installer scripts that set up a PolyMC instance pre-configured with the modpack.
**No Microsoft account is required** — PolyMC supports offline accounts natively, matching
the server's `ONLINE_MODE=false` configuration.

### What the scripts do

1. Locate (or offer to install) PolyMC.
2. Verify (or offer to install) Java 21+.
3. Download `packwiz-installer-bootstrap.jar`.
4. Create a NeoForge 1.21.1 instance directly inside PolyMC's `instances/` directory.
5. Configure the packwiz pre-launch hook so mods sync on every launch.

### Usage

**Linux:**

```bash
bash scripts/install-client-linux.sh
```

**macOS:**

```bash
bash scripts/install-client-macos.sh
```

**Windows** (PowerShell 5.1+, ships with Windows 10/11):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-client-windows.ps1
```

Or double-click `scripts\install-client-windows.bat`.

### Connecting to the server (offline mode)

The server runs with `ONLINE_MODE=false` — no Mojang/Microsoft account is needed.

1. Open PolyMC after installation.
2. Add an offline account: **Accounts** (top-right) → **Add Offline** → enter any username.
3. Select the `Minecraft Infra Pack 1.21.1 (NeoForge)` instance and click **Launch**.
4. Once in-game, open **Multiplayer** → **Add Server**, enter the server address, and connect.

### Environment overrides

| Variable | Script | Description |
|---|---|---|
| `POLYMC_DIR` | Linux | Override auto-detection of PolyMC data directory |

---

## Prerequisites

| Tool | Required by | Install |
|---|---|---|
| `tar` | backup.sh, restore.sh | pre-installed on all Linux distros |
| `zstd` | backup.sh (optional) | `apt install zstd` / `pacman -S zstd` |
| `docker` | restore.sh, rcon.sh | https://docs.docker.com/get-docker/ |
| `mcrcon` | rcon.sh (optional) | https://github.com/Tiiffi/mcrcon |
| PolyMC | install-client-*.sh/ps1 | https://polymc.org/download/ |
| Java 21+ | install-client-*.sh/ps1 | https://adoptium.net/temurin/releases/?version=21 |
