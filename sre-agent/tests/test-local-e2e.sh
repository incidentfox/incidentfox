#!/bin/bash
# End-to-end test script for local Kind deployment
# Tests new investigations, follow-ups, and sandbox reuse

set -e

echo "🧪 IncidentFox E2E Test Suite"
echo "=============================="
echo ""

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! kubectl get deployment sandbox-router-deployment &>/dev/null; then
    echo "❌ Sandbox Router not deployed. Run: make router-deploy"
    exit 1
fi

if ! kubectl get runtimeclass gvisor &>/dev/null; then
    echo "❌ gVisor RuntimeClass not found. Run: make gvisor-install"
    exit 1
fi

if ! kubectl get secret incidentfox-secrets &>/dev/null; then
    echo "❌ Secrets not configured. Run: make k8s-secrets"
    exit 1
fi

# Note: Port-forward is needed for local dev because server.py runs outside the cluster
# In production, server.py runs inside the cluster and uses K8s service DNS
if ! lsof -i :8080 &>/dev/null; then
    echo "⚠️  Port-forward not detected. Starting it..."
    kubectl port-forward svc/sandbox-router-svc 8080:8080 >/dev/null 2>&1 &
    PORT_FORWARD_PID=$!
    sleep 3
    echo "✅ Port-forward started (PID: $PORT_FORWARD_PID)"
else
    echo "✅ Port-forward already running on :8080"
    PORT_FORWARD_PID=""
fi

# Check if server is running
if ! lsof -i :8000 &>/dev/null; then
    echo "❌ Server not running. Start it with:"
    echo "   cd sre-agent"
    echo "   source .venv/bin/activate"
    echo "   ROUTER_LOCAL_PORT=8080 python server.py"
    [ -n "$PORT_FORWARD_PID" ] && kill $PORT_FORWARD_PID
    exit 1
fi

echo "✅ Server is running"
echo ""

# Test 1: New investigation
echo "Test 1: New Investigation"
echo "-------------------------"
RESPONSE=$(curl -s -X POST http://localhost:8000/investigate \
    -H "Content-Type: application/json" \
    -d '{"prompt": "What is 12 + 8?"}')

# Extract thread_id from response
THREAD_ID=$(echo "$RESPONSE" | grep -o 'thread-[a-f0-9]*' | head -1)

if [ -z "$THREAD_ID" ]; then
    echo "❌ Failed to get thread_id from response"
    echo "Response: $RESPONSE"
    [ -n "$PORT_FORWARD_PID" ] && kill $PORT_FORWARD_PID
    exit 1
fi

echo "Thread ID: $THREAD_ID"
echo "Response preview:"
echo "$RESPONSE" | head -20

# Verify sandbox was actually created in cluster
sleep 3
SANDBOX_NAME="investigation-$THREAD_ID"
if kubectl get sandbox "$SANDBOX_NAME" &>/dev/null; then
    echo "✅ Test 1 PASSED - Sandbox created in cluster"
    kubectl get sandbox "$SANDBOX_NAME" -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,RUNTIME:.spec.podTemplate.spec.runtimeClassName
else
    echo "❌ Test 1 FAILED - Sandbox not found in cluster"
    echo "   Expected: $SANDBOX_NAME"
    [ -n "$PORT_FORWARD_PID" ] && kill $PORT_FORWARD_PID
    exit 1
fi

echo ""
sleep 2

# Test 2: Follow-up question (sandbox reuse)
echo "Test 2: Follow-Up (Sandbox Reuse)"
echo "----------------------------------"

# Get sandbox creation time before follow-up
SANDBOX_CREATED=$(kubectl get sandbox "$SANDBOX_NAME" -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null)

RESPONSE=$(curl -s -X POST http://localhost:8000/investigate \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": \"What is 50 / 5?\", \"thread_id\": \"$THREAD_ID\"}")

echo "Response preview:"
echo "$RESPONSE" | head -20

# Verify same sandbox still exists (not recreated)
sleep 2
SANDBOX_CREATED_AFTER=$(kubectl get sandbox "$SANDBOX_NAME" -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null)

if [ "$SANDBOX_CREATED" = "$SANDBOX_CREATED_AFTER" ]; then
    echo "✅ Test 2 PASSED - Same sandbox reused (not recreated)"
    echo "   Created: $SANDBOX_CREATED"
else
    echo "❌ Test 2 FAILED - Sandbox was recreated (should be reused)"
    [ -n "$PORT_FORWARD_PID" ] && kill $PORT_FORWARD_PID
    exit 1
fi

echo ""
sleep 2

# Test 3: Concurrent investigation (different thread)
echo "Test 3: Concurrent Investigation"
echo "---------------------------------"
RESPONSE=$(curl -s -X POST http://localhost:8000/investigate \
    -H "Content-Type: application/json" \
    -d '{"prompt": "What is 7 * 3?"}')

THREAD_ID_2=$(echo "$RESPONSE" | grep -o 'thread-[a-f0-9]*' | head -1)

if [ -z "$THREAD_ID_2" ]; then
    echo "❌ Failed to get second thread_id"
    [ -n "$PORT_FORWARD_PID" ] && kill $PORT_FORWARD_PID
    exit 1
fi

echo "New Thread ID: $THREAD_ID_2"
echo "Response preview:"
echo "$RESPONSE" | head -20

# Verify second sandbox was created
sleep 3
SANDBOX_NAME_2="investigation-$THREAD_ID_2"
if kubectl get sandbox "$SANDBOX_NAME_2" &>/dev/null; then
    echo "✅ Test 3 PASSED - Second sandbox created for concurrent investigation"
    echo "   Sandbox 1: $SANDBOX_NAME"
    echo "   Sandbox 2: $SANDBOX_NAME_2"
    kubectl get sandbox -l managed-by=incidentfox-server -o custom-columns=NAME:.metadata.name,RUNTIME:.spec.podTemplate.spec.runtimeClassName
else
    echo "❌ Test 3 FAILED - Second sandbox not found"
    [ -n "$PORT_FORWARD_PID" ] && kill $PORT_FORWARD_PID
    exit 1
fi

echo ""
sleep 2

# Test 4: Verify gVisor runtime
echo "Test 4: Verify gVisor Runtime"
echo "------------------------------"
SANDBOXES=$(kubectl get sandbox -o json | jq -r '.items[] | select(.metadata.labels["managed-by"]=="incidentfox-server") | "\(.metadata.name) \(.spec.podTemplate.spec.runtimeClassName)"')

echo "Active sandboxes:"
echo "$SANDBOXES"

if echo "$SANDBOXES" | grep -q "gvisor"; then
    echo "✅ Test 4 PASSED - Sandboxes using gVisor runtime"
else
    echo "⚠️  Test 4 WARNING - gVisor runtime not detected"
fi

echo ""

# Summary
echo "================================"
echo "✅ All E2E Tests PASSED!"
echo "================================"
echo ""
echo "Created sandboxes:"
kubectl get sandbox -l managed-by=incidentfox-server -o custom-columns=NAME:.metadata.name,RUNTIME:.spec.podTemplate.spec.runtimeClassName,AGE:.metadata.creationTimestamp

echo ""
echo "Cleanup:"
echo "  kubectl delete sandbox investigation-$THREAD_ID"
echo "  kubectl delete sandbox investigation-$THREAD_ID_2"
echo "  make k8s-clean  # Delete all sandboxes"

# Cleanup port-forward if we started it
if [ -n "$PORT_FORWARD_PID" ]; then
    echo ""
    echo "Stopping port-forward (PID: $PORT_FORWARD_PID)..."
    kill $PORT_FORWARD_PID
fi


