.PHONY: help setup install run clean

help: ## Show available commands
	@echo ""
	@echo "╔═══════════════════════════════════════════════╗"
	@echo "║       IncidentFox Slack Bot                   ║"
	@echo "╚═══════════════════════════════════════════════╝"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo ""

setup: ## Create venv and install dependencies (first time setup)
	@echo "📦 Setting up virtual environment..."
	uv venv
	@echo "✅ Virtual environment created"
	@echo ""
	@echo "Next steps:"
	@echo "  1. source .venv/bin/activate"
	@echo "  2. make install"
	@echo "  3. cp env.example .env  # Edit with your tokens"
	@echo "  4. make run"

install: ## Install dependencies (run inside venv)
	@echo "📥 Installing dependencies..."
	uv pip install -e .
	@echo "✅ Dependencies installed"

run: ## Run the Slack bot (Socket Mode)
	@echo "⚡️ Starting Slack bot..."
	python app.py

clean: ## Remove virtual environment and cache files
	rm -rf .venv __pycache__ *.egg-info uv.lock
	@echo "🧹 Cleaned up"

deploy-prod: ## Deploy to production (builds, pushes to ECR, deploys to EKS)
	@./scripts/deploy-prod.sh

prod-url: ## Get production LoadBalancer URL
	@CONTEXT=$$(kubectl config current-context 2>/dev/null); \
	if ! echo "$$CONTEXT" | grep -q "incidentfox-prod"; then \
		echo "⚠️  Current context: $$CONTEXT"; \
		echo "💡 Switch to production: kubectl config use-context arn:aws:eks:us-west-2:103002841599:cluster/incidentfox-prod"; \
		echo ""; \
	fi; \
	URL=$$(kubectl get svc slack-bot-svc -n incidentfox-prod -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null); \
	if [ -z "$$URL" ]; then \
		echo "❌ Not deployed or context not set to production"; \
	else \
		echo "Slack Webhook URL:"; \
		echo "  http://$$URL/slack/events"; \
		echo ""; \
		echo "Health Check:"; \
		echo "  http://$$URL/health"; \
	fi

