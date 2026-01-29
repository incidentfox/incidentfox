"""Debezium/Kafka Connect tools for CDC connector management.

Supports:
- Debezium connectors (PostgreSQL, MySQL, MongoDB, etc.)
- Any Kafka Connect connector
- Confluent Platform Connect
- Self-hosted Kafka Connect clusters
"""

import os
from typing import Any

import httpx

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_kafka_connect_config() -> dict:
    """Get Kafka Connect configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("kafka_connect")
        if config and config.get("url"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("KAFKA_CONNECT_URL"):
        return {
            "url": os.getenv("KAFKA_CONNECT_URL"),
            "username": os.getenv("KAFKA_CONNECT_USERNAME"),
            "password": os.getenv("KAFKA_CONNECT_PASSWORD"),
            "ssl_verify": os.getenv("KAFKA_CONNECT_SSL_VERIFY", "true").lower()
            == "true",
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="kafka_connect",
        tool_id="debezium_tools",
        missing_fields=["url"],
    )


def _get_client() -> httpx.Client:
    """Get HTTP client for Kafka Connect REST API."""
    config = _get_kafka_connect_config()

    # Build auth if provided
    auth = None
    if config.get("username") and config.get("password"):
        auth = (config["username"], config["password"])

    return httpx.Client(
        base_url=config["url"].rstrip("/"),
        auth=auth,
        verify=config.get("ssl_verify", True),
        timeout=30.0,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )


def debezium_list_connectors() -> dict[str, Any]:
    """
    List all Kafka Connect connectors.

    Returns:
        Dict with list of connector names
    """
    try:
        client = _get_client()

        response = client.get("/connectors")
        response.raise_for_status()

        connectors = response.json()
        client.close()

        logger.info("debezium_connectors_listed", count=len(connectors))

        return {
            "connector_count": len(connectors),
            "connectors": sorted(connectors),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_list_connectors", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        logger.error("debezium_list_connectors_failed", status=e.response.status_code)
        raise ToolExecutionError(
            "debezium_list_connectors",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error("debezium_list_connectors_failed", error=str(e))
        raise ToolExecutionError("debezium_list_connectors", str(e), e)


def debezium_get_connector_status(connector_name: str) -> dict[str, Any]:
    """
    Get the status of a Kafka Connect connector.

    Useful for monitoring CDC health and identifying issues.

    Args:
        connector_name: Name of the connector

    Returns:
        Dict with connector status including tasks
    """
    try:
        client = _get_client()

        response = client.get(f"/connectors/{connector_name}/status")
        response.raise_for_status()

        status = response.json()
        client.close()

        # Extract key info
        connector_state = status.get("connector", {}).get("state", "UNKNOWN")
        tasks = status.get("tasks", [])

        # Determine overall health
        failed_tasks = [t for t in tasks if t.get("state") == "FAILED"]
        running_tasks = [t for t in tasks if t.get("state") == "RUNNING"]

        if connector_state == "RUNNING" and len(failed_tasks) == 0:
            health = "healthy"
        elif connector_state == "PAUSED":
            health = "paused"
        elif len(failed_tasks) > 0:
            health = "degraded" if len(running_tasks) > 0 else "failed"
        else:
            health = "unhealthy"

        # Get error messages from failed tasks
        errors = []
        for task in failed_tasks:
            if task.get("trace"):
                errors.append(
                    {
                        "task_id": task.get("id"),
                        "trace": task.get("trace", "")[:500],
                    }
                )

        logger.info(
            "debezium_connector_status_retrieved",
            connector=connector_name,
            health=health,
        )

        return {
            "name": status.get("name"),
            "connector_state": connector_state,
            "connector_worker_id": status.get("connector", {}).get("worker_id"),
            "task_count": len(tasks),
            "running_tasks": len(running_tasks),
            "failed_tasks": len(failed_tasks),
            "health": health,
            "tasks": tasks,
            "errors": errors,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_get_connector_status", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Connector '{connector_name}' not found",
            }
        raise ToolExecutionError(
            "debezium_get_connector_status",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "debezium_get_connector_status_failed",
            error=str(e),
            connector=connector_name,
        )
        raise ToolExecutionError("debezium_get_connector_status", str(e), e)


def debezium_get_connector_config(connector_name: str) -> dict[str, Any]:
    """
    Get the configuration of a Kafka Connect connector.

    Args:
        connector_name: Name of the connector

    Returns:
        Dict with connector configuration
    """
    try:
        client = _get_client()

        response = client.get(f"/connectors/{connector_name}/config")
        response.raise_for_status()

        config = response.json()
        client.close()

        # Mask sensitive values
        masked_config = {}
        sensitive_keys = ["password", "secret", "key", "token", "credential"]

        for k, v in config.items():
            if any(s in k.lower() for s in sensitive_keys):
                masked_config[k] = "***REDACTED***"
            else:
                masked_config[k] = v

        logger.info(
            "debezium_connector_config_retrieved",
            connector=connector_name,
        )

        return {
            "name": connector_name,
            "config": masked_config,
            "connector_class": config.get("connector.class"),
            "tasks_max": config.get("tasks.max"),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_get_connector_config", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Connector '{connector_name}' not found",
            }
        raise ToolExecutionError(
            "debezium_get_connector_config",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "debezium_get_connector_config_failed",
            error=str(e),
            connector=connector_name,
        )
        raise ToolExecutionError("debezium_get_connector_config", str(e), e)


def debezium_create_connector(
    connector_name: str, config: dict[str, Any]
) -> dict[str, Any]:
    """
    Create a new Kafka Connect connector.

    WARNING: This creates a CDC connector that will start capturing changes.
    Make sure the configuration is correct!

    Args:
        connector_name: Name for the new connector
        config: Connector configuration

    Returns:
        Dict with creation result
    """
    try:
        client = _get_client()

        payload = {
            "name": connector_name,
            "config": config,
        }

        response = client.post("/connectors", json=payload)
        response.raise_for_status()

        result = response.json()
        client.close()

        logger.info(
            "debezium_connector_created",
            connector=connector_name,
            connector_class=config.get("connector.class"),
        )

        return {
            "name": result.get("name"),
            "config": result.get("config"),
            "tasks": result.get("tasks", []),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_create_connector", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            return {
                "success": False,
                "error": f"Connector '{connector_name}' already exists",
            }
        raise ToolExecutionError(
            "debezium_create_connector",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "debezium_create_connector_failed",
            error=str(e),
            connector=connector_name,
        )
        raise ToolExecutionError("debezium_create_connector", str(e), e)


def debezium_update_connector(
    connector_name: str, config: dict[str, Any]
) -> dict[str, Any]:
    """
    Update a Kafka Connect connector configuration.

    WARNING: This will restart the connector with new configuration.

    Args:
        connector_name: Name of the connector
        config: New connector configuration

    Returns:
        Dict with update result
    """
    try:
        client = _get_client()

        response = client.put(f"/connectors/{connector_name}/config", json=config)
        response.raise_for_status()

        result = response.json()
        client.close()

        logger.info(
            "debezium_connector_updated",
            connector=connector_name,
        )

        return {
            "name": connector_name,
            "config": result,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_update_connector", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Connector '{connector_name}' not found",
            }
        raise ToolExecutionError(
            "debezium_update_connector",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "debezium_update_connector_failed",
            error=str(e),
            connector=connector_name,
        )
        raise ToolExecutionError("debezium_update_connector", str(e), e)


def debezium_restart_connector(connector_name: str) -> dict[str, Any]:
    """
    Restart a Kafka Connect connector.

    Useful for:
    - Recovering from transient errors
    - Applying configuration changes
    - Resetting connector state

    Args:
        connector_name: Name of the connector

    Returns:
        Dict with restart result
    """
    try:
        client = _get_client()

        response = client.post(f"/connectors/{connector_name}/restart")
        response.raise_for_status()

        client.close()

        logger.info(
            "debezium_connector_restarted",
            connector=connector_name,
        )

        return {
            "name": connector_name,
            "action": "restart",
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_restart_connector", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Connector '{connector_name}' not found",
            }
        raise ToolExecutionError(
            "debezium_restart_connector",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "debezium_restart_connector_failed",
            error=str(e),
            connector=connector_name,
        )
        raise ToolExecutionError("debezium_restart_connector", str(e), e)


def debezium_restart_task(connector_name: str, task_id: int) -> dict[str, Any]:
    """
    Restart a specific task of a Kafka Connect connector.

    Args:
        connector_name: Name of the connector
        task_id: Task ID to restart

    Returns:
        Dict with restart result
    """
    try:
        client = _get_client()

        response = client.post(f"/connectors/{connector_name}/tasks/{task_id}/restart")
        response.raise_for_status()

        client.close()

        logger.info(
            "debezium_task_restarted",
            connector=connector_name,
            task_id=task_id,
        )

        return {
            "name": connector_name,
            "task_id": task_id,
            "action": "restart_task",
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_restart_task", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Connector '{connector_name}' or task {task_id} not found",
            }
        raise ToolExecutionError(
            "debezium_restart_task",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "debezium_restart_task_failed",
            error=str(e),
            connector=connector_name,
            task_id=task_id,
        )
        raise ToolExecutionError("debezium_restart_task", str(e), e)


def debezium_pause_connector(connector_name: str) -> dict[str, Any]:
    """
    Pause a Kafka Connect connector.

    Useful for:
    - Maintenance windows
    - Troubleshooting without losing progress
    - Controlled stop of CDC

    Args:
        connector_name: Name of the connector

    Returns:
        Dict with pause result
    """
    try:
        client = _get_client()

        response = client.put(f"/connectors/{connector_name}/pause")
        response.raise_for_status()

        client.close()

        logger.info(
            "debezium_connector_paused",
            connector=connector_name,
        )

        return {
            "name": connector_name,
            "action": "pause",
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_pause_connector", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Connector '{connector_name}' not found",
            }
        raise ToolExecutionError(
            "debezium_pause_connector",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "debezium_pause_connector_failed",
            error=str(e),
            connector=connector_name,
        )
        raise ToolExecutionError("debezium_pause_connector", str(e), e)


def debezium_resume_connector(connector_name: str) -> dict[str, Any]:
    """
    Resume a paused Kafka Connect connector.

    Args:
        connector_name: Name of the connector

    Returns:
        Dict with resume result
    """
    try:
        client = _get_client()

        response = client.put(f"/connectors/{connector_name}/resume")
        response.raise_for_status()

        client.close()

        logger.info(
            "debezium_connector_resumed",
            connector=connector_name,
        )

        return {
            "name": connector_name,
            "action": "resume",
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_resume_connector", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Connector '{connector_name}' not found",
            }
        raise ToolExecutionError(
            "debezium_resume_connector",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "debezium_resume_connector_failed",
            error=str(e),
            connector=connector_name,
        )
        raise ToolExecutionError("debezium_resume_connector", str(e), e)


def debezium_delete_connector(connector_name: str) -> dict[str, Any]:
    """
    Delete a Kafka Connect connector.

    WARNING: This permanently removes the connector and stops CDC.
    Offset information is retained in Kafka.

    Args:
        connector_name: Name of the connector

    Returns:
        Dict with deletion result
    """
    try:
        client = _get_client()

        response = client.delete(f"/connectors/{connector_name}")
        response.raise_for_status()

        client.close()

        logger.info(
            "debezium_connector_deleted",
            connector=connector_name,
        )

        return {
            "name": connector_name,
            "action": "delete",
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_delete_connector", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Connector '{connector_name}' not found",
            }
        raise ToolExecutionError(
            "debezium_delete_connector",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "debezium_delete_connector_failed",
            error=str(e),
            connector=connector_name,
        )
        raise ToolExecutionError("debezium_delete_connector", str(e), e)


def debezium_get_connector_plugins() -> dict[str, Any]:
    """
    List available connector plugins.

    Returns:
        Dict with available connector plugins
    """
    try:
        client = _get_client()

        response = client.get("/connector-plugins")
        response.raise_for_status()

        plugins = response.json()
        client.close()

        # Categorize plugins
        debezium_plugins = [
            p for p in plugins if "debezium" in p.get("class", "").lower()
        ]
        other_plugins = [
            p for p in plugins if "debezium" not in p.get("class", "").lower()
        ]

        logger.info("debezium_plugins_listed", count=len(plugins))

        return {
            "plugin_count": len(plugins),
            "debezium_count": len(debezium_plugins),
            "debezium_plugins": [p.get("class") for p in debezium_plugins],
            "other_plugins": [p.get("class") for p in other_plugins],
            "plugins": plugins,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "debezium_get_connector_plugins", "kafka_connect"
        )
    except httpx.HTTPStatusError as e:
        raise ToolExecutionError(
            "debezium_get_connector_plugins",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error("debezium_get_connector_plugins_failed", error=str(e))
        raise ToolExecutionError("debezium_get_connector_plugins", str(e), e)


# List of all Debezium/Kafka Connect tools for registration
DEBEZIUM_TOOLS = [
    debezium_list_connectors,
    debezium_get_connector_status,
    debezium_get_connector_config,
    debezium_create_connector,
    debezium_update_connector,
    debezium_restart_connector,
    debezium_restart_task,
    debezium_pause_connector,
    debezium_resume_connector,
    debezium_delete_connector,
    debezium_get_connector_plugins,
]
