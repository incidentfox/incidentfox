"""
Sentry error tracking and performance monitoring tools.

Provides Sentry API access for issues, projects, and releases.
"""

import json
import logging
import os
from typing import Optional

from ..core.agent import function_tool
from . import get_proxy_headers, register_tool

logger = logging.getLogger(__name__)


def _get_sentry_config():
    """Get Sentry configuration.

    Supports two modes:
    - Direct: SENTRY_AUTH_TOKEN + SENTRY_ORGANIZATION (sends to sentry.io)
    - Proxy: SENTRY_BASE_URL points to credential-resolver proxy (handles auth).
             The proxy adds /api/0/ prefix, so base_url should NOT include it.
    """
    base_url = os.getenv("SENTRY_BASE_URL")
    auth_token = os.getenv("SENTRY_AUTH_TOKEN")
    organization = os.getenv("SENTRY_ORGANIZATION")

    if base_url:
        # Proxy mode: credential-resolver handles auth
        return {
            "base_url": base_url.rstrip("/"),
            "auth_token": auth_token,  # May be None
            "organization": organization or "",
            "project": os.getenv("SENTRY_PROJECT"),
        }

    if not auth_token or not organization:
        raise ValueError("SENTRY_AUTH_TOKEN and SENTRY_ORGANIZATION must be set")

    return {
        "base_url": "https://sentry.io/api/0",
        "auth_token": auth_token,
        "organization": organization,
        "project": os.getenv("SENTRY_PROJECT"),
    }


def _get_sentry_headers():
    """Get Sentry API headers."""
    config = _get_sentry_config()
    headers = {"Content-Type": "application/json"}
    if config.get("auth_token"):
        headers["Authorization"] = f"Bearer {config['auth_token']}"
    else:
        # Proxy mode: add JWT/tenant headers for credential-resolver
        headers.update(get_proxy_headers())
    return headers


@function_tool
def sentry_list_issues(
    project: str = "",
    query: str = "",
    limit: int = 25,
) -> str:
    """
    List Sentry issues (errors and events).

    Args:
        project: Project slug (uses env default if not specified)
        query: Optional search query (e.g., "is:unresolved")
        limit: Maximum issues to return

    Returns:
        JSON with issues list
    """
    logger.info(f"sentry_list_issues: project={project}, query={query}")

    try:
        import requests

        config = _get_sentry_config()
        headers = _get_sentry_headers()

        project_slug = project or config.get("project")
        if not project_slug:
            return json.dumps({"ok": False, "error": "project must be specified"})

        url = f"{config['base_url']}/projects/{config['organization']}/{project_slug}/issues/"

        params = {"limit": limit}
        if query:
            params["query"] = query

        response = requests.get(url, headers=headers, params=params, timeout=30)
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

        return json.dumps(
            {
                "ok": True,
                "issues": issues,
                "count": len(issues),
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set SENTRY_AUTH_TOKEN and SENTRY_ORGANIZATION",
            }
        )
    except Exception as e:
        logger.error(f"sentry_list_issues error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def sentry_get_issue_details(issue_id: str) -> str:
    """
    Get detailed information about a specific Sentry issue.

    Args:
        issue_id: Sentry issue ID

    Returns:
        JSON with issue details
    """
    if not issue_id:
        return json.dumps({"ok": False, "error": "issue_id is required"})

    logger.info(f"sentry_get_issue_details: issue_id={issue_id}")

    try:
        import requests

        headers = _get_sentry_headers()
        config = _get_sentry_config()
        url = f"{config['base_url']}/issues/{issue_id}/"

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        issue = response.json()

        return json.dumps(
            {
                "ok": True,
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
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set SENTRY_AUTH_TOKEN and SENTRY_ORGANIZATION",
            }
        )
    except Exception as e:
        logger.error(f"sentry_get_issue_details error: {e}")
        return json.dumps({"ok": False, "error": str(e), "issue_id": issue_id})


@function_tool
def sentry_list_projects() -> str:
    """
    List all Sentry projects in the organization.

    Returns:
        JSON with projects list
    """
    logger.info("sentry_list_projects")

    try:
        import requests

        config = _get_sentry_config()
        headers = _get_sentry_headers()

        url = f"{config['base_url']}/organizations/{config['organization']}/projects/"

        response = requests.get(url, headers=headers, timeout=30)
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

        return json.dumps(
            {
                "ok": True,
                "projects": projects,
                "count": len(projects),
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set SENTRY_AUTH_TOKEN and SENTRY_ORGANIZATION",
            }
        )
    except Exception as e:
        logger.error(f"sentry_list_projects error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def sentry_get_project_stats(
    project: str,
    stat: str = "received",
    resolution: str = "1h",
) -> str:
    """
    Get statistics for a Sentry project.

    Args:
        project: Project slug
        stat: Stat type (received, rejected, blacklisted)
        resolution: Time resolution (1h, 1d, 1w, 1m)

    Returns:
        JSON with project statistics
    """
    if not project:
        return json.dumps({"ok": False, "error": "project is required"})

    logger.info(f"sentry_get_project_stats: project={project}, stat={stat}")

    try:
        import requests

        config = _get_sentry_config()
        headers = _get_sentry_headers()

        url = f"{config['base_url']}/projects/{config['organization']}/{project}/stats/"

        params = {
            "stat": stat,
            "resolution": resolution,
        }

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        return json.dumps(
            {
                "ok": True,
                "project": project,
                "stat": stat,
                "resolution": resolution,
                "data": response.json(),
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set SENTRY_AUTH_TOKEN and SENTRY_ORGANIZATION",
            }
        )
    except Exception as e:
        logger.error(f"sentry_get_project_stats error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def sentry_list_releases(project: str, limit: int = 10) -> str:
    """
    List releases for a Sentry project.

    Args:
        project: Project slug
        limit: Maximum releases to return

    Returns:
        JSON with releases list
    """
    if not project:
        return json.dumps({"ok": False, "error": "project is required"})

    logger.info(f"sentry_list_releases: project={project}")

    try:
        import requests

        config = _get_sentry_config()
        headers = _get_sentry_headers()

        url = f"{config['base_url']}/projects/{config['organization']}/{project}/releases/"

        params = {"per_page": limit}

        response = requests.get(url, headers=headers, params=params, timeout=30)
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

        return json.dumps(
            {
                "ok": True,
                "releases": releases,
                "count": len(releases),
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set SENTRY_AUTH_TOKEN and SENTRY_ORGANIZATION",
            }
        )
    except Exception as e:
        logger.error(f"sentry_list_releases error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


# Register tools
register_tool("sentry_list_issues", sentry_list_issues)
register_tool("sentry_get_issue_details", sentry_get_issue_details)
register_tool("sentry_list_projects", sentry_list_projects)
register_tool("sentry_get_project_stats", sentry_get_project_stats)
register_tool("sentry_list_releases", sentry_list_releases)
