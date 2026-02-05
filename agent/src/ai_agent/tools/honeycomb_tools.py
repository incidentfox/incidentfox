"""Honeycomb observability tools."""

import os
import time
from typing import Any

import httpx

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_API_ENDPOINT = "https://api.honeycomb.io"


def _get_honeycomb_config() -> dict:
    """Get Honeycomb configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("honeycomb")
        if config and config.get("api_key"):
            return {
                "api_key": config["api_key"],
                "api_endpoint": config.get("api_endpoint", DEFAULT_API_ENDPOINT),
            }

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("HONEYCOMB_API_KEY"):
        return {
            "api_key": os.getenv("HONEYCOMB_API_KEY"),
            "api_endpoint": os.getenv("HONEYCOMB_API_ENDPOINT", DEFAULT_API_ENDPOINT),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="honeycomb",
        tool_id="honeycomb_tools",
        missing_fields=["api_key"],
    )


def _get_honeycomb_headers() -> dict[str, str]:
    """Get Honeycomb API headers."""
    config = _get_honeycomb_config()
    return {
        "X-Honeycomb-Team": config["api_key"],
        "Content-Type": "application/json",
    }


def _get_base_url() -> str:
    """Get the Honeycomb API base URL."""
    config = _get_honeycomb_config()
    return config["api_endpoint"].rstrip("/")


def honeycomb_list_datasets() -> list[dict[str, Any]]:
    """
    List all datasets in the Honeycomb environment.

    Returns:
        List of datasets with their names, slugs, and descriptions
    """
    try:
        url = f"{_get_base_url()}/1/datasets"

        with httpx.Client() as client:
            response = client.get(url, headers=_get_honeycomb_headers(), timeout=30)
            response.raise_for_status()
            datasets = response.json()

        result = []
        for ds in datasets:
            result.append(
                {
                    "name": ds.get("name"),
                    "slug": ds.get("slug"),
                    "description": ds.get("description"),
                    "created_at": ds.get("created_at"),
                    "last_written_at": ds.get("last_written_at"),
                }
            )

        logger.info("honeycomb_datasets_listed", count=len(result))
        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "honeycomb_list_datasets", "honeycomb"
        )
    except Exception as e:
        logger.error("honeycomb_list_datasets_failed", error=str(e))
        raise ToolExecutionError("honeycomb_list_datasets", str(e), e)


def honeycomb_get_columns(dataset_slug: str) -> list[dict[str, Any]]:
    """
    Get all columns (fields) available in a Honeycomb dataset.

    Args:
        dataset_slug: The dataset slug/identifier

    Returns:
        List of columns with their names, types, and descriptions
    """
    try:
        url = f"{_get_base_url()}/1/columns/{dataset_slug}"

        with httpx.Client() as client:
            response = client.get(url, headers=_get_honeycomb_headers(), timeout=30)
            response.raise_for_status()
            columns = response.json()

        result = []
        for col in columns:
            result.append(
                {
                    "key_name": col.get("key_name"),
                    "type": col.get("type"),
                    "description": col.get("description"),
                    "hidden": col.get("hidden", False),
                    "last_written": col.get("last_written"),
                }
            )

        logger.info("honeycomb_columns_listed", dataset=dataset_slug, count=len(result))
        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "honeycomb_get_columns", "honeycomb"
        )
    except Exception as e:
        logger.error("honeycomb_get_columns_failed", error=str(e), dataset=dataset_slug)
        raise ToolExecutionError("honeycomb_get_columns", str(e), e)


def honeycomb_run_query(
    dataset_slug: str,
    calculations: list[dict[str, str]] | None = None,
    filters: list[dict[str, Any]] | None = None,
    breakdowns: list[str] | None = None,
    time_range: int = 3600,
    granularity: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Run an analytics query on a Honeycomb dataset.

    Args:
        dataset_slug: The dataset slug/identifier
        calculations: List of calculations, e.g., [{"op": "COUNT"}, {"op": "AVG", "column": "duration_ms"}]
                     Supported ops: COUNT, SUM, AVG, MAX, MIN, P50, P75, P90, P95, P99,
                                   HEATMAP, COUNT_DISTINCT, CONCURRENCY, RATE_AVG, RATE_SUM, RATE_MAX
        filters: List of filters, e.g., [{"column": "status_code", "op": "=", "value": 500}]
                Filter ops: =, !=, >, >=, <, <=, starts-with, does-not-start-with,
                           exists, does-not-exist, contains, does-not-contain, in, not-in
        breakdowns: List of columns to group by, e.g., ["service.name", "http.method"]
        time_range: Time range in seconds (default: 3600 = 1 hour, max: 604800 = 7 days)
        granularity: Time bucket size in seconds (optional, auto-calculated if not set)
        limit: Maximum number of results per group (optional)

    Returns:
        Query results with data points and metadata

    Example:
        honeycomb_run_query(
            "production",
            calculations=[{"op": "COUNT"}, {"op": "P99", "column": "duration_ms"}],
            filters=[{"column": "http.status_code", "op": ">=", "value": 500}],
            breakdowns=["service.name"],
            time_range=3600
        )
    """
    try:
        base_url = _get_base_url()
        headers = _get_honeycomb_headers()

        # Default to COUNT if no calculations specified
        if not calculations:
            calculations = [{"op": "COUNT"}]

        # Build query spec
        query_spec = {
            "calculations": calculations,
            "time_range": time_range,
        }

        if filters:
            query_spec["filters"] = filters
        if breakdowns:
            query_spec["breakdowns"] = breakdowns
        if granularity:
            query_spec["granularity"] = granularity
        if limit:
            query_spec["limit"] = limit

        with httpx.Client(timeout=60) as client:
            # Step 1: Create query spec
            create_response = client.post(
                f"{base_url}/1/queries/{dataset_slug}",
                headers=headers,
                json=query_spec,
            )
            create_response.raise_for_status()
            query_data = create_response.json()
            query_id = query_data.get("id")

            if not query_id:
                raise ToolExecutionError(
                    "honeycomb_run_query",
                    "Failed to create query - no query ID returned",
                )

            # Step 2: Execute query
            execute_response = client.post(
                f"{base_url}/1/query_results/{dataset_slug}",
                headers=headers,
                json={"query_id": query_id},
            )
            execute_response.raise_for_status()
            result_data = execute_response.json()
            query_result_id = result_data.get("id")

            if not query_result_id:
                raise ToolExecutionError(
                    "honeycomb_run_query",
                    "Failed to execute query - no result ID returned",
                )

            # Step 3: Poll for results
            max_attempts = 30
            poll_interval = 1.0

            for attempt in range(max_attempts):
                poll_response = client.get(
                    f"{base_url}/1/query_results/{dataset_slug}/{query_result_id}",
                    headers=headers,
                )
                poll_response.raise_for_status()
                poll_data = poll_response.json()

                if poll_data.get("complete"):
                    # Query completed
                    result = {
                        "query_id": query_id,
                        "result_id": query_result_id,
                        "data": poll_data.get("data", {}).get("results", []),
                        "series": poll_data.get("data", {}).get("series", []),
                        "complete": True,
                    }

                    logger.info(
                        "honeycomb_query_completed",
                        dataset=dataset_slug,
                        results=len(result["data"]),
                    )
                    return result

                time.sleep(poll_interval)

            # Timeout
            raise ToolExecutionError(
                "honeycomb_run_query",
                f"Query timed out after {max_attempts * poll_interval} seconds",
            )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "honeycomb_run_query", "honeycomb")
    except ToolExecutionError:
        raise
    except Exception as e:
        logger.error("honeycomb_run_query_failed", error=str(e), dataset=dataset_slug)
        raise ToolExecutionError("honeycomb_run_query", str(e), e)


def honeycomb_list_slos(dataset_slug: str) -> list[dict[str, Any]]:
    """
    List all SLOs (Service Level Objectives) for a dataset.

    Args:
        dataset_slug: The dataset slug/identifier

    Returns:
        List of SLOs with their names, targets, and current status
    """
    try:
        url = f"{_get_base_url()}/1/slos/{dataset_slug}"

        with httpx.Client() as client:
            response = client.get(url, headers=_get_honeycomb_headers(), timeout=30)
            response.raise_for_status()
            slos = response.json()

        result = []
        for slo in slos:
            result.append(
                {
                    "id": slo.get("id"),
                    "name": slo.get("name"),
                    "description": slo.get("description"),
                    "target_percentage": slo.get("target_percentage"),
                    "time_period_days": slo.get("time_period_days"),
                    "sli": slo.get("sli"),
                }
            )

        logger.info("honeycomb_slos_listed", dataset=dataset_slug, count=len(result))
        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "honeycomb_list_slos", "honeycomb")
    except Exception as e:
        logger.error("honeycomb_list_slos_failed", error=str(e), dataset=dataset_slug)
        raise ToolExecutionError("honeycomb_list_slos", str(e), e)


def honeycomb_get_slo(dataset_slug: str, slo_id: str) -> dict[str, Any]:
    """
    Get detailed information about a specific SLO including current budget status.

    Args:
        dataset_slug: The dataset slug/identifier
        slo_id: The SLO identifier

    Returns:
        SLO details including target, current budget, and burn rate
    """
    try:
        url = f"{_get_base_url()}/1/slos/{dataset_slug}/{slo_id}"

        with httpx.Client() as client:
            response = client.get(url, headers=_get_honeycomb_headers(), timeout=30)
            response.raise_for_status()
            slo = response.json()

        result = {
            "id": slo.get("id"),
            "name": slo.get("name"),
            "description": slo.get("description"),
            "target_percentage": slo.get("target_percentage"),
            "time_period_days": slo.get("time_period_days"),
            "sli": slo.get("sli"),
            "budget_remaining": slo.get("budget_remaining"),
            "exhaustion_time": slo.get("exhaustion_time"),
            "created_at": slo.get("created_at"),
            "updated_at": slo.get("updated_at"),
        }

        logger.info("honeycomb_slo_fetched", dataset=dataset_slug, slo_id=slo_id)
        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "honeycomb_get_slo", "honeycomb")
    except Exception as e:
        logger.error(
            "honeycomb_get_slo_failed",
            error=str(e),
            dataset=dataset_slug,
            slo_id=slo_id,
        )
        raise ToolExecutionError("honeycomb_get_slo", str(e), e)


def honeycomb_list_triggers(dataset_slug: str) -> list[dict[str, Any]]:
    """
    List all triggers (alerts) for a dataset.

    Args:
        dataset_slug: The dataset slug/identifier

    Returns:
        List of triggers with their names, conditions, and status
    """
    try:
        url = f"{_get_base_url()}/1/triggers/{dataset_slug}"

        with httpx.Client() as client:
            response = client.get(url, headers=_get_honeycomb_headers(), timeout=30)
            response.raise_for_status()
            triggers = response.json()

        result = []
        for trigger in triggers:
            result.append(
                {
                    "id": trigger.get("id"),
                    "name": trigger.get("name"),
                    "description": trigger.get("description"),
                    "disabled": trigger.get("disabled", False),
                    "triggered": trigger.get("triggered", False),
                    "frequency": trigger.get("frequency"),
                    "threshold": trigger.get("threshold"),
                    "query_id": trigger.get("query_id"),
                }
            )

        logger.info(
            "honeycomb_triggers_listed", dataset=dataset_slug, count=len(result)
        )
        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "honeycomb_list_triggers", "honeycomb"
        )
    except Exception as e:
        logger.error(
            "honeycomb_list_triggers_failed", error=str(e), dataset=dataset_slug
        )
        raise ToolExecutionError("honeycomb_list_triggers", str(e), e)


def honeycomb_get_trigger(dataset_slug: str, trigger_id: str) -> dict[str, Any]:
    """
    Get detailed information about a specific trigger.

    Args:
        dataset_slug: The dataset slug/identifier
        trigger_id: The trigger identifier

    Returns:
        Trigger details including query, threshold, and recipients
    """
    try:
        url = f"{_get_base_url()}/1/triggers/{dataset_slug}/{trigger_id}"

        with httpx.Client() as client:
            response = client.get(url, headers=_get_honeycomb_headers(), timeout=30)
            response.raise_for_status()
            trigger = response.json()

        result = {
            "id": trigger.get("id"),
            "name": trigger.get("name"),
            "description": trigger.get("description"),
            "disabled": trigger.get("disabled", False),
            "triggered": trigger.get("triggered", False),
            "frequency": trigger.get("frequency"),
            "threshold": trigger.get("threshold"),
            "query_id": trigger.get("query_id"),
            "query": trigger.get("query"),
            "recipients": trigger.get("recipients", []),
            "created_at": trigger.get("created_at"),
            "updated_at": trigger.get("updated_at"),
        }

        logger.info(
            "honeycomb_trigger_fetched", dataset=dataset_slug, trigger_id=trigger_id
        )
        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "honeycomb_get_trigger", "honeycomb"
        )
    except Exception as e:
        logger.error(
            "honeycomb_get_trigger_failed",
            error=str(e),
            dataset=dataset_slug,
            trigger_id=trigger_id,
        )
        raise ToolExecutionError("honeycomb_get_trigger", str(e), e)


def honeycomb_list_markers(
    dataset_slug: str, time_range: int = 86400
) -> list[dict[str, Any]]:
    """
    List deployment markers for a dataset.

    Args:
        dataset_slug: The dataset slug/identifier
        time_range: Time range in seconds to look back (default: 86400 = 24 hours)

    Returns:
        List of markers with their messages, types, and timestamps
    """
    try:
        url = f"{_get_base_url()}/1/markers/{dataset_slug}"

        with httpx.Client() as client:
            response = client.get(url, headers=_get_honeycomb_headers(), timeout=30)
            response.raise_for_status()
            markers = response.json()

        result = []
        for marker in markers:
            result.append(
                {
                    "id": marker.get("id"),
                    "message": marker.get("message"),
                    "type": marker.get("type"),
                    "url": marker.get("url"),
                    "created_at": marker.get("created_at"),
                    "start_time": marker.get("start_time"),
                    "end_time": marker.get("end_time"),
                }
            )

        logger.info("honeycomb_markers_listed", dataset=dataset_slug, count=len(result))
        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "honeycomb_list_markers", "honeycomb"
        )
    except Exception as e:
        logger.error(
            "honeycomb_list_markers_failed", error=str(e), dataset=dataset_slug
        )
        raise ToolExecutionError("honeycomb_list_markers", str(e), e)


def honeycomb_create_marker(
    dataset_slug: str,
    message: str,
    marker_type: str = "deploy",
    url: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
) -> dict[str, Any]:
    """
    Create a deployment marker in Honeycomb.

    Args:
        dataset_slug: The dataset slug/identifier
        message: Marker message (e.g., "Deployed v1.2.3")
        marker_type: Type of marker (e.g., "deploy", "feature-flag", "incident")
        url: Optional URL to link (e.g., GitHub release URL)
        start_time: Unix timestamp for marker start (default: now)
        end_time: Unix timestamp for marker end (optional)

    Returns:
        Created marker details
    """
    try:
        url_endpoint = f"{_get_base_url()}/1/markers/{dataset_slug}"

        body = {
            "message": message,
            "type": marker_type,
        }

        if url:
            body["url"] = url
        if start_time:
            body["start_time"] = start_time
        if end_time:
            body["end_time"] = end_time

        with httpx.Client() as client:
            response = client.post(
                url_endpoint,
                headers=_get_honeycomb_headers(),
                json=body,
                timeout=30,
            )
            response.raise_for_status()
            marker = response.json()

        result = {
            "id": marker.get("id"),
            "message": marker.get("message"),
            "type": marker.get("type"),
            "url": marker.get("url"),
            "created_at": marker.get("created_at"),
            "start_time": marker.get("start_time"),
            "end_time": marker.get("end_time"),
            "success": True,
        }

        logger.info(
            "honeycomb_marker_created",
            dataset=dataset_slug,
            marker_id=result["id"],
            type=marker_type,
        )
        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "honeycomb_create_marker", "honeycomb"
        )
    except Exception as e:
        logger.error(
            "honeycomb_create_marker_failed", error=str(e), dataset=dataset_slug
        )
        raise ToolExecutionError("honeycomb_create_marker", str(e), e)


# List of all Honeycomb tools for registration
HONEYCOMB_TOOLS = [
    honeycomb_list_datasets,
    honeycomb_get_columns,
    honeycomb_run_query,
    honeycomb_list_slos,
    honeycomb_get_slo,
    honeycomb_list_triggers,
    honeycomb_get_trigger,
    honeycomb_list_markers,
    honeycomb_create_marker,
]
