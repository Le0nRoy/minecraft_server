# Minecraft Infrastructure Makefile
# Usage: make <target>

.PHONY: all up down restart logs logs-all status pull backup restore rcon shell \
        health update-mods packwiz-refresh setup install-systemd install-client-linux \
        build deploy clean clean-backups help \
        _check-env _check-docker

# Load .env if present
-include .env
export

COMPOSE  = docker compose -f server/docker-compose.yml
SCRIPTS  = ./scripts

.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Guard targets
# ---------------------------------------------------------------------------

_check-env:
	@if [ ! -f .env ]; then \
	    echo "ERROR: .env file not found. Run 'make setup' first."; \
	    exit 1; \
	fi

_check-docker:
	@if ! docker info > /dev/null 2>&1; then \
	    echo "ERROR: Docker daemon is not running."; \
	    exit 1; \
	fi

# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

## up         Start the server in detached mode
up: _check-env _check-docker
	@$(COMPOSE) up -d
	@echo "Server started. Follow logs with: make logs"

## down       Stop and remove containers
down: _check-docker
	@$(COMPOSE) down

## restart    Restart all containers
restart: _check-docker
	@$(COMPOSE) restart

## logs       Follow minecraft container logs
logs: _check-docker
	@$(COMPOSE) logs -f minecraft

## logs-all   Follow all container logs
logs-all: _check-docker
	@$(COMPOSE) logs -f

## status     Show container status and healthcheck URL
status: _check-docker
	@$(COMPOSE) ps
	@echo ""
	@echo "Healthcheck: http://localhost:$${HEALTHCHECK_PORT:-8080}/health"

## pull       Pull latest images
pull: _check-docker
	@$(COMPOSE) pull

# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

## backup     Create a timestamped backup
backup:
	@$(SCRIPTS)/backup.sh

## restore    Restore a backup (BACKUP=<file> for specific file)
restore:
	@$(SCRIPTS)/restore.sh $(if $(BACKUP),$(BACKUP),)

## rcon       Send an RCON command  (CMD="say hello")
rcon:
	@$(SCRIPTS)/rcon.sh "$(CMD)"

## shell      Open a bash shell in the minecraft container
shell: _check-docker
	@$(COMPOSE) exec minecraft bash

## health     Query the healthcheck endpoint
health:
	@curl -s http://localhost:$${HEALTHCHECK_PORT:-8080}/health | python3 -m json.tool

# ---------------------------------------------------------------------------
# Mod management
# ---------------------------------------------------------------------------

## update-mods   Run the packwiz mod update script
update-mods:
	@packwiz/scripts/update-mods.sh

## packwiz-refresh  Refresh the packwiz index
packwiz-refresh:
	@cd packwiz && packwiz refresh

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

## setup      Copy .env.example → .env (if .env absent) and print next steps
setup:
	@if [ ! -f .env ]; then \
	    cp .env.example .env; \
	    echo "Created .env from .env.example"; \
	    echo ""; \
	    echo "Next steps:"; \
	    echo "  1. Edit .env and fill in your credentials / settings"; \
	    echo "  2. Run 'make up' to start the server"; \
	else \
	    echo ".env already exists — no changes made."; \
	fi

## install-systemd         Install systemd service units
install-systemd:
	@sudo systemd/install.sh

## install-client-linux    Install the Linux client helper
install-client-linux:
	@$(SCRIPTS)/install-client-linux.sh

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

## build      Rebuild Docker images without cache
build: _check-docker
	@$(COMPOSE) build --no-cache

## deploy     Pull → down → up → tail logs for 10 seconds
deploy: _check-env _check-docker
	@$(MAKE) pull
	@$(MAKE) down
	@$(MAKE) up
	@$(COMPOSE) logs --tail=50 --follow minecraft & sleep 10; kill %% 2>/dev/null; true

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

## clean      Remove stopped containers and prune unused images
clean: _check-docker
	@printf "Remove stopped containers and prune images? [y/N] "; \
	read ans; \
	case "$$ans" in \
	    [Yy]*) \
	        $(COMPOSE) rm -f; \
	        docker image prune -f; \
	        echo "Done.";; \
	    *) echo "Aborted.";; \
	esac

## clean-backups   Remove backups older than BACKUP_RETENTION_DAYS
clean-backups:
	@DAYS=$${BACKUP_RETENTION_DAYS:-14}; \
	DIR=$${BACKUP_DIR:-./backups}; \
	echo "Removing backups older than $$DAYS days from $$DIR ..."; \
	find "$$DIR" -maxdepth 1 -type f -mtime +$$DAYS -print -delete; \
	echo "Done."

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

## help       Show this help message
help:
	@printf "\n\033[1mMinecraft Infrastructure — available targets:\033[0m\n\n"
	@printf "  \033[36m%-24s\033[0m %s\n" "Target" "Description"
	@printf "  %-24s %s\n"               "------" "-----------"
	@printf "  \033[36m%-24s\033[0m %s\n" "up"                  "Start the server in detached mode"
	@printf "  \033[36m%-24s\033[0m %s\n" "down"                "Stop and remove containers"
	@printf "  \033[36m%-24s\033[0m %s\n" "restart"             "Restart all containers"
	@printf "  \033[36m%-24s\033[0m %s\n" "logs"                "Follow minecraft container logs"
	@printf "  \033[36m%-24s\033[0m %s\n" "logs-all"            "Follow all container logs"
	@printf "  \033[36m%-24s\033[0m %s\n" "status"              "Show container status + healthcheck URL"
	@printf "  \033[36m%-24s\033[0m %s\n" "pull"                "Pull latest Docker images"
	@printf "  \033[36m%-24s\033[0m %s\n" "backup"              "Create a timestamped backup"
	@printf "  \033[36m%-24s\033[0m %s\n" "restore"             "Restore a backup (BACKUP=<file> for specific)"
	@printf "  \033[36m%-24s\033[0m %s\n" "rcon CMD=\"<cmd>\""  "Send an RCON command to the server"
	@printf "  \033[36m%-24s\033[0m %s\n" "shell"               "Open bash in the minecraft container"
	@printf "  \033[36m%-24s\033[0m %s\n" "health"              "Query the healthcheck endpoint"
	@printf "  \033[36m%-24s\033[0m %s\n" "update-mods"         "Run the packwiz mod update script"
	@printf "  \033[36m%-24s\033[0m %s\n" "packwiz-refresh"     "Refresh the packwiz index"
	@printf "  \033[36m%-24s\033[0m %s\n" "setup"               "Copy .env.example → .env and show next steps"
	@printf "  \033[36m%-24s\033[0m %s\n" "install-systemd"     "Install systemd service units"
	@printf "  \033[36m%-24s\033[0m %s\n" "install-client-linux" "Install the Linux client helper"
	@printf "  \033[36m%-24s\033[0m %s\n" "build"               "Rebuild Docker images without cache"
	@printf "  \033[36m%-24s\033[0m %s\n" "deploy"              "pull → down → up → tail logs 10 s"
	@printf "  \033[36m%-24s\033[0m %s\n" "clean"               "Remove stopped containers, prune images"
	@printf "  \033[36m%-24s\033[0m %s\n" "clean-backups"       "Remove backups older than BACKUP_RETENTION_DAYS"
	@printf "  \033[36m%-24s\033[0m %s\n" "help"                "Show this help message"
	@printf "\n"
