"""Jira integration tools for issue and epic management."""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_jira_config() -> dict:
    """Get Jira configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("jira")
        if (
            config
            and config.get("url")
            and config.get("email")
            and config.get("api_token")
        ):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if (
        os.getenv("JIRA_URL")
        and os.getenv("JIRA_EMAIL")
        and os.getenv("JIRA_API_TOKEN")
    ):
        return {
            "url": os.getenv("JIRA_URL"),
            "email": os.getenv("JIRA_EMAIL"),
            "api_token": os.getenv("JIRA_API_TOKEN"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="jira",
        tool_id="jira_tools",
        missing_fields=["url", "email", "api_token"],
    )


def _get_jira_client():
    """Get Jira API client."""
    try:
        from jira import JIRA

        config = _get_jira_config()

        return JIRA(
            server=config["url"], basic_auth=(config["email"], config["api_token"])
        )

    except ImportError:
        raise ToolExecutionError(
            "jira", "jira package not installed. Install with: poetry add jira"
        )


def jira_create_issue(
    project_key: str,
    summary: str,
    description: str,
    issue_type: str = "Task",
    priority: str | None = None,
    assignee: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """
    Create a new Jira issue.

    Args:
        project_key: Jira project key (e.g., "PROJ")
        summary: Issue title/summary
        description: Issue description
        issue_type: Issue type (Task, Bug, Story, etc.)
        priority: Priority level (High, Medium, Low)
        assignee: Assignee username or email
        labels: List of labels to add

    Returns:
        Created issue details including key and URL
    """
    try:
        jira = _get_jira_client()

        issue_dict = {
            "project": {"key": project_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
        }

        if priority:
            issue_dict["priority"] = {"name": priority}

        if labels:
            issue_dict["labels"] = labels

        issue = jira.create_issue(fields=issue_dict)

        # Assign after creation if assignee specified
        if assignee:
            try:
                jira.assign_issue(issue, assignee)
            except Exception as e:
                logger.warning("jira_assign_failed", error=str(e), issue_key=issue.key)

        logger.info("jira_issue_created", issue_key=issue.key)

        return {
            "key": issue.key,
            "id": issue.id,
            "url": f"{jira._options['server']}/browse/{issue.key}",
            "summary": summary,
            "issue_type": issue_type,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "jira_create_issue", "jira")
    except Exception as e:
        logger.error("jira_create_issue_failed", error=str(e), project=project_key)
        raise ToolExecutionError("jira_create_issue", str(e), e)


def jira_create_epic(
    project_key: str, summary: str, description: str, epic_name: str | None = None
) -> dict[str, Any]:
    """
    Create a new Jira epic.

    Args:
        project_key: Jira project key
        summary: Epic title/summary
        description: Epic description
        epic_name: Short epic name (defaults to summary)

    Returns:
        Created epic details
    """
    try:
        jira = _get_jira_client()

        epic_dict = {
            "project": {"key": project_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": "Epic"},
        }

        # Some Jira instances require epic name field
        if epic_name:
            epic_dict["customfield_10011"] = epic_name  # Common epic name field ID

        epic = jira.create_issue(fields=epic_dict)

        logger.info("jira_epic_created", epic_key=epic.key)

        return {
            "key": epic.key,
            "id": epic.id,
            "url": f"{jira._options['server']}/browse/{epic.key}",
            "summary": summary,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "jira_create_epic", "jira")
    except Exception as e:
        logger.error("jira_create_epic_failed", error=str(e), project=project_key)
        raise ToolExecutionError("jira_create_epic", str(e), e)


def jira_get_issue(issue_key: str) -> dict[str, Any]:
    """
    Get details of a specific Jira issue.

    Args:
        issue_key: Jira issue key (e.g., "PROJ-123")

    Returns:
        Issue details including status, assignee, description, comments
    """
    try:
        jira = _get_jira_client()
        issue = jira.issue(issue_key)

        logger.info("jira_issue_fetched", issue_key=issue_key)

        return {
            "key": issue.key,
            "id": issue.id,
            "summary": issue.fields.summary,
            "description": issue.fields.description or "",
            "status": issue.fields.status.name,
            "issue_type": issue.fields.issuetype.name,
            "priority": issue.fields.priority.name if issue.fields.priority else None,
            "assignee": (
                issue.fields.assignee.displayName if issue.fields.assignee else None
            ),
            "reporter": (
                issue.fields.reporter.displayName if issue.fields.reporter else None
            ),
            "created": str(issue.fields.created),
            "updated": str(issue.fields.updated),
            "labels": issue.fields.labels or [],
            "url": f"{jira._options['server']}/browse/{issue.key}",
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "jira_get_issue", "jira")
    except Exception as e:
        logger.error("jira_get_issue_failed", error=str(e), issue_key=issue_key)
        raise ToolExecutionError("jira_get_issue", str(e), e)


def jira_add_comment(issue_key: str, comment: str) -> dict[str, Any]:
    """
    Add a comment to a Jira issue.

    Args:
        issue_key: Jira issue key
        comment: Comment text

    Returns:
        Added comment details
    """
    try:
        jira = _get_jira_client()
        comment_obj = jira.add_comment(issue_key, comment)

        logger.info("jira_comment_added", issue_key=issue_key)

        return {
            "id": comment_obj.id,
            "issue_key": issue_key,
            "author": comment_obj.author.displayName if comment_obj.author else None,
            "created": str(comment_obj.created),
            "body": comment,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "jira_add_comment", "jira")
    except Exception as e:
        logger.error("jira_add_comment_failed", error=str(e), issue_key=issue_key)
        raise ToolExecutionError("jira_add_comment", str(e), e)


def jira_update_issue(
    issue_key: str,
    summary: str | None = None,
    description: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
) -> dict[str, Any]:
    """
    Update an existing Jira issue.

    Args:
        issue_key: Jira issue key
        summary: New summary (optional)
        description: New description (optional)
        status: New status (optional, triggers transition)
        assignee: New assignee (optional)
        priority: New priority (optional)

    Returns:
        Update result
    """
    try:
        jira = _get_jira_client()
        issue = jira.issue(issue_key)

        # Update fields
        update_dict = {}
        if summary:
            update_dict["summary"] = summary
        if description:
            update_dict["description"] = description
        if priority:
            update_dict["priority"] = {"name": priority}

        if update_dict:
            issue.update(fields=update_dict)

        # Update assignee separately
        if assignee:
            jira.assign_issue(issue, assignee)

        # Transition status if specified
        if status:
            transitions = jira.transitions(issue)
            for transition in transitions:
                if transition["name"].lower() == status.lower():
                    jira.transition_issue(issue, transition["id"])
                    break

        logger.info("jira_issue_updated", issue_key=issue_key)

        return {
            "key": issue_key,
            "updated": True,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "jira_update_issue", "jira")
    except Exception as e:
        logger.error("jira_update_issue_failed", error=str(e), issue_key=issue_key)
        raise ToolExecutionError("jira_update_issue", str(e), e)


def jira_list_issues(
    project_key: str, jql: str | None = None, max_results: int = 50
) -> list[dict[str, Any]]:
    """
    List issues in a Jira project.

    Args:
        project_key: Jira project key
        jql: Optional JQL query to filter issues
        max_results: Maximum issues to return

    Returns:
        List of issues
    """
    try:
        jira = _get_jira_client()

        # Build JQL query
        if jql:
            search_jql = jql
        else:
            search_jql = f"project = {project_key} ORDER BY created DESC"

        issues = jira.search_issues(search_jql, maxResults=max_results)

        issue_list = []
        for issue in issues:
            issue_list.append(
                {
                    "key": issue.key,
                    "summary": issue.fields.summary,
                    "status": issue.fields.status.name,
                    "issue_type": issue.fields.issuetype.name,
                    "assignee": (
                        issue.fields.assignee.displayName
                        if issue.fields.assignee
                        else None
                    ),
                    "created": str(issue.fields.created),
                    "url": f"{jira._options['server']}/browse/{issue.key}",
                }
            )

        logger.info("jira_issues_listed", project=project_key, count=len(issue_list))
        return issue_list

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "jira_list_issues", "jira")
    except Exception as e:
        logger.error("jira_list_issues_failed", error=str(e), project=project_key)
        raise ToolExecutionError("jira_list_issues", str(e), e)


# List of all Jira tools for registration
JIRA_TOOLS = [
    jira_create_issue,
    jira_create_epic,
    jira_get_issue,
    jira_add_comment,
    jira_update_issue,
    jira_list_issues,
]
