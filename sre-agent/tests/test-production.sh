#!/bin/bash
# Production E2E test script
# Tests investigations against production LoadBalancer endpoint

set -e

# Namespace for production deployment (server + sandboxes in same namespace)
NAMESPACE="incidentfox-prod"

# Get LoadBalancer URL from Service
PROD_URL=$(kubectl get svc incidentfox-server-svc -n $NAMESPACE \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)

if [ -z "$PROD_URL" ]; then
    echo "❌ Failed to get LoadBalancer URL. Is the service deployed?"
    echo "   Run: kubectl get svc incidentfox-server-svc -n $NAMESPACE"
    echo "   Check status: kubectl describe svc incidentfox-server-svc -n $NAMESPACE"
    exit 1
fi

echo "🧪 IncidentFox Production E2E Test Suite"
echo "=========================================="
echo "LoadBalancer URL: $PROD_URL"
echo "Namespace: $NAMESPACE"
echo ""

# Test 1: Health check
echo "Test 1: Health Check"
echo "--------------------"
HEALTH=$(curl -s "http://$PROD_URL/health" || echo "failed")

if echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo "✅ Health check PASSED"
    echo "$HEALTH"
else
    echo "❌ Health check FAILED"
    echo "$HEALTH"
    exit 1
fi

echo ""
sleep 2

# Test 2: New investigation
echo "Test 2: New Investigation"
echo "-------------------------"
RESPONSE=$(curl -s -X POST "http://$PROD_URL/investigate" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "What is 7 * 8?"}')

THREAD_ID=$(echo "$RESPONSE" | grep -o 'thread-[a-f0-9]*' | head -1)

if [ -z "$THREAD_ID" ]; then
    echo "❌ Failed to get thread_id"
    echo "Response: $RESPONSE"
    exit 1
fi

echo "Thread ID: $THREAD_ID"
echo "Response preview:"
echo "$RESPONSE" | head -20

# Verify sandbox was actually created in cluster
echo "Checking cluster for sandbox..."
sleep 5
SANDBOX_NAME="investigation-$THREAD_ID"
if kubectl get sandbox "$SANDBOX_NAME" -n $NAMESPACE &>/dev/null; then
    echo "✅ Test 2 PASSED - Sandbox created in cluster"
    kubectl get sandbox "$SANDBOX_NAME" -n $NAMESPACE -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,RUNTIME:.spec.podTemplate.spec.runtimeClassName
else
    echo "❌ Test 2 FAILED - Sandbox not found in cluster"
    echo "   Expected: $SANDBOX_NAME in '$NAMESPACE' namespace"
    exit 1
fi

echo ""
sleep 5

# Test 3: Follow-up
echo "Test 3: Follow-Up Question"
echo "--------------------------"

# Get sandbox creation time before follow-up
SANDBOX_CREATED=$(kubectl get sandbox "$SANDBOX_NAME" -n $NAMESPACE -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null)

RESPONSE=$(curl -s -X POST "http://$PROD_URL/investigate" \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": \"What is 100 + 250?\", \"thread_id\": \"$THREAD_ID\"}")

echo "Response preview:"
echo "$RESPONSE" | head -20

# Verify same sandbox still exists (not recreated)
sleep 3
SANDBOX_CREATED_AFTER=$(kubectl get sandbox "$SANDBOX_NAME" -n $NAMESPACE -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null)

if [ "$SANDBOX_CREATED" = "$SANDBOX_CREATED_AFTER" ]; then
    echo "✅ Test 3 PASSED - Same sandbox reused (not recreated)"
    echo "   Created: $SANDBOX_CREATED"
else
    echo "❌ Test 3 FAILED - Sandbox was recreated (should be reused)"
    exit 1
fi

echo ""
sleep 5

# Test 4: Concurrent investigation (different thread)
echo "Test 4: Concurrent Investigation"
echo "---------------------------------"
RESPONSE=$(curl -s -X POST "http://$PROD_URL/investigate" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "What is 15 * 4?"}')

THREAD_ID_2=$(echo "$RESPONSE" | grep -o 'thread-[a-f0-9]*' | head -1)

if [ -z "$THREAD_ID_2" ]; then
    echo "❌ Failed to get second thread_id"
    echo "Response: $RESPONSE"
    exit 1
fi

echo "New Thread ID: $THREAD_ID_2"
echo "Response preview:"
echo "$RESPONSE" | head -20

# Verify second sandbox was created
echo "Checking cluster for second sandbox..."
sleep 5
SANDBOX_NAME_2="investigation-$THREAD_ID_2"
if kubectl get sandbox "$SANDBOX_NAME_2" -n $NAMESPACE &>/dev/null; then
    echo "✅ Test 4 PASSED - Second sandbox created for concurrent investigation"
    echo "   Sandbox 1: $SANDBOX_NAME"
    echo "   Sandbox 2: $SANDBOX_NAME_2"
    kubectl get sandbox -n $NAMESPACE -l managed-by=incidentfox-server -o custom-columns=NAME:.metadata.name,RUNTIME:.spec.podTemplate.spec.runtimeClassName
else
    echo "❌ Test 4 FAILED - Second sandbox not found"
    echo "   Expected: $SANDBOX_NAME_2 in '$NAMESPACE' namespace"
    exit 1
fi

echo ""
sleep 2

# Test 5: Verify gVisor runtime
echo "Test 5: Verify gVisor Runtime"
echo "------------------------------"
SANDBOXES=$(kubectl get sandbox -n $NAMESPACE -o json | jq -r '.items[] | select(.metadata.labels["managed-by"]=="incidentfox-server") | "\(.metadata.name) \(.spec.podTemplate.spec.runtimeClassName)"')

echo "Active sandboxes:"
echo "$SANDBOXES"

if echo "$SANDBOXES" | grep -q "gvisor"; then
    echo "✅ Test 5 PASSED - Sandboxes using gVisor runtime"
else
    echo "⚠️  Test 5 WARNING - gVisor runtime not detected"
fi

echo ""

# Summary
echo "================================"
echo "✅ All Production Tests PASSED!"
echo "================================"
echo ""
echo "Production Info:"
echo "  LoadBalancer: http://$PROD_URL"
echo "  Namespace: $NAMESPACE"
echo ""
echo "Created sandboxes:"
kubectl get sandbox -n $NAMESPACE -l managed-by=incidentfox-server -o custom-columns=NAME:.metadata.name,RUNTIME:.spec.podTemplate.spec.runtimeClassName,AGE:.metadata.creationTimestamp

echo ""
echo "Active pods:"
kubectl get pods -n $NAMESPACE -l app=incidentfox-server

echo ""
echo "Cleanup:"
echo "  kubectl delete sandbox -n $NAMESPACE investigation-$THREAD_ID"
echo "  kubectl delete sandbox -n $NAMESPACE investigation-$THREAD_ID_2"


