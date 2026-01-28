#!/bin/bash
# ONE-COMMAND Production Deployment
# Usage: ./scripts/deploy-prod-simple.sh

set -e

echo "🚀 ONE-COMMAND PRODUCTION DEPLOYMENT"
echo "======================================="
echo ""

# Check prerequisites
if [ ! -f ".env" ]; then
    echo "❌ .env file not found. Create it from .env.example"
    exit 1
fi

# Load API keys
source .env
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ ANTHROPIC_API_KEY not set in .env"
    exit 1
fi

# Switch to production context
echo "1️⃣  Switching to production cluster..."
kubectl config use-context arn:aws:eks:us-west-2:103002841599:cluster/incidentfox-prod

# Build and push multi-platform image
echo ""
echo "2️⃣  Building multi-platform Docker image..."
docker buildx create --use --name multiplatform 2>/dev/null || docker buildx use multiplatform
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-agent:latest \
    --push \
    .

# Update secrets
echo ""
echo "3️⃣  Updating production secrets..."
kubectl create secret generic incidentfox-secrets \
    --namespace=incidentfox-prod \
    --from-literal=anthropic-api-key="${ANTHROPIC_API_KEY}" \
    --from-literal=laminar-api-key="${LMNR_PROJECT_API_KEY:-}" \
    --dry-run=client -o yaml | kubectl apply -f -

# Update ECR pull secret
echo ""
echo "4️⃣  Refreshing ECR credentials..."
kubectl create secret docker-registry ecr-registry-secret \
    --docker-server=103002841599.dkr.ecr.us-west-2.amazonaws.com \
    --docker-username=AWS \
    --docker-password=$(aws ecr get-login-password --region us-west-2) \
    --namespace=incidentfox-prod \
    --dry-run=client -o yaml | kubectl apply -f -

# Deploy service patcher (cluster-wide)
echo ""
echo "5️⃣  Deploying service patcher..."
kubectl apply -f k8s/service-patcher.yaml

# Deploy sandbox template
echo ""
echo "6️⃣  Deploying sandbox template..."
kubectl apply -f k8s/sandbox-template.yaml -n incidentfox-prod

# Deploy updated YAML (picks up new image + config changes like USE_GVISOR)
echo ""
echo "7️⃣  Deploying updated server configuration..."
kubectl apply -f k8s/server-deployment.yaml -n incidentfox-prod
kubectl rollout status deployment/incidentfox-server -n incidentfox-prod --timeout=3m

# Get production URL
echo ""
echo "✅ DEPLOYMENT COMPLETE!"
echo ""
echo "Production URL:"
PROD_URL=$(kubectl get svc incidentfox-server-svc -n incidentfox-prod -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "  http://$PROD_URL"
echo ""
echo "Test with:"
echo "  curl http://$PROD_URL/health"
echo ""
echo "View logs:"
echo "  kubectl logs -n incidentfox-prod -l app=incidentfox-server --tail=50"

