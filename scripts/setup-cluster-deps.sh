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
#   2. Karpenter (optional — set KARPENTER_ROLE_ARN to enable)

set -e

echo "=== IncidentFox Cluster Dependencies ==="
echo "Cluster: $(kubectl config current-context)"
echo ""

# ---------- agent-sandbox ----------
AGENT_SANDBOX_VERSION="${AGENT_SANDBOX_VERSION:-v0.1.1}"
echo "1/2  agent-sandbox ${AGENT_SANDBOX_VERSION}"

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

# ---------- Karpenter (optional, for production burst scaling) ----------
KARPENTER_VERSION="${KARPENTER_VERSION:-1.1.1}"
if [ -n "${KARPENTER_ROLE_ARN:-}" ]; then
    echo "2/2  Karpenter ${KARPENTER_VERSION}"

    # Resolve cluster name and endpoint
    CLUSTER_NAME="${CLUSTER_NAME:-$(kubectl config current-context | sed 's/arn:aws:eks:[^:]*:[^:]*:cluster\///')}"
    CLUSTER_ENDPOINT="${CLUSTER_ENDPOINT:-$(aws eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.endpoint' --output text)}"

    echo "     Cluster: ${CLUSTER_NAME}"
    echo "     Endpoint: ${CLUSTER_ENDPOINT}"

    helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
        --version "${KARPENTER_VERSION}" \
        --namespace karpenter --create-namespace \
        --set "settings.clusterName=${CLUSTER_NAME}" \
        --set "settings.clusterEndpoint=${CLUSTER_ENDPOINT}" \
        --set "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn=${KARPENTER_ROLE_ARN}" \
        ${KARPENTER_QUEUE_NAME:+--set "settings.interruptionQueue=${KARPENTER_QUEUE_NAME}"} \
        --set controller.resources.requests.cpu=200m \
        --set controller.resources.requests.memory=256Mi \
        --set controller.resources.limits.cpu=1 \
        --set controller.resources.limits.memory=1Gi \
        --wait

    echo "     Waiting for controller..."
    kubectl wait --for=condition=ready --timeout=120s \
        pod -l app.kubernetes.io/name=karpenter \
        -n karpenter 2>/dev/null || echo "     Karpenter starting (may take a minute)..."
    echo "     Done"
else
    echo "2/2  Karpenter (skipped — set KARPENTER_ROLE_ARN to enable)"
fi
echo ""

echo "=== All dependencies installed ==="
echo ""
echo "Next: helm install incidentfox charts/incidentfox -f charts/incidentfox/values.<env>.yaml"
