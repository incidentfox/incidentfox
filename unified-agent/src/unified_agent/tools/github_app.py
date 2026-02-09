"""GitHub App integration tools for advanced CI/CD integration and PR automation."""

import os
import time
from typing import Any

import jwt
import requests

import json
import logging

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


def _get_github_app_config() -> str:
    """Get GitHub App configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    # Credentials from environment variables
    # 2. Try environment variables (dev/testing fallback)
    if (
        os.getenv("GITHUB_APP_ID")
        and os.getenv("GITHUB_APP_PRIVATE_KEY")
        and os.getenv("GITHUB_APP_INSTALLATION_ID")
    ):
        return {
            "app_id": os.getenv("GITHUB_APP_ID"),
            "private_key": os.getenv("GITHUB_APP_PRIVATE_KEY"),
            "installation_id": os.getenv("GITHUB_APP_INSTALLATION_ID"),
            "webhook_secret": os.getenv("GITHUB_APP_WEBHOOK_SECRET"),
        }

    # 3. Not configured - raise error
    return {"error": "integration not configured"}


def _generate_jwt_token(app_id: str, private_key: str) -> str:
    """Generate JWT for GitHub App authentication."""
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,  # 10 minutes
        "iss": app_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def _get_installation_token(app_id: str, private_key: str, installation_id: str) -> str:
    """Get installation access token for GitHub App."""
    jwt_token = _generate_jwt_token(app_id, private_key)

    response = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
        },
    )
    response.raise_for_status()
    return response.json()["token"]


def _get_github_headers() -> str:
    """Get GitHub API headers with authentication."""
    config = _get_github_app_config()
    token = _get_installation_token(
        config["app_id"], config["private_key"], config["installation_id"]
    )
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


@function_tool
def github_app_create_check_run(
    repo: str,
    name: str,
    head_sha: str,
    status: str = "completed",
    conclusion: str | None = None,
    output: dict[str, Any] | None = None,
) -> str:
    """
    Create a check run on a commit.

    Args:
        repo: Repository in "owner/repo" format
        name: Check run name
        head_sha: Commit SHA
        status: Check status (queued, in_progress, completed)
        conclusion: Check conclusion (success, failure, neutral, cancelled, skipped, timed_out, action_required)
        output: Check output with title, summary, and text

    Returns:
        Created check run details
    """
    try:
        headers = _get_github_headers()

        payload = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
        }

        if conclusion:
            payload["conclusion"] = conclusion

        if output:
            payload["output"] = output

        response = requests.post(
            f"https://api.github.com/repos/{repo}/check-runs",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()

        result = response.json()
        logger.info("github_check_run_created", repo=repo, name=name, sha=head_sha)

        return {
            "id": result["id"],
            "name": result["name"],
            "status": result["status"],
            "conclusion": result.get("conclusion"),
            "html_url": result["html_url"],
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("github_check_run_failed", error=str(e), repo=repo)
        return json.dumps({"ok": False, "error": "github_app_create_check_run"})


@function_tool
def github_app_add_pr_comment(
    repo: str, pr_number: int, comment: str
) -> str:
    """
    Add a comment to a pull request.

    Args:
        repo: Repository in "owner/repo" format
        pr_number: Pull request number
        comment: Comment text (supports markdown)

    Returns:
        Created comment details
    """
    try:
        headers = _get_github_headers()

        response = requests.post(
            f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments",
            json={"body": comment},
            headers=headers,
        )
        response.raise_for_status()

        result = response.json()
        logger.info("github_pr_comment_added", repo=repo, pr=pr_number)

        return {
            "id": result["id"],
            "html_url": result["html_url"],
            "created_at": result["created_at"],
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("github_pr_comment_failed", error=str(e), repo=repo, pr=pr_number)
        return json.dumps({"ok": False, "error": "github_app_add_pr_comment"})


@function_tool
def github_app_update_pr_status(
    repo: str,
    sha: str,
    state: str,
    context: str,
    description: str,
    target_url: str | None = None,
) -> str:
    """
    Update commit status (alternative to check runs).

    Args:
        repo: Repository in "owner/repo" format
        sha: Commit SHA
        state: Status state (error, failure, pending, success)
        context: Status context (e.g., "ci/integration-tests")
        description: Status description
        target_url: Optional URL with details

    Returns:
        Status update result
    """
    try:
        headers = _get_github_headers()

        payload = {
            "state": state,
            "context": context,
            "description": description,
        }

        if target_url:
            payload["target_url"] = target_url

        response = requests.post(
            f"https://api.github.com/repos/{repo}/statuses/{sha}",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()

        result = response.json()
        logger.info("github_status_updated", repo=repo, sha=sha, state=state)

        return {
            "id": result["id"],
            "state": result["state"],
            "context": result["context"],
            "created_at": result["created_at"],
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("github_status_update_failed", error=str(e), repo=repo)
        return json.dumps({"ok": False, "error": "github_app_update_pr_status"})


@function_tool
def github_app_list_installations() -> str:
    """
    List all installations for this GitHub App.

    Returns:
        List of installations
    """
    try:
        config = _get_github_app_config()
        jwt_token = _generate_jwt_token(config["app_id"], config["private_key"])

        response = requests.get(
            "https://api.github.com/app/installations",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        response.raise_for_status()

        installations = []
        for install in response.json():
            installations.append(
                {
                    "id": install["id"],
                    "account_login": install["account"]["login"],
                    "account_type": install["account"]["type"],
                    "created_at": install["created_at"],
                    "html_url": install["html_url"],
                }
            )

        logger.info("github_installations_listed", count=len(installations))
        return installations

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("github_installations_list_failed", error=str(e))
        return json.dumps({"ok": False, "error": "github_app_list_installations"})


# List of all GitHub App tools for registration
GITHUB_APP_TOOLS = [
    github_app_create_check_run,
    github_app_add_pr_comment,
    github_app_update_pr_status,
    github_app_list_installations,
]


# Register tools
register_tool("github_app_create_check_run", github_app_create_check_run)
register_tool("github_app_add_pr_comment", github_app_add_pr_comment)
register_tool("github_app_update_pr_status", github_app_update_pr_status)
register_tool("github_app_list_installations", github_app_list_installations)
