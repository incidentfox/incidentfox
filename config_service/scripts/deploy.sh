#!/bin/bash
set -e

# Deployment script for Config Service

AWS_REGION="${AWS_REGION:-us-west-2}"
AWS_PROFILE="${AWS_PROFILE:-playground}"
ECR_REPOSITORY="incidentfox-config-service"
NAMESPACE="incidentfox"

echo "🚀 Deploying Config Service"
echo "  Region: $AWS_REGION"
echo "  Profile: $AWS_PROFILE"
echo "  Namespace: $NAMESPACE"

# Get AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile $AWS_PROFILE)
ECR_URL="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY"

echo "  ECR: $ECR_URL"

# Login to ECR
echo "📦 Logging in to ECR..."
aws ecr get-login-password --region $AWS_REGION --profile $AWS_PROFILE | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build Docker image (for AMD64 platform)
echo "🔨 Building Docker image for linux/amd64..."
cd "$(dirname "$0")/.."  # Go to config_service root
docker build --platform linux/amd64 -t $ECR_REPOSITORY:latest .

# Tag image
echo "🏷️  Tagging image..."
GIT_SHA=$(git rev-parse --short HEAD)
docker tag $ECR_REPOSITORY:latest $ECR_URL:latest
docker tag $ECR_REPOSITORY:latest $ECR_URL:$GIT_SHA

# Push to ECR
echo "⬆️  Pushing to ECR..."
docker push $ECR_URL:latest
docker push $ECR_URL:$GIT_SHA

# Update to new image tag (Kubernetes automatically detects and pulls)
echo "🔄 Updating deployment to new image..."
kubectl set image deployment/$ECR_REPOSITORY \
    $ECR_REPOSITORY=$ECR_URL:$GIT_SHA \
    -n $NAMESPACE

# Wait for rollout
echo "⏳ Waiting for rollout to complete..."
kubectl rollout status deployment/$ECR_REPOSITORY -n $NAMESPACE --timeout=5m

echo "✅ Deployment complete!"
echo "📊 Check deployment status:"
echo "  kubectl get deployment $ECR_REPOSITORY -n $NAMESPACE"
echo "📝 View logs:"
echo "  kubectl logs -f deployment/$ECR_REPOSITORY -n $NAMESPACE"
echo "🔍 Check pods:"
echo "  kubectl get pods -n $NAMESPACE -l app=$ECR_REPOSITORY"
