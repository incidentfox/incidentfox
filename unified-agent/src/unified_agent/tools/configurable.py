"""
Configurable Tools

Tools that require team-specific configuration (e.g., Grafana URL, API keys).
These tools are created dynamically with injected configuration.

The pattern:
1. Define a tool factory function that takes config
2. Factory returns a configured tool function
3. Tool loader calls factory with team's config
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import logging
import os

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


# =============================================================================
# Tool Configuration Schema
# =============================================================================

TOOL_CONFIG_SCHEMAS: dict[str, dict[str, Any]] = {
    "grafana_query_prometheus": {
        "base_url": {
            "type": "string",
            "required": True,
            "display_name": "Grafana URL",
            "description": "Your Grafana instance URL",
            "placeholder": "https://grafana.example.com",
        },
        "api_key": {
            "type": "secret",
            "required": True,
            "display_name": "Grafana API Key",
            "description": "Service account token or API key with viewer permissions",
        },
        "default_datasource": {
            "type": "string",
            "required": False,
            "default": "prometheus",
            "display_name": "Default Datasource",
        },
        "org_id": {
            "type": "integer",
            "required": False,
            "default": 1,
            "display_name": "Organization ID",
        },
    },
    "datadog_query": {
        "api_key": {
            "type": "secret",
            "required": True,
            "display_name": "Datadog API Key",
        },
        "app_key": {
            "type": "secret",
            "required": True,
            "display_name": "Datadog Application Key",
        },
        "site": {
            "type": "string",
            "required": False,
            "default": "datadoghq.com",
            "display_name": "Datadog Site",
            "allowed_values": [
                "datadoghq.com",
                "datadoghq.eu",
                "us3.datadoghq.com",
                "us5.datadoghq.com",
            ],
        },
    },
    "newrelic_query": {
        "api_key": {
            "type": "secret",
            "required": True,
            "display_name": "New Relic API Key",
        },
        "account_id": {
            "type": "string",
            "required": True,
            "display_name": "New Relic Account ID",
        },
        "region": {
            "type": "string",
            "required": False,
            "default": "US",
            "allowed_values": ["US", "EU"],
        },
    },
    "pagerduty_query": {
        "api_key": {
            "type": "secret",
            "required": True,
            "display_name": "PagerDuty API Key",
        },
    },
    "elasticsearch_search": {
        "url": {
            "type": "string",
            "required": True,
            "display_name": "Elasticsearch URL",
            "placeholder": "https://elasticsearch.example.com:9200",
        },
        "username": {
            "type": "string",
            "required": False,
        },
        "password": {
            "type": "secret",
            "required": False,
        },
        "default_index": {
            "type": "string",
            "required": False,
            "default": "logs-*",
        },
    },
}


@function_tool
def get_tool_config_schema(tool_name: str) -> str:
    """Get the configuration schema for a tool."""
    return TOOL_CONFIG_SCHEMAS.get(tool_name, {})


@function_tool
def validate_tool_config(tool_name: str, config: dict[str, Any]) -> str:
    """
    Validate tool configuration against its schema.

    Returns:
        {
            'valid': bool,
            'missing': [field_name, ...],
            'errors': [error_message, ...]
        }
    """
    schema = get_tool_config_schema(tool_name)
    if not schema:
        return {"valid": True, "missing": [], "errors": []}

    missing = []
    errors = []

    for field_name, field_schema in schema.items():
        value = config.get(field_name)

        # Check required
        if field_schema.get("required"):
            if value is None or value == "":
                missing.append(field_name)
                continue

        # Check type (basic)
        if value is not None:
            expected_type = field_schema.get("type")
            if expected_type == "integer" and not isinstance(value, int):
                try:
                    int(value)
                except:
                    errors.append(f"{field_name}: expected integer")
            elif expected_type == "string" and not isinstance(value, str):
                errors.append(f"{field_name}: expected string")

        # Check allowed values
        if value is not None and "allowed_values" in field_schema:
            if value not in field_schema["allowed_values"]:
                errors.append(
                    f"{field_name}: must be one of {field_schema['allowed_values']}"
                )

    return {
        "valid": len(missing) == 0 and len(errors) == 0,
        "missing": missing,
        "errors": errors,
    }


# =============================================================================
# Configurable Grafana Tools
# =============================================================================


@function_tool
def create_grafana_query_prometheus(config: dict[str, Any]) -> Callable | None:
    """
    Create a configured grafana_query_prometheus tool.

    Args:
        config: Tool configuration with base_url, api_key, etc.

    Returns:
        Configured tool function or None if config invalid
    """
    base_url = config.get("base_url")
    api_key = config.get("api_key")
    default_datasource = config.get("default_datasource", "prometheus")
    org_id = config.get("org_id", 1)

    if not base_url or not api_key:
        return None

    @function_tool
    def grafana_query_prometheus(
        query: str,
        time_range: str = "1h",
        step: str = "1m",
        datasource: str = "",
    ) -> str:
        """
        Query Prometheus metrics via Grafana.

        Args:
            query: PromQL query (e.g., 'rate(http_requests_total[5m])')
            time_range: Time range (e.g., '1h', '24h', '7d')
            step: Query step/resolution (e.g., '1m', '5m')
            datasource: Datasource name (uses default if not specified)

        Returns:
            JSON with query results
        """
        try:
            import httpx
        except ImportError:
            return json.dumps({"error": "httpx not installed"})

        ds = datasource or default_datasource

        # Parse time range
        time_map = {"m": 60, "h": 3600, "d": 86400}
        unit = time_range[-1]
        value = int(time_range[:-1])
        seconds = value * time_map.get(unit, 3600)

        import time

        end = int(time.time())
        start = end - seconds

        # Parse step
        step_unit = step[-1]
        step_value = int(step[:-1])
        step_seconds = step_value * time_map.get(step_unit, 60)

        url = f"{base_url.rstrip('/')}/api/ds/query"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "queries": [
                {
                    "refId": "A",
                    "datasource": {"type": "prometheus", "uid": ds},
                    "expr": query,
                    "range": True,
                    "interval": step,
                }
            ],
            "from": str(start * 1000),
            "to": str(end * 1000),
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    # Extract values
                    results = []
                    for result in data.get("results", {}).values():
                        for frame in result.get("frames", []):
                            schema = frame.get("schema", {})
                            data_section = frame.get("data", {})
                            values = data_section.get("values", [])
                            if len(values) >= 2:
                                timestamps = values[0]
                                metric_values = values[1]
                                results.append(
                                    {
                                        "metric": schema.get("name", "unknown"),
                                        "values": list(zip(timestamps, metric_values))[
                                            -20:
                                        ],  # Last 20
                                    }
                                )

                    return json.dumps(
                        {
                            "ok": True,
                            "query": query,
                            "datasource": ds,
                            "time_range": time_range,
                            "results": results,
                        }
                    )
                else:
                    return json.dumps(
                        {
                            "ok": False,
                            "error": f"Grafana returned {response.status_code}",
                            "detail": response.text[:500],
                        }
                    )
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    return grafana_query_prometheus


@function_tool
def create_grafana_list_dashboards(config: dict[str, Any]) -> Callable | None:
    """Create configured grafana_list_dashboards tool."""
    base_url = config.get("base_url")
    api_key = config.get("api_key")

    if not base_url or not api_key:
        return None

    @function_tool
    def grafana_list_dashboards(query: str = "", limit: int = 20) -> str:
        """
        List Grafana dashboards.

        Args:
            query: Search query to filter dashboards
            limit: Maximum number of dashboards to return

        Returns:
            JSON with list of dashboards
        """
        try:
            import httpx
        except ImportError:
            return json.dumps({"error": "httpx not installed"})

        url = f"{base_url.rstrip('/')}/api/search"
        params = {"type": "dash-db", "limit": limit}
        if query:
            params["query"] = query

        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(url, params=params, headers=headers)

                if response.status_code == 200:
                    dashboards = response.json()
                    return json.dumps(
                        {
                            "ok": True,
                            "count": len(dashboards),
                            "dashboards": [
                                {
                                    "uid": d.get("uid"),
                                    "title": d.get("title"),
                                    "url": f"{base_url}/d/{d.get('uid')}",
                                    "folder": d.get("folderTitle"),
                                }
                                for d in dashboards
                            ],
                        }
                    )
                else:
                    return json.dumps(
                        {"ok": False, "error": f"HTTP {response.status_code}"}
                    )
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    return grafana_list_dashboards


# =============================================================================
# Tool Factory Registry
# =============================================================================

TOOL_FACTORIES: dict[str, Callable[[dict[str, Any]], Callable | None]] = {
    "grafana_query_prometheus": create_grafana_query_prometheus,
    "grafana_list_dashboards": create_grafana_list_dashboards,
    # Add more as needed
}


@function_tool
def create_configured_tool(
    tool_name: str,
    config: dict[str, Any],
) -> Callable | None:
    """
    Create a configured tool from a factory.

    Args:
        tool_name: Name of the tool
        config: Tool configuration

    Returns:
        Configured tool function or None if factory not found or config invalid
    """
    factory = TOOL_FACTORIES.get(tool_name)
    if not factory:
        logger.debug("no_factory_for_tool", tool_name=tool_name)
        return None

    # Validate config
    validation = validate_tool_config(tool_name, config)
    if not validation["valid"]:
        logger.warning(
            "tool_config_invalid",
            tool_name=tool_name,
            missing=validation["missing"],
            errors=validation["errors"],
        )
        return None

    tool = factory(config)
    if tool:
        logger.info("configured_tool_created", tool_name=tool_name)

    return tool


@function_tool
def create_all_configured_tools(
    tool_configs: dict[str, dict[str, Any]],
) -> str:
    """
    Create all configured tools from a config dict.

    Args:
        tool_configs: Dict of tool_name → config

    Returns:
        Dict of tool_name → configured tool function
    """
    tools = {}

    for tool_name, config in tool_configs.items():
        tool = create_configured_tool(tool_name, config)
        if tool:
            tools[tool_name] = tool

    return tools


# Register tools
register_tool("get_tool_config_schema", get_tool_config_schema)
register_tool("validate_tool_config", validate_tool_config)
register_tool("create_grafana_query_prometheus", create_grafana_query_prometheus)
register_tool("create_grafana_list_dashboards", create_grafana_list_dashboards)
register_tool("create_configured_tool", create_configured_tool)
register_tool("create_all_configured_tools", create_all_configured_tools)
