# Server

Docker Compose stack for the Minecraft Fabric 1.20.1 server.

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
- `config/fabric/fabric-server-launch.properties` — Fabric launcher config
