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

# Configure auto-permissions for read-only tools
echo ""
echo "Configuring tool permissions..."

SETTINGS_DIR="$HOME/.claude"
SETTINGS_FILE="$SETTINGS_DIR/settings.json"

# Create settings directory if it doesn't exist
mkdir -p "$SETTINGS_DIR"

# Use Python to safely merge permissions into settings.json
python3 << 'PYTHON_SCRIPT'
import json
import os

settings_file = os.path.expanduser("~/.claude/settings.json")

# Permissions to add (read-only tools allowed, remediation tools blocked)
new_permissions = {
    "allow": [
        "mcp__incidentfox__list_*",
        "mcp__incidentfox__get_*",
        "mcp__incidentfox__search_*",
        "mcp__incidentfox__describe_*",
        "mcp__incidentfox__query_*",
        "mcp__incidentfox__docker_*",
        "mcp__incidentfox__git_*",
        "mcp__incidentfox__correlate_*",
        "mcp__incidentfox__detect_*",
        "mcp__incidentfox__find_*",
        "mcp__incidentfox__start_investigation",
        "mcp__incidentfox__add_finding",
        "mcp__incidentfox__complete_investigation",
        "mcp__incidentfox__generate_postmortem",
        "mcp__incidentfox__check_known_issues",
        "mcp__incidentfox__prometheus_*"
    ],
    "deny": [
        "mcp__incidentfox__propose_*"
    ]
}

# Load existing settings or create new
if os.path.exists(settings_file):
    with open(settings_file, 'r') as f:
        try:
            settings = json.load(f)
        except json.JSONDecodeError:
            settings = {}
else:
    settings = {}

# Merge permissions
if "permissions" not in settings:
    settings["permissions"] = {}

existing_allow = set(settings["permissions"].get("allow", []))
existing_deny = set(settings["permissions"].get("deny", []))

# Add new permissions (don't remove existing ones)
existing_allow.update(new_permissions["allow"])
existing_deny.update(new_permissions["deny"])

settings["permissions"]["allow"] = sorted(list(existing_allow))
settings["permissions"]["deny"] = sorted(list(existing_deny))

# Save
with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print("  ✓ Read-only tools auto-approved (no permission prompts)")
print("  ✓ Remediation tools require confirmation (propose_*)")
PYTHON_SCRIPT

echo ""
echo "============================================"
echo "Installation complete!"
echo "============================================"
echo ""
echo "Start Claude Code and try:"
echo "  > Check my Kubernetes cluster health"
echo "  > What integrations are configured?"
echo "  > List pods in the default namespace"
echo ""
echo "Read-only tools are auto-approved. Remediation tools will"
echo "still ask for confirmation before making changes."
echo ""
echo "Full docs: $SCRIPT_DIR/README.md"
echo ""
