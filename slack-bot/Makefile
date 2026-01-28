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

