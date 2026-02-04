#!/bin/bash
# Deploy config-service to EKS (same VPC as RDS)
# This script is idempotent - safe to run multiple times
set -e

NAMESPACE="incidentfox-prod"
REGION="us-west-2"
ECR_REGISTRY="103002841599.dkr.ecr.us-west-2.amazonaws.com"
IMAGE_NAME="incidentfox-config-service"

echo "🚀 Deploying config-service to EKS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 1: Ensure namespace exists
echo "1️⃣  Ensuring namespace exists..."
kubectl get namespace $NAMESPACE > /dev/null 2>&1 || kubectl create namespace $NAMESPACE
echo "   ✅ Namespace: $NAMESPACE"

# Step 2: Refresh ECR credentials
echo ""
echo "2️⃣  Refreshing ECR credentials..."
aws ecr get-login-password --region $REGION | kubectl create secret docker-registry ecr-registry-secret \
  --docker-server=$ECR_REGISTRY \
  --docker-username=AWS \
  --docker-password=$(aws ecr get-login-password --region $REGION) \
  --namespace=$NAMESPACE \
  --dry-run=client -o yaml | kubectl apply -f -
echo "   ✅ ECR credentials refreshed"

# Step 3: Create K8s secrets from AWS Secrets Manager
echo ""
echo "3️⃣  Creating K8s secrets from AWS Secrets Manager..."

# Get RDS credentials
RDS_SECRET=$(aws secretsmanager get-secret-value --secret-id "incidentfox/prod/rds" --region $REGION --query 'SecretString' --output text 2>/dev/null || echo "{}")
if [ "$RDS_SECRET" == "{}" ]; then
  echo "   ❌ ERROR: incidentfox/prod/rds secret not found in Secrets Manager"
  echo "   Please create RDS first using: config_service/k8s/setup-rds.sh"
  exit 1
fi

DB_HOST=$(echo $RDS_SECRET | jq -r '.host')
DB_NAME=$(echo $RDS_SECRET | jq -r '.dbname')
DB_USERNAME=$(echo $RDS_SECRET | jq -r '.username')
DB_PASSWORD=$(echo $RDS_SECRET | jq -r '.password')

# Get config-service secrets (token pepper, admin token, encryption key)
CONFIG_SECRET=$(aws secretsmanager get-secret-value --secret-id "incidentfox/prod/config-service" --region $REGION --query 'SecretString' --output text 2>/dev/null || echo "{}")
if [ "$CONFIG_SECRET" == "{}" ]; then
  echo "   ⚠️  Config service secrets not found, generating new ones..."
  TOKEN_PEPPER=$(openssl rand -base64 32)
  ADMIN_TOKEN=$(openssl rand -base64 32)
  # Generate Fernet encryption key (32 bytes, base64-encoded = 44 chars)
  ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  aws secretsmanager create-secret \
    --name "incidentfox/prod/config-service" \
    --description "Config service secrets (auth + column encryption)" \
    --secret-string "{\"token_pepper\":\"$TOKEN_PEPPER\",\"admin_token\":\"$ADMIN_TOKEN\",\"encryption_key\":\"$ENCRYPTION_KEY\"}" \
    --region $REGION > /dev/null
else
  TOKEN_PEPPER=$(echo $CONFIG_SECRET | jq -r '.token_pepper')
  ADMIN_TOKEN=$(echo $CONFIG_SECRET | jq -r '.admin_token')
  # Get encryption key, or generate if missing (for existing deployments)
  ENCRYPTION_KEY=$(echo $CONFIG_SECRET | jq -r '.encryption_key')
  if [ "$ENCRYPTION_KEY" == "null" ] || [ -z "$ENCRYPTION_KEY" ]; then
    echo "   ⚠️  Encryption key missing, generating and updating secret..."
    ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    aws secretsmanager update-secret \
      --secret-id "incidentfox/prod/config-service" \
      --secret-string "{\"token_pepper\":\"$TOKEN_PEPPER\",\"admin_token\":\"$ADMIN_TOKEN\",\"encryption_key\":\"$ENCRYPTION_KEY\"}" \
      --region $REGION > /dev/null
  fi
fi

# Get GitHub App secrets
GITHUB_SECRET=$(aws secretsmanager get-secret-value --secret-id "incidentfox/prod/github-app" --region $REGION --query 'SecretString' --output text 2>/dev/null || echo "{}")
if [ "$GITHUB_SECRET" == "{}" ]; then
  echo "   ⚠️  GitHub App secrets not found in Secrets Manager"
  echo "   To add GitHub App integration, create secret: incidentfox/prod/github-app"
  GITHUB_APP_ID=""
  GITHUB_APP_CLIENT_ID=""
  GITHUB_APP_CLIENT_SECRET=""
  GITHUB_APP_PRIVATE_KEY=""
  GITHUB_APP_WEBHOOK_SECRET=""
else
  GITHUB_APP_ID=$(echo $GITHUB_SECRET | jq -r '.app_id')
  GITHUB_APP_CLIENT_ID=$(echo $GITHUB_SECRET | jq -r '.client_id')
  GITHUB_APP_CLIENT_SECRET=$(echo $GITHUB_SECRET | jq -r '.client_secret')
  GITHUB_APP_PRIVATE_KEY=$(echo $GITHUB_SECRET | jq -r '.private_key')
  GITHUB_APP_WEBHOOK_SECRET=$(echo $GITHUB_SECRET | jq -r '.webhook_secret')
  echo "   ✅ GitHub App secrets retrieved"
fi

kubectl create secret generic config-service-secrets \
  --namespace=$NAMESPACE \
  --from-literal=db-host="$DB_HOST" \
  --from-literal=db-name="$DB_NAME" \
  --from-literal=db-username="$DB_USERNAME" \
  --from-literal=db-password="$DB_PASSWORD" \
  --from-literal=token-pepper="$TOKEN_PEPPER" \
  --from-literal=admin-token="$ADMIN_TOKEN" \
  --from-literal=encryption-key="$ENCRYPTION_KEY" \
  --from-literal=github-app-id="$GITHUB_APP_ID" \
  --from-literal=github-app-client-id="$GITHUB_APP_CLIENT_ID" \
  --from-literal=github-app-client-secret="$GITHUB_APP_CLIENT_SECRET" \
  --from-literal=github-app-private-key="$GITHUB_APP_PRIVATE_KEY" \
  --from-literal=github-app-webhook-secret="$GITHUB_APP_WEBHOOK_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "   ✅ Secrets created"
echo "   DB Host: $DB_HOST"

# Step 4: Deploy config-service
echo ""
echo "4️⃣  Deploying config-service..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
kubectl apply -f "$SCRIPT_DIR/deployment.yaml"

# Force a rollout to pick up the new image (since we use :latest tag)
kubectl rollout restart deployment/config-service -n $NAMESPACE

# Step 5: Wait for rollout
echo ""
echo "5️⃣  Waiting for rollout..."
kubectl rollout status deployment/config-service -n $NAMESPACE --timeout=3m

# Step 6: Run database migrations
echo ""
echo "6️⃣  Running database migrations..."
DATABASE_URL="postgresql+psycopg2://${DB_USERNAME}:${DB_PASSWORD}@${DB_HOST}:5432/${DB_NAME}?sslmode=require"
kubectl exec -n $NAMESPACE deployment/config-service -- env DATABASE_URL="$DATABASE_URL" alembic upgrade head

echo ""
echo "✅ DEPLOYMENT COMPLETE!"
echo ""
echo "Config Service URL (internal):"
echo "  http://config-service-svc.${NAMESPACE}.svc.cluster.local:8080"
echo ""
echo "Test with:"
echo "  kubectl exec -n $NAMESPACE deployment/config-service -- curl -s http://localhost:8080/health"
echo ""
echo "View logs:"
echo "  kubectl logs -n $NAMESPACE -l app=config-service --tail=50 -f"
