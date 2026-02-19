"""Shared Grafana/Prometheus API client with credential proxy support.

This client is designed to work with the IncidentFox credential proxy.
Credentials are injected automatically - scripts should NOT check for
GRAFANA_API_KEY in environment variables.
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx


def get_config() -> dict[str, Any]:
    """Load configuration from standard locations."""
    config = {}

    # Check for config file
    config_paths = [
        Path.home() / ".incidentfox" / "config.json",
        Path("/etc/incidentfox/config.json"),
    ]

    for path in config_paths:
        if path.exists():
            with open(path) as f:
                config = json.load(f)
                break

    # Environment overrides
    if os.getenv("TENANT_ID"):
        config["tenant_id"] = os.getenv("TENANT_ID")
    if os.getenv("TEAM_ID"):
        config["team_id"] = os.getenv("TEAM_ID")

    return config


def get_grafana_url(endpoint: str) -> str:
    """Get the Grafana API URL for an endpoint.

    In production, this routes through the credential proxy.
    """
    base_url = os.getenv("GRAFANA_BASE_URL") or os.getenv("GRAFANA_URL")
    if not base_url:
        raise RuntimeError(
            "GRAFANA_BASE_URL or GRAFANA_URL not set. "
            "Agent must run through credential proxy."
        )

    return f"{base_url.rstrip('/')}{endpoint}"


def get_prometheus_url(endpoint: str) -> str:
    """Get the Prometheus API URL for an endpoint.

    In production, this routes through the credential proxy.
    """
    base_url = os.getenv("PROMETHEUS_BASE_URL") or os.getenv("PROMETHEUS_URL")
    if not base_url:
        raise RuntimeError(
            "PROMETHEUS_BASE_URL or PROMETHEUS_URL not set. "
            "Agent must run through credential proxy."
        )

    return f"{base_url.rstrip('/')}{endpoint}"


def get_grafana_headers() -> dict[str, str]:
    """Get headers for Grafana API requests.

    Supports multiple auth methods:
    1. Service Account token (Bearer) - GRAFANA_API_KEY or GRAFANA_TOKEN
    2. Basic auth - GRAFANA_API_KEY="user:pass" or GRAFANA_USER + GRAFANA_PASSWORD
    3. Proxy mode - tenant context headers

    Environment variables:
        GRAFANA_API_KEY: Service account token (glsa_xxx) or "user:pass"
        GRAFANA_TOKEN: Service account token (alternative)
        GRAFANA_USER + GRAFANA_PASSWORD: Basic auth credentials
    """
    config = get_config()
    import base64

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Priority 1: API key / Service Account token
    api_key = os.getenv("GRAFANA_API_KEY") or os.getenv("GRAFANA_TOKEN")
    if api_key:
        if ":" in api_key:
            # Basic auth format (user:pass)
            encoded = base64.b64encode(api_key.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        else:
            # Bearer token (service account)
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    # Priority 2: Explicit user/password
    user = os.getenv("GRAFANA_USER")
    password = os.getenv("GRAFANA_PASSWORD")
    if user and password:
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
        return headers

    # Priority 3: Proxy mode - add JWT for authentication with credential-resolver
    # The JWT contains tenant/team context and is validated by credential-resolver
    sandbox_jwt = os.getenv("SANDBOX_JWT")
    if sandbox_jwt:
        headers["X-Sandbox-JWT"] = sandbox_jwt
    else:
        # Fallback to tenant headers (for local dev without JWT)
        headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
        headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def get_prometheus_headers() -> dict[str, str]:
    """Get headers for Prometheus API requests.

    Supports multiple auth methods:
    1. Bearer token - PROMETHEUS_TOKEN
    2. Basic auth - PROMETHEUS_USER + PROMETHEUS_PASSWORD
    3. Falls back to Grafana auth (for Grafana datasource proxy)

    Environment variables:
        PROMETHEUS_TOKEN: Bearer token
        PROMETHEUS_USER + PROMETHEUS_PASSWORD: Basic auth
    """
    import base64

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Priority 1: Bearer token
    token = os.getenv("PROMETHEUS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers

    # Priority 2: Basic auth
    user = os.getenv("PROMETHEUS_USER")
    password = os.getenv("PROMETHEUS_PASSWORD")
    if user and password:
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
        return headers

    # Priority 3: Fall back to Grafana auth (for datasource proxy pattern)
    return get_grafana_headers()


def get_headers() -> dict[str, str]:
    """Get headers for API requests (backward compatible).

    Uses Grafana headers by default.
    """
    return get_grafana_headers()


def query_prometheus(
    query: str,
    time_seconds: int | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Execute an instant PromQL query.

    Args:
        query: PromQL query string
        time_seconds: Evaluation timestamp (Unix seconds), default now
        timeout: Query timeout in seconds

    Returns:
        Prometheus query result
    """
    url = get_prometheus_url("/api/v1/query")

    params = {"query": query, "timeout": f"{timeout}s"}
    if time_seconds:
        params["time"] = str(time_seconds)

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_prometheus_headers(), params=params)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Prometheus API error {response.status_code}: {response.text}"
            )

        return response.json()


def query_prometheus_range(
    query: str,
    start_seconds: int,
    end_seconds: int,
    step: str = "1m",
    timeout: int = 30,
) -> dict[str, Any]:
    """Execute a range PromQL query.

    Args:
        query: PromQL query string
        start_seconds: Start timestamp (Unix seconds)
        end_seconds: End timestamp (Unix seconds)
        step: Query step (e.g., "1m", "5m", "1h")
        timeout: Query timeout in seconds

    Returns:
        Prometheus query result with time series
    """
    url = get_prometheus_url("/api/v1/query_range")

    params = {
        "query": query,
        "start": str(start_seconds),
        "end": str(end_seconds),
        "step": step,
        "timeout": f"{timeout}s",
    }

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_prometheus_headers(), params=params)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Prometheus API error {response.status_code}: {response.text}"
            )

        return response.json()


def list_dashboards(query: str | None = None) -> list[dict[str, Any]]:
    """List Grafana dashboards.

    Args:
        query: Optional search query

    Returns:
        List of dashboard objects
    """
    url = get_grafana_url("/api/search")

    params = {"type": "dash-db"}
    if query:
        params["query"] = query

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers(), params=params)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Grafana API error {response.status_code}: {response.text}"
            )

        return response.json()


def get_dashboard(uid: str) -> dict[str, Any]:
    """Get a Grafana dashboard by UID.

    Args:
        uid: Dashboard UID

    Returns:
        Dashboard object with panels
    """
    url = get_grafana_url(f"/api/dashboards/uid/{uid}")

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers())

        if response.status_code >= 400:
            raise RuntimeError(
                f"Grafana API error {response.status_code}: {response.text}"
            )

        return response.json()


def get_alerts(state: str | None = None) -> list[dict[str, Any]]:
    """Get Grafana alerts.

    Args:
        state: Filter by state (alerting, pending, ok, etc.)

    Returns:
        List of alert objects
    """
    url = get_grafana_url("/api/alerts")

    params = {}
    if state:
        params["state"] = state

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers(), params=params)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Grafana API error {response.status_code}: {response.text}"
            )

        return response.json()


def get_annotations(
    from_seconds: int | None = None,
    to_seconds: int | None = None,
    tags: list[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get Grafana annotations (deployment markers, etc.).

    Args:
        from_seconds: Start timestamp (Unix milliseconds)
        to_seconds: End timestamp (Unix milliseconds)
        tags: Filter by tags
        limit: Maximum results

    Returns:
        List of annotation objects
    """
    url = get_grafana_url("/api/annotations")

    params = {"limit": limit}
    if from_seconds:
        params["from"] = str(from_seconds * 1000)  # Convert to milliseconds
    if to_seconds:
        params["to"] = str(to_seconds * 1000)
    if tags:
        params["tags"] = ",".join(tags)

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers(), params=params)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Grafana API error {response.status_code}: {response.text}"
            )

        return response.json()


def format_metric_result(result: dict[str, Any]) -> str:
    """Format a Prometheus query result for display."""
    status = result.get("status", "unknown")
    data = result.get("data", {})
    result_type = data.get("resultType", "unknown")
    results = data.get("result", [])

    output = f"Status: {status}\n"
    output += f"Result type: {result_type}\n"
    output += f"Series count: {len(results)}\n\n"

    for r in results[:20]:  # Limit display
        metric = r.get("metric", {})
        labels = ", ".join(f"{k}={v}" for k, v in metric.items())

        if result_type == "vector":
            value = r.get("value", [None, None])
            output += f"  {{{labels}}}: {value[1]}\n"
        elif result_type == "matrix":
            values = r.get("values", [])
            output += f"  {{{labels}}}: {len(values)} samples\n"
            if values:
                output += f"    Latest: {values[-1][1]}\n"

    if len(results) > 20:
        output += f"\n  ... and {len(results) - 20} more series"

    return output
