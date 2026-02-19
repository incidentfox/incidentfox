"""Vercel API client for deployment and project operations.

Supports credential proxy mode (production) and direct token mode (local dev).
Credentials are injected automatically by the proxy -- scripts should NOT
check for VERCEL_TOKEN in environment variables.
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx


def get_config() -> dict[str, Any]:
    """Load configuration from standard locations."""
    config = {}

    config_paths = [
        Path.home() / ".incidentfox" / "config.json",
        Path("/etc/incidentfox/config.json"),
    ]

    for path in config_paths:
        if path.exists():
            with open(path) as f:
                config = json.load(f)
                break

    if os.getenv("TENANT_ID"):
        config["tenant_id"] = os.getenv("TENANT_ID")
    if os.getenv("TEAM_ID"):
        config["team_id"] = os.getenv("TEAM_ID")

    return config


def get_api_url(endpoint: str) -> str:
    """Get the Vercel API URL, routing through credential proxy in production."""
    base_url = os.getenv("VERCEL_BASE_URL")
    if not base_url:
        base_url = "https://api.vercel.com"
    return f"{base_url.rstrip('/')}{endpoint}"


def get_headers() -> dict[str, str]:
    """Get headers for Vercel API requests."""
    config = get_config()

    headers = {
        "Content-Type": "application/json",
    }

    sandbox_jwt = os.getenv("SANDBOX_JWT")
    if sandbox_jwt:
        headers["X-Sandbox-JWT"] = sandbox_jwt
    else:
        headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
        headers["X-Team-Id"] = config.get("team_id") or "local"

    # Direct token mode for local development only
    token = os.getenv("VERCEL_TOKEN")
    if token and not os.getenv("VERCEL_BASE_URL"):
        headers["Authorization"] = f"Bearer {token}"

    return headers


def _inject_team_id(params: dict[str, Any] | None) -> dict[str, Any]:
    """Inject teamId query parameter if VERCEL_TEAM_ID is set."""
    if params is None:
        params = {}
    team_id = os.getenv("VERCEL_TEAM_ID")
    if team_id and "teamId" not in params:
        params["teamId"] = team_id
    return params


def api_request(
    method: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | list | None = None,
) -> dict[str, Any] | list:
    """Make a request to the Vercel API."""
    url = get_api_url(endpoint)
    headers = get_headers()
    params = _inject_team_id(params)

    with httpx.Client(timeout=60.0) as client:
        response = client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Vercel API error {response.status_code}: {response.text}"
            )

        return response.json()


# =========================================================================
# Read operations
# =========================================================================


def list_projects(limit: int = 20) -> list[dict[str, Any]]:
    """List all projects.

    Returns:
        List of project objects.
    """
    result = api_request("GET", "/v9/projects", params={"limit": limit})
    return result.get("projects", [])


def get_project(project_id: str) -> dict[str, Any]:
    """Get a single project by ID or name.

    Args:
        project_id: Project ID (prj_...) or project name.
    """
    return api_request("GET", f"/v9/projects/{project_id}")


def list_deployments(
    project_id: str | None = None,
    state: str | None = None,
    target: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List deployments with optional filters.

    Args:
        project_id: Filter by project ID or name.
        state: Filter by state (BUILDING, READY, ERROR, CANCELED, QUEUED).
        target: Filter by target (production, preview).
        limit: Maximum number of deployments to return.

    Returns:
        List of deployment objects.
    """
    params: dict[str, Any] = {"limit": limit}
    if project_id:
        params["projectId"] = project_id
    if state:
        params["state"] = state
    if target:
        params["target"] = target

    result = api_request("GET", "/v6/deployments", params=params)
    return result.get("deployments", [])


def get_deployment(deployment_id: str) -> dict[str, Any]:
    """Get a single deployment by ID or URL.

    Args:
        deployment_id: Deployment ID (dpl_...) or deployment URL.
    """
    return api_request("GET", f"/v13/deployments/{deployment_id}")


def get_deployment_events(deployment_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get build log events for a deployment.

    Args:
        deployment_id: Deployment ID.
        limit: Maximum number of events to return.

    Returns:
        List of deployment event objects (build log lines).
    """
    result = api_request(
        "GET",
        f"/v3/deployments/{deployment_id}/events",
        params={"limit": limit},
    )
    # The events endpoint returns a list directly
    if isinstance(result, list):
        return result
    return result.get("events", result.get("items", []))


# =========================================================================
# Write operations
# =========================================================================


def create_deployment(
    name: str,
    git_source: dict[str, Any],
    target: str = "preview",
) -> dict[str, Any]:
    """Create a new deployment.

    Args:
        name: Project name.
        git_source: Git source configuration, e.g.:
            {
                "type": "github",
                "repo": "owner/repo",
                "ref": "main"
            }
        target: Deployment target -- "production" or "preview".

    Returns:
        Created deployment object.
    """
    payload: dict[str, Any] = {
        "name": name,
        "target": target,
        "gitSource": git_source,
    }

    return api_request("POST", "/v13/deployments", json_data=payload)


# =========================================================================
# Formatting helpers
# =========================================================================


def format_project(project: dict[str, Any]) -> str:
    """Format project details for human-readable display."""
    name = project.get("name", "unknown")
    project_id = project.get("id", "")
    framework = project.get("framework") or "unknown"
    node_version = project.get("nodeVersion") or "default"

    # Git repo link
    repo_link = ""
    link = project.get("link", {})
    if link:
        link_type = link.get("type", "")
        org = link.get("org", link.get("owner", ""))
        repo = link.get("repo", "")
        if org and repo:
            repo_link = f"{org}/{repo} ({link_type})"

    # Domains
    aliases = project.get("alias", [])
    if isinstance(aliases, list):
        domains = ", ".join(
            a.get("domain", str(a)) if isinstance(a, dict) else str(a)
            for a in aliases[:5]
        )
    else:
        domains = ""

    # Targets / latest deployments
    targets = project.get("targets", {})
    prod_url = ""
    if targets and isinstance(targets, dict):
        prod = targets.get("production", {})
        if isinstance(prod, dict):
            prod_url = prod.get("url", "")

    lines = [
        f"Project: {name} ({project_id})",
        f"Framework: {framework} | Node: {node_version}",
    ]
    if repo_link:
        lines.append(f"Git Repo: {repo_link}")
    if domains:
        lines.append(f"Domains: {domains}")
    if prod_url:
        lines.append(f"Production URL: https://{prod_url}")

    return "\n".join(lines)


def format_deployment(deployment: dict[str, Any]) -> str:
    """Format deployment details for human-readable display."""
    dep_id = deployment.get("uid", deployment.get("id", ""))
    name = deployment.get("name", "")
    state = deployment.get("state", deployment.get("readyState", "UNKNOWN"))
    url = deployment.get("url", "")
    target = deployment.get("target") or "preview"
    created = deployment.get("createdAt", deployment.get("created", ""))

    # Git metadata
    meta = deployment.get("meta", {})
    branch = meta.get("githubCommitRef", meta.get("gitlabCommitRef", ""))
    commit_sha = meta.get("githubCommitSha", meta.get("gitlabCommitSha", ""))
    commit_msg = meta.get("githubCommitMessage", meta.get("gitlabCommitMessage", ""))

    # Error info
    error_code = deployment.get("errorCode", "")
    error_message = deployment.get("errorMessage", "")

    # Build timestamps
    building_at = deployment.get("buildingAt", "")
    ready = deployment.get("ready", "")

    lines = [
        f"Deployment: {dep_id}",
        f"Project: {name} | Target: {target} | State: {state}",
    ]
    if url:
        lines.append(f"URL: https://{url}")
    if branch:
        lines.append(f"Branch: {branch}")
    if commit_sha:
        short_sha = commit_sha[:8] if len(commit_sha) > 8 else commit_sha
        lines.append(
            f"Commit: {short_sha} - {commit_msg}"
            if commit_msg
            else f"Commit: {short_sha}"
        )
    if created:
        lines.append(f"Created: {_format_timestamp(created)}")
    if building_at and ready:
        lines.append(
            f"Build: {_format_timestamp(building_at)} -> {_format_timestamp(ready)}"
        )
    if error_code:
        lines.append(f"Error: [{error_code}] {error_message}")

    return "\n".join(lines)


def _format_timestamp(ts: Any) -> str:
    """Format a Vercel timestamp (milliseconds since epoch or ISO string)."""
    if isinstance(ts, (int, float)):
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(ts)
