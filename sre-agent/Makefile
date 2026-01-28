.PHONY: help

help: ## Show available commands
	@echo ""
	@echo "╔═══════════════════════════════════════════════════════════════╗"
	@echo "║           SRE Agent - IncidentFox Investigation               ║"
	@echo "╚═══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "🏠 LOCAL DEVELOPMENT"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@grep -E '^[a-zA-Z_-]+:.*?## 🏠.*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "☁️  PRODUCTION"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@grep -E '^[a-zA-Z_-]+:.*?## ☁️.*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "📊 UTILITIES"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@grep -E '^[a-zA-Z_-]+:.*?## 📊.*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "For more details, see: DEPLOYMENT_QUICK_START.md"
	@echo ""

# ═══════════════════════════════════════════════════════════════
# 🏠 LOCAL DEVELOPMENT
# ═══════════════════════════════════════════════════════════════

setup-local: ## 🏠 First-time local setup (creates Kind cluster, installs components)
	@./scripts/setup-local.sh

dev: ## 🏠 Start local dev environment (docker-compose-like, Ctrl+C to stop)
	@./scripts/dev.sh

test-local: ## 🏠 Quick test agent locally (no K8s, fast iteration)
	@echo "💡 Usage: make test-local PROMPT='your question here'"
	@echo ""
	@uv run python test_local.py "$(PROMPT)"

dev-clean: ## 🏠 Clean up local sandboxes manually
	@echo "🧹 Cleaning up..."
	@if ! kubectl config current-context | grep -q "kind-incidentfox"; then \
		kubectl config use-context kind-incidentfox 2>/dev/null || true; \
	fi
	@kubectl delete sandbox --all --timeout=30s 2>/dev/null || true
	@echo "✅ Cleaned"

dev-reset: ## 🏠 Delete Kind cluster and start fresh (nuclear option)
	@echo "☢️  This will DELETE the entire Kind cluster!"
	@read -p "Continue? (y/N) " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		kind delete cluster --name incidentfox || true; \
		echo "✅ Deleted. Run 'make setup-local' to recreate"; \
	fi

# ═══════════════════════════════════════════════════════════════
# ☁️  PRODUCTION
# ═══════════════════════════════════════════════════════════════

setup-prod: ## ☁️ First-time production setup (creates EKS cluster, installs components)
	@./scripts/setup-prod.sh

deploy-prod: ## ☁️ Deploy to production (builds multi-platform, pushes to ECR, deploys)
	@./scripts/deploy-prod.sh

# ═══════════════════════════════════════════════════════════════
# 📊 UTILITIES
# ═══════════════════════════════════════════════════════════════

dev-status: ## 📊 Show status of local dev environment
	@echo "📊 Local Development Status"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Context: $$(kubectl config current-context 2>/dev/null || echo 'None')"
	@echo ""
	@echo "Controller:"
	@kubectl get statefulset -n agent-sandbox-system agent-sandbox-controller 2>/dev/null || echo "  ❌ Not running (run: make setup-local)"
	@echo ""
	@echo "Router:"
	@kubectl get deployment sandbox-router-deployment 2>/dev/null || echo "  ❌ Not running (run: make setup-local)"
	@echo ""
	@echo "Active Sandboxes:"
	@kubectl get sandbox --no-headers 2>/dev/null | wc -l | xargs -I {} echo "  {}"
	@echo ""
	@echo "Server:"
	@if pgrep -f "python.*server.py" > /dev/null; then \
		echo "  ✅ Running (PID: $$(pgrep -f 'python.*server.py'))"; \
	else \
		echo "  ❌ Not running (run: make dev)"; \
	fi

dev-logs: ## 📊 View server and router logs
	@echo "📋 Server logs:"
	@if [ -f /tmp/server.log ]; then \
		tail -50 /tmp/server.log; \
	else \
		echo "  No logs (server not running?)"; \
	fi
	@echo ""
	@echo "📋 Router logs:"
	@kubectl logs -l app=sandbox-router --tail=20 --prefix=true 2>/dev/null || echo "  Router not running"

prod-url: ## 📊 Get production LoadBalancer URL
	@CONTEXT=$$(kubectl config current-context 2>/dev/null); \
	if ! echo "$$CONTEXT" | grep -q "incidentfox-prod"; then \
		echo "⚠️  Current context: $$CONTEXT"; \
		echo "💡 Switch to production: kubectl config use-context arn:aws:eks:us-west-2:103002841599:cluster/incidentfox-prod"; \
		echo ""; \
	fi; \
	kubectl get svc incidentfox-server-svc -n incidentfox-prod \
		-o jsonpath='http://{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null && echo "" \
		|| echo "❌ Not deployed or context not set to production"

test-local-server: ## 📊 Run quick E2E test against local server
	@echo "🧪 Testing local server..."
	@curl -s -X POST http://localhost:8000/investigate \
		-H "Content-Type: application/json" \
		-d '{"prompt": "What is 2+2?"}' | head -20
	@echo ""
	@echo "✅ Test complete"

test-prod: ## 📊 Run quick E2E test against production
	@echo "🧪 Testing production..."
	@CONTEXT=$$(kubectl config current-context 2>/dev/null); \
	if ! echo "$$CONTEXT" | grep -q "incidentfox-prod"; then \
		echo "⚠️  Current context: $$CONTEXT"; \
		echo "💡 Switch to production: kubectl config use-context arn:aws:eks:us-west-2:103002841599:cluster/incidentfox-prod"; \
		echo ""; \
	fi; \
	PROD_URL=$$(kubectl get svc incidentfox-server-svc -n incidentfox-prod \
		-o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null); \
	if [ -z "$$PROD_URL" ]; then \
		echo "❌ Production URL not found"; \
		exit 1; \
	fi; \
	curl -s -m 30 -X POST "http://$$PROD_URL/investigate" \
		-H "Content-Type: application/json" \
		-d '{"prompt": "What is 2+2?"}' | head -20
	@echo ""
	@echo "✅ Test complete"

# ═══════════════════════════════════════════════════════════════
# 🛠️  INTERNAL (Advanced users only)
# ═══════════════════════════════════════════════════════════════

setup: ## Install Python dependencies
	uv venv
	.venv/bin/activate && uv pip install -e .
