#!/bin/bash
# Setup local kind cluster for agent-sandbox

set -e

echo "🚀 Setting up kind cluster for IncidentFox agent-sandbox..."

# Check if kind is installed
if ! command -v kind &> /dev/null; then
    echo "📦 Installing kind..."
    brew install kind
fi

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo "📦 Installing kubectl..."
    brew install kubectl
fi

# Create kind cluster if it doesn't exist
if ! kind get clusters | grep -q "incidentfox"; then
    echo "🔧 Creating kind cluster 'incidentfox'..."
    kind create cluster --name incidentfox --config - <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraMounts:
  - hostPath: /var/run/docker.sock
    containerPath: /var/run/docker.sock
EOF
else
    echo "✅ Kind cluster 'incidentfox' already exists"
fi

# Set kubectl context
kubectl config use-context kind-incidentfox

# Install agent-sandbox CRDs and controller
echo "📦 Installing agent-sandbox..."
export VERSION="v0.1.0"

# Install core Sandbox CRD
kubectl apply -f https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${VERSION}/manifest.yaml

# Install extensions (SandboxTemplate, SandboxClaim, SandboxWarmPool)
echo "📦 Installing agent-sandbox extensions..."
kubectl apply -f https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${VERSION}/extensions.yaml

# Wait for controller to be ready
echo "⏳ Waiting for agent-sandbox controller..."
sleep 5  # Give pods time to be created
kubectl wait --for=condition=ready --timeout=120s \
    pod -l app=agent-sandbox-controller \
    -n agent-sandbox-system 2>/dev/null || echo "  Controller starting (may take a minute)..."

echo "✅ Kind cluster ready!"
echo ""
echo "Next steps:"
echo "  1. Build agent Docker image: make docker-build"
echo "  2. Load image into kind: make docker-load"
echo "  3. Deploy sandbox template: kubectl apply -f k8s/sandbox-template.yaml"

