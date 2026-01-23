#!/bin/bash
# IncidentFox Claude Code Plugin Installer
# Usage: ./install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_DIR="$SCRIPT_DIR/mcp-servers/incidentfox"

echo "Installing IncidentFox Claude Code Plugin..."
echo ""

# Check for required tools
if ! command -v claude &> /dev/null; then
    echo "Error: Claude Code CLI not found. Install it first:"
    echo "  npm install -g @anthropic-ai/claude-code"
    exit 1
fi

if ! command -v uv &> /dev/null; then
    echo "Error: uv not found. Install it first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Install Python dependencies
echo "Installing Python dependencies..."
cd "$MCP_DIR"
uv sync
cd "$SCRIPT_DIR"

# Add MCP server to Claude Code
echo ""
echo "Adding MCP server to Claude Code..."

# Build the JSON config
CONFIG=$(cat <<EOF
{
  "command": "uv",
  "args": ["--directory", "$MCP_DIR", "run", "incidentfox-mcp"],
  "env": {
    "KUBECONFIG": "\${KUBECONFIG:-~/.kube/config}",
    "AWS_REGION": "\${AWS_REGION:-us-east-1}",
    "AWS_DEFAULT_REGION": "\${AWS_DEFAULT_REGION:-us-east-1}",
    "DATADOG_API_KEY": "\${DATADOG_API_KEY}",
    "DATADOG_APP_KEY": "\${DATADOG_APP_KEY}",
    "PROMETHEUS_URL": "\${PROMETHEUS_URL}",
    "ALERTMANAGER_URL": "\${ALERTMANAGER_URL}",
    "ELASTICSEARCH_URL": "\${ELASTICSEARCH_URL}",
    "LOKI_URL": "\${LOKI_URL}"
  }
}
EOF
)

# Remove existing config if present
claude mcp remove incidentfox -s user 2>/dev/null || true

# Add new config
claude mcp add-json incidentfox "$CONFIG" -s user

echo ""
echo "Verifying installation..."
claude mcp list

echo ""
echo "============================================"
echo "Installation complete!"
echo "============================================"
echo ""
echo "The following tools are now available in Claude Code:"
echo "  - Kubernetes: list_pods, get_pod_logs, get_pod_events, ..."
echo "  - AWS: describe_ec2_instance, get_cloudwatch_logs, ..."
echo "  - Datadog: query_datadog_metrics, search_datadog_logs, ..."
echo "  - Docker: docker_ps, docker_logs, docker_inspect, ..."
echo "  - Git: git_log, git_diff, correlate_with_deployment, ..."
echo "  - And 30+ more!"
echo ""
echo "Quick test:"
echo "  claude -p 'Use git_log to show the last 3 commits'"
echo ""
echo "For the full plugin experience (skills + commands):"
echo "  claude --plugin-dir $SCRIPT_DIR"
echo ""
