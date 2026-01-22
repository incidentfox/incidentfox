# ═══════════════════════════════════════════════════════════════════════════════
# IncidentFox Local Development
# ═══════════════════════════════════════════════════════════════════════════════

.PHONY: help setup start stop restart logs status cli clean clean-all seed ui build run quickstart venv dev-restart dev-build

DOCKER_COMPOSE = docker compose
VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

# ─────────────────────────────────────────────────────────────────────────────
# Help
# ─────────────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║           IncidentFox Local Development                        ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(GREEN)Quick Start:$(NC)"
	@echo "  make setup     First-time setup (creates .env)"
	@echo "  make start     Start required services"
	@echo "  make seed      Generate team token (run after first start)"
	@echo "  make cli       Run interactive CLI REPL"
	@echo ""
	@echo "$(GREEN)Service Management:$(NC)"
	@echo "  make start        Start: PostgreSQL + Config Service + Agent"
	@echo "  make start-ui     Start: Above + Web UI (localhost:3000)"
	@echo "  make start-raptor Start: Above + RAPTOR KB (localhost:8000)"
	@echo "  make start-all    Start: All services including UI and RAPTOR"
	@echo "  make stop         Stop all services"
	@echo "  make restart      Restart all services"
	@echo "  make logs         Follow all service logs"
	@echo "  make logs-agent   Follow agent logs only"
	@echo "  make logs-raptor  Follow RAPTOR logs only"
	@echo "  make status       Show service status and health"
	@echo ""
	@echo "$(GREEN)Utilities:$(NC)"
	@echo "  make build        Build all Docker images"
	@echo "  make dev-build    Build agent only (no start)"
	@echo "  make dev-restart  Restart agent only (rebuilds if changed)"
	@echo "  make shell        Open bash in agent container"
	@echo "  make db-shell     Open psql in postgres"
	@echo "  make clean        Remove containers and volumes"
	@echo ""
	@echo "$(YELLOW)First time? Run:$(NC)"
	@echo "  make quickstart"
	@echo ""
	@echo "$(YELLOW)Already configured? Run:$(NC)"
	@echo "  make run"
	@echo ""
	@echo "$(DIM)Note: start/run auto-rebuild agent if code changes$(NC)"
	@echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────
setup:
	@echo "$(BLUE)🔧 Setting up IncidentFox Local...$(NC)"
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		PEPPER=$$(python3 -c "import secrets; print(secrets.token_urlsafe(32))"); \
		if [ "$$(uname)" = "Darwin" ]; then \
			sed -i '' "s/^TOKEN_PEPPER=$$/TOKEN_PEPPER=$$PEPPER/" .env; \
		else \
			sed -i "s/^TOKEN_PEPPER=$$/TOKEN_PEPPER=$$PEPPER/" .env; \
		fi; \
		echo "$(GREEN)✅ Created .env with generated TOKEN_PEPPER$(NC)"; \
	else \
		echo "$(YELLOW)ℹ️  .env already exists$(NC)"; \
	fi
	@echo ""
	@echo "$(YELLOW)📝 Next steps:$(NC)"
	@echo "   1. Edit .env and add your OPENAI_API_KEY"
	@echo "   2. Run: make start"
	@echo "   3. Run: make seed"
	@echo "   4. Run: make cli"
	@echo ""

# Ensure venv exists and CLI is installed
$(VENV)/bin/python: pyproject.toml
	@echo "$(BLUE)🐍 Setting up Python environment...$(NC)"
	@python3 -m venv $(VENV)
	@$(PIP) install --upgrade pip -q
	@$(PIP) install -e . -q
	@echo "$(GREEN)✅ Python environment ready$(NC)"

venv: $(VENV)/bin/python

seed:
	@echo "$(BLUE)🌱 Generating team token...$(NC)"
	@if ! $(DOCKER_COMPOSE) ps config-service | grep -q "running"; then \
		echo "$(RED)❌ Config service not running. Run 'make start' first.$(NC)"; \
		exit 1; \
	fi
	@$(DOCKER_COMPOSE) exec -T config-service python scripts/issue_team_token.py \
		--org-id local --team-node-id default --issued-by "local-cli" 2>/dev/null | tee /tmp/incidentfox_token.txt
	@TOKEN=$$(tail -1 /tmp/incidentfox_token.txt 2>/dev/null | tr -d '[:space:]'); \
	if [ -n "$$TOKEN" ] && echo "$$TOKEN" | grep -q '\.'; then \
		if [ "$$(uname)" = "Darwin" ]; then \
			sed -i '' "s/^TEAM_TOKEN=.*/TEAM_TOKEN=$$TOKEN/" .env; \
		else \
			sed -i "s/^TEAM_TOKEN=.*/TEAM_TOKEN=$$TOKEN/" .env; \
		fi; \
		echo ""; \
		echo "$(GREEN)✅ Team token saved to .env$(NC)"; \
		echo ""; \
		echo "$(GREEN)You can now run: make cli$(NC)"; \
	else \
		echo "$(YELLOW)⚠️  Could not extract token. Trying alternative method...$(NC)"; \
		$(DOCKER_COMPOSE) logs config-service --tail=20; \
	fi

# ─────────────────────────────────────────────────────────────────────────────
# Quick Start Commands
# ─────────────────────────────────────────────────────────────────────────────
quickstart: $(VENV)/bin/python
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║           IncidentFox Quick Start                              ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@# Step 1: Setup .env if needed
	@if [ ! -f .env ]; then \
		echo "$(BLUE)🔧 Creating .env file...$(NC)"; \
		cp .env.example .env; \
		PEPPER=$$(python3 -c "import secrets; print(secrets.token_urlsafe(32))"); \
		if [ "$$(uname)" = "Darwin" ]; then \
			sed -i '' "s/^TOKEN_PEPPER=$$/TOKEN_PEPPER=$$PEPPER/" .env; \
		else \
			sed -i "s/^TOKEN_PEPPER=$$/TOKEN_PEPPER=$$PEPPER/" .env; \
		fi; \
		echo "$(GREEN)✅ Created .env$(NC)"; \
	fi
	@# Step 2: Check/prompt for OpenAI API key
	@if [ -z "$$(grep '^OPENAI_API_KEY=' .env 2>/dev/null | cut -d= -f2 | grep -v '^sk-your' | grep -v '^$$')" ]; then \
		echo ""; \
		echo "$(YELLOW)📝 OpenAI API key required$(NC)"; \
		echo "   Get one at: https://platform.openai.com/api-keys"; \
		echo ""; \
		printf "   Enter your OpenAI API key: "; \
		read -r API_KEY; \
		if [ -n "$$API_KEY" ]; then \
			if [ "$$(uname)" = "Darwin" ]; then \
				sed -i '' "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=$$API_KEY|" .env; \
			else \
				sed -i "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=$$API_KEY|" .env; \
			fi; \
			echo "$(GREEN)   ✅ API key saved$(NC)"; \
		else \
			echo "$(RED)   ❌ No API key provided$(NC)"; \
			exit 1; \
		fi; \
	else \
		echo "$(GREEN)✅ OpenAI API key already configured$(NC)"; \
	fi
	@echo ""
	@# Step 3: Start services
	@echo "$(BLUE)🚀 Starting services...$(NC)"
	@$(DOCKER_COMPOSE) up -d postgres config-service agent
	@echo "$(YELLOW)⏳ Waiting for services to be healthy...$(NC)"
	@sleep 8
	@# Step 4: Seed token if needed
	@if [ -z "$$(grep '^TEAM_TOKEN=' .env 2>/dev/null | cut -d= -f2 | grep -v '^$$')" ]; then \
		echo "$(BLUE)🌱 Generating team token...$(NC)"; \
		$(DOCKER_COMPOSE) exec -T config-service python scripts/issue_team_token.py \
			--org-id local --team-node-id default --issued-by "local-cli" 2>/dev/null | tee /tmp/incidentfox_token.txt; \
		TOKEN=$$(tail -1 /tmp/incidentfox_token.txt 2>/dev/null | tr -d '[:space:]'); \
		if [ -n "$$TOKEN" ] && echo "$$TOKEN" | grep -q '\.'; then \
			if [ "$$(uname)" = "Darwin" ]; then \
				sed -i '' "s/^TEAM_TOKEN=.*/TEAM_TOKEN=$$TOKEN/" .env; \
			else \
				sed -i "s/^TEAM_TOKEN=.*/TEAM_TOKEN=$$TOKEN/" .env; \
			fi; \
			echo "$(GREEN)✅ Team token generated$(NC)"; \
		fi; \
	else \
		echo "$(GREEN)✅ Team token already configured$(NC)"; \
	fi
	@echo ""
	@echo "$(GREEN)✅ Setup complete! Starting CLI...$(NC)"
	@echo ""
	@# Step 5: Launch CLI
	@set -a && . ./.env && set +a && $(PYTHON) -m incidentfox_cli

run: $(VENV)/bin/python
	@echo "$(BLUE)🚀 Starting IncidentFox...$(NC)"
	@# Check prerequisites
	@if [ ! -f .env ]; then \
		echo "$(RED)❌ .env not found. Run 'make quickstart' for first-time setup.$(NC)"; \
		exit 1; \
	fi
	@if [ -z "$$(grep '^OPENAI_API_KEY=' .env 2>/dev/null | cut -d= -f2 | grep -v '^sk-your' | grep -v '^$$')" ]; then \
		echo "$(RED)❌ OPENAI_API_KEY not set in .env$(NC)"; \
		echo "$(YELLOW)   Run 'make quickstart' or edit .env manually$(NC)"; \
		exit 1; \
	fi
	@# Start services (rebuilds agent if code changed)
	@echo "$(BLUE)🔨 Starting services (rebuilds if code changed)...$(NC)"
	@$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up -d --build postgres config-service agent
	@echo "$(YELLOW)⏳ Waiting for services...$(NC)"
	@sleep 8
	@# Seed token if needed
	@if [ -z "$$(grep '^TEAM_TOKEN=' .env 2>/dev/null | cut -d= -f2 | grep -v '^$$')" ]; then \
		echo "$(BLUE)🌱 Generating team token...$(NC)"; \
		$(DOCKER_COMPOSE) exec -T config-service python scripts/issue_team_token.py \
			--org-id local --team-node-id default --issued-by "local-cli" 2>/dev/null | tee /tmp/incidentfox_token.txt; \
		TOKEN=$$(tail -1 /tmp/incidentfox_token.txt 2>/dev/null | tr -d '[:space:]'); \
		if [ -n "$$TOKEN" ] && echo "$$TOKEN" | grep -q '\.'; then \
			if [ "$$(uname)" = "Darwin" ]; then \
				sed -i '' "s/^TEAM_TOKEN=.*/TEAM_TOKEN=$$TOKEN/" .env; \
			else \
				sed -i "s/^TEAM_TOKEN=.*/TEAM_TOKEN=$$TOKEN/" .env; \
			fi; \
			echo "$(GREEN)✅ Team token generated$(NC)"; \
		fi; \
	fi
	@# Launch CLI
	@echo "$(BLUE)🦊 Starting CLI...$(NC)"
	@set -a && . ./.env && set +a && $(PYTHON) -m incidentfox_cli

# ─────────────────────────────────────────────────────────────────────────────
# Services
# ─────────────────────────────────────────────────────────────────────────────
build:
	@echo "$(BLUE)🔨 Building Docker images...$(NC)"
	$(DOCKER_COMPOSE) build

start:
	@echo "$(BLUE)🚀 Starting IncidentFox services (rebuilds if code changed)...$(NC)"
	@if [ -z "$$(grep '^OPENAI_API_KEY=' .env 2>/dev/null | cut -d= -f2 | grep -v '^sk-your')" ]; then \
		echo "$(RED)❌ OPENAI_API_KEY not set in .env$(NC)"; \
		echo "$(YELLOW)   Edit .env and add your OpenAI API key$(NC)"; \
		exit 1; \
	fi
	$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up -d --build postgres config-service agent
	@echo ""
	@echo "$(YELLOW)⏳ Waiting for services to be healthy...$(NC)"
	@sleep 8
	@$(DOCKER_COMPOSE) ps
	@echo ""
	@echo "$(GREEN)✅ Services started:$(NC)"
	@echo "   PostgreSQL:     localhost:5432"
	@echo "   Config Service: localhost:8080"
	@echo "   Agent API:      localhost:8081"
	@echo ""
	@if [ -z "$$(grep '^TEAM_TOKEN=' .env 2>/dev/null | cut -d= -f2)" ]; then \
		echo "$(YELLOW)📝 Next: Run 'make seed' to generate team token$(NC)"; \
	else \
		echo "$(GREEN)Ready! Run 'make cli' to start the CLI$(NC)"; \
	fi

start-ui: start
	@echo ""
	@echo "$(BLUE)🖥️  Starting Web UI...$(NC)"
	$(DOCKER_COMPOSE) --profile ui up -d web-ui
	@echo "$(GREEN)✅ Web UI: http://localhost:3000$(NC)"

start-raptor: start
	@echo ""
	@echo "$(BLUE)🔍 Starting RAPTOR Knowledge Base...$(NC)"
	$(DOCKER_COMPOSE) --profile raptor up -d raptor
	@echo "$(GREEN)✅ RAPTOR: http://localhost:8000$(NC)"
	@echo "$(DIM)Trees persisted in Docker volume: incidentfox-raptor-trees$(NC)"

start-all: start
	@echo ""
	@echo "$(BLUE)🚀 Starting all optional services...$(NC)"
	$(DOCKER_COMPOSE) --profile ui --profile raptor up -d web-ui raptor
	@echo "$(GREEN)✅ Web UI: http://localhost:3000$(NC)"
	@echo "$(GREEN)✅ RAPTOR: http://localhost:8000$(NC)"

stop:
	@echo "$(BLUE)🛑 Stopping services...$(NC)"
	$(DOCKER_COMPOSE) --profile ui --profile raptor down

restart: stop start

logs:
	$(DOCKER_COMPOSE) logs -f

logs-agent:
	$(DOCKER_COMPOSE) logs -f agent

logs-config:
	$(DOCKER_COMPOSE) logs -f config-service

logs-raptor:
	$(DOCKER_COMPOSE) --profile raptor logs -f raptor

status:
	@echo "$(BLUE)Service Status:$(NC)"
	@$(DOCKER_COMPOSE) ps
	@echo ""
	@echo "$(BLUE)Health Checks:$(NC)"
	@curl -s http://localhost:8080/health >/dev/null 2>&1 && echo "  Config Service: $(GREEN)✅ OK$(NC)" || echo "  Config Service: $(RED)❌ DOWN$(NC)"
	@curl -s http://localhost:8081/health >/dev/null 2>&1 && echo "  Agent:          $(GREEN)✅ OK$(NC)" || echo "  Agent:          $(RED)❌ DOWN$(NC)"
	@curl -s http://localhost:3000 >/dev/null 2>&1 && echo "  Web UI:         $(GREEN)✅ OK$(NC)" || echo "  Web UI:         $(YELLOW)⚪ Not started$(NC)"

# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
cli: $(VENV)/bin/python
	@if [ -z "$$(grep '^TEAM_TOKEN=' .env 2>/dev/null | cut -d= -f2)" ]; then \
		echo "$(RED)❌ TEAM_TOKEN not set in .env$(NC)"; \
		echo "$(YELLOW)   Run 'make seed' first$(NC)"; \
		exit 1; \
	fi
	@# Rebuild agent if code changed (fast if no changes due to caching)
	@echo "$(BLUE)🔨 Checking for code changes...$(NC)"
	@$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up -d --build agent
	@if ! curl -s http://localhost:8081/health >/dev/null 2>&1; then \
		echo "$(YELLOW)⏳ Waiting for agent...$(NC)"; \
		sleep 5; \
	fi
	@echo "$(BLUE)🦊 Starting IncidentFox CLI...$(NC)"
	@set -a && . ./.env && set +a && $(PYTHON) -m incidentfox_cli

# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────
shell:
	$(DOCKER_COMPOSE) exec agent bash

db-shell:
	$(DOCKER_COMPOSE) exec postgres psql -U incidentfox -d incidentfox

clean:
	@echo "$(BLUE)🧹 Cleaning up...$(NC)"
	$(DOCKER_COMPOSE) --profile ui down -v --remove-orphans
	@echo "$(GREEN)✅ Removed containers and volumes$(NC)"

clean-all: clean
	@echo "$(BLUE)🧹 Removing Python virtual environment...$(NC)"
	@rm -rf $(VENV)
	@echo "$(GREEN)✅ Removed .venv$(NC)"

# ─────────────────────────────────────────────────────────────────────────────
# Development helpers
# ─────────────────────────────────────────────────────────────────────────────
test-agent:
	@echo "$(BLUE)Testing agent API...$(NC)"
	@TOKEN=$$(grep '^TEAM_TOKEN=' .env | cut -d= -f2); \
	curl -s -X POST http://localhost:8081/agents/planner/run \
		-H "Content-Type: application/json" \
		-H "X-IncidentFox-Team-Token: $$TOKEN" \
		-d '{"message": "What can you help me with?", "context": {}, "max_turns": 5, "timeout": 60}' | python3 -m json.tool

test-health:
	@echo "$(BLUE)Testing service health...$(NC)"
	@echo "Config Service:"
	@curl -s http://localhost:8080/health | python3 -m json.tool
	@echo ""
	@echo "Agent:"
	@curl -s http://localhost:8081/health | python3 -m json.tool

# ─────────────────────────────────────────────────────────────────────────────
# Development with local source
# ─────────────────────────────────────────────────────────────────────────────
dev-build:
	@echo "$(BLUE)🔨 Building agent from local source...$(NC)"
	$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml build agent

dev-restart:
	@echo "$(BLUE)🔄 Restarting agent (rebuilds if code changed)...$(NC)"
	$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up -d --build agent
	@sleep 5
	@echo "$(GREEN)✅ Agent restarted$(NC)"

test-stream:
	@echo "$(BLUE)Testing SSE streaming endpoint...$(NC)"
	@TOKEN=$$(grep '^TEAM_TOKEN=' .env | cut -d= -f2); \
	curl -N -X POST http://localhost:8081/agents/planner/run/stream \
		-H "Content-Type: application/json" \
		-H "X-IncidentFox-Team-Token: $$TOKEN" \
		-d '{"message": "Hello, what can you help with?", "context": {}, "max_turns": 3, "timeout": 30}'
