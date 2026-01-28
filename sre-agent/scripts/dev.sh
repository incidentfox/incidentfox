#!/bin/bash
# Local Development Runner (docker-compose-like UX)
# Builds, deploys, and runs server with auto-cleanup on exit
# Usage: make dev (or ./scripts/dev.sh)

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Track PIDs for cleanup
SERVER_PID=""
PORT_FORWARD_PID=""
LOG_WATCHER_PID=""

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}🧹 Cleaning up...${NC}"
    
    # Kill log watcher
    if [ -n "$LOG_WATCHER_PID" ]; then
        echo "  Stopping log watcher (PID: $LOG_WATCHER_PID)..."
        kill $LOG_WATCHER_PID 2>/dev/null || true
    fi
    
    # Kill server
    if [ -n "$SERVER_PID" ]; then
        echo "  Stopping server (PID: $SERVER_PID)..."
        kill $SERVER_PID 2>/dev/null || true
    fi
    
    # Kill port-forward
    if [ -n "$PORT_FORWARD_PID" ]; then
        echo "  Stopping port-forward (PID: $PORT_FORWARD_PID)..."
        kill $PORT_FORWARD_PID 2>/dev/null || true
    fi
    
    # Clean up sandboxes
    echo "  Deleting sandboxes..."
    kubectl delete sandbox --all --timeout=10s 2>/dev/null || true
    
    echo -e "${GREEN}✅ Cleanup complete${NC}"
    echo ""
    echo "💡 Run 'make dev' again to restart"
    exit 0
}

# Function to watch and stream sandbox logs
watch_sandbox_logs() {
    local CYAN='\033[0;36m'
    local RED='\033[0;31m'
    local GREEN='\033[0;32m'
    local NC='\033[0m'
    local seen_pods=""
    
    while true; do
        # Get all investigation pods
        pods=$(kubectl get pods --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep "^investigation-" || true)
        
        for pod in $pods; do
            # Skip if we've already started streaming this pod
            if [[ "$seen_pods" == *"$pod"* ]]; then
                continue
            fi
            seen_pods="$seen_pods $pod"
            
            # Wait for pod to be running
            pod_status=$(kubectl get pod "$pod" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
            if [[ "$pod_status" != "Running" ]]; then
                echo -e "${CYAN}⏳ Waiting for $pod (status: $pod_status)...${NC}"
                kubectl wait --for=condition=Ready pod/"$pod" --timeout=60s 2>/dev/null || true
            fi
            
            # Start streaming logs for this pod in background
            # Using --prefix and --timestamps for better visibility
            echo -e "${GREEN}📋 Streaming logs for: $pod${NC}"
            (
                kubectl logs -f "$pod" --prefix 2>/dev/null | while read -r line; do
                    # Highlight errors in red
                    if [[ "$line" == *"Error"* ]] || [[ "$line" == *"error"* ]] || [[ "$line" == *"Traceback"* ]] || [[ "$line" == *"IndentationError"* ]]; then
                        echo -e "${RED}$line${NC}"
                    else
                        echo "$line"
                    fi
                done
            ) &
        done
        
        sleep 2
    done
}

# Trap signals
trap cleanup SIGINT SIGTERM EXIT

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           🚀 Starting Local Development Environment            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check if setup was done
echo -e "${BLUE}📋 Checking setup...${NC}"

# Check if Docker is running FIRST
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running!${NC}"
    echo ""
    echo "Please start Docker Desktop, then run 'make dev' again."
    echo ""
    exit 1
fi
echo "  ✓ Docker running"

# Check if Kind cluster exists
if ! kind get clusters 2>/dev/null | grep -q "incidentfox"; then
    echo -e "${RED}❌ Kind cluster 'incidentfox' not found!${NC}"
    echo ""
    echo "First-time setup required:"
    echo "  make setup-local"
    echo ""
    exit 1
fi
echo "  ✓ Kind cluster exists"

# Switch to kind-incidentfox context
if ! kubectl config use-context kind-incidentfox >/dev/null 2>&1; then
    echo -e "${RED}❌ Failed to switch kubectl context!${NC}"
    echo ""
    echo "Try: kubectl config use-context kind-incidentfox"
    echo ""
    exit 1
fi
echo "  ✓ kubectl context set"

# Check if sandbox router is deployed
if ! kubectl get deployment sandbox-router-deployment &>/dev/null; then
    echo -e "${RED}❌ Sandbox Router not deployed!${NC}"
    echo ""
    echo "The Kind cluster exists but components aren't installed."
    echo "Run: make setup-local"
    echo ""
    exit 1
fi
echo "  ✓ Sandbox router deployed"

echo -e "${GREEN}✅ Setup OK${NC}"
echo ""

# Clean old sandboxes
echo -e "${BLUE}🧹 Cleaning old sandboxes...${NC}"
kubectl delete sandbox --all --timeout=10s 2>/dev/null || true
echo ""

# Build and load image
echo -e "${BLUE}🔨 Building fresh image...${NC}"
docker build -q -t incidentfox-agent:dev .
echo -e "${GREEN}✅ Image built${NC}"
echo ""

echo -e "${BLUE}📦 Loading into Kind...${NC}"
kind load docker-image incidentfox-agent:dev --name incidentfox
echo -e "${GREEN}✅ Image loaded${NC}"
echo ""

# Deploy sandbox template (with new image, without gVisor for local)
echo -e "${BLUE}📋 Deploying sandbox template...${NC}"
grep -v "runtimeClassName" k8s/sandbox-template.yaml | kubectl apply -f - >/dev/null
echo -e "${GREEN}✅ Template deployed${NC}"
echo ""

# Setup port-forward to router
echo -e "${BLUE}🔀 Setting up port-forward to router...${NC}"
pkill -f "kubectl.*port-forward.*8080" 2>/dev/null || true
sleep 1
ROUTER_POD=$(kubectl get pod -l app=sandbox-router --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -z "$ROUTER_POD" ]; then
    echo -e "${RED}❌ No running router pods found!${NC}"
    echo ""
    echo "Router might be starting up. Check with:"
    echo "  kubectl get pods -l app=sandbox-router"
    echo ""
    exit 1
fi
kubectl port-forward $ROUTER_POD 8080:8080 >/dev/null 2>&1 &
PORT_FORWARD_PID=$!
sleep 2
echo -e "${GREEN}✅ Port-forward ready (PID: $PORT_FORWARD_PID)${NC}"
echo ""

# Load environment
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env file not found!${NC}"
    exit 1
fi
source .env

# Check if port 8000 is already in use
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo ""
    echo -e "${RED}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  ❌ Port 8000 is already in use!                              ║${NC}"
    echo -e "${RED}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}This usually means 'make dev' is already running in another terminal.${NC}"
    echo ""
    echo "🔍 Process using port 8000:"
    lsof -Pi :8000 -sTCP:LISTEN
    echo ""
    echo -e "${BLUE}To fix this:${NC}"
    echo ""
    echo "  ${GREEN}Option 1:${NC} Kill the existing process:"
    echo "    pkill -9 -f 'python.*server.py'"
    echo ""
    echo "  ${GREEN}Option 2:${NC} Find and stop the other terminal running 'make dev'"
    echo ""
    exit 1
fi

# Start server
echo -e "${BLUE}🚀 Starting server...${NC}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ Server running on http://localhost:8000${NC}"
echo ""
echo "Test with:"
echo "  curl -X POST http://localhost:8000/investigate \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"prompt\": \"What is 2+2?\"}'"
echo ""
echo -e "${BLUE}📋 Sandbox logs will stream here automatically${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop and cleanup${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

export ROUTER_LOCAL_PORT=8080
export SANDBOX_IMAGE=incidentfox-agent:dev

# Start log watcher in background (streams sandbox pod logs)
watch_sandbox_logs &
LOG_WATCHER_PID=$!

# Start server (in foreground so we see its output)
.venv/bin/python server.py &
SERVER_PID=$!

# Wait for server to exit or for signal
wait $SERVER_PID

