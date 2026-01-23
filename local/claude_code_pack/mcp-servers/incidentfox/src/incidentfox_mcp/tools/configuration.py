"""Configuration management tools.

Allows Claude to save credentials mid-session and check configuration status.
Credentials are stored in ~/.incidentfox/.env and persist across sessions.
"""

import json

from mcp.server.fastmcp import FastMCP

from ..utils.config import CONFIG_FILE
from ..utils.config import get_config_status as _get_config_status
from ..utils.config import save_credential as _save_credential


def register_tools(mcp: FastMCP):
    """Register configuration management tools."""

    @mcp.tool()
    def save_credential(key: str, value: str) -> str:
        """Save a credential or configuration value to persistent storage.

        Credentials are saved to ~/.incidentfox/.env and will be available
        immediately for subsequent tool calls, and will persist across sessions.

        Common keys:
        - DATADOG_API_KEY: Datadog API key
        - DATADOG_APP_KEY: Datadog application key
        - AWS_REGION: AWS region (e.g., us-east-1, eu-west-1)
        - PROMETHEUS_URL: Prometheus server URL
        - ALERTMANAGER_URL: Alertmanager URL
        - ELASTICSEARCH_URL: Elasticsearch URL
        - LOKI_URL: Loki URL

        Args:
            key: Configuration key (e.g., 'DATADOG_API_KEY')
            value: The value to save

        Returns:
            JSON with confirmation message
        """
        try:
            _save_credential(key, value)
            return json.dumps(
                {
                    "status": "saved",
                    "key": key,
                    "config_file": str(CONFIG_FILE),
                    "message": f"Configuration '{key}' saved. It will be used immediately and persist across sessions.",
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e), "key": key}, indent=2)

    @mcp.tool()
    def get_config_status() -> str:
        """Check which integrations are configured and which need credentials.

        Shows the status of all supported integrations (Kubernetes, AWS, Datadog,
        Prometheus, etc.) and indicates which environment variables are set or missing.

        Use this to understand what's configured before running investigation tools,
        or to diagnose why a tool returned a "not configured" error.

        Returns:
            JSON with configuration status for all integrations
        """
        try:
            status = _get_config_status()
            return json.dumps(status, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    def delete_credential(key: str) -> str:
        """Delete a credential from persistent storage.

        Removes the specified key from ~/.incidentfox/.env.

        Args:
            key: Configuration key to delete

        Returns:
            JSON with confirmation message
        """
        try:
            # Read existing config
            existing = {}
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE) as f:
                    for line in f:
                        line_stripped = line.strip()
                        if not line_stripped or line_stripped.startswith("#"):
                            continue
                        if "=" in line_stripped:
                            k, _, v = line_stripped.partition("=")
                            existing[k.strip()] = v.strip()

            # Check if key exists
            if key not in existing:
                return json.dumps(
                    {
                        "status": "not_found",
                        "key": key,
                        "message": f"Key '{key}' was not in config file",
                    },
                    indent=2,
                )

            # Remove the key
            del existing[key]

            # Write back
            with open(CONFIG_FILE, "w") as f:
                f.write("# IncidentFox Configuration\n")
                f.write("# Generated automatically - you can edit this file\n\n")
                for k, v in sorted(existing.items()):
                    if " " in v or not v:
                        f.write(f'{k}="{v}"\n')
                    else:
                        f.write(f"{k}={v}\n")

            return json.dumps(
                {
                    "status": "deleted",
                    "key": key,
                    "message": f"Key '{key}' has been removed from config",
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e), "key": key}, indent=2)
