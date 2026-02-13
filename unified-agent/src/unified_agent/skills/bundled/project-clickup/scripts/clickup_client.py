"""ClickUp API client for SRE Agent.

Supports two authentication modes:
1. Proxy mode (production): Routes through credential-resolver
2. Direct mode (local dev): Uses CLICKUP_API_TOKEN environment variable

Environment variables:
    CREDENTIAL_PROXY_URL: Proxy URL for production (e.g., http://credential-resolver:8002)
    CLICKUP_API_TOKEN: API token for direct mode
    CLICKUP_TEAM_ID: Team/Workspace ID (required for most operations)
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


def get_config() -> dict[str, str | None]:
    """Get ClickUp configuration from environment."""
    return {
        "proxy_url": os.environ.get("CREDENTIAL_PROXY_URL"),
        "api_token": os.environ.get("CLICKUP_API_TOKEN"),
        "team_id": os.environ.get("CLICKUP_TEAM_ID"),
    }


def get_api_url(path: str) -> str:
    """Get the full API URL for a ClickUp endpoint.

    In proxy mode, routes through credential-resolver.
    In direct mode, uses ClickUp API directly.

    Args:
        path: API path (e.g., "team/{team_id}/space")

    Returns:
        Full URL for the API request
    """
    config = get_config()
    proxy_url = config.get("proxy_url")

    if proxy_url:
        # Proxy mode: route through credential-resolver
        base = proxy_url.rstrip("/")
        return f"{base}/clickup/api/v2/{path.lstrip('/')}"
    else:
        # Direct mode: use ClickUp API directly
        return f"https://api.clickup.com/api/v2/{path.lstrip('/')}"


def get_headers() -> dict[str, str]:
    """Get HTTP headers for ClickUp API requests.

    In proxy mode, uses JWT for credential injection.
    In direct mode, uses API token directly.

    Returns:
        Dictionary of HTTP headers
    """
    config = get_config()
    headers = {
        "Content-Type": "application/json",
    }

    # In direct mode, add Authorization header
    if not config.get("proxy_url"):
        api_token = config.get("api_token")
        if not api_token:
            raise ValueError(
                "CLICKUP_API_TOKEN environment variable required in direct mode"
            )
        headers["Authorization"] = api_token

    return headers


def make_request(
    path: str,
    method: str = "GET",
    data: dict | None = None,
    params: dict | None = None,
) -> dict[str, Any]:
    """Make an HTTP request to the ClickUp API.

    Args:
        path: API path
        method: HTTP method (GET, POST, PUT, DELETE)
        data: Request body for POST/PUT
        params: Query parameters

    Returns:
        JSON response as dictionary
    """
    url = get_api_url(path)

    # Add query parameters
    if params:
        query_string = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if query_string:
            url = f"{url}?{query_string}"

    headers = get_headers()

    # Prepare request
    body = None
    if data:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_data = response.read().decode("utf-8")
            if response_data:
                return json.loads(response_data)
            return {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"ClickUp API error {e.code}: {error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"ClickUp connection error: {e.reason}") from e


def get_team_id() -> str:
    """Get the team/workspace ID.

    Returns:
        Team ID from environment or first available team
    """
    config = get_config()
    team_id = config.get("team_id")

    if team_id:
        return team_id

    # Try to get from API
    teams = list_teams()
    if teams:
        return teams[0]["id"]

    raise ValueError(
        "CLICKUP_TEAM_ID environment variable required or no teams accessible"
    )


def list_teams() -> list[dict[str, Any]]:
    """List all teams/workspaces accessible to the user.

    Returns:
        List of team objects
    """
    response = make_request("team")
    return response.get("teams", [])


def list_spaces(team_id: str | None = None) -> list[dict[str, Any]]:
    """List all spaces in a team.

    Args:
        team_id: Team ID (uses default if not provided)

    Returns:
        List of space objects
    """
    if not team_id:
        team_id = get_team_id()

    response = make_request(f"team/{team_id}/space")
    return response.get("spaces", [])


def list_folders(space_id: str) -> list[dict[str, Any]]:
    """List all folders in a space.

    Args:
        space_id: Space ID

    Returns:
        List of folder objects
    """
    response = make_request(f"space/{space_id}/folder")
    return response.get("folders", [])


def list_lists(
    space_id: str | None = None, folder_id: str | None = None
) -> list[dict[str, Any]]:
    """List all lists in a space or folder.

    Args:
        space_id: Space ID (for folderless lists)
        folder_id: Folder ID

    Returns:
        List of list objects
    """
    if folder_id:
        response = make_request(f"folder/{folder_id}/list")
    elif space_id:
        response = make_request(f"space/{space_id}/list")
    else:
        raise ValueError("Either space_id or folder_id required")

    return response.get("lists", [])


def get_task(task_id: str, include_subtasks: bool = False) -> dict[str, Any]:
    """Get a task by ID.

    Args:
        task_id: Task ID
        include_subtasks: Whether to include subtasks

    Returns:
        Task object
    """
    params = {}
    if include_subtasks:
        params["include_subtasks"] = "true"

    return make_request(f"task/{task_id}", params=params)


def get_tasks(
    list_id: str,
    archived: bool = False,
    page: int = 0,
    order_by: str | None = None,
    reverse: bool = False,
    subtasks: bool = False,
    statuses: list[str] | None = None,
    include_closed: bool = False,
    assignees: list[str] | None = None,
    due_date_gt: int | None = None,
    due_date_lt: int | None = None,
    date_created_gt: int | None = None,
    date_created_lt: int | None = None,
    date_updated_gt: int | None = None,
    date_updated_lt: int | None = None,
) -> list[dict[str, Any]]:
    """Get tasks from a list.

    Args:
        list_id: List ID
        archived: Include archived tasks
        page: Page number (0-indexed)
        order_by: Order field (id, created, updated, due_date)
        reverse: Reverse sort order
        subtasks: Include subtasks
        statuses: Filter by status names
        include_closed: Include closed tasks
        assignees: Filter by assignee user IDs
        due_date_gt: Due date greater than (Unix ms)
        due_date_lt: Due date less than (Unix ms)
        date_created_gt: Created date greater than (Unix ms)
        date_created_lt: Created date less than (Unix ms)
        date_updated_gt: Updated date greater than (Unix ms)
        date_updated_lt: Updated date less than (Unix ms)

    Returns:
        List of task objects
    """
    params = {
        "archived": str(archived).lower(),
        "page": str(page),
        "subtasks": str(subtasks).lower(),
        "include_closed": str(include_closed).lower(),
    }

    if order_by:
        params["order_by"] = order_by
    if reverse:
        params["reverse"] = "true"
    if statuses:
        params["statuses[]"] = ",".join(statuses)
    if assignees:
        params["assignees[]"] = ",".join(assignees)
    if due_date_gt:
        params["due_date_gt"] = str(due_date_gt)
    if due_date_lt:
        params["due_date_lt"] = str(due_date_lt)
    if date_created_gt:
        params["date_created_gt"] = str(date_created_gt)
    if date_created_lt:
        params["date_created_lt"] = str(date_created_lt)
    if date_updated_gt:
        params["date_updated_gt"] = str(date_updated_gt)
    if date_updated_lt:
        params["date_updated_lt"] = str(date_updated_lt)

    response = make_request(f"list/{list_id}/task", params=params)
    return response.get("tasks", [])


def search_tasks(
    team_id: str | None = None,
    query: str | None = None,
    statuses: list[str] | None = None,
    include_closed: bool = True,
    assignees: list[str] | None = None,
    list_ids: list[str] | None = None,
    space_ids: list[str] | None = None,
    folder_ids: list[str] | None = None,
    date_created_gt: int | None = None,
    date_created_lt: int | None = None,
    date_updated_gt: int | None = None,
    date_updated_lt: int | None = None,
    order_by: str | None = None,
    reverse: bool = False,
    page: int = 0,
) -> list[dict[str, Any]]:
    """Search for tasks across the team.

    Args:
        team_id: Team ID (uses default if not provided)
        query: Search query string
        statuses: Filter by status names
        include_closed: Include closed tasks
        assignees: Filter by assignee user IDs
        list_ids: Filter by list IDs
        space_ids: Filter by space IDs
        folder_ids: Filter by folder IDs
        date_created_gt: Created after (Unix ms)
        date_created_lt: Created before (Unix ms)
        date_updated_gt: Updated after (Unix ms)
        date_updated_lt: Updated before (Unix ms)
        order_by: Sort field
        reverse: Reverse sort order
        page: Page number

    Returns:
        List of task objects
    """
    if not team_id:
        team_id = get_team_id()

    params = {
        "page": str(page),
        "include_closed": str(include_closed).lower(),
    }

    if query:
        # Note: ClickUp uses a filtered team tasks endpoint
        # The search is done via custom_task_ids or through filtering
        pass  # Query filtering happens client-side or via specific endpoints

    if statuses:
        for status in statuses:
            params["statuses[]"] = status
    if assignees:
        for assignee in assignees:
            params["assignees[]"] = assignee
    if list_ids:
        for list_id in list_ids:
            params["list_ids[]"] = list_id
    if space_ids:
        for space_id in space_ids:
            params["space_ids[]"] = space_id
    if folder_ids:
        for folder_id in folder_ids:
            params["folder_ids[]"] = folder_id
    if date_created_gt:
        params["date_created_gt"] = str(date_created_gt)
    if date_created_lt:
        params["date_created_lt"] = str(date_created_lt)
    if date_updated_gt:
        params["date_updated_gt"] = str(date_updated_gt)
    if date_updated_lt:
        params["date_updated_lt"] = str(date_updated_lt)
    if order_by:
        params["order_by"] = order_by
    if reverse:
        params["reverse"] = "true"

    response = make_request(f"team/{team_id}/task", params=params)
    tasks = response.get("tasks", [])

    # Client-side query filtering if provided
    if query:
        query_lower = query.lower()
        tasks = [
            t
            for t in tasks
            if query_lower in t.get("name", "").lower()
            or query_lower in (t.get("description") or "").lower()
        ]

    return tasks


def get_task_comments(task_id: str) -> list[dict[str, Any]]:
    """Get comments on a task.

    Args:
        task_id: Task ID

    Returns:
        List of comment objects
    """
    response = make_request(f"task/{task_id}/comment")
    return response.get("comments", [])


def create_task_comment(task_id: str, comment_text: str) -> dict[str, Any]:
    """Create a comment on a task.

    Args:
        task_id: Task ID
        comment_text: Comment text (supports markdown)

    Returns:
        Created comment object
    """
    data = {"comment_text": comment_text}
    return make_request(f"task/{task_id}/comment", method="POST", data=data)


def create_task(
    list_id: str,
    name: str,
    description: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    assignees: list[str] | None = None,
    tags: list[str] | None = None,
    due_date: int | None = None,
    custom_fields: list[dict] | None = None,
) -> dict[str, Any]:
    """Create a new task.

    Args:
        list_id: List ID to create task in
        name: Task name
        description: Task description (markdown)
        status: Status name
        priority: Priority (1=urgent, 2=high, 3=normal, 4=low)
        assignees: List of assignee user IDs
        tags: List of tag names
        due_date: Due date (Unix ms)
        custom_fields: List of custom field values

    Returns:
        Created task object
    """
    data = {"name": name}

    if description:
        data["description"] = description
    if status:
        data["status"] = status
    if priority:
        data["priority"] = priority
    if assignees:
        data["assignees"] = assignees
    if tags:
        data["tags"] = tags
    if due_date:
        data["due_date"] = due_date
    if custom_fields:
        data["custom_fields"] = custom_fields

    return make_request(f"list/{list_id}/task", method="POST", data=data)


def update_task(
    task_id: str,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    assignees: dict | None = None,
    due_date: int | None = None,
) -> dict[str, Any]:
    """Update a task.

    Args:
        task_id: Task ID
        name: New task name
        description: New description
        status: New status name
        priority: New priority
        assignees: Assignee changes {"add": [...], "rem": [...]}
        due_date: New due date (Unix ms)

    Returns:
        Updated task object
    """
    data = {}

    if name:
        data["name"] = name
    if description:
        data["description"] = description
    if status:
        data["status"] = status
    if priority:
        data["priority"] = priority
    if assignees:
        data["assignees"] = assignees
    if due_date:
        data["due_date"] = due_date

    return make_request(f"task/{task_id}", method="PUT", data=data)


def format_task(task: dict[str, Any], verbose: bool = False) -> str:
    """Format a task for display.

    Args:
        task: Task object
        verbose: Include full details

    Returns:
        Formatted string
    """
    lines = []

    name = task.get("name", "Untitled")
    task_id = task.get("id", "")
    status = task.get("status", {}).get("status", "Unknown")
    priority = task.get("priority")

    priority_str = ""
    if priority:
        priority_map = {1: "URGENT", 2: "HIGH", 3: "NORMAL", 4: "LOW"}
        priority_str = f" [{priority_map.get(priority.get('id'), 'NORMAL')}]"

    lines.append(f"{name}{priority_str}")
    lines.append(f"  ID: {task_id}")
    lines.append(f"  Status: {status}")

    if verbose:
        # Assignees
        assignees = task.get("assignees", [])
        if assignees:
            names = [a.get("username", a.get("email", "Unknown")) for a in assignees]
            lines.append(f"  Assignees: {', '.join(names)}")

        # Due date
        due_date = task.get("due_date")
        if due_date:
            from datetime import datetime

            dt = datetime.fromtimestamp(int(due_date) / 1000)
            lines.append(f"  Due: {dt.strftime('%Y-%m-%d %H:%M')}")

        # Description
        description = task.get("description")
        if description:
            # Truncate long descriptions
            desc_preview = (
                description[:200] + "..." if len(description) > 200 else description
            )
            lines.append(f"  Description: {desc_preview}")

        # Tags
        tags = task.get("tags", [])
        if tags:
            tag_names = [t.get("name", "") for t in tags]
            lines.append(f"  Tags: {', '.join(tag_names)}")

        # URL
        url = task.get("url")
        if url:
            lines.append(f"  URL: {url}")

    return "\n".join(lines)
