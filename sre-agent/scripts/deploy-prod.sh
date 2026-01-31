#!/bin/bash
# ONE-COMMAND Production Deployment
# Usage: ./scripts/deploy-prod.sh

set -e

echo "🚀 ONE-COMMAND PRODUCTION DEPLOYMENT"
echo "======================================="
echo ""

# Check prerequisites
# Look for .env file - prefer root .env (has real credentials), fallback to local
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

# Load environment (optional keys for observability)
source "$ENV_FILE"
# Note: ANTHROPIC_API_KEY is NOT required here - customer keys are in config-service,
# and the shared trial key is fetched from AWS Secrets Manager via IRSA.
# Only LMNR_PROJECT_API_KEY (our observability) and JWT_SECRET are used from .env.

# Switch to production context
echo "1️⃣  Switching to production cluster..."
kubectl config use-context arn:aws:eks:us-west-2:103002841599:cluster/incidentfox-prod

# Login to ECR (required for docker buildx --push)
echo ""
echo "2️⃣  Logging into ECR..."
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 103002841599.dkr.ecr.us-west-2.amazonaws.com

# Build and push multi-platform sre-agent image
echo ""
echo "3️⃣  Building multi-platform sre-agent image..."
docker buildx create --use --name multiplatform 2>/dev/null || docker buildx use multiplatform
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-agent:latest \
    --push \
    .

# Build and push credential-resolver image
echo ""
echo "4️⃣  Building credential-resolver image..."
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/credential-resolver:latest \
    -f credential-proxy/Dockerfile \
    credential-proxy \
    --push

# Update secrets (platform secrets only - customer keys are in config-service)
echo ""
echo "5️⃣  Updating production secrets..."
# Generate JWT secret if not provided (should be set in .env for consistency)
JWT_SECRET="${JWT_SECRET:-$(openssl rand -hex 32)}"

# Multi-tenant architecture:
# - jwt-secret: Required for sre-agent <-> credential-resolver auth
# - laminar-api-key: OUR observability tracing (not customer's)
# - Customer API keys (Anthropic BYOK, Coralogix, Datadog): stored in config-service RDS
# - Shared Anthropic key (free trials): fetched from AWS Secrets Manager via IRSA
kubectl create secret generic incidentfox-secrets \
    --namespace=incidentfox-prod \
    --from-literal=jwt-secret="${JWT_SECRET}" \
    --from-literal=laminar-api-key="${LMNR_PROJECT_API_KEY:-}" \
    --dry-run=client -o yaml | kubectl apply -f -

# Update ECR pull secret
echo ""
echo "6️⃣  Refreshing ECR credentials for K8s..."
kubectl create secret docker-registry ecr-registry-secret \
    --docker-server=103002841599.dkr.ecr.us-west-2.amazonaws.com \
    --docker-username=AWS \
    --docker-password=$(aws ecr get-login-password --region us-west-2) \
    --namespace=incidentfox-prod \
    --dry-run=client -o yaml | kubectl apply -f -

# Deploy credential-resolver (must be before sandbox template)
echo ""
echo "7️⃣  Deploying credential-resolver..."
kubectl apply -f credential-proxy/k8s/serviceaccount.yaml
kubectl apply -f credential-proxy/k8s/deployment.yaml
kubectl apply -f credential-proxy/k8s/service.yaml
kubectl rollout status deployment/credential-resolver -n incidentfox-prod --timeout=2m

# Deploy envoy proxy config (in incidentfox-prod namespace for sandbox pods)
echo ""
echo "8️⃣  Deploying envoy proxy config..."
kubectl apply -f credential-proxy/k8s/configmap-envoy.yaml

# Deploy service patcher (cluster-wide)
echo ""
echo "9️⃣  Deploying service patcher..."
kubectl apply -f k8s/service-patcher.yaml

# Deploy sandbox template
echo ""
echo "🔟  Deploying sandbox template..."
kubectl apply -f k8s/sandbox-template.yaml -n incidentfox-prod

# Deploy updated YAML (picks up new image + config changes like USE_GVISOR)
echo ""
echo "1️⃣1️⃣  Deploying updated server configuration..."
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
echo "  kubectl logs -n incidentfox-prod -l app=credential-resolver --tail=50"
