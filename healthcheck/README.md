# Minecraft Server Healthcheck

A lightweight HTTP service that exposes Minecraft server status by polling the
server's RCON interface every 30 seconds and caching the result. Requests to
`/health` are served from this cache, so they are always fast and never block
on RCON.

## Endpoints

| Method | Path      | Description |
|--------|-----------|-------------|
| GET    | `/health` | Full server status (JSON). Returns HTTP 200 when online, 503 otherwise. |
| GET    | `/ping`   | Liveness probe — always returns `{"alive": true}` with HTTP 200. |

### `/health` response schema

```json
{
  "status": "online|offline|starting",
  "uptime_seconds": 12345,
  "players_online": 3,
  "players_max": 20,
  "version": "unknown",
  "motd": "",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

`status` values:
- `online` — RCON reachable, server is accepting players.
- `starting` — RCON unreachable but the game port is open (server still booting).
- `offline` — RCON unreachable and game port is closed.

## Environment variables

| Variable        | Default     | Description |
|-----------------|-------------|-------------|
| `RCON_HOST`     | `localhost` | Hostname or IP of the Minecraft server. |
| `RCON_PORT`     | `25575`     | RCON port. |
| `RCON_PASSWORD` | *(empty)*   | RCON password (must match `server.properties`). |
| `SERVER_PORT`   | `25565`     | Game port — used for TCP reachability fallback. |

## Running with Docker

```bash
docker build -t mc-healthcheck .
docker run -d \
  -p 8080:8080 \
  -e RCON_HOST=minecraft \
  -e RCON_PORT=25575 \
  -e RCON_PASSWORD=secret \
  -e SERVER_PORT=25565 \
  mc-healthcheck
```

## Running locally

```bash
pip install -r requirements.txt
RCON_HOST=localhost RCON_PASSWORD=secret python app.py
```
