"""GitHub API client for PR review operations.

Supports credential proxy mode (production) and direct token mode (local dev).
Credentials are injected automatically by the proxy — scripts should NOT
check for GITHUB_TOKEN in environment variables.
"""

import base64
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
    """Get the GitHub API URL, routing through credential proxy in production."""
    base_url = os.getenv("GITHUB_BASE_URL")
    if not base_url:
        base_url = "https://api.github.com"
    return f"{base_url.rstrip('/')}{endpoint}"


def get_headers() -> dict[str, str]:
    """Get headers for GitHub API requests."""
    config = get_config()

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    sandbox_jwt = os.getenv("SANDBOX_JWT")
    if sandbox_jwt:
        headers["X-Sandbox-JWT"] = sandbox_jwt
    else:
        headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
        headers["X-Team-Id"] = config.get("team_id") or "local"

    token = os.getenv("GITHUB_TOKEN")
    if token and not os.getenv("GITHUB_BASE_URL"):
        headers["Authorization"] = f"Bearer {token}"

    return headers


def api_request(
    method: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | list | None = None,
) -> dict[str, Any] | list:
    """Make a request to the GitHub API."""
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


# =========================================================================
# Read operations
# =========================================================================


def get_pr(owner: str, repo: str, pr_number: int) -> dict[str, Any]:
    """Get pull request details."""
    return api_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")


def get_pr_files(
    owner: str, repo: str, pr_number: int, per_page: int = 100
) -> list[dict[str, Any]]:
    """Get files changed in a pull request."""
    return api_request(
        "GET",
        f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
        params={"per_page": min(per_page, 100)},
    )


def read_file(owner: str, repo: str, path: str, ref: str | None = None) -> str:
    """Read a file's contents from the repository.

    Returns the decoded file content as a string.
    """
    params = {}
    if ref:
        params["ref"] = ref

    result = api_request("GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)

    if isinstance(result, list):
        raise RuntimeError(f"{path} is a directory, not a file")

    content = result.get("content", "")
    encoding = result.get("encoding", "base64")

    if encoding == "base64":
        return base64.b64decode(content).decode("utf-8")
    return content


def search_code(
    query: str, repo: str | None = None, per_page: int = 20
) -> dict[str, Any]:
    """Search code across repositories.

    Args:
        query: Search query (GitHub code search syntax)
        repo: Limit search to a specific repo (owner/repo)
        per_page: Results per page
    """
    full_query = query
    if repo:
        full_query += f" repo:{repo}"

    return api_request(
        "GET",
        "/search/code",
        params={"q": full_query, "per_page": min(per_page, 100)},
    )


def list_reviews(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    """List all reviews on a pull request."""
    return api_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews")


def list_review_comments(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    """List all inline review comments on a pull request."""
    return api_request(
        "GET",
        f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
        params={"per_page": 100},
    )


def list_pr_comments(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    """List all general (non-inline) comments on a PR."""
    return api_request(
        "GET",
        f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
        params={"per_page": 100},
    )


def compare_commits(owner: str, repo: str, base: str, head: str) -> dict[str, Any]:
    """Compare two commits and return the diff.

    Returns files changed between base and head.
    """
    return api_request("GET", f"/repos/{owner}/{repo}/compare/{base}...{head}")


# =========================================================================
# Write operations
# =========================================================================


def create_review(
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    comments: list[dict[str, Any]] | None = None,
    event: str = "COMMENT",
) -> dict[str, Any]:
    """Create a PR review with optional inline comments.

    Args:
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number
        body: Review summary body
        comments: List of inline comments, each with:
            - path (str): File path relative to repo root
            - line (int): Line number in the new version of the file
            - body (str): Comment text (supports GitHub markdown + suggestion blocks)
        event: Review event type — COMMENT, APPROVE, or REQUEST_CHANGES

    Returns:
        Created review object
    """
    # Fetch PR to get the head commit SHA — required for line-level comments
    pr = get_pr(owner, repo, pr_number)
    commit_id = pr.get("head", {}).get("sha")

    payload: dict[str, Any] = {
        "body": body,
        "event": event,
    }
    if commit_id:
        payload["commit_id"] = commit_id

    if comments:
        payload["comments"] = [
            {
                "path": c["path"],
                "line": c["line"],
                "side": "RIGHT",
                "body": c["body"],
            }
            for c in comments
        ]

    return api_request(
        "POST",
        f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
        json_data=payload,
    )


def add_pr_comment(owner: str, repo: str, pr_number: int, body: str) -> dict[str, Any]:
    """Add a general comment on a PR (not inline, not a review)."""
    return api_request(
        "POST",
        f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
        json_data={"body": body},
    )


def create_branch(
    owner: str, repo: str, branch: str, from_branch: str | None = None
) -> dict[str, Any]:
    """Create a new branch.

    If from_branch is not specified, branches from the repo's default branch.
    """
    # Get source ref SHA
    if from_branch:
        ref_data = api_request(
            "GET", f"/repos/{owner}/{repo}/git/ref/heads/{from_branch}"
        )
    else:
        # Get default branch
        repo_data = api_request("GET", f"/repos/{owner}/{repo}")
        default_branch = repo_data.get("default_branch", "main")
        ref_data = api_request(
            "GET", f"/repos/{owner}/{repo}/git/ref/heads/{default_branch}"
        )

    sha = ref_data.get("object", {}).get("sha")
    if not sha:
        raise RuntimeError("Could not get SHA for source branch")

    return api_request(
        "POST",
        f"/repos/{owner}/{repo}/git/refs",
        json_data={"ref": f"refs/heads/{branch}", "sha": sha},
    )


def create_or_update_file(
    owner: str,
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: str,
    sha: str | None = None,
) -> dict[str, Any]:
    """Create or update a file in a repository.

    For updates, pass the current file SHA (from read_file_with_sha).
    Content should be the full file content (will be base64-encoded automatically).
    """
    import base64

    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    return api_request(
        "PUT", f"/repos/{owner}/{repo}/contents/{path}", json_data=payload
    )


def create_pull_request(
    owner: str,
    repo: str,
    title: str,
    head: str,
    body: str = "",
    base: str | None = None,
) -> dict[str, Any]:
    """Create a pull request.

    If base is not specified, uses the repo's default branch.
    """
    payload = {"title": title, "head": head, "body": body}
    if base:
        payload["base"] = base
    else:
        repo_data = api_request("GET", f"/repos/{owner}/{repo}")
        payload["base"] = repo_data.get("default_branch", "main")

    return api_request("POST", f"/repos/{owner}/{repo}/pulls", json_data=payload)


def create_commit_status(
    owner: str,
    repo: str,
    sha: str,
    state: str,
    description: str = "",
    context: str = "IncidentFox",
    target_url: str | None = None,
) -> dict[str, Any]:
    """Create a commit status (shows as check in PR UI).

    Valid states: error, failure, pending, success.
    """
    payload = {"state": state, "description": description[:140], "context": context}
    if target_url:
        payload["target_url"] = target_url

    return api_request(
        "POST", f"/repos/{owner}/{repo}/statuses/{sha}", json_data=payload
    )


def read_file_with_sha(
    owner: str, repo: str, path: str, ref: str | None = None
) -> dict[str, Any]:
    """Read a file's contents and SHA (needed for updates).

    Returns dict with 'content' (decoded string) and 'sha'.
    """
    params = {}
    if ref:
        params["ref"] = ref

    result = api_request("GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)

    if isinstance(result, list):
        raise RuntimeError(f"{path} is a directory, not a file")

    content = result.get("content", "")
    encoding = result.get("encoding", "base64")

    decoded = (
        base64.b64decode(content).decode("utf-8") if encoding == "base64" else content
    )
    return {"content": decoded, "sha": result.get("sha", ""), "path": path}


# =========================================================================
# Formatting helpers
# =========================================================================


def format_pr_summary(pr: dict[str, Any]) -> str:
    """Format PR details for display."""
    number = pr.get("number")
    title = pr.get("title", "")
    user = pr.get("user", {}).get("login", "unknown")
    state = pr.get("state", "")
    head = pr.get("head", {}).get("ref", "")
    base = pr.get("base", {}).get("ref", "")
    body = pr.get("body") or "(no description)"

    return (
        f"PR #{number}: {title}\n"
        f"Author: {user} | State: {state}\n"
        f"Branch: {head} → {base}\n"
        f"Description:\n{body[:1000]}"
    )


def format_file_changes(files: list[dict[str, Any]]) -> str:
    """Format file changes for display."""
    lines = [f"Files changed: {len(files)}\n"]
    for f in files:
        status = f.get("status", "modified")
        filename = f.get("filename", "")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        lines.append(f"  [{status}] {filename} (+{additions} -{deletions})")
    return "\n".join(lines)
