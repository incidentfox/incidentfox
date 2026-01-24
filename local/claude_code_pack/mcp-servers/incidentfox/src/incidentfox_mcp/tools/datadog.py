"""Datadog monitoring and APM tools.

Provides tools for querying Datadog:
- query_datadog_metrics: Query metrics
- search_datadog_logs: Search logs
- get_service_apm_metrics: Get APM traces and metrics
"""

import json
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from ..utils.config import get_env


class DatadogConfigError(Exception):
    """Raised when Datadog is not configured."""

    def __init__(self, message: str):
        super().__init__(message)


def _get_datadog_config():
    """Get Datadog configuration from environment or config file."""
    api_key = get_env("DATADOG_API_KEY")
    app_key = get_env("DATADOG_APP_KEY")

    if not api_key or not app_key:
        missing = []
        if not api_key:
            missing.append("DATADOG_API_KEY")
        if not app_key:
            missing.append("DATADOG_APP_KEY")
        raise DatadogConfigError(
            f"Datadog not configured. Missing: {', '.join(missing)}. "
            f"Use save_credential tool to set these, or export as environment variables."
        )

    return {"api_key": api_key, "app_key": app_key}


def _get_datadog_client():
    """Get Datadog API client."""
    try:
        from datadog_api_client import ApiClient, Configuration

        dd_config = _get_datadog_config()

        config = Configuration()
        config.api_key["apiKeyAuth"] = dd_config["api_key"]
        config.api_key["appKeyAuth"] = dd_config["app_key"]

        return ApiClient(config)

    except ImportError:
        raise DatadogConfigError("datadog-api-client not installed")


def register_tools(mcp: FastMCP):
    """Register Datadog tools with the MCP server."""

    @mcp.tool()
    def query_datadog_metrics(query: str, hours_ago: int = 1) -> str:
        """Query metrics from Datadog.

        Args:
            query: Datadog metric query (e.g., "avg:system.cpu.user{*}", "sum:requests{service:api}.as_count()")
            hours_ago: How many hours back to query (default: 1)

        Returns:
            JSON with metric data points
        """
        try:
            from datadog_api_client.v1.api.metrics_api import MetricsApi

            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours_ago)

            with _get_datadog_client() as api_client:
                api_instance = MetricsApi(api_client)
                response = api_instance.query_metrics(
                    _from=int(start_time.timestamp()),
                    to=int(end_time.timestamp()),
                    query=query,
                )

            series_data = []
            if hasattr(response, "series") and response.series:
                for s in response.series:
                    series_data.append(
                        {
                            "metric": s.metric if hasattr(s, "metric") else query,
                            "points": (
                                [[p[0], p[1]] for p in s.pointlist]
                                if hasattr(s, "pointlist")
                                else []
                            ),
                        }
                    )

            return json.dumps(
                {
                    "query": query,
                    "series": series_data,
                    "from_time": str(start_time),
                    "to_time": str(end_time),
                },
                indent=2,
            )

        except DatadogConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "query": query})

    @mcp.tool()
    def search_datadog_logs(
        query: str,
        minutes_ago: int = 15,
        limit: int = 100,
    ) -> str:
        """Search logs in Datadog.

        Use the Datadog log query syntax for filtering.

        Args:
            query: Datadog log query (e.g., "service:api status:error", "@http.status_code:>=500")
            minutes_ago: How many minutes back to search (default: 15)
            limit: Maximum number of results (default: 100)

        Returns:
            JSON with log entries
        """
        try:
            from datadog_api_client.v2.api.logs_api import LogsApi
            from datadog_api_client.v2.model.logs_list_request import LogsListRequest
            from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter

            start_time = datetime.utcnow() - timedelta(minutes=minutes_ago)

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
                        "message": attrs.message if hasattr(attrs, "message") else None,
                        "service": attrs.service if hasattr(attrs, "service") else None,
                        "status": attrs.status if hasattr(attrs, "status") else None,
                        "host": attrs.host if hasattr(attrs, "host") else None,
                    }
                )

            return json.dumps(
                {
                    "query": query,
                    "log_count": len(logs),
                    "logs": logs,
                },
                indent=2,
            )

        except DatadogConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "query": query})

    @mcp.tool()
    def get_service_apm_metrics(
        service: str,
        env: str = "production",
        hours_ago: int = 1,
    ) -> str:
        """Get APM metrics for a service from Datadog.

        Returns request rate, error rate, and latency percentiles.

        Args:
            service: Service name as it appears in Datadog APM
            env: Environment (default: "production")
            hours_ago: How many hours back to query (default: 1)

        Returns:
            JSON with APM metrics (requests, errors, latency)
        """
        try:
            from datadog_api_client.v1.api.metrics_api import MetricsApi

            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours_ago)

            metrics = {}
            queries = {
                "requests_per_second": f"sum:trace.http.request.hits{{service:{service},env:{env}}}.as_rate()",
                "error_rate": f"sum:trace.http.request.errors{{service:{service},env:{env}}}.as_rate()",
                "latency_p50": f"p50:trace.http.request.duration{{service:{service},env:{env}}}",
                "latency_p95": f"p95:trace.http.request.duration{{service:{service},env:{env}}}",
                "latency_p99": f"p99:trace.http.request.duration{{service:{service},env:{env}}}",
            }

            with _get_datadog_client() as api_client:
                api_instance = MetricsApi(api_client)

                for metric_name, query in queries.items():
                    try:
                        response = api_instance.query_metrics(
                            _from=int(start_time.timestamp()),
                            to=int(end_time.timestamp()),
                            query=query,
                        )

                        if hasattr(response, "series") and response.series:
                            points = response.series[0].pointlist
                            if points:
                                # Get the latest value
                                metrics[metric_name] = points[-1][1]
                    except Exception:
                        metrics[metric_name] = None

            return json.dumps(
                {
                    "service": service,
                    "env": env,
                    "metrics": metrics,
                    "from_time": str(start_time),
                    "to_time": str(end_time),
                },
                indent=2,
            )

        except DatadogConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "service": service})
