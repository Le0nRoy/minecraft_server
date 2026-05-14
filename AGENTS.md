# Agent File Ownership Map

This document describes which directories AI agents should treat as authoritative
for each concern. When making changes, agents should confine edits to the relevant
subtree and avoid modifying files owned by other concerns without explicit instruction.

## Directory Ownership

| Directory       | Owner Concern         | Description                                              |
|-----------------|-----------------------|----------------------------------------------------------|
| `packwiz/`      | Mod definitions       | Mod list, pack metadata, and packwiz index files         |
| `server/`       | Docker + game config  | Dockerfile, docker-compose, server.properties, ops, etc. |
| `healthcheck/`  | HTTP health service   | Health endpoint source code and configuration            |
| `telegram-bot/` | Notification bot      | Telegram bot source code and configuration               |
| `scripts/`      | Automation scripts    | Backup, startup, shutdown, and maintenance scripts       |
| `systemd/`      | Service units         | systemd unit files for host-level service management     |
| `backups/`      | Backup storage        | Runtime backup archives — gitignored, never committed    |

## Cross-Cutting Files

| File               | Description                                              |
|--------------------|----------------------------------------------------------|
| `.env.example`     | Canonical list of all required environment variables     |
| `.env`             | Live secrets — never committed, never read by agents     |
| `docker-compose.yml` | Top-level service orchestration                        |
| `AGENTS.md`        | This file — update when adding new directories           |
