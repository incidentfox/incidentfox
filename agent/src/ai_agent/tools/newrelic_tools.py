"""New Relic APM and monitoring tools."""

import os
from typing import Any

import httpx

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_newrelic_config() -> dict:
    """Get New Relic configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("newrelic")
        if config and config.get("api_key"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("NEWRELIC_API_KEY"):
        return {"api_key": os.getenv("NEWRELIC_API_KEY")}

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="newrelic", tool_id="newrelic_tools", missing_fields=["api_key"]
    )


def _get_newrelic_headers() -> dict[str, str]:
    """Get New Relic API headers."""
    config = _get_newrelic_config()

    return {"Api-Key": config["api_key"], "Content-Type": "application/json"}


def query_newrelic_nrql(
    account_id: str, nrql_query: str, timeout: int = 30
) -> list[dict[str, Any]]:
    """
    Run an NRQL query in New Relic.

    Args:
        account_id: New Relic account ID
        nrql_query: NRQL query string
        timeout: Query timeout in seconds

    Returns:
        Query results

    Example query:
        "SELECT average(duration) FROM Transaction WHERE appName = 'MyApp' SINCE 1 hour ago"
    """
    try:
        url = "https://api.newrelic.com/graphql"

        graphql_query = """
        query($accountId: Int!, $nrql: Nrql!) {
            actor {
                account(id: $accountId) {
                    nrql(query: $nrql) {
                        results
                    }
                }
            }
        }
        """

        with httpx.Client() as client:
            response = client.post(
                url,
                headers=_get_newrelic_headers(),
                json={
                    "query": graphql_query,
                    "variables": {"accountId": int(account_id), "nrql": nrql_query},
                },
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()

        results = (
            data.get("data", {})
            .get("actor", {})
            .get("account", {})
            .get("nrql", {})
            .get("results", [])
        )

        logger.info("newrelic_nrql_completed", account=account_id, results=len(results))
        return results

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "query_newrelic_nrql", "newrelic")
    except Exception as e:
        logger.error("newrelic_nrql_failed", error=str(e), query=nrql_query)
        raise ToolExecutionError("query_newrelic_nrql", str(e), e)


def get_apm_summary(
    app_name: str, account_id: str, time_range: str = "30m"
) -> dict[str, Any]:
    """
    Get APM summary for an application.

    Args:
        app_name: Application name in New Relic
        account_id: New Relic account ID
        time_range: Time range (e.g., '30m', '1h')

    Returns:
        APM summary with key metrics
    """
    try:
        # Query key APM metrics
        queries = {
            "response_time": f"SELECT average(duration) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
            "throughput": f"SELECT count(*) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
            "error_rate": f"SELECT percentage(count(*), WHERE error = true) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
            "apdex": f"SELECT apdex(duration, t: 0.5) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
        }

        summary = {}
        for metric_name, query in queries.items():
            try:
                result = query_newrelic_nrql(account_id, query)
                summary[metric_name] = result[0] if result else None
            except:
                summary[metric_name] = None

        logger.info("newrelic_apm_summary", app=app_name)
        return {"app": app_name, "summary": summary}

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "get_apm_summary", "newrelic")
    except Exception as e:
        logger.error("newrelic_apm_failed", error=str(e), app=app_name)
        raise ToolExecutionError("get_apm_summary", str(e), e)
