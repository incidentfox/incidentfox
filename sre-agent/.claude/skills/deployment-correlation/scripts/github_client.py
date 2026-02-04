"""Shared GitHub API client with credential proxy support.

This client is designed to work with the IncidentFox credential proxy.
Credentials are injected automatically - scripts should NOT check for
GITHUB_TOKEN in environment variables.
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


def get_api_url(endpoint: str) -> str:
    """Get the GitHub API URL for an endpoint.

    In production, this routes through the credential proxy.
    The proxy injects the GitHub token automatically.
    """
    base_url = os.getenv("GITHUB_BASE_URL")
    if not base_url:
        # Fall back to direct API (for local development only)
        base_url = "https://api.github.com"

    return f"{base_url.rstrip('/')}{endpoint}"


def get_headers() -> dict[str, str]:
    """Get headers for GitHub API requests.

    The credential proxy will inject Authorization header.
    We include tenant/team IDs for the proxy to look up credentials.
    """
    config = get_config()

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Proxy mode - use JWT for credential-resolver auth
    sandbox_jwt = os.getenv("SANDBOX_JWT")
    if sandbox_jwt:
        headers["X-Sandbox-JWT"] = sandbox_jwt
    else:
        # Fallback for local dev
        headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
        headers["X-Team-Id"] = config.get("team_id") or "local"

    # For local development, allow direct token usage
    token = os.getenv("GITHUB_TOKEN")
    if token and not os.getenv("GITHUB_BASE_URL"):
        headers["Authorization"] = f"Bearer {token}"

    return headers


def api_request(
    method: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a request to the GitHub API.

    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint (e.g., /repos/owner/repo/commits)
        params: Query parameters
        json_data: JSON body for POST/PUT requests

    Returns:
        Parsed JSON response

    Raises:
        RuntimeError: If the request fails
    """
    url = get_api_url(endpoint)
    headers = get_headers()

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
                f"GitHub API error {response.status_code}: {response.text}"
            )

        return response.json()


def list_commits(
    owner: str,
    repo: str,
    branch: str | None = None,
    since: str | None = None,
    until: str | None = None,
    per_page: int = 30,
) -> list[dict[str, Any]]:
    """List commits in a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch name (default: default branch)
        since: ISO 8601 timestamp to start from
        until: ISO 8601 timestamp to end at
        per_page: Number of results per page (max 100)

    Returns:
        List of commit objects
    """
    params = {"per_page": min(per_page, 100)}
    if branch:
        params["sha"] = branch
    if since:
        params["since"] = since
    if until:
        params["until"] = until

    return api_request("GET", f"/repos/{owner}/{repo}/commits", params=params)


def get_commit(owner: str, repo: str, sha: str) -> dict[str, Any]:
    """Get detailed information about a specific commit.

    Args:
        owner: Repository owner
        repo: Repository name
        sha: Commit SHA

    Returns:
        Detailed commit object with files changed
    """
    return api_request("GET", f"/repos/{owner}/{repo}/commits/{sha}")


def compare_commits(
    owner: str,
    repo: str,
    base: str,
    head: str,
) -> dict[str, Any]:
    """Compare two commits or branches.

    Args:
        owner: Repository owner
        repo: Repository name
        base: Base commit/branch
        head: Head commit/branch

    Returns:
        Comparison object with commits and files changed
    """
    return api_request("GET", f"/repos/{owner}/{repo}/compare/{base}...{head}")


def list_pull_requests(
    owner: str,
    repo: str,
    state: str = "all",
    base: str | None = None,
    per_page: int = 30,
) -> list[dict[str, Any]]:
    """List pull requests in a repository.

    Args:
        owner: Repository owner
        repo: Repository name
        state: Filter by state (open, closed, all)
        base: Filter by base branch
        per_page: Number of results per page

    Returns:
        List of pull request objects
    """
    params = {"state": state, "per_page": min(per_page, 100)}
    if base:
        params["base"] = base

    return api_request("GET", f"/repos/{owner}/{repo}/pulls", params=params)


def get_pull_request(owner: str, repo: str, pr_number: int) -> dict[str, Any]:
    """Get detailed information about a pull request.

    Args:
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number

    Returns:
        Pull request object
    """
    return api_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")


def get_pr_files(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Get files changed in a pull request.

    Args:
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number

    Returns:
        List of file objects with changes
    """
    return api_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}/files")


def list_workflow_runs(
    owner: str,
    repo: str,
    branch: str | None = None,
    status: str | None = None,
    per_page: int = 30,
) -> dict[str, Any]:
    """List workflow runs (CI/CD).

    Args:
        owner: Repository owner
        repo: Repository name
        branch: Filter by branch
        status: Filter by status (completed, in_progress, queued)
        per_page: Number of results per page

    Returns:
        Object with workflow_runs array
    """
    params = {"per_page": min(per_page, 100)}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status

    return api_request("GET", f"/repos/{owner}/{repo}/actions/runs", params=params)


def format_commit(commit: dict[str, Any], detailed: bool = False) -> str:
    """Format a commit for display.

    Args:
        commit: Commit object from API
        detailed: Include files changed

    Returns:
        Formatted string
    """
    sha = commit.get("sha", "")[:7]
    message = commit.get("commit", {}).get("message", "").split("\n")[0]
    author = commit.get("commit", {}).get("author", {}).get("name", "unknown")
    date = commit.get("commit", {}).get("author", {}).get("date", "")

    output = f"{sha} - {message} ({author}, {date})"

    if detailed and "files" in commit:
        output += "\n  Files changed:"
        for f in commit.get("files", [])[:10]:
            status = f.get("status", "modified")
            filename = f.get("filename", "")
            output += f"\n    [{status}] {filename}"
        if len(commit.get("files", [])) > 10:
            output += f"\n    ... and {len(commit['files']) - 10} more files"

    return output
