#!/bin/bash
# Production Environment Setup (First-Time Only)
# Creates AWS EKS cluster with all required components
# Usage: ./scripts/setup-prod.sh

set -e

# Configuration
CLUSTER_NAME="${CLUSTER_NAME:-incidentfox-prod}"
REGION="${REGION:-us-west-2}"
NODE_TYPE="${NODE_TYPE:-t3.medium}"
NODE_COUNT="${NODE_COUNT:-3}"
K8S_VERSION="${K8S_VERSION:-1.31}"
NAMESPACE="${NAMESPACE:-incidentfox-prod}"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║      🚀 Production Environment Setup (First-Time Only)         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Configuration:"
echo "  Cluster: $CLUSTER_NAME"
echo "  Region: $REGION"
echo "  Nodes: $NODE_COUNT x $NODE_TYPE"
echo "  Kubernetes: $K8S_VERSION"
echo "  Namespace: $NAMESPACE"
echo ""

# Check prerequisites
echo "📋 Checking prerequisites..."
command -v eksctl >/dev/null 2>&1 || { echo "❌ eksctl not found. Install: https://eksctl.io"; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "❌ kubectl not found"; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "❌ AWS CLI not found"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "❌ Docker not found"; exit 1; }

# Check AWS credentials
aws sts get-caller-identity >/dev/null 2>&1 || { echo "❌ AWS credentials not configured"; exit 1; }
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "✅ AWS Account: $AWS_ACCOUNT_ID"
echo ""

# Step 1: Create EKS Cluster
echo "1️⃣  Creating EKS Cluster..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if eksctl get cluster --name $CLUSTER_NAME --region $REGION >/dev/null 2>&1; then
    echo "⚠️  Cluster $CLUSTER_NAME already exists"
    echo ""
    read -p "Continue with existing cluster? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 1
    fi
    echo "Using existing cluster..."
else
    echo "Creating cluster (this takes ~15 minutes)..."
    eksctl create cluster \
        --name $CLUSTER_NAME \
        --region $REGION \
        --version $K8S_VERSION \
        --nodegroup-name standard-workers \
        --node-type $NODE_TYPE \
        --nodes $NODE_COUNT \
        --nodes-min 2 \
        --nodes-max 6 \
        --managed \
        --with-oidc
    echo "✅ EKS Cluster created"
fi

# Update kubeconfig
eksctl utils write-kubeconfig --cluster=$CLUSTER_NAME --region=$REGION
echo ""

# Step 2: Create ECR Repositories
echo "2️⃣  Creating ECR repositories..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Create incidentfox-agent repository
REPO_NAME="incidentfox-agent"
if aws ecr describe-repositories --repository-names $REPO_NAME --region $REGION >/dev/null 2>&1; then
    echo "✅ Repository already exists: $REPO_NAME"
else
    aws ecr create-repository \
        --repository-name $REPO_NAME \
        --region $REGION \
        --image-scanning-configuration scanOnPush=true >/dev/null
    echo "✅ Repository created: $REPO_NAME"
fi

# Create credential-resolver repository
REPO_NAME="credential-resolver"
if aws ecr describe-repositories --repository-names $REPO_NAME --region $REGION >/dev/null 2>&1; then
    echo "✅ Repository already exists: $REPO_NAME"
else
    aws ecr create-repository \
        --repository-name $REPO_NAME \
        --region $REGION \
        --image-scanning-configuration scanOnPush=true >/dev/null
    echo "✅ Repository created: $REPO_NAME"
fi

# Create slack-bot repository
REPO_NAME="slack-bot"
if aws ecr describe-repositories --repository-names $REPO_NAME --region $REGION >/dev/null 2>&1; then
    echo "✅ Repository already exists: $REPO_NAME"
else
    aws ecr create-repository \
        --repository-name $REPO_NAME \
        --region $REGION \
        --image-scanning-configuration scanOnPush=true >/dev/null
    echo "✅ Repository created: $REPO_NAME"
fi
echo ""

# Step 3: Install agent-sandbox Controller
echo "3️⃣  Installing agent-sandbox controller..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
kubectl apply -f https://github.com/kubernetes-sigs/agent-sandbox/releases/latest/download/install.yaml
echo "Waiting for controller..."
kubectl wait --for=condition=ready pod -l control-plane=controller-manager -n agent-sandbox-system --timeout=120s 2>/dev/null || echo "Controller starting..."
echo "✅ agent-sandbox controller installed"
echo ""

# Step 4: Install gVisor (optional but recommended)
echo "4️⃣  Installing gVisor..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f "k8s/aws/gvisor-installer.yaml" ]; then
    kubectl apply -f k8s/aws/gvisor-installer.yaml
    echo "Waiting for gVisor installation..."
    kubectl wait --for=condition=ready pod -l app=gvisor-installer -n kube-system --timeout=120s 2>/dev/null || echo "gVisor installing..."
    echo "✅ gVisor installed"
else
    echo "⚠️  gVisor installer not found (optional, skipping)"
fi
echo ""

# Step 5: Create Namespace
echo "5️⃣  Creating namespace and secrets..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f - >/dev/null

# Load .env if exists
if [ -f ".env" ]; then
    source .env
fi

# Get API keys
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  ANTHROPIC_API_KEY not set in .env"
    echo "Please enter your shared Anthropic API key (for free tier and non-BYOK customers):"
    read -r ANTHROPIC_API_KEY
fi

if [ -z "$JWT_SECRET" ]; then
    echo "⚠️  JWT_SECRET not set in .env, generating..."
    JWT_SECRET=$(openssl rand -hex 32)
    echo "💡 Add this to your .env file: JWT_SECRET=$JWT_SECRET"
fi

# Multi-tenant architecture secrets setup:
# 1. Shared Anthropic key -> AWS Secrets Manager (accessed via IRSA by credential-resolver)
# 2. Platform secrets -> K8s secrets (JWT for auth, Laminar for our observability)
# 3. Customer BYOK keys -> config-service RDS (set by customers via UI/API)

echo ""
echo "Writing shared Anthropic key to AWS Secrets Manager..."
aws secretsmanager create-secret \
    --name incidentfox/prod/anthropic \
    --description "Shared Anthropic API key for free tier and non-BYOK customers" \
    --secret-string "$ANTHROPIC_API_KEY" \
    --region $REGION 2>/dev/null && echo "✅ Created secret in Secrets Manager" || \
aws secretsmanager update-secret \
    --secret-id incidentfox/prod/anthropic \
    --secret-string "$ANTHROPIC_API_KEY" \
    --region $REGION >/dev/null && echo "✅ Updated secret in Secrets Manager"

echo ""
echo "Creating K8s platform secrets (JWT + Laminar)..."
kubectl create secret generic incidentfox-secrets \
    --namespace=$NAMESPACE \
    --from-literal=jwt-secret="$JWT_SECRET" \
    --from-literal=laminar-api-key="${LMNR_PROJECT_API_KEY:-}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "✅ Platform secrets created"
echo ""

# Step 6: Create ECR pull secret
echo "6️⃣  Creating ECR pull secret..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
kubectl create secret docker-registry ecr-registry-secret \
    --namespace=$NAMESPACE \
    --docker-server=$AWS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com \
    --docker-username=AWS \
    --docker-password=$(aws ecr get-login-password --region $REGION) \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
echo "✅ ECR pull secret created"
echo ""

# Step 7: Deploy Service Patcher
echo "7️⃣  Deploying service patcher..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
kubectl apply -f k8s/service-patcher.yaml
kubectl wait --for=condition=available --timeout=30s deployment/sandbox-service-patcher 2>/dev/null || echo "Service patcher starting..."
echo "✅ Service patcher deployed"
echo ""

# Step 8: Deploy Sandbox Template
echo "8️⃣  Deploying sandbox template..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
kubectl apply -f k8s/sandbox-template.yaml -n $NAMESPACE >/dev/null
echo "✅ Sandbox template deployed"
echo ""

# Step 9: Install Cluster Autoscaler
echo "9️⃣  Installing Cluster Autoscaler..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if Helm is installed, install if not
if ! command -v helm >/dev/null 2>&1; then
    echo "Helm not found, installing..."
    
    # Detect OS
    OS="$(uname -s)"
    case "${OS}" in
        Linux*)
            curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
            ;;
        Darwin*)
            if command -v brew >/dev/null 2>&1; then
                brew install helm
            else
                curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
            fi
            ;;
        *)
            echo "⚠️  Unsupported OS: ${OS}"
            echo "   Install Helm manually: https://helm.sh/docs/intro/install/"
            echo "   Then rerun: make setup-prod"
            exit 1
            ;;
    esac
    
    echo "✅ Helm installed"
fi
    # Create IAM service account for cluster autoscaler
    echo "Creating IAM service account for cluster autoscaler..."
    eksctl create iamserviceaccount \
        --name cluster-autoscaler \
        --namespace kube-system \
        --cluster $CLUSTER_NAME \
        --region $REGION \
        --attach-policy-arn arn:aws:iam::aws:policy/AutoScalingFullAccess \
        --approve \
        --override-existing-serviceaccounts 2>/dev/null || echo "  Service account already exists"
    
    # Add Helm repo
    helm repo add autoscaler https://kubernetes.github.io/autoscaler 2>/dev/null || true
    helm repo update >/dev/null
    
    # Install cluster autoscaler
    echo "Installing cluster autoscaler..."
    helm upgrade --install cluster-autoscaler autoscaler/cluster-autoscaler \
        --namespace kube-system \
        --set autoDiscovery.clusterName=$CLUSTER_NAME \
        --set awsRegion=$REGION \
        --set rbac.serviceAccount.name=cluster-autoscaler \
        --set rbac.serviceAccount.annotations."eks\.amazonaws\.com/role-arn"="arn:aws:iam::${AWS_ACCOUNT_ID}:role/eksctl-${CLUSTER_NAME}-addon-iamserviceaccount-kube-system-cluster-autoscaler" \
        --wait --timeout=3m 2>/dev/null && {
            echo "✅ Cluster Autoscaler installed (scales nodes 2-6)"
        } || {
            echo "⚠️  Cluster Autoscaler installation had issues"
            echo "   You can install it manually later with:"
            echo "     helm install cluster-autoscaler autoscaler/cluster-autoscaler \\"
            echo "       --namespace kube-system \\"
            echo "       --set autoDiscovery.clusterName=$CLUSTER_NAME \\"
            echo "       --set awsRegion=$REGION"
        }
echo ""

# Final summary
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        ✅ Production Environment Setup Complete!               ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 What was created:"
echo "  ✅ EKS cluster: $CLUSTER_NAME"
echo "  ✅ ECR repositories: incidentfox-agent, credential-resolver, slack-bot"
echo "  ✅ agent-sandbox controller"
echo "  ✅ gVisor runtime"
echo "  ✅ Namespace: $NAMESPACE"
echo "  ✅ Secrets configured"
echo "  ✅ Service patcher"
echo "  ✅ Sandbox template"
echo "  ✅ Cluster Autoscaler (scales nodes 2-6)"
echo ""
echo "🚀 Next steps:"
echo "  1. Run: make deploy-prod"
echo "  2. Get URL: make prod-url"
echo "  3. Test the deployment"
echo ""
echo "💡 You only need to run this setup script once."
echo "   From now on, just use 'make deploy-prod' to deploy code changes."
echo ""
echo "💰 Estimated cost: ~\$166/month for base infrastructure"
echo ""
echo "📈 Auto-scaling enabled:"
echo "  • Pods: 2-10 replicas (HPA)"
echo "  • Nodes: 2-6 nodes (Cluster Autoscaler)"
echo "  • Scales down when idle for cost savings"
echo ""

