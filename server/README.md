# Server

Docker Compose stack for the Minecraft NeoForge 1.21.1 server.

## Prerequisites

Copy `../.env.example` to `../.env` and fill in all required values before starting.

## Starting the server

```bash
docker compose up -d
```

To enable the Telegram notification bot (optional):

```bash
COMPOSE_PROFILES=telegram docker compose up -d
```

## Viewing logs

```bash
docker compose logs -f minecraft
```

## Connecting via RCON

```bash
docker compose exec minecraft rcon-cli
```

## Stopping the server

```bash
docker compose down
```

## Configuration

- `config/server.properties` — standard Minecraft server properties
- `config/ops.json` — server operators list
- `config/whitelist.json` — whitelist (enable with `white-list=true` in server.properties)
- `config/banned-players.json` / `config/banned-ips.json` — ban lists

## Offline mode (no Microsoft account required)

The server runs with `ONLINE_MODE=false` and `ENFORCE_SECURE_PROFILE=false`, so players
do not need a Mojang/Microsoft account to connect.

**Client setup:** use the installer scripts in `scripts/` to set up PolyMC, which
supports offline accounts natively:

```
scripts/install-client-linux.sh    # Linux
scripts/install-client-macos.sh    # macOS
scripts/install-client-windows.ps1 # Windows
```

**Connecting:**

1. Open PolyMC → **Accounts** (top-right) → **Add Offline** → enter any username.
2. Launch the `Minecraft Infra Pack 1.21.1 (NeoForge)` instance.
3. In-game: **Multiplayer** → **Add Server** → enter the server address → **Join Server**.

> **Note:** Because online mode is disabled, any username can join. Access is restricted
> at the network level (Tailscale / local network) rather than by Mojang authentication.
