# IncidentFox — Local Development
#
# Usage:
#   make dev        Start core services (postgres, config-service, credential-proxy, sre-agent)
#   make dev-slack  Start with Slack bot (requires SLACK_BOT_TOKEN + SLACK_APP_TOKEN in .env)
#   make stop       Stop all services
#   make logs       Follow all logs
#   make clean      Remove containers, volumes, and images
#   make db-shell   Open psql shell

.PHONY: dev dev-slack stop logs logs-agent logs-config status clean db-shell

dev:
	docker compose up -d --build

dev-slack:
	docker compose --profile slack up -d --build

stop:
	docker compose --profile slack down

logs:
	docker compose --profile slack logs -f

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
