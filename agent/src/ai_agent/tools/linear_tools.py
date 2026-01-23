"""Linear integration tools for issue tracking."""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_linear_config() -> dict:
    """Get Linear configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("linear")
        if config and config.get("api_key"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("LINEAR_API_KEY"):
        return {"api_key": os.getenv("LINEAR_API_KEY")}

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="linear", tool_id="linear_tools", missing_fields=["api_key"]
    )


def _get_linear_headers():
    """Get Linear API headers."""
    config = _get_linear_config()

    return {
        "Authorization": config["api_key"],
        "Content-Type": "application/json",
    }


def linear_create_issue(
    title: str,
    description: str = "",
    team_id: str | None = None,
    priority: int = 0,
    assignee_id: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """
    Create a new Linear issue.

    Args:
        title: Issue title
        description: Issue description (markdown)
        team_id: Team ID (if not provided, uses default team)
        priority: Priority level (0=None, 1=Urgent, 2=High, 3=Medium, 4=Low)
        assignee_id: Assignee user ID
        labels: List of label IDs to add

    Returns:
        Created issue details including ID and URL
    """
    try:
        import requests

        headers = _get_linear_headers()

        # Build GraphQL mutation
        mutation = """
        mutation CreateIssue($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id
                    identifier
                    title
                    url
                }
            }
        }
        """

        input_data = {
            "title": title,
            "description": description,
            "priority": priority,
        }

        if team_id:
            input_data["teamId"] = team_id
        if assignee_id:
            input_data["assigneeId"] = assignee_id
        if labels:
            input_data["labelIds"] = labels

        response = requests.post(
            "https://api.linear.app/graphql",
            headers=headers,
            json={"query": mutation, "variables": {"input": input_data}},
        )
        response.raise_for_status()

        data = response.json()
        issue = data["data"]["issueCreate"]["issue"]

        logger.info(
            "linear_issue_created", issue_id=issue["id"], identifier=issue["identifier"]
        )

        return {
            "id": issue["id"],
            "identifier": issue["identifier"],
            "title": issue["title"],
            "url": issue["url"],
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "linear_create_issue", "linear")
    except Exception as e:
        logger.error("linear_create_issue_failed", error=str(e), title=title)
        raise ToolExecutionError("linear_create_issue", str(e), e)


def linear_create_project(
    name: str,
    description: str = "",
    team_id: str | None = None,
    lead_id: str | None = None,
) -> dict[str, Any]:
    """
    Create a new Linear project.

    Args:
        name: Project name
        description: Project description
        team_id: Team ID
        lead_id: Project lead user ID

    Returns:
        Created project details
    """
    try:
        import requests

        headers = _get_linear_headers()

        mutation = """
        mutation CreateProject($input: ProjectCreateInput!) {
            projectCreate(input: $input) {
                success
                project {
                    id
                    name
                    url
                }
            }
        }
        """

        input_data = {
            "name": name,
            "description": description,
        }

        if team_id:
            input_data["teamIds"] = [team_id]
        if lead_id:
            input_data["leadId"] = lead_id

        response = requests.post(
            "https://api.linear.app/graphql",
            headers=headers,
            json={"query": mutation, "variables": {"input": input_data}},
        )
        response.raise_for_status()

        data = response.json()
        project = data["data"]["projectCreate"]["project"]

        logger.info("linear_project_created", project_id=project["id"], name=name)

        return {
            "id": project["id"],
            "name": project["name"],
            "url": project["url"],
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "linear_create_project", "linear")
    except Exception as e:
        logger.error("linear_create_project_failed", error=str(e), name=name)
        raise ToolExecutionError("linear_create_project", str(e), e)


def linear_get_issue(issue_id: str) -> dict[str, Any]:
    """
    Get details of a Linear issue.

    Args:
        issue_id: Issue ID or identifier (e.g., "TEAM-123")

    Returns:
        Issue details
    """
    try:
        import requests

        headers = _get_linear_headers()

        query = """
        query GetIssue($id: String!) {
            issue(id: $id) {
                id
                identifier
                title
                description
                state {
                    name
                }
                assignee {
                    name
                }
                priority
                createdAt
                updatedAt
                url
            }
        }
        """

        response = requests.post(
            "https://api.linear.app/graphql",
            headers=headers,
            json={"query": query, "variables": {"id": issue_id}},
        )
        response.raise_for_status()

        data = response.json()
        issue = data["data"]["issue"]

        logger.info("linear_issue_fetched", issue_id=issue_id)

        return {
            "id": issue["id"],
            "identifier": issue["identifier"],
            "title": issue["title"],
            "description": issue.get("description", ""),
            "state": issue["state"]["name"] if issue.get("state") else None,
            "assignee": issue["assignee"]["name"] if issue.get("assignee") else None,
            "priority": issue.get("priority"),
            "created_at": issue.get("createdAt"),
            "updated_at": issue.get("updatedAt"),
            "url": issue["url"],
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "linear_get_issue", "linear")
    except Exception as e:
        logger.error("linear_get_issue_failed", error=str(e), issue_id=issue_id)
        raise ToolExecutionError("linear_get_issue", str(e), e)


def linear_list_issues(
    team_id: str | None = None, state: str | None = None, max_results: int = 50
) -> list[dict[str, Any]]:
    """
    List Linear issues with optional filters.

    Args:
        team_id: Filter by team ID
        state: Filter by state name
        max_results: Maximum issues to return

    Returns:
        List of issues
    """
    try:
        import requests

        headers = _get_linear_headers()

        query = """
        query ListIssues($first: Int!) {
            issues(first: $first) {
                nodes {
                    id
                    identifier
                    title
                    state {
                        name
                    }
                    assignee {
                        name
                    }
                    createdAt
                    url
                }
            }
        }
        """

        response = requests.post(
            "https://api.linear.app/graphql",
            headers=headers,
            json={"query": query, "variables": {"first": max_results}},
        )
        response.raise_for_status()

        data = response.json()
        issues = data["data"]["issues"]["nodes"]

        issue_list = []
        for issue in issues:
            issue_list.append(
                {
                    "id": issue["id"],
                    "identifier": issue["identifier"],
                    "title": issue["title"],
                    "state": issue["state"]["name"] if issue.get("state") else None,
                    "assignee": (
                        issue["assignee"]["name"] if issue.get("assignee") else None
                    ),
                    "created_at": issue.get("createdAt"),
                    "url": issue["url"],
                }
            )

        logger.info("linear_issues_listed", count=len(issue_list))
        return issue_list

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "linear_list_issues", "linear")
    except Exception as e:
        logger.error("linear_list_issues_failed", error=str(e))
        raise ToolExecutionError("linear_list_issues", str(e), e)


# List of all Linear tools for registration
LINEAR_TOOLS = [
    linear_create_issue,
    linear_create_project,
    linear_get_issue,
    linear_list_issues,
]
