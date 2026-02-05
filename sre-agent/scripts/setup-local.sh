#!/bin/bash
# Local Development Environment Setup (First-Time Only)
# Creates Kind cluster with all required components
# Usage: ./scripts/setup-local.sh

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║       🔧 Local Development Setup (First-Time Only)             ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check prerequisites
echo "📋 Checking prerequisites..."
command -v kind >/dev/null 2>&1 || { echo "❌ kind not found. Install: https://kind.sigs.k8s.io/"; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "❌ kubectl not found"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "❌ Docker not found"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "❌ jq not found. Install: brew install jq"; exit 1; }
echo "✅ Prerequisites OK"
echo ""

# Check if cluster already exists
if kind get clusters 2>/dev/null | grep -q "^incidentfox$"; then
    echo "⚠️  Kind cluster 'incidentfox' already exists!"
    echo ""
    read -p "Delete and recreate? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🗑️  Deleting existing cluster..."
        kind delete cluster --name incidentfox
    else
        echo "Cancelled. Using existing cluster."
        kubectl config use-context kind-incidentfox
        echo ""
        echo "⏩ Skipping to component setup..."
        echo ""
        SKIP_CLUSTER=true
    fi
fi

# Step 1: Create Kind cluster
if [ "$SKIP_CLUSTER" != "true" ]; then
    echo "1️⃣  Creating Kind cluster..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ./k8s/setup-kind.sh
    echo "✅ Kind cluster created"
    echo ""
fi

# Step 2: Install Sandbox Router
echo "2️⃣  Building and deploying Sandbox Router..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Clone/update agent-sandbox repo
if [ ! -d "$HOME/.cache/agent-sandbox" ]; then
    echo "Cloning agent-sandbox repo..."
    git clone https://github.com/kubernetes-sigs/agent-sandbox.git "$HOME/.cache/agent-sandbox"
else
    echo "Updating agent-sandbox repo..."
    cd "$HOME/.cache/agent-sandbox" && git pull && cd - >/dev/null
fi

# Build router image
echo "Building router image..."
cd "$HOME/.cache/agent-sandbox/clients/python/agentic-sandbox-client/sandbox-router"
docker build -t sandbox-router:local . >/dev/null 2>&1
cd - >/dev/null

# Load into Kind
echo "Loading into Kind..."
kind load docker-image sandbox-router:local --name incidentfox

# Deploy router
kubectl apply -f k8s/sandbox_router.yaml

# Patch for local development (use local image, not ECR)
kubectl set image deployment/sandbox-router-deployment router=sandbox-router:local
kubectl patch deployment sandbox-router-deployment -p '{"spec":{"template":{"spec":{"imagePullSecrets":[],"containers":[{"name":"router","imagePullPolicy":"IfNotPresent"}]}}}}'
kubectl rollout status deployment/sandbox-router-deployment --timeout=60s

echo "✅ Sandbox Router deployed"
echo ""

# Step 3: Deploy Service Patcher
echo "3️⃣  Deploying service patcher..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
kubectl apply -f k8s/service-patcher.yaml
kubectl wait --for=condition=available --timeout=30s deployment/sandbox-service-patcher 2>/dev/null || true
echo "✅ Service patcher deployed"
echo ""

# Step 4: Create secrets
echo "4️⃣  Creating secrets..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Look for .env file - prefer root .env (has real credentials), fallback to local
if [ -f "../.env" ]; then
    echo "  Using root .env file"
    ENV_FILE="../.env"
elif [ -f ".env" ]; then
    echo "  Using local .env file"
    ENV_FILE=".env"
else
    echo "❌ .env file not found!"
    echo ""
    echo "Create .env in the repo root with:"
    echo "  ANTHROPIC_API_KEY=sk-ant-..."
    echo "  CORALOGIX_API_KEY=..."
    echo ""
    exit 1
fi

source "$ENV_FILE"

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ ANTHROPIC_API_KEY not set in .env"
    exit 1
fi

kubectl create secret generic incidentfox-secrets \
    --from-literal=anthropic-api-key="${ANTHROPIC_API_KEY}" \
    --from-literal=laminar-api-key="${LMNR_PROJECT_API_KEY:-}" \
    --from-literal=coralogix-api-key="${CORALOGIX_API_KEY:-}" \
    --from-literal=coralogix-domain="${CORALOGIX_DOMAIN:-}" \
    --from-literal=datadog-api-key="${DATADOG_API_KEY:-}" \
    --from-literal=datadog-app-key="${DATADOG_APP_KEY:-}" \
    --from-literal=datadog-site="${DATADOG_SITE:-datadoghq.com}" \
    --from-literal=prometheus-url="${PROMETHEUS_URL:-}" \
    --from-literal=alertmanager-url="${ALERTMANAGER_URL:-}" \
    --from-literal=grafana-url="${GRAFANA_URL:-}" \
    --from-literal=grafana-api-key="${GRAFANA_API_KEY:-}" \
    --from-literal=sentry-auth-token="${SENTRY_AUTH_TOKEN:-}" \
    --from-literal=sentry-organization="${SENTRY_ORGANIZATION:-}" \
    --from-literal=sentry-project="${SENTRY_PROJECT:-}" \
    --from-literal=elasticsearch-url="${ELASTICSEARCH_URL:-}" \
    --from-literal=elasticsearch-index="${ELASTICSEARCH_INDEX:-logs-*}" \
    --from-literal=loki-url="${LOKI_URL:-}" \
    --from-literal=splunk-host="${SPLUNK_HOST:-}" \
    --from-literal=splunk-token="${SPLUNK_TOKEN:-}" \
    --from-literal=splunk-port="${SPLUNK_PORT:-8089}" \
    --from-literal=github-token="${GITHUB_TOKEN:-}" \
    --from-literal=github-app-id="${GITHUB_APP_ID:-}" \
    --from-literal=github-private-key-b64="${GITHUB_PRIVATE_KEY_B64:-}" \
    --from-literal=github-webhook-secret="${GITHUB_WEBHOOK_SECRET:-}" \
    --from-literal=github-installation-id="${GITHUB_INSTALLATION_ID:-}" \
    --from-literal=github-repository="${GITHUB_REPOSITORY:-}" \
    --from-literal=slack-bot-token="${SLACK_BOT_TOKEN:-}" \
    --from-literal=slack-default-channel="${SLACK_DEFAULT_CHANNEL:-}" \
    --from-literal=pagerduty-api-key="${PAGERDUTY_API_KEY:-}" \
    --from-literal=aws-access-key-id="${AWS_ACCESS_KEY_ID:-}" \
    --from-literal=aws-secret-access-key="${AWS_SECRET_ACCESS_KEY:-}" \
    --from-literal=aws-region="${AWS_REGION:-us-west-2}" \
    --from-literal=database-url="${DATABASE_URL:-}" \
    --from-literal=history-db-path="${HISTORY_DB_PATH:-~/.incidentfox/history.db}" \
    --from-literal=remediation-log-path="${REMEDIATION_LOG_PATH:-~/.incidentfox/logs/remediation.log}" \
    --from-literal=llm-provider="${LLM_PROVIDER:-claude}" \
    --from-literal=llm-model="${LLM_MODEL:-}" \
    --from-literal=gemini-api-key="${GEMINI_API_KEY:-}" \
    --from-literal=openai-api-key="${OPENAI_API_KEY:-}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "✅ Secrets created"
echo ""

# Step 5: Deploy credential proxy (Envoy + credential-resolver)
echo "5️⃣  Deploying credential proxy..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Create incidentfox-prod namespace (where credential-resolver runs)
kubectl create namespace incidentfox-prod 2>/dev/null || true

# Copy secrets to incidentfox-prod namespace (credential-resolver needs them)
kubectl delete secret incidentfox-secrets -n incidentfox-prod 2>/dev/null || true
kubectl get secret incidentfox-secrets -n default -o json | \
    jq '.metadata.namespace = "incidentfox-prod" | del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp)' | \
    kubectl create -f - >/dev/null 2>&1 || true

# Build credential-resolver image
echo "Building credential-resolver image..."
docker build -q -t credential-resolver:local ./credential-proxy

# Load into Kind
echo "Loading credential-resolver into Kind..."
kind load docker-image credential-resolver:local --name incidentfox

# Deploy credential-resolver
echo "Deploying credential-resolver..."
kubectl apply -f credential-proxy/k8s/deployment-local.yaml
kubectl apply -f credential-proxy/k8s/service-local.yaml

# Wait for credential-resolver to be ready
kubectl rollout status deployment/credential-resolver -n incidentfox-prod --timeout=60s

# Deploy envoy config ConfigMap (in default namespace where sandboxes run)
echo "Deploying envoy proxy config..."
kubectl apply -f credential-proxy/k8s/configmap-envoy-local.yaml

echo "✅ Credential proxy deployed"
echo ""

# Step 6: Deploy sandbox template (without gVisor for local dev)
echo "6️⃣  Deploying sandbox template..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
# Remove gVisor runtimeClassName for local dev (not available in Kind)
grep -v "runtimeClassName" k8s/sandbox-template.yaml | kubectl apply -f - >/dev/null
echo "✅ Sandbox template deployed"
echo ""

# Final summary
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║          ✅ Local Development Setup Complete!                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 What was installed:"
echo "  ✅ Kind cluster (incidentfox)"
echo "  ✅ agent-sandbox controller"
echo "  ✅ Sandbox Router"
echo "  ✅ Service patcher"
echo "  ✅ Credential proxy (Envoy + credential-resolver)"
echo "  ✅ Sandbox template"
echo "  ✅ Secrets"
echo ""
echo "🚀 Next steps:"
echo "  1. Run: make dev"
echo "  2. Test with curl"
echo "  3. Press Ctrl+C to stop and cleanup"
echo ""
echo "💡 You only need to run this setup script once."
echo "   From now on, just use 'make dev' to start testing."
echo ""

