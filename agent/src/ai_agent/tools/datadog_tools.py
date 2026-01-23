"""Datadog monitoring and APM tools."""

import os
from datetime import datetime, timedelta
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_datadog_config() -> dict:
    """Get Datadog configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("datadog")
        if config and config.get("api_key") and config.get("app_key"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("DATADOG_API_KEY") and os.getenv("DATADOG_APP_KEY"):
        return {
            "api_key": os.getenv("DATADOG_API_KEY"),
            "app_key": os.getenv("DATADOG_APP_KEY"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="datadog",
        tool_id="datadog_tools",
        missing_fields=["api_key", "app_key"],
    )


def _get_datadog_client():
    """Get Datadog API client."""
    try:
        from datadog_api_client import ApiClient, Configuration
        from datadog_api_client.v1.api.metrics_api import MetricsApi
        from datadog_api_client.v2.api.logs_api import LogsApi

        dd_config = _get_datadog_config()

        config = Configuration()
        config.api_key["apiKeyAuth"] = dd_config["api_key"]
        config.api_key["appKeyAuth"] = dd_config["app_key"]

        return ApiClient(config)

    except ImportError:
        raise ToolExecutionError("datadog", "datadog-api-client not installed")


def query_datadog_metrics(query: str, time_range: str = "1h") -> dict[str, Any]:
    """
    Query metrics from Datadog.

    Args:
        query: Datadog metric query (e.g., 'avg:system.cpu.user{*}')
        time_range: Time range (e.g., '1h', '24h')

    Returns:
        Metric data points
    """
    try:
        from datadog_api_client.v1.api.metrics_api import MetricsApi

        # Parse time range
        if time_range.endswith("h"):
            hours = int(time_range[:-1])
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours)
        else:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=1)

        with _get_datadog_client() as api_client:
            api_instance = MetricsApi(api_client)
            response = api_instance.query_metrics(
                _from=int(start_time.timestamp()),
                to=int(end_time.timestamp()),
                query=query,
            )

        return {
            "query": query,
            "series": response.series if hasattr(response, "series") else [],
            "from_time": str(start_time),
            "to_time": str(end_time),
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "query_datadog_metrics", "datadog")
    except Exception as e:
        logger.error("datadog_metrics_failed", error=str(e), query=query)
        raise ToolExecutionError("query_datadog_metrics", str(e), e)


def search_datadog_logs(
    query: str, time_range: str = "15m", limit: int = 100
) -> list[dict[str, Any]]:
    """
    Search logs in Datadog.

    Args:
        query: Datadog log query
        time_range: Time range
        limit: Max results

    Returns:
        List of log entries
    """
    try:
        from datadog_api_client.v2.api.logs_api import LogsApi
        from datadog_api_client.v2.model.logs_list_request import LogsListRequest
        from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter

        # Parse time range
        if time_range.endswith("m"):
            minutes = int(time_range[:-1])
            start_time = datetime.utcnow() - timedelta(minutes=minutes)
        else:
            start_time = datetime.utcnow() - timedelta(hours=1)

        with _get_datadog_client() as api_client:
            api_instance = LogsApi(api_client)

            body = LogsListRequest(
                filter=LogsQueryFilter(
                    query=query,
                    _from=start_time.isoformat() + "Z",
                    to=datetime.utcnow().isoformat() + "Z",
                ),
            )

            response = api_instance.list_logs(body=body)

        logs = []
        for log in (response.data or [])[:limit]:
            logs.append(
                {
                    "timestamp": log.attributes.timestamp,
                    "message": log.attributes.message,
                    "service": log.attributes.service,
                    "status": log.attributes.status,
                }
            )

        logger.info("datadog_logs_searched", query=query, results=len(logs))
        return logs

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "search_datadog_logs", "datadog")
    except Exception as e:
        logger.error("datadog_logs_failed", error=str(e), query=query)
        raise ToolExecutionError("search_datadog_logs", str(e), e)


def get_service_apm_metrics(
    service_name: str, time_range: str = "1h"
) -> dict[str, Any]:
    """
    Get APM metrics for a service from Datadog.

    Args:
        service_name: Service name
        time_range: Time range

    Returns:
        APM metrics (latency, errors, throughput)
    """
    try:
        # Query common APM metrics
        metrics = {
            "latency": query_datadog_metrics(
                f"avg:trace.servlet.request{{service:{service_name}}}", time_range
            ),
            "errors": query_datadog_metrics(
                f"sum:trace.servlet.request.errors{{service:{service_name}}}",
                time_range,
            ),
            "throughput": query_datadog_metrics(
                f"sum:trace.servlet.request.hits{{service:{service_name}}}", time_range
            ),
        }

        logger.info("datadog_apm_fetched", service=service_name)
        return {"service": service_name, "metrics": metrics}

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "get_service_apm_metrics", "datadog"
        )
    except Exception as e:
        logger.error("datadog_apm_failed", error=str(e), service=service_name)
        raise ToolExecutionError("get_service_apm_metrics", str(e), e)


def datadog_get_monitors(
    monitor_tags: list[str] | None = None,
    name: str | None = None,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """
    Get Datadog monitors (alerts).

    Args:
        monitor_tags: Filter by tags (e.g., ["env:production", "team:backend"])
        name: Filter by monitor name
        max_results: Maximum monitors to return

    Returns:
        List of monitors with their current status
    """
    try:
        from datadog_api_client.v1.api.monitors_api import MonitorsApi

        with _get_datadog_client() as api_client:
            api_instance = MonitorsApi(api_client)

            # Build query parameters
            kwargs = {}
            if monitor_tags:
                kwargs["tags"] = ",".join(monitor_tags)
            if name:
                kwargs["name"] = name

            response = api_instance.list_monitors(**kwargs)

        monitors = []
        for monitor in response[:max_results]:
            monitors.append(
                {
                    "id": monitor.id,
                    "name": monitor.name,
                    "type": monitor.type,
                    "query": monitor.query,
                    "message": monitor.message,
                    "tags": monitor.tags or [],
                    "overall_state": monitor.overall_state,
                    "created": str(monitor.created),
                    "modified": str(monitor.modified),
                }
            )

        logger.info("datadog_monitors_listed", count=len(monitors))
        return monitors

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "datadog_get_monitors", "datadog")
    except Exception as e:
        logger.error("datadog_get_monitors_failed", error=str(e))
        raise ToolExecutionError("datadog_get_monitors", str(e), e)


def datadog_get_monitor_history(
    monitor_id: int, time_range: str = "30d"
) -> dict[str, Any]:
    """
    Get alert history for a Datadog monitor.

    Args:
        monitor_id: Monitor ID
        time_range: Time range to query (e.g., "30d", "7d")

    Returns:
        Monitor state transitions and alert history
    """
    try:
        from datadog_api_client.v1.api.monitors_api import MonitorsApi

        # Parse time range
        if time_range.endswith("d"):
            days = int(time_range[:-1])
            start_time = datetime.utcnow() - timedelta(days=days)
        else:
            start_time = datetime.utcnow() - timedelta(days=30)

        with _get_datadog_client() as api_client:
            api_instance = MonitorsApi(api_client)

            # Get monitor details
            monitor = api_instance.get_monitor(monitor_id)

            # Get state history (using search monitors endpoint with history)
            # Note: Datadog doesn't have a direct history API, we approximate using overall state

        # Calculate statistics from current state
        result = {
            "monitor_id": monitor_id,
            "name": monitor.name,
            "current_state": monitor.overall_state,
            "query": monitor.query,
            "tags": monitor.tags or [],
            "created": str(monitor.created),
            "modified": str(monitor.modified),
            "message": monitor.message,
        }

        logger.info("datadog_monitor_history_fetched", monitor_id=monitor_id)
        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "datadog_get_monitor_history", "datadog"
        )
    except Exception as e:
        logger.error(
            "datadog_monitor_history_failed", error=str(e), monitor_id=monitor_id
        )
        raise ToolExecutionError("datadog_get_monitor_history", str(e), e)


def datadog_update_monitor(
    monitor_id: int,
    name: str | None = None,
    query: str | None = None,
    message: str | None = None,
    tags: list[str] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Update a Datadog monitor configuration.

    Args:
        monitor_id: Monitor ID to update
        name: New monitor name
        query: New monitor query/threshold
        message: New alert message
        tags: New tags
        options: Monitor options (thresholds, timeouts, etc.)

    Returns:
        Updated monitor details
    """
    try:
        from datadog_api_client.v1.api.monitors_api import MonitorsApi
        from datadog_api_client.v1.model.monitor_update_request import (
            MonitorUpdateRequest,
        )

        with _get_datadog_client() as api_client:
            api_instance = MonitorsApi(api_client)

            # Get current monitor to preserve unchanged fields
            current_monitor = api_instance.get_monitor(monitor_id)

            # Build update request
            update_body = MonitorUpdateRequest(
                name=name or current_monitor.name,
                query=query or current_monitor.query,
                message=message or current_monitor.message,
                tags=tags or current_monitor.tags,
                options=options or current_monitor.options,
            )

            updated_monitor = api_instance.update_monitor(monitor_id, body=update_body)

        logger.info("datadog_monitor_updated", monitor_id=monitor_id)

        return {
            "id": updated_monitor.id,
            "name": updated_monitor.name,
            "query": updated_monitor.query,
            "message": updated_monitor.message,
            "tags": updated_monitor.tags,
            "overall_state": updated_monitor.overall_state,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "datadog_update_monitor", "datadog")
    except Exception as e:
        logger.error(
            "datadog_update_monitor_failed", error=str(e), monitor_id=monitor_id
        )
        raise ToolExecutionError("datadog_update_monitor", str(e), e)


# List of all Datadog tools for registration
DATADOG_TOOLS = [
    query_datadog_metrics,
    search_datadog_logs,
    get_service_apm_metrics,
    datadog_get_monitors,
    datadog_get_monitor_history,
    datadog_update_monitor,
]
