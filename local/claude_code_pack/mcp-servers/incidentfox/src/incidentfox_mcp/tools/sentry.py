"""Sentry error tracking and performance monitoring tools.

Provides tools for:
- Listing and getting issue details
- Understanding error patterns
- Correlating errors with releases
- Getting project statistics

Essential for application error correlation during incidents.
"""

import json

from mcp.server.fastmcp import FastMCP

from ..utils.config import get_env


class SentryConfigError(Exception):
    """Raised when Sentry is not configured."""

    def __init__(self, message: str):
        super().__init__(message)


def _get_sentry_config():
    """Get Sentry configuration from environment or config file."""
    auth_token = get_env("SENTRY_AUTH_TOKEN")
    organization = get_env("SENTRY_ORGANIZATION")

    if not auth_token or not organization:
        missing = []
        if not auth_token:
            missing.append("SENTRY_AUTH_TOKEN")
        if not organization:
            missing.append("SENTRY_ORGANIZATION")
        raise SentryConfigError(
            f"Sentry not configured. Missing: {', '.join(missing)}. "
            "Use save_credential tool to set these, or export as environment variables."
        )

    return {
        "auth_token": auth_token,
        "organization": organization,
        "project": get_env("SENTRY_PROJECT"),
    }


def _get_sentry_headers():
    """Get Sentry API headers."""
    config = _get_sentry_config()
    return {
        "Authorization": f"Bearer {config['auth_token']}",
        "Content-Type": "application/json",
    }


def register_tools(mcp: FastMCP):
    """Register Sentry tools with the MCP server."""

    @mcp.tool()
    def sentry_list_issues(
        project: str | None = None, query: str | None = None, limit: int = 25
    ) -> str:
        """List Sentry issues (errors and events).

        Use to see recent errors and their frequency.

        Args:
            project: Project slug (uses config default if not specified)
            query: Optional search query (e.g., "is:unresolved")
            limit: Maximum issues to return (default: 25)

        Returns:
            JSON with list of issues including counts and last seen
        """
        try:
            import requests

            config = _get_sentry_config()
            headers = _get_sentry_headers()

            project_slug = project or config.get("project")
            if not project_slug:
                return json.dumps(
                    {"error": "Project must be specified in config or as parameter"}
                )

            url = f"https://sentry.io/api/0/projects/{config['organization']}/{project_slug}/issues/"

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
                    "project": project_slug,
                    "issue_count": len(issues),
                    "issues": issues,
                },
                indent=2,
            )

        except SentryConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "project": project})

    @mcp.tool()
    def sentry_get_issue_details(issue_id: str) -> str:
        """Get detailed information about a specific Sentry issue.

        Use to understand the full error context and stack trace.

        Args:
            issue_id: Sentry issue ID

        Returns:
            JSON with issue details including metadata and tags
        """
        try:
            import requests

            headers = _get_sentry_headers()

            url = f"https://sentry.io/api/0/issues/{issue_id}/"

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            issue = response.json()

            return json.dumps(
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
                    "metadata": issue.get("metadata", {}),
                    "tags": issue.get("tags", []),
                },
                indent=2,
            )

        except SentryConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "issue_id": issue_id})

    @mcp.tool()
    def sentry_list_projects() -> str:
        """List all Sentry projects in the organization.

        Use to discover available projects to query.

        Returns:
            JSON with list of projects
        """
        try:
            import requests

            config = _get_sentry_config()
            headers = _get_sentry_headers()

            url = f"https://sentry.io/api/0/organizations/{config['organization']}/projects/"

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
                {"project_count": len(projects), "projects": projects}, indent=2
            )

        except SentryConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def sentry_get_project_stats(
        project: str, stat: str = "received", resolution: str = "1h"
    ) -> str:
        """Get statistics for a Sentry project.

        Use to understand error volume trends.

        Args:
            project: Project slug
            stat: Stat type (received, rejected, blacklisted)
            resolution: Time resolution (1h, 1d, 1w, 1m)

        Returns:
            JSON with project statistics
        """
        try:
            import requests

            config = _get_sentry_config()
            headers = _get_sentry_headers()

            url = f"https://sentry.io/api/0/projects/{config['organization']}/{project}/stats/"

            params = {"stat": stat, "resolution": resolution}

            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            stats = response.json()

            return json.dumps(
                {
                    "project": project,
                    "stat": stat,
                    "resolution": resolution,
                    "data": stats,
                },
                indent=2,
            )

        except SentryConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "project": project})

    @mcp.tool()
    def sentry_list_releases(project: str, limit: int = 10) -> str:
        """List releases for a Sentry project.

        Use to correlate errors with specific releases.

        Args:
            project: Project slug
            limit: Maximum releases to return (default: 10)

        Returns:
            JSON with list of releases
        """
        try:
            import requests

            config = _get_sentry_config()
            headers = _get_sentry_headers()

            url = f"https://sentry.io/api/0/projects/{config['organization']}/{project}/releases/"

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
                    "project": project,
                    "release_count": len(releases),
                    "releases": releases,
                },
                indent=2,
            )

        except SentryConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "project": project})
