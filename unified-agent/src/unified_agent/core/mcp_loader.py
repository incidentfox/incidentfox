"""
MCP (Model Context Protocol) Configuration Loader

Handles MCP server configuration with inheritance:
- Org defines default MCPs (inherited by all teams)
- Teams can add their own MCPs
- Teams can disable org MCPs

MCP Config Structure:
{
    "mcp_servers": {
        "github-mcp": {
            "name": "GitHub MCP Server",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_TOKEN": "${github_token}"},
            "enabled": true
        }
    }
}
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""

    id: str
    name: str
    type: str  # 'stdio', 'http', 'sse'

    # For stdio type
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    # For http/sse type
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    # Status
    enabled: bool = True

    # Config schema for required values
    config_schema: dict[str, Any] = field(default_factory=dict)
    config_values: dict[str, Any] = field(default_factory=dict)

    # Source
    source: str = "org"  # 'org', 'team', 'system'


def parse_mcp_config(
    config_dict: dict[str, Any], source: str = "org"
) -> MCPServerConfig:
    """Parse a dict into an MCPServerConfig."""
    return MCPServerConfig(
        id=config_dict.get("id", ""),
        name=config_dict.get("name", config_dict.get("id", "Unknown")),
        type=config_dict.get("type", "stdio"),
        command=config_dict.get("command"),
        args=config_dict.get("args", []),
        env=config_dict.get("env", {}),
        url=config_dict.get("url"),
        headers=config_dict.get("headers", {}),
        enabled=config_dict.get("enabled", True),
        config_schema=config_dict.get("config_schema", {}),
        config_values=config_dict.get("config_values", {}),
        source=source,
    )


def resolve_mcp_config(effective_config: dict[str, Any]) -> list[MCPServerConfig]:
    """
    Resolve MCP configuration from canonical dict format.

    Args:
        effective_config: The merged effective configuration with canonical format

    Returns:
        List of MCPServerConfig objects for enabled MCPs
    """
    mcp_servers_dict = effective_config.get("mcp_servers", {})

    if not isinstance(mcp_servers_dict, dict):
        logger.warning("mcp_servers config is not a dict (type=%s)", type(mcp_servers_dict))
        mcp_servers_dict = {}

    mcp_configs = []
    for mcp_id, mcp_config in mcp_servers_dict.items():
        if not isinstance(mcp_config, dict):
            logger.warning("Invalid MCP config for %s (type=%s)", mcp_id, type(mcp_config))
            continue

        if not mcp_config.get("enabled", True):
            logger.debug("Skipping disabled MCP: %s", mcp_id)
            continue

        config_with_id = {**mcp_config, "id": mcp_id}
        try:
            parsed = parse_mcp_config(config_with_id, source="effective")
            mcp_configs.append(parsed)
        except Exception as e:
            logger.error("Failed to parse MCP config for %s: %s", mcp_id, e)
            continue

    logger.info(
        "MCP config resolved: %d total, %d enabled",
        len(mcp_servers_dict), len(mcp_configs),
    )

    return mcp_configs


def substitute_env_vars(value: str, config_values: dict[str, Any]) -> str:
    """
    Substitute ${variable} references in a string.

    Looks up in:
    1. config_values (team-provided values)
    2. Environment variables
    """
    import re

    def replace(match):
        var_name = match.group(1)
        if var_name in config_values:
            return str(config_values[var_name])
        return os.getenv(var_name, match.group(0))

    return re.sub(r"\$\{(\w+)\}", replace, value)


def prepare_mcp_env(mcp: MCPServerConfig) -> dict[str, str]:
    """
    Prepare environment variables for an MCP server.

    Substitutes ${variable} references with actual values.
    """
    env = os.environ.copy()

    for key, value in mcp.env.items():
        if isinstance(value, str):
            env[key] = substitute_env_vars(value, mcp.config_values)
        else:
            env[key] = str(value)

    return env


def validate_mcp_config(mcp: MCPServerConfig) -> dict[str, Any]:
    """
    Validate MCP configuration.

    Returns:
        {
            'valid': bool,
            'missing': [field names],
            'errors': [error messages]
        }
    """
    missing = []
    errors = []

    if not mcp.id:
        errors.append("MCP must have an id")

    if mcp.type == "stdio":
        if not mcp.command:
            errors.append("stdio MCP must have a command")
    elif mcp.type in ("http", "sse"):
        if not mcp.url:
            errors.append(f"{mcp.type} MCP must have a url")
    else:
        errors.append(f"Unknown MCP type: {mcp.type}")

    for field_name, field_schema in mcp.config_schema.items():
        if field_schema.get("required"):
            value = mcp.config_values.get(field_name)
            if value is None or value == "":
                missing.append(field_name)

    for key, value in mcp.env.items():
        if isinstance(value, str) and "${" in value:
            var_match = substitute_env_vars(value, mcp.config_values)
            if "${" in var_match:
                missing.append(f"env.{key}")

    return {
        "valid": len(missing) == 0 and len(errors) == 0,
        "missing": missing,
        "errors": errors,
    }


class MCPConnection:
    """
    Connection to an MCP server.

    Handles starting/stopping stdio processes or connecting to HTTP servers.
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.process: subprocess.Popen | None = None
        self.connected = False

    def connect(self) -> bool:
        """Connect to or start the MCP server."""
        if self.config.type == "stdio":
            return self._start_stdio_process()
        elif self.config.type in ("http", "sse"):
            return self._test_http_connection()
        return False

    def disconnect(self):
        """Disconnect from or stop the MCP server."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
        self.connected = False

    def _start_stdio_process(self) -> bool:
        """Start a stdio MCP process."""
        try:
            env = prepare_mcp_env(self.config)

            cmd = [self.config.command] + self.config.args

            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            self.connected = True
            logger.info("MCP process started: %s (pid=%s)", self.config.id, self.process.pid)
            return True

        except Exception as e:
            logger.error("MCP process start failed for %s: %s", self.config.id, e)
            return False

    def _test_http_connection(self) -> bool:
        """Test connection to an HTTP MCP server."""
        try:
            import httpx

            headers = dict(self.config.headers)
            for key, value in headers.items():
                headers[key] = substitute_env_vars(value, self.config.config_values)

            with httpx.Client(timeout=10.0) as client:
                response = client.get(self.config.url, headers=headers)
                self.connected = response.status_code < 500
                return self.connected

        except Exception as e:
            logger.error("MCP HTTP connection failed for %s: %s", self.config.id, e)
            return False


class MCPManager:
    """
    Manages MCP server connections for a team.

    Usage:
        manager = MCPManager(effective_config)
        manager.start_all()
        # ... use MCPs ...
        manager.stop_all()
    """

    def __init__(self, effective_config: dict[str, Any]):
        self.config = effective_config
        self.mcp_configs = resolve_mcp_config(effective_config)
        self.connections: dict[str, MCPConnection] = {}

    def get_enabled_mcps(self) -> list[MCPServerConfig]:
        """Get list of enabled and valid MCP configurations."""
        enabled = []
        for mcp in self.mcp_configs:
            if not mcp.enabled:
                continue

            validation = validate_mcp_config(mcp)
            if validation["valid"]:
                enabled.append(mcp)
            else:
                logger.warning(
                    "MCP validation failed for %s: missing=%s, errors=%s",
                    mcp.id, validation["missing"], validation["errors"],
                )

        return enabled

    def start_all(self) -> dict[str, bool]:
        """Start all enabled MCP servers."""
        results = {}

        for mcp in self.get_enabled_mcps():
            conn = MCPConnection(mcp)
            success = conn.connect()
            results[mcp.id] = success

            if success:
                self.connections[mcp.id] = conn

        logger.info(
            "MCP servers started: %d/%d",
            sum(1 for v in results.values() if v), len(self.mcp_configs),
        )

        return results

    def stop_all(self):
        """Stop all MCP servers."""
        for conn in self.connections.values():
            conn.disconnect()
        self.connections.clear()

    def get_connection(self, mcp_id: str) -> MCPConnection | None:
        """Get a specific MCP connection."""
        return self.connections.get(mcp_id)

    def __enter__(self):
        self.start_all()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_all()


# =============================================================================
# Default MCP Configurations
# =============================================================================

DEFAULT_MCP_CONFIGS = [
    {
        "id": "filesystem-mcp",
        "name": "Filesystem MCP",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": {},
        "enabled": False,  # Disabled by default for security
    },
    {
        "id": "github-mcp",
        "name": "GitHub MCP",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {
            "GITHUB_PERSONAL_ACCESS_TOKEN": "${github_token}",
        },
        "config_schema": {
            "github_token": {
                "type": "secret",
                "required": True,
                "display_name": "GitHub Token",
                "description": "Personal access token with repo access",
            },
        },
        "enabled": True,
    },
    {
        "id": "slack-mcp",
        "name": "Slack MCP",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env": {
            "SLACK_BOT_TOKEN": "${slack_bot_token}",
        },
        "config_schema": {
            "slack_bot_token": {
                "type": "secret",
                "required": True,
            },
        },
        "enabled": False,
    },
]


def get_default_mcp_config() -> dict[str, Any]:
    """
    Get default MCP configuration for testing/fallback (canonical format).

    Returns dict format: {mcp_id: {name, command, args, env, enabled, ...}}
    """
    mcp_servers_dict = {}
    for mcp_config in DEFAULT_MCP_CONFIGS:
        if isinstance(mcp_config, dict) and "id" in mcp_config:
            mcp_id = mcp_config["id"]
            config_without_id = {k: v for k, v in mcp_config.items() if k != "id"}
            mcp_servers_dict[mcp_id] = config_without_id

    return {
        "mcp_servers": mcp_servers_dict,
    }
