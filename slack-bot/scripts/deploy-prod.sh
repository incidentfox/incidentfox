#!/bin/bash
# Deploy Slack Bot to Production
# Usage: ./scripts/deploy-prod.sh

set -e

echo "🤖 SLACK-BOT PRODUCTION DEPLOYMENT"
echo "======================================"
echo ""

# Check prerequisites
if [ -f "../.env" ]; then
    echo "  Using root .env file"
    ENV_FILE="../.env"
elif [ -f ".env" ]; then
    echo "  Using local .env file"
    ENV_FILE=".env"
else
    echo "❌ .env file not found. Create it in repo root."
    exit 1
fi

# Load secrets
source "$ENV_FILE"
if [ -z "$SLACK_CLIENT_ID" ]; then
    echo "❌ SLACK_CLIENT_ID not set in .env"
    exit 1
fi
if [ -z "$SLACK_CLIENT_SECRET" ]; then
    echo "❌ SLACK_CLIENT_SECRET not set in .env"
    exit 1
fi
if [ -z "$SLACK_SIGNING_SECRET" ]; then
    echo "❌ SLACK_SIGNING_SECRET not set in .env"
    exit 1
fi

# Switch to production context
echo "1️⃣  Switching to production cluster..."
kubectl config use-context arn:aws:eks:us-west-2:103002841599:cluster/incidentfox-prod

# Login to ECR
echo ""
echo "2️⃣  Logging into ECR..."
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 103002841599.dkr.ecr.us-west-2.amazonaws.com

# Build and push multi-platform image
echo ""
echo "3️⃣  Building multi-platform slack-bot image..."
docker buildx create --use --name multiplatform 2>/dev/null || docker buildx use multiplatform
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/slack-bot:latest \
    --push \
    .

# Update secrets
echo ""
echo "4️⃣  Updating production secrets..."
kubectl create secret generic slack-bot-secrets \
    --namespace=incidentfox-prod \
    --from-literal=slack-signing-secret="${SLACK_SIGNING_SECRET}" \
    --from-literal=slack-client-id="${SLACK_CLIENT_ID}" \
    --from-literal=slack-client-secret="${SLACK_CLIENT_SECRET}" \
    --from-literal=incident-io-api-key="${INCIDENT_IO_API_KEY:-}" \
    --dry-run=client -o yaml | kubectl apply -f -

# Deploy slack-bot
echo ""
echo "5️⃣  Deploying slack-bot..."
kubectl apply -f k8s/serviceaccount.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service-https.yaml
kubectl apply -f k8s/hpa.yaml
kubectl rollout status deployment/slack-bot -n incidentfox-prod --timeout=3m

# Get public URL
echo ""
echo "✅ DEPLOYMENT COMPLETE!"
echo ""
echo "📡 Slack Bot URLs (HTTPS):"
echo "  Event Subscriptions: https://slack.incidentfox.ai/slack/events"
echo "  OAuth Install: https://slack.incidentfox.ai/slack/install"
echo "  OAuth Redirect: https://slack.incidentfox.ai/slack/oauth_redirect"
echo ""
echo "📋 Next Steps for Public Distribution:"
echo "  1. Go to https://api.slack.com/apps → Your App"
echo "  2. Manage Distribution → Activate Public Distribution"
echo "  3. Share your installation link with users!"
echo ""
echo "View logs:"
echo "  kubectl logs -n incidentfox-prod -l app=slack-bot --tail=50 -f"
echo ""
