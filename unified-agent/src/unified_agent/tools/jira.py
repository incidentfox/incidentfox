"""
Jira integration tools for issue tracking and incident management.

Provides Jira API access for creating, reading, updating, and searching issues.
Useful for incident tracking, post-mortem management, and alert fatigue analysis.
"""

import base64
import json
import logging
import os

from ..core.agent import function_tool
from . import get_proxy_headers, register_tool

logger = logging.getLogger(__name__)


def _get_jira_base_url():
    """Get Jira REST API base URL (supports proxy mode).

    Supports two modes:
    - Direct: JIRA_URL (e.g., https://your-company.atlassian.net)
    - Proxy: JIRA_BASE_URL points to credential-resolver
    """
    proxy_url = os.getenv("JIRA_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")

    jira_url = os.getenv("JIRA_URL")
    if jira_url:
        return f"{jira_url.rstrip('/')}/rest/api/3"

    raise ValueError("JIRA_URL or JIRA_BASE_URL environment variable not set")


def _get_jira_headers():
    """Get Jira API headers.

    Supports two modes:
    - Direct: JIRA_EMAIL + JIRA_API_TOKEN (Basic auth)
    - Proxy: JIRA_BASE_URL points to credential-resolver (handles auth)
    """
    if os.getenv("JIRA_BASE_URL"):
        # Proxy mode: credential-resolver handles auth
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        headers.update(get_proxy_headers())
        return headers

    email = os.getenv("JIRA_EMAIL")
    api_token = os.getenv("JIRA_API_TOKEN")
    if not email or not api_token:
        raise ValueError("JIRA_EMAIL and JIRA_API_TOKEN environment variables not set")

    credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _get_jira_browse_url():
    """Get the Jira browse URL for constructing issue links."""
    proxy_url = os.getenv("JIRA_BASE_URL")
    if proxy_url:
        # In proxy mode, we may not know the actual Jira URL
        return None

    jira_url = os.getenv("JIRA_URL", "")
    return jira_url.rstrip("/")


def _jira_request(method, path, params=None, json_body=None):
    """Make a request to Jira API."""
    import requests

    base_url = _get_jira_base_url()
    headers = _get_jira_headers()
    url = f"{base_url}/{path.lstrip('/')}"

    response = requests.request(
        method,
        url,
        headers=headers,
        params=params,
        json=json_body,
        timeout=30,
    )
    response.raise_for_status()

    if response.status_code == 204:
        return None
    return response.json()


@function_tool
def jira_create_issue(
    project_key: str,
    summary: str,
    description: str,
    issue_type: str = "Task",
    priority: str = "",
    assignee: str = "",
    labels: str = "",
) -> str:
    """
    Create a new Jira issue.

    Args:
        project_key: Jira project key (e.g., "PROJ")
        summary: Issue title/summary
        description: Issue description
        issue_type: Issue type (Task, Bug, Story, etc.)
        priority: Priority level (High, Medium, Low)
        assignee: Assignee account ID or email
        labels: Comma-separated labels

    Returns:
        JSON with created issue details
    """
    if not project_key or not summary:
        return json.dumps(
            {"ok": False, "error": "project_key and summary are required"}
        )

    logger.info(f"jira_create_issue: project={project_key}, type={issue_type}")

    try:
        fields = {
            "project": {"key": project_key},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            },
            "issuetype": {"name": issue_type},
        }

        if priority:
            fields["priority"] = {"name": priority}

        if labels:
            fields["labels"] = [l.strip() for l in labels.split(",")]

        data = _jira_request("POST", "/issue", json_body={"fields": fields})

        issue_key = data["key"]

        # Assign after creation if specified
        if assignee:
            try:
                _jira_request(
                    "PUT",
                    f"/issue/{issue_key}/assignee",
                    json_body={"accountId": assignee},
                )
            except Exception as e:
                logger.warning(f"jira_create_issue: assign failed: {e}")

        browse_url = _get_jira_browse_url()
        result = {
            "ok": True,
            "key": issue_key,
            "id": data.get("id"),
            "summary": summary,
            "issue_type": issue_type,
        }
        if browse_url:
            result["url"] = f"{browse_url}/browse/{issue_key}"

        return json.dumps(result)

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN",
            }
        )
    except Exception as e:
        logger.error(f"jira_create_issue error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project_key": project_key})


@function_tool
def jira_create_epic(
    project_key: str,
    summary: str,
    description: str,
    epic_name: str = "",
) -> str:
    """
    Create a new Jira epic.

    Args:
        project_key: Jira project key
        summary: Epic title/summary
        description: Epic description
        epic_name: Short epic name (defaults to summary)

    Returns:
        JSON with created epic details
    """
    if not project_key or not summary:
        return json.dumps(
            {"ok": False, "error": "project_key and summary are required"}
        )

    logger.info(f"jira_create_epic: project={project_key}")

    try:
        fields = {
            "project": {"key": project_key},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            },
            "issuetype": {"name": "Epic"},
        }

        # Some Jira instances require epic name field
        if epic_name:
            fields["customfield_10011"] = epic_name

        data = _jira_request("POST", "/issue", json_body={"fields": fields})

        issue_key = data["key"]
        browse_url = _get_jira_browse_url()

        result = {
            "ok": True,
            "key": issue_key,
            "id": data.get("id"),
            "summary": summary,
        }
        if browse_url:
            result["url"] = f"{browse_url}/browse/{issue_key}"

        return json.dumps(result)

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN",
            }
        )
    except Exception as e:
        logger.error(f"jira_create_epic error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project_key": project_key})


@function_tool
def jira_get_issue(issue_key: str) -> str:
    """
    Get details of a specific Jira issue.

    Args:
        issue_key: Jira issue key (e.g., "PROJ-123")

    Returns:
        JSON with issue details including status, assignee, description
    """
    if not issue_key:
        return json.dumps({"ok": False, "error": "issue_key is required"})

    logger.info(f"jira_get_issue: issue_key={issue_key}")

    try:
        data = _jira_request("GET", f"/issue/{issue_key}")

        fields = data.get("fields", {})
        browse_url = _get_jira_browse_url()

        # Extract description text from ADF format
        desc = ""
        raw_desc = fields.get("description")
        if isinstance(raw_desc, dict):
            # Atlassian Document Format - extract text
            for block in raw_desc.get("content", []):
                for inline in block.get("content", []):
                    if inline.get("type") == "text":
                        desc += inline.get("text", "")
                desc += "\n"
            desc = desc.strip()
        elif isinstance(raw_desc, str):
            desc = raw_desc

        result = {
            "ok": True,
            "key": data["key"],
            "id": data["id"],
            "summary": fields.get("summary"),
            "description": desc,
            "status": fields.get("status", {}).get("name"),
            "issue_type": fields.get("issuetype", {}).get("name"),
            "priority": (
                fields.get("priority", {}).get("name")
                if fields.get("priority")
                else None
            ),
            "assignee": (
                fields.get("assignee", {}).get("displayName")
                if fields.get("assignee")
                else None
            ),
            "reporter": (
                fields.get("reporter", {}).get("displayName")
                if fields.get("reporter")
                else None
            ),
            "created": fields.get("created"),
            "updated": fields.get("updated"),
            "labels": fields.get("labels", []),
        }
        if browse_url:
            result["url"] = f"{browse_url}/browse/{data['key']}"

        return json.dumps(result)

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN",
            }
        )
    except Exception as e:
        logger.error(f"jira_get_issue error: {e}")
        return json.dumps({"ok": False, "error": str(e), "issue_key": issue_key})


@function_tool
def jira_add_comment(issue_key: str, comment: str) -> str:
    """
    Add a comment to a Jira issue.

    Args:
        issue_key: Jira issue key (e.g., "PROJ-123")
        comment: Comment text

    Returns:
        JSON with added comment details
    """
    if not issue_key or not comment:
        return json.dumps({"ok": False, "error": "issue_key and comment are required"})

    logger.info(f"jira_add_comment: issue_key={issue_key}")

    try:
        body = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": comment}],
                    }
                ],
            }
        }

        data = _jira_request("POST", f"/issue/{issue_key}/comment", json_body=body)

        author = data.get("author", {})

        return json.dumps(
            {
                "ok": True,
                "id": data.get("id"),
                "issue_key": issue_key,
                "author": author.get("displayName"),
                "created": data.get("created"),
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN",
            }
        )
    except Exception as e:
        logger.error(f"jira_add_comment error: {e}")
        return json.dumps({"ok": False, "error": str(e), "issue_key": issue_key})


@function_tool
def jira_update_issue(
    issue_key: str,
    summary: str = "",
    description: str = "",
    status: str = "",
    assignee: str = "",
    priority: str = "",
) -> str:
    """
    Update an existing Jira issue.

    Args:
        issue_key: Jira issue key (e.g., "PROJ-123")
        summary: New summary (optional)
        description: New description (optional)
        status: New status (optional, triggers transition)
        assignee: New assignee account ID (optional)
        priority: New priority (optional)

    Returns:
        JSON with update result
    """
    if not issue_key:
        return json.dumps({"ok": False, "error": "issue_key is required"})

    logger.info(f"jira_update_issue: issue_key={issue_key}")

    try:
        # Update fields
        fields = {}
        if summary:
            fields["summary"] = summary
        if description:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            }
        if priority:
            fields["priority"] = {"name": priority}

        if fields:
            _jira_request("PUT", f"/issue/{issue_key}", json_body={"fields": fields})

        # Update assignee separately
        if assignee:
            _jira_request(
                "PUT",
                f"/issue/{issue_key}/assignee",
                json_body={"accountId": assignee},
            )

        # Transition status if specified
        if status:
            transitions = _jira_request("GET", f"/issue/{issue_key}/transitions")
            for transition in transitions.get("transitions", []):
                if transition["name"].lower() == status.lower():
                    _jira_request(
                        "POST",
                        f"/issue/{issue_key}/transitions",
                        json_body={"transition": {"id": transition["id"]}},
                    )
                    break

        return json.dumps({"ok": True, "key": issue_key, "updated": True})

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN",
            }
        )
    except Exception as e:
        logger.error(f"jira_update_issue error: {e}")
        return json.dumps({"ok": False, "error": str(e), "issue_key": issue_key})


@function_tool
def jira_list_issues(
    project_key: str,
    jql: str = "",
    max_results: int = 50,
) -> str:
    """
    List issues in a Jira project.

    Args:
        project_key: Jira project key (e.g., "PROJ")
        jql: Optional JQL query to filter issues
        max_results: Maximum issues to return

    Returns:
        JSON with list of issues
    """
    if not project_key:
        return json.dumps({"ok": False, "error": "project_key is required"})

    logger.info(f"jira_list_issues: project={project_key}")

    try:
        search_jql = jql if jql else f"project = {project_key} ORDER BY created DESC"

        data = _jira_request(
            "GET",
            "/search",
            params={
                "jql": search_jql,
                "maxResults": max_results,
                "fields": "summary,status,issuetype,assignee,created",
            },
        )

        browse_url = _get_jira_browse_url()
        issues = []

        for item in data.get("issues", []):
            fields = item.get("fields", {})
            issue = {
                "key": item["key"],
                "summary": fields.get("summary"),
                "status": fields.get("status", {}).get("name"),
                "issue_type": fields.get("issuetype", {}).get("name"),
                "assignee": (
                    fields.get("assignee", {}).get("displayName")
                    if fields.get("assignee")
                    else None
                ),
                "created": fields.get("created"),
            }
            if browse_url:
                issue["url"] = f"{browse_url}/browse/{item['key']}"
            issues.append(issue)

        return json.dumps({"ok": True, "issues": issues, "count": len(issues)})

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN",
            }
        )
    except Exception as e:
        logger.error(f"jira_list_issues error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project_key": project_key})


@function_tool
def jira_search_issues(
    jql: str,
    max_results: int = 100,
    fields: str = "",
) -> str:
    """
    Search Jira issues using JQL (Jira Query Language).

    Powerful search for finding incident tickets, post-mortems, action items.
    Useful for alert fatigue analysis to find patterns in incident handling.

    Common JQL patterns:
    - Find incidents: 'type = Incident AND created >= -30d'
    - Find by label: 'labels = "alert-tuning" OR labels = "incident"'
    - Find open action items: 'type = Task AND labels = "action-item" AND status != Done'
    - Find by text: 'summary ~ "high CPU" OR description ~ "alert fatigue"'
    - Find stale issues: 'updated <= -90d AND status != Done'

    Args:
        jql: JQL query string
        max_results: Maximum issues to return (default 100)
        fields: Comma-separated fields to return (default: common fields)

    Returns:
        JSON with issues and summary statistics
    """
    if not jql:
        return json.dumps({"ok": False, "error": "jql is required"})

    logger.info(f"jira_search_issues: jql={jql[:100]}")

    try:
        search_fields = (
            fields
            if fields
            else (
                "summary,status,issuetype,priority,assignee,reporter,"
                "created,updated,labels,description,resolution,resolutiondate"
            )
        )

        data = _jira_request(
            "GET",
            "/search",
            params={
                "jql": jql,
                "maxResults": max_results,
                "fields": search_fields,
            },
        )

        browse_url = _get_jira_browse_url()
        issues = []

        for item in data.get("issues", []):
            f = item.get("fields", {})

            # Extract description text
            desc_snippet = ""
            raw_desc = f.get("description")
            if isinstance(raw_desc, dict):
                for block in raw_desc.get("content", []):
                    for inline in block.get("content", []):
                        if inline.get("type") == "text":
                            desc_snippet += inline.get("text", "")
                    desc_snippet += "\n"
                desc_snippet = desc_snippet.strip()
            elif isinstance(raw_desc, str):
                desc_snippet = raw_desc

            if len(desc_snippet) > 500:
                desc_snippet = desc_snippet[:500] + "..."

            issue = {
                "key": item["key"],
                "summary": f.get("summary"),
                "status": f.get("status", {}).get("name") if f.get("status") else None,
                "issue_type": (
                    f.get("issuetype", {}).get("name") if f.get("issuetype") else None
                ),
                "priority": (
                    f.get("priority", {}).get("name") if f.get("priority") else None
                ),
                "assignee": (
                    f.get("assignee", {}).get("displayName")
                    if f.get("assignee")
                    else None
                ),
                "reporter": (
                    f.get("reporter", {}).get("displayName")
                    if f.get("reporter")
                    else None
                ),
                "created": f.get("created"),
                "updated": f.get("updated"),
                "labels": f.get("labels", []),
                "resolution": (
                    f.get("resolution", {}).get("name") if f.get("resolution") else None
                ),
                "resolution_date": f.get("resolutiondate"),
            }

            if desc_snippet:
                issue["description_snippet"] = desc_snippet
            if browse_url:
                issue["url"] = f"{browse_url}/browse/{item['key']}"

            issues.append(issue)

        # Compute summary statistics
        status_counts = {}
        priority_counts = {}
        assignee_counts = {}

        for issue in issues:
            s = issue.get("status")
            if s:
                status_counts[s] = status_counts.get(s, 0) + 1

            p = issue.get("priority")
            if p:
                priority_counts[p] = priority_counts.get(p, 0) + 1

            a = issue.get("assignee")
            if a:
                assignee_counts[a] = assignee_counts.get(a, 0) + 1

        # Top 10 assignees by count
        top_assignees = dict(
            sorted(assignee_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        )

        return json.dumps(
            {
                "ok": True,
                "jql": jql,
                "total_results": data.get("total", len(issues)),
                "summary": {
                    "by_status": status_counts,
                    "by_priority": priority_counts,
                    "by_assignee": top_assignees,
                },
                "issues": issues,
                "count": len(issues),
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN",
            }
        )
    except Exception as e:
        logger.error(f"jira_search_issues error: {e}")
        return json.dumps({"ok": False, "error": str(e), "jql": jql[:100]})


# Register tools
register_tool("jira_create_issue", jira_create_issue)
register_tool("jira_create_epic", jira_create_epic)
register_tool("jira_get_issue", jira_get_issue)
register_tool("jira_add_comment", jira_add_comment)
register_tool("jira_update_issue", jira_update_issue)
register_tool("jira_list_issues", jira_list_issues)
register_tool("jira_search_issues", jira_search_issues)
