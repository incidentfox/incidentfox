"""Sentry error tracking and performance monitoring tools."""

import os
from typing import Any

import requests

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_sentry_config() -> dict:
    """Get Sentry configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("sentry")
        if config and config.get("auth_token") and config.get("organization"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("SENTRY_AUTH_TOKEN") and os.getenv("SENTRY_ORGANIZATION"):
        return {
            "auth_token": os.getenv("SENTRY_AUTH_TOKEN"),
            "organization": os.getenv("SENTRY_ORGANIZATION"),
            "project": os.getenv("SENTRY_PROJECT"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="sentry",
        tool_id="sentry_tools",
        missing_fields=["auth_token", "organization"],
    )


def _get_sentry_headers() -> dict:
    """Get Sentry API headers with authentication."""
    config = _get_sentry_config()
    return {
        "Authorization": f"Bearer {config['auth_token']}",
        "Content-Type": "application/json",
    }


def sentry_list_issues(
    project: str | None = None, query: str | None = None, limit: int = 25
) -> list[dict[str, Any]]:
    """
    List Sentry issues (errors and events).

    Args:
        project: Project slug (uses config default if not specified)
        query: Optional search query (e.g., "is:unresolved")
        limit: Maximum issues to return

    Returns:
        List of Sentry issues
    """
    try:
        config = _get_sentry_config()
        headers = _get_sentry_headers()

        project_slug = project or config.get("project")
        if not project_slug:
            raise ValueError("Project must be specified in config or as parameter")

        url = f"https://sentry.io/api/0/projects/{config['organization']}/{project_slug}/issues/"

        params = {"limit": limit}
        if query:
            params["query"] = query

        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        issues = []
        for issue in response.json():
            issues.append(
                {
                    "id": issue["id"],
                    "title": issue["title"],
                    "short_id": issue["shortId"],
                    "status": issue["status"],
                    "level": issue["level"],
                    "count": issue["count"],
                    "user_count": issue["userCount"],
                    "first_seen": issue["firstSeen"],
                    "last_seen": issue["lastSeen"],
                    "permalink": issue["permalink"],
                }
            )

        logger.info("sentry_issues_listed", project=project_slug, count=len(issues))
        return issues

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "sentry_list_issues", "sentry")
    except Exception as e:
        logger.error("sentry_list_issues_failed", error=str(e), project=project)
        raise ToolExecutionError("sentry_list_issues", str(e), e)


def sentry_get_issue_details(issue_id: str) -> dict[str, Any]:
    """
    Get detailed information about a specific Sentry issue.

    Args:
        issue_id: Sentry issue ID

    Returns:
        Issue details including events and metadata
    """
    try:
        config = _get_sentry_config()
        headers = _get_sentry_headers()

        url = f"https://sentry.io/api/0/issues/{issue_id}/"

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        issue = response.json()

        logger.info("sentry_issue_details_retrieved", issue_id=issue_id)

        return {
            "id": issue["id"],
            "title": issue["title"],
            "short_id": issue["shortId"],
            "status": issue["status"],
            "level": issue["level"],
            "count": issue["count"],
            "user_count": issue["userCount"],
            "first_seen": issue["firstSeen"],
            "last_seen": issue["lastSeen"],
            "permalink": issue["permalink"],
            "metadata": issue.get("metadata", {}),
            "tags": issue.get("tags", []),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "sentry_get_issue_details", "sentry"
        )
    except Exception as e:
        logger.error("sentry_get_issue_details_failed", error=str(e), issue_id=issue_id)
        raise ToolExecutionError("sentry_get_issue_details", str(e), e)


def sentry_update_issue_status(issue_id: str, status: str) -> dict[str, Any]:
    """
    Update the status of a Sentry issue.

    Args:
        issue_id: Sentry issue ID
        status: New status (resolved, unresolved, ignored, resolvedInNextRelease)

    Returns:
        Update result
    """
    try:
        config = _get_sentry_config()
        headers = _get_sentry_headers()

        url = f"https://sentry.io/api/0/issues/{issue_id}/"

        response = requests.put(url, json={"status": status}, headers=headers)
        response.raise_for_status()

        logger.info("sentry_issue_status_updated", issue_id=issue_id, status=status)

        return {
            "issue_id": issue_id,
            "status": status,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "sentry_update_issue_status", "sentry"
        )
    except Exception as e:
        logger.error(
            "sentry_update_issue_status_failed", error=str(e), issue_id=issue_id
        )
        raise ToolExecutionError("sentry_update_issue_status", str(e), e)


def sentry_list_projects() -> list[dict[str, Any]]:
    """
    List all Sentry projects in the organization.

    Returns:
        List of projects
    """
    try:
        config = _get_sentry_config()
        headers = _get_sentry_headers()

        url = (
            f"https://sentry.io/api/0/organizations/{config['organization']}/projects/"
        )

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        projects = []
        for project in response.json():
            projects.append(
                {
                    "id": project["id"],
                    "slug": project["slug"],
                    "name": project["name"],
                    "platform": project.get("platform"),
                    "status": project.get("status"),
                }
            )

        logger.info("sentry_projects_listed", count=len(projects))
        return projects

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "sentry_list_projects", "sentry")
    except Exception as e:
        logger.error("sentry_list_projects_failed", error=str(e))
        raise ToolExecutionError("sentry_list_projects", str(e), e)


def sentry_get_project_stats(
    project: str, stat: str = "received", resolution: str = "1h"
) -> dict[str, Any]:
    """
    Get statistics for a Sentry project.

    Args:
        project: Project slug
        stat: Stat type (received, rejected, blacklisted)
        resolution: Time resolution (1h, 1d, 1w, 1m)

    Returns:
        Project statistics
    """
    try:
        config = _get_sentry_config()
        headers = _get_sentry_headers()

        url = f"https://sentry.io/api/0/projects/{config['organization']}/{project}/stats/"

        params = {
            "stat": stat,
            "resolution": resolution,
        }

        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        stats = response.json()

        logger.info("sentry_project_stats_retrieved", project=project, stat=stat)

        return {
            "project": project,
            "stat": stat,
            "resolution": resolution,
            "data": stats,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "sentry_get_project_stats", "sentry"
        )
    except Exception as e:
        logger.error("sentry_get_project_stats_failed", error=str(e), project=project)
        raise ToolExecutionError("sentry_get_project_stats", str(e), e)


def sentry_list_releases(project: str, limit: int = 10) -> list[dict[str, Any]]:
    """
    List releases for a Sentry project.

    Args:
        project: Project slug
        limit: Maximum releases to return

    Returns:
        List of releases
    """
    try:
        config = _get_sentry_config()
        headers = _get_sentry_headers()

        url = f"https://sentry.io/api/0/projects/{config['organization']}/{project}/releases/"

        params = {"per_page": limit}

        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        releases = []
        for release in response.json():
            releases.append(
                {
                    "version": release["version"],
                    "short_version": release.get("shortVersion"),
                    "date_created": release["dateCreated"],
                    "date_released": release.get("dateReleased"),
                    "new_groups": release.get("newGroups", 0),
                    "url": release.get("url"),
                }
            )

        logger.info("sentry_releases_listed", project=project, count=len(releases))
        return releases

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "sentry_list_releases", "sentry")
    except Exception as e:
        logger.error("sentry_list_releases_failed", error=str(e), project=project)
        raise ToolExecutionError("sentry_list_releases", str(e), e)


# List of all Sentry tools for registration
SENTRY_TOOLS = [
    sentry_list_issues,
    sentry_get_issue_details,
    sentry_update_issue_status,
    sentry_list_projects,
    sentry_get_project_stats,
    sentry_list_releases,
]
