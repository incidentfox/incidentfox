"""
Coralogix tools for querying logs, metrics, and traces.

Coralogix API documentation: https://coralogix.com/docs/
"""

import json
import logging
import os
from datetime import datetime, timedelta

import httpx

from ..core.config_required import handle_integration_not_configured
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError

logger = logging.getLogger(__name__)


def get_coralogix_config() -> dict:
    """
    Get Coralogix configuration from execution context.

    Priority:
    1. Execution context (production, multi-tenant safe)
    2. Environment variables (dev/testing fallback)

    Returns:
        Coralogix configuration dict

    Raises:
        IntegrationNotConfiguredError: If integration not configured
    """
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("coralogix")
        if config and config.get("api_key"):
            logger.debug(
                "coralogix_config_from_context",
                org_id=context.org_id,
                team_node_id=context.team_node_id,
            )
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("CORALOGIX_API_KEY"):
        logger.debug("coralogix_config_from_env")
        return {
            "api_key": os.getenv("CORALOGIX_API_KEY"),
            "region": os.getenv("CORALOGIX_REGION", "cx498"),
            "team_id": os.getenv("CORALOGIX_TEAM_ID"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="coralogix",
        tool_id="search_coralogix_logs",
        missing_fields=["api_key", "region"],
    )


def _get_api_url(endpoint: str) -> str:
    """Build Coralogix API URL from region."""
    config = get_coralogix_config()
    region = config.get("region", "cx498")

    # Build API URL from region (e.g., cx498, eu1, ap1)
    base_url = f"https://ng-api-http.{region}.coralogix.com"

    return f"{base_url}{endpoint}"


def _get_headers() -> dict:
    """Get Coralogix API headers."""
    config = get_coralogix_config()
    api_key = config.get("api_key", "")

    # Coralogix uses "Bearer <token>" format, but make sure we don't double-add Bearer
    if api_key.lower().startswith("bearer "):
        auth_value = api_key
    else:
        auth_value = f"Bearer {api_key}"

    return {
        "Authorization": auth_value,
        "Content-Type": "application/json",
    }


def search_coralogix_logs(
    query: str,
    time_range_minutes: int = 60,
    limit: int = 100,
    severity: str | None = None,
) -> str:
    """
    Search Coralogix logs using DataPrime query language.

    IMPORTANT: Use correct DataPrime syntax:
    - Equality: == (not = or =~)
    - Labels are accessed via $l.fieldname
    - Metadata via $m.fieldname

    Common fields:
    - $l.applicationname: Application/environment name
    - $l.subsystemname: Service name (matches your service naming)
    - $m.severity: "1"-"6" (1=Debug, 5=Error, 6=Critical)

    Example queries:
    - List all services: "source logs | groupby $l.subsystemname aggregate count() as cnt | orderby cnt desc | limit 20"
    - Get service errors: "source logs | filter $l.subsystemname == '<service>' | filter $m.severity >= '5' | limit 50"
    - Search for text: "source logs | filter $d.logRecord.body contains 'error' | limit 20"

    Args:
        query: DataPrime query string. ALWAYS start with "source logs |"
        time_range_minutes: How far back to search (default 60 minutes)
        limit: Maximum number of results (default 100)
        severity: Optional severity filter (Debug, Verbose, Info, Warning, Error, Critical)

    Returns:
        JSON with log entries. Each entry has: metadata, labels, userData (contains the log body).
    """
    try:
        config = get_coralogix_config()
    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "search_coralogix_logs", "coralogix"
        )

    logger.info(f"Searching Coralogix logs: {query[:50]}...")

    try:
        # Build the query
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=time_range_minutes)

        # DataPrime query endpoint
        url = _get_api_url("/api/v1/dataprime/query")

        payload = {
            "query": query,
            "metadata": {
                "startDate": start_time.isoformat() + "Z",
                "endDate": end_time.isoformat() + "Z",
                "tier": "TIER_FREQUENT_SEARCH",
            },
            "limit": limit,
        }

        if severity:
            payload["metadata"]["severity"] = severity.upper()

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=_get_headers(), json=payload)
            response.raise_for_status()

            # Coralogix returns NDJSON (newline-delimited JSON)
            # Parse each line as separate JSON object
            lines = response.text.strip().split("\n")
            all_results = []
            for line in lines:
                if line.strip():
                    try:
                        obj = json.loads(line)
                        # Extract results from the response structure
                        if "result" in obj and "results" in obj["result"]:
                            all_results.extend(obj["result"]["results"])
                    except json.JSONDecodeError:
                        continue

            return json.dumps(
                {
                    "success": True,
                    "query": query,
                    "time_range": f"Last {time_range_minutes} minutes",
                    "result_count": len(all_results),
                    "results": all_results[:limit],
                },
                indent=2,
                default=str,
            )

    except httpx.HTTPStatusError as e:
        logger.error(f"Coralogix API error: {e.response.status_code}")
        return json.dumps(
            {
                "success": False,
                "error": f"API error: {e.response.status_code}",
                "details": e.response.text[:500] if e.response.text else None,
            }
        )
    except Exception as e:
        logger.error(f"Coralogix query failed: {e}")
        return json.dumps({"success": False, "error": str(e)})


def get_coralogix_error_logs(
    service: str | None = None,
    application: str | None = None,
    time_range_minutes: int = 60,
    limit: int = 50,
    include_warnings: bool = True,
) -> str:
    """
    Get recent error logs from Coralogix for a specific service.

    This tool searches for logs that:
    1. Have severity >= Warning (4) if include_warnings=True, or >= Error (5) otherwise
    2. OR contain error-related keywords in the log body (Error, failed, exception)

    Args:
        service: Service name to filter (matches $l.subsystemname)
        application: Application/environment name (matches $l.applicationname).
                     IMPORTANT: Set this to filter logs to your specific environment.
        time_range_minutes: How far back to search (default 60 minutes)
        limit: Maximum number of results (default 50)
        include_warnings: Include warning-level logs (default True, recommended since
                         many errors are logged at warning level)

    Returns:
        JSON with error logs. Check the 'body' field in userData for the actual error message.
    """
    # Build DataPrime query
    # Strategy: Use text-based search to catch errors logged at any severity level
    # Many applications log errors at WARNING or INFO level
    query = "source logs"

    # Filter by application first (for multi-tenant isolation)
    if application:
        query += f" | filter $l.applicationname == '{application}'"

    # Filter by service
    if service:
        query += f" | filter $l.subsystemname == '{service}'"

    # Search for error-related content OR high severity
    # $d ~~ 'pattern' does full-text search on the document
    severity_threshold = "4" if include_warnings else "5"
    query += f" | filter $m.severity >= '{severity_threshold}' || $d ~~ 'Error' || $d ~~ 'failed' || $d ~~ 'exception'"

    query += f" | limit {limit}"

    return search_coralogix_logs(query, time_range_minutes, limit)


def get_coralogix_alerts(
    status: str | None = None,
    severity: str | None = None,
    limit: int = 20,
) -> str:
    """
    Get Coralogix alerts by querying recent alert events from logs.

    Args:
        status: Optional status filter (Active, Resolved, Snoozed)
        severity: Optional severity filter (Info, Warning, Critical)
        limit: Maximum number of alerts (default 20)

    Returns:
        JSON with alert information.
    """
    try:
        config = get_coralogix_config()
    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "get_coralogix_alerts", "coralogix")

    logger.info("Fetching Coralogix alerts via DataPrime query...")

    # Query for warning and error level logs as "alerts"
    # Coralogix severity: 4=Warning, 5=Error, 6=Critical
    query = "source logs | filter $m.severity == '4' || $m.severity == '5' || $m.severity == '6'"
    query += f" | limit {limit}"

    return search_coralogix_logs(query, time_range_minutes=60, limit=limit)


def query_coralogix_metrics(
    metric_name: str,
    time_range_minutes: int = 60,
    aggregation: str = "avg",
    group_by: str | None = None,
) -> str:
    """
    Query Coralogix metrics using PromQL-compatible syntax.

    Args:
        metric_name: Name of the metric to query
        time_range_minutes: Time range for the query (default 60 minutes)
        aggregation: Aggregation function (avg, sum, min, max, count)
        group_by: Optional label to group results by

    Returns:
        JSON with metric data points.
    """
    try:
        config = get_coralogix_config()
    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "query_coralogix_metrics", "coralogix"
        )

    logger.info(f"Querying Coralogix metric: {metric_name}")

    try:
        url = _get_api_url("/api/v1/metrics/query")

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=time_range_minutes)

        # Build PromQL query
        if group_by:
            promql = f"{aggregation}({metric_name}) by ({group_by})"
        else:
            promql = f"{aggregation}({metric_name})"

        payload = {
            "query": promql,
            "start": int(start_time.timestamp()),
            "end": int(end_time.timestamp()),
            "step": "60s",
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=_get_headers(), json=payload)
            response.raise_for_status()

            result = response.json()
            return json.dumps(
                {
                    "success": True,
                    "metric": metric_name,
                    "aggregation": aggregation,
                    "time_range": f"Last {time_range_minutes} minutes",
                    "data": result.get("data", {}),
                },
                indent=2,
                default=str,
            )

    except Exception as e:
        logger.error(f"Coralogix metrics query failed: {e}")
        return json.dumps({"success": False, "error": str(e)})


def search_coralogix_traces(
    service: str | None = None,
    operation: str | None = None,
    min_duration_ms: int | None = None,
    time_range_minutes: int = 60,
    limit: int = 50,
) -> str:
    """
    Search Coralogix distributed traces.

    Args:
        service: Service name to filter traces
        operation: Operation/span name to filter
        min_duration_ms: Minimum duration in milliseconds (for finding slow traces)
        time_range_minutes: Time range for search (default 60 minutes)
        limit: Maximum traces to return (default 50)

    Returns:
        JSON with trace information.
    """
    try:
        config = get_coralogix_config()
    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "search_coralogix_traces", "coralogix"
        )

    logger.info(f"Searching Coralogix traces for service: {service}")

    try:
        url = _get_api_url("/api/v1/tracing/spans")

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=time_range_minutes)

        payload = {
            "startTimeUnixNano": int(start_time.timestamp() * 1e9),
            "endTimeUnixNano": int(end_time.timestamp() * 1e9),
            "limit": limit,
        }

        if service:
            payload["serviceName"] = service
        if operation:
            payload["operationName"] = operation
        if min_duration_ms:
            payload["minDurationNano"] = min_duration_ms * 1_000_000

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=_get_headers(), json=payload)
            response.raise_for_status()

            traces = response.json()
            return json.dumps(
                {
                    "success": True,
                    "service": service,
                    "trace_count": len(traces.get("spans", [])),
                    "spans": traces.get("spans", [])[:limit],
                },
                indent=2,
                default=str,
            )

    except Exception as e:
        logger.error(f"Coralogix trace search failed: {e}")
        return json.dumps({"success": False, "error": str(e)})


def get_coralogix_service_health(service: str, time_range_minutes: int = 60) -> str:
    """
    Get overall health summary for a service from Coralogix.

    Args:
        service: Service/application name
        time_range_minutes: Time range to analyze (default 60 minutes)

    Returns:
        JSON with service health metrics (error rate, latency, throughput).
    """
    try:
        config = get_coralogix_config()
    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "get_coralogix_service_health", "coralogix"
        )

    logger.info(f"Getting Coralogix health for service: {service}")

    # Get error logs count
    error_result = json.loads(
        get_coralogix_error_logs(service, time_range_minutes, limit=1000)
    )

    # Build summary
    health_summary = {
        "service": service,
        "time_range": f"Last {time_range_minutes} minutes",
        "error_count": (
            error_result.get("result_count", 0)
            if error_result.get("success")
            else "unknown"
        ),
        "status": "healthy" if error_result.get("result_count", 0) < 10 else "degraded",
    }

    if error_result.get("result_count", 0) >= 50:
        health_summary["status"] = "critical"

    return json.dumps(
        {
            "success": True,
            **health_summary,
        },
        indent=2,
    )


def list_coralogix_services(time_range_minutes: int = 60) -> str:
    """
    List all services (subsystems) that have emitted logs to Coralogix recently.

    Use this as a discovery tool to find which services are active and their log volumes.

    Args:
        time_range_minutes: How far back to look (default 60 minutes)

    Returns:
        JSON with service names and log counts, sorted by volume (highest first).
    """
    query = "source logs | groupby $l.subsystemname aggregate count() as log_count | orderby log_count desc | limit 30"
    return search_coralogix_logs(query, time_range_minutes, limit=30)


def coralogix_get_alert_rules() -> str:
    """
    Get all Coralogix alert rules/configurations.

    Returns:
        JSON with list of configured alert rules
    """
    try:
        config = get_coralogix_config()
    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "coralogix_get_alert_rules", "coralogix"
        )

    logger.info("Fetching Coralogix alert rules...")

    try:
        url = _get_api_url("/api/v1/alerts")

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=_get_headers())
            response.raise_for_status()

            alerts = response.json()

            return json.dumps(
                {
                    "success": True,
                    "alert_count": len(alerts.get("alerts", [])),
                    "alerts": alerts.get("alerts", []),
                },
                indent=2,
                default=str,
            )

    except Exception as e:
        logger.error(f"Coralogix get alert rules failed: {e}")
        return json.dumps({"success": False, "error": str(e)})


def coralogix_get_alert_history(
    alert_name: str | None = None, time_range_minutes: int = 1440
) -> str:
    """
    Get firing history for Coralogix alerts.

    Args:
        alert_name: Optional alert name to filter
        time_range_minutes: Time range to query (default 24 hours)

    Returns:
        JSON with alert firing history
    """
    try:
        config = get_coralogix_config()
    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "coralogix_get_alert_history", "coralogix"
        )

    logger.info(f"Fetching Coralogix alert history for: {alert_name or 'all alerts'}")

    try:
        # Query for alert-level logs (severity 4-6)
        query = "source logs | filter $m.severity >= '4'"

        if alert_name:
            query += f" | filter $d ~~ '{alert_name}'"

        query += " | limit 100"

        result = search_coralogix_logs(query, time_range_minutes, limit=100)

        # Parse the result
        result_data = json.loads(result)

        if result_data.get("success"):
            # Group by time to show alert frequency
            alerts = result_data.get("results", [])

            return json.dumps(
                {
                    "success": True,
                    "alert_name": alert_name,
                    "time_range_minutes": time_range_minutes,
                    "firing_count": len(alerts),
                    "recent_firings": alerts[:20],  # Most recent 20
                },
                indent=2,
                default=str,
            )
        else:
            return result

    except Exception as e:
        logger.error(f"Coralogix alert history failed: {e}")
        return json.dumps({"success": False, "error": str(e)})


# List of all Coralogix tools for registration
CORALOGIX_TOOLS = [
    search_coralogix_logs,
    get_coralogix_error_logs,
    get_coralogix_alerts,
    query_coralogix_metrics,
    search_coralogix_traces,
    get_coralogix_service_health,
    list_coralogix_services,
    coralogix_get_alert_rules,
    coralogix_get_alert_history,
]
