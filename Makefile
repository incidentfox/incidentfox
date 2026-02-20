# IncidentFox — Local Development
#
# Usage:
#   make dev        Start all services (postgres, config-service, credential-proxy, sre-agent, slack-bot)
#                   Note: slack-bot requires SLACK_BOT_TOKEN + SLACK_APP_TOKEN in .env
#   make stop       Stop all services
#   make restart    Restart all services (rebuild)
#   make logs       Follow all logs
#   make clean      Remove containers, volumes, and images
#   make db-shell   Open psql shell

.PHONY: dev dev-slack restart stop logs logs-agent logs-config status clean db-shell

dev:
	docker compose up -d --build

# Backward-compat alias (dev-slack was removed — slack-bot now starts with `make dev`)
dev-slack: dev

restart:
	docker compose up -d --build

stop:
	docker compose down

logs:
	docker compose logs -f

logs-agent:
	docker compose logs -f sre-agent

logs-config:
	docker compose logs -f config-service

status:
	@docker compose --profile slack ps
	@echo ""
	@curl -sf http://localhost:8080/health > /dev/null 2>&1 && echo "config-service: healthy" || echo "config-service: down"
	@curl -sf http://localhost:8000/health > /dev/null 2>&1 && echo "sre-agent: healthy" || echo "sre-agent: down"

clean:
	docker compose --profile slack down -v --remove-orphans

db-shell:
	docker compose exec postgres psql -U incidentfox -d incidentfox
