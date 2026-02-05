"""
Datadog monitoring and APM tools.

Provides Datadog API access for metrics, logs, and APM data.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from ..core.agent import function_tool
from . import register_tool

logger = logging.getLogger(__name__)


def _get_datadog_client():
    """Get Datadog API client."""
    try:
        from datadog_api_client import ApiClient, Configuration
    except ImportError:
        raise RuntimeError(
            "datadog-api-client not installed: pip install datadog-api-client"
        )

    api_key = os.getenv("DATADOG_API_KEY")
    app_key = os.getenv("DATADOG_APP_KEY")

    if not api_key or not app_key:
        raise ValueError("DATADOG_API_KEY and DATADOG_APP_KEY must be set")

    config = Configuration()
    config.api_key["apiKeyAuth"] = api_key
    config.api_key["appKeyAuth"] = app_key

    return ApiClient(config)


@function_tool
def query_datadog_metrics(query: str, time_range_minutes: int = 60) -> str:
    """
    Query metrics from Datadog.

    Args:
        query: Datadog metric query (e.g., 'avg:system.cpu.user{*}')
        time_range_minutes: Time range in minutes (default 60)

    Returns:
        JSON with metric data points
    """
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    logger.info(f"query_datadog_metrics: query={query}")

    try:
        from datadog_api_client.v1.api.metrics_api import MetricsApi

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=time_range_minutes)

        with _get_datadog_client() as api_client:
            api_instance = MetricsApi(api_client)
            response = api_instance.query_metrics(
                _from=int(start_time.timestamp()),
                to=int(end_time.timestamp()),
                query=query,
            )

        series_data = []
        if hasattr(response, "series") and response.series:
            for s in response.series[:10]:  # Limit series
                series_data.append(
                    {
                        "metric": s.get("metric"),
                        "scope": s.get("scope"),
                        "pointlist": s.get("pointlist", [])[-100:],  # Last 100 points
                    }
                )

        return json.dumps(
            {
                "ok": True,
                "query": query,
                "from_time": str(start_time),
                "to_time": str(end_time),
                "series": series_data,
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set DATADOG_API_KEY and DATADOG_APP_KEY",
            }
        )
    except Exception as e:
        logger.error(f"query_datadog_metrics error: {e}")
        return json.dumps({"ok": False, "error": str(e), "query": query})


@function_tool
def search_datadog_logs(
    query: str,
    time_range_minutes: int = 15,
    limit: int = 100,
) -> str:
    """
    Search logs in Datadog.

    Args:
        query: Datadog log query
        time_range_minutes: Time range in minutes (default 15)
        limit: Maximum results

    Returns:
        JSON with log entries
    """
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    logger.info(f"search_datadog_logs: query={query}")

    try:
        from datadog_api_client.v2.api.logs_api import LogsApi
        from datadog_api_client.v2.model.logs_list_request import LogsListRequest
        from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter

        start_time = datetime.utcnow() - timedelta(minutes=time_range_minutes)

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
            attrs = log.attributes
            logs.append(
                {
                    "timestamp": str(attrs.timestamp) if attrs.timestamp else None,
                    "message": attrs.message,
                    "service": attrs.service,
                    "status": attrs.status,
                }
            )

        return json.dumps(
            {
                "ok": True,
                "query": query,
                "logs": logs,
                "count": len(logs),
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set DATADOG_API_KEY and DATADOG_APP_KEY",
            }
        )
    except Exception as e:
        logger.error(f"search_datadog_logs error: {e}")
        return json.dumps({"ok": False, "error": str(e), "query": query})


@function_tool
def get_service_apm_metrics(service_name: str, time_range_minutes: int = 60) -> str:
    """
    Get APM metrics for a service from Datadog.

    Args:
        service_name: Service name
        time_range_minutes: Time range in minutes

    Returns:
        JSON with APM metrics (latency, errors, throughput)
    """
    if not service_name:
        return json.dumps({"ok": False, "error": "service_name is required"})

    logger.info(f"get_service_apm_metrics: service={service_name}")

    try:
        # Query common APM metrics
        latency = query_datadog_metrics(
            f"avg:trace.servlet.request{{service:{service_name}}}",
            time_range_minutes,
        )
        errors = query_datadog_metrics(
            f"sum:trace.servlet.request.errors{{service:{service_name}}}",
            time_range_minutes,
        )
        throughput = query_datadog_metrics(
            f"sum:trace.servlet.request.hits{{service:{service_name}}}",
            time_range_minutes,
        )

        return json.dumps(
            {
                "ok": True,
                "service": service_name,
                "metrics": {
                    "latency": json.loads(latency),
                    "errors": json.loads(errors),
                    "throughput": json.loads(throughput),
                },
            }
        )

    except Exception as e:
        logger.error(f"get_service_apm_metrics error: {e}")
        return json.dumps({"ok": False, "error": str(e), "service": service_name})


# Register tools
register_tool("query_datadog_metrics", query_datadog_metrics)
register_tool("search_datadog_logs", search_datadog_logs)
register_tool("get_service_apm_metrics", get_service_apm_metrics)
