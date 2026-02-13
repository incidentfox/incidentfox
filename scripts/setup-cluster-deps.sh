#!/bin/bash
# Install cluster-level dependencies required before 'helm install incidentfox'
# This script is idempotent - safe to run multiple times.
#
# Prerequisites:
#   - kubectl configured for the target cluster
#   - helm v3 installed
#
# Dependencies installed:
#   1. agent-sandbox CRDs + controller (Sandbox, SandboxTemplate, SandboxClaim, SandboxWarmPool)

set -e

echo "=== IncidentFox Cluster Dependencies ==="
echo "Cluster: $(kubectl config current-context)"
echo ""

# ---------- agent-sandbox ----------
AGENT_SANDBOX_VERSION="${AGENT_SANDBOX_VERSION:-v0.1.1}"
echo "1/1  agent-sandbox ${AGENT_SANDBOX_VERSION}"

if kubectl get crd sandboxes.agents.x-k8s.io &> /dev/null; then
    echo "     Already installed, applying updates..."
else
    echo "     Installing..."
fi

kubectl apply -f "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${AGENT_SANDBOX_VERSION}/manifest.yaml"
kubectl apply -f "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${AGENT_SANDBOX_VERSION}/extensions.yaml"

echo "     Waiting for controller..."
kubectl wait --for=condition=ready --timeout=120s \
    pod -l app=agent-sandbox-controller \
    -n agent-sandbox-system 2>/dev/null || echo "     Controller starting (may take a minute)..."
echo "     Done"
echo ""

echo "=== All dependencies installed ==="
echo ""
echo "Next: helm install incidentfox charts/incidentfox -f charts/incidentfox/values.<env>.yaml"
