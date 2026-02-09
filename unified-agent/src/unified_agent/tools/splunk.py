"""Splunk enterprise log management and analytics tools."""

import os
from typing import Any

import json
import logging

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


def _get_splunk_config() -> str:
    """Get Splunk configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    # Credentials from environment variables
    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("SPLUNK_HOST") and os.getenv("SPLUNK_TOKEN"):
        return {
            "host": os.getenv("SPLUNK_HOST"),
            "token": os.getenv("SPLUNK_TOKEN"),
            "default_index": os.getenv("SPLUNK_DEFAULT_INDEX", "main"),
        }

    # 3. Not configured - raise error
    return {"error": "splunk not configured"}


def _get_splunk_service():
    """Get Splunk service client."""
    try:
        import splunklib.client as client

        config = _get_splunk_config()

        return client.connect(
            host=config["host"]
            .replace("https://", "")
            .replace("http://", "")
            .split(":")[0],
            port=config.get("port", 8089),
            token=config["token"],
        )

    except ImportError:
        return json.dumps({"ok": False, "error": "Tool execution error"})
            "splunk", "splunk-sdk not installed. Install with: pip install splunk-sdk"
        )


@function_tool
def splunk_search(
    query: str,
    earliest_time: str = "-15m",
    latest_time: str = "now",
    max_results: int = 100,
) -> str:
    """
    Execute a Splunk search query.

    Args:
        query: SPL (Splunk Processing Language) search query
        earliest_time: Start time for search (e.g., "-15m", "-1h", "-1d")
        latest_time: End time for search (default: "now")
        max_results: Maximum results to return

    Returns:
        List of search results
    """
    try:
        service = _get_splunk_service()

        # Create search job
        search_kwargs = {
            "earliest_time": earliest_time,
            "latest_time": latest_time,
            "max_count": max_results,
        }

        job = service.jobs.create(query, **search_kwargs)

        # Wait for job to complete
        import time

        while not job.is_done():
            time.sleep(0.5)

        # Get results
        results = []
        for result in job.results():
            results.append(dict(result))

        logger.info(
            "splunk_search_completed", query_hash=hash(query), results=len(results)
        )

        return results

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("splunk_search_failed", error=str(e))
        return json.dumps({"ok": False, "error": "splunk_search"})


@function_tool
def splunk_list_indexes() -> str:
    """
    List all Splunk indexes.

    Returns:
        List of indexes with metadata
    """
    try:
        service = _get_splunk_service()

        indexes = []
        for index in service.indexes:
            indexes.append(
                {
                    "name": index.name,
                    "total_event_count": index.content.get("totalEventCount", 0),
                    "current_db_size_mb": round(
                        int(index.content.get("currentDBSizeMB", 0)), 2
                    ),
                    "max_time": index.content.get("maxTime"),
                    "min_time": index.content.get("minTime"),
                }
            )

        logger.info("splunk_indexes_listed", count=len(indexes))
        return indexes

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("splunk_list_indexes_failed", error=str(e))
        return json.dumps({"ok": False, "error": "splunk_list_indexes"})


@function_tool
def splunk_get_saved_searches() -> str:
    """
    Get all saved searches (alerts and reports).

    Returns:
        List of saved searches
    """
    try:
        service = _get_splunk_service()

        saved_searches = []
        for search in service.saved_searches:
            saved_searches.append(
                {
                    "name": search.name,
                    "search": search.content.get("search"),
                    "cron_schedule": search.content.get("cron_schedule"),
                    "is_scheduled": search.content.get("is_scheduled") == "1",
                    "alert_type": search.content.get("alert_type"),
                    "description": search.content.get("description", ""),
                }
            )

        logger.info("splunk_saved_searches_listed", count=len(saved_searches))
        return saved_searches

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("splunk_get_saved_searches_failed", error=str(e))
        return json.dumps({"ok": False, "error": "splunk_get_saved_searches"})


@function_tool
def splunk_get_alerts(earliest_time: str = "-24h") -> str:
    """
    Get triggered alerts.

    Args:
        earliest_time: How far back to look for alerts (e.g., "-24h", "-7d")

    Returns:
        List of triggered alerts
    """
    try:
        service = _get_splunk_service()

        # Search for fired alerts
        query = f"search index=_audit action=alert_fired earliest={earliest_time}"
        job = service.jobs.create(query)

        # Wait for completion
        import time

        while not job.is_done():
            time.sleep(0.5)

        alerts = []
        for result in job.results():
            alerts.append(
                {
                    "alert_name": result.get("savedsearch_name"),
                    "trigger_time": result.get("trigger_time"),
                    "severity": result.get("severity"),
                    "triggered_alert_count": result.get("triggered_alert_count"),
                }
            )

        logger.info("splunk_alerts_retrieved", count=len(alerts))
        return alerts

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("splunk_get_alerts_failed", error=str(e))
        return json.dumps({"ok": False, "error": "splunk_get_alerts"})


# List of all Splunk tools for registration
SPLUNK_TOOLS = [
    splunk_search,
    splunk_list_indexes,
    splunk_get_saved_searches,
    splunk_get_alerts,
]


# Register tools
register_tool("splunk_search", splunk_search)
register_tool("splunk_list_indexes", splunk_list_indexes)
register_tool("splunk_get_saved_searches", splunk_get_saved_searches)
register_tool("splunk_get_alerts", splunk_get_alerts)
