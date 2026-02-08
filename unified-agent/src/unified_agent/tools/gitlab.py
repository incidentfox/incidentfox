"""
GitLab integration tools.

Provides GitLab API access for projects, merge requests, pipelines, issues,
and commits. Supports self-hosted GitLab instances via GITLAB_URL.

Environment variables:
    GITLAB_TOKEN: Personal access token with 'api' scope (required)
    GITLAB_URL: GitLab instance URL (default: https://gitlab.com)
    GITLAB_VERIFY_SSL: Verify SSL certificates (default: true)
"""

import json
import logging
import os

from ..core.agent import function_tool
from . import register_tool

logger = logging.getLogger(__name__)


def _get_gitlab_client():
    """Get GitLab client for the configured instance."""
    try:
        import gitlab as gitlab_lib
    except ImportError:
        raise RuntimeError("python-gitlab not installed: pip install python-gitlab")

    token = os.getenv("GITLAB_TOKEN")
    if not token:
        raise ValueError(
            "GITLAB_TOKEN environment variable not set. "
            "Use a personal, project, or group access token with 'api' scope. "
            "For enterprise, prefer group access tokens (GitLab Premium) "
            "or project access tokens over personal tokens."
        )

    url = os.getenv("GITLAB_URL", "https://gitlab.com")
    verify_ssl = os.getenv("GITLAB_VERIFY_SSL", "true").lower() in ("true", "1", "yes")

    return gitlab_lib.Gitlab(url=url, private_token=token, ssl_verify=verify_ssl)


# =============================================================================
# Project Tools
# =============================================================================


@function_tool
def gitlab_list_projects(
    search: str = "",
    visibility: str = "",
    max_results: int = 20,
) -> str:
    """
    List GitLab projects accessible to the authenticated user.

    Args:
        search: Search query to filter projects by name
        visibility: Filter by visibility (public, internal, private)
        max_results: Maximum projects to return

    Returns:
        JSON with projects list
    """
    logger.info(f"gitlab_list_projects: search={search}, visibility={visibility}")

    try:
        gl = _get_gitlab_client()

        kwargs = {"per_page": max_results}
        if search:
            kwargs["search"] = search
        if visibility:
            kwargs["visibility"] = visibility

        projects = gl.projects.list(**kwargs)

        project_list = []
        for p in projects:
            project_list.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "path_with_namespace": p.path_with_namespace,
                    "web_url": p.web_url,
                    "default_branch": getattr(p, "default_branch", None),
                    "visibility": p.visibility,
                    "description": getattr(p, "description", None),
                }
            )

        return json.dumps(
            {"ok": True, "projects": project_list, "count": len(project_list)}
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_list_projects error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def gitlab_get_project(project: str) -> str:
    """
    Get detailed information about a GitLab project.

    Args:
        project: Project ID or path (e.g., "group/project")

    Returns:
        JSON with project details
    """
    if not project:
        return json.dumps({"ok": False, "error": "project is required"})

    logger.info(f"gitlab_get_project: project={project}")

    try:
        gl = _get_gitlab_client()
        p = gl.projects.get(project)

        return json.dumps(
            {
                "ok": True,
                "id": p.id,
                "name": p.name,
                "path_with_namespace": p.path_with_namespace,
                "description": p.description,
                "web_url": p.web_url,
                "default_branch": p.default_branch,
                "visibility": p.visibility,
                "created_at": p.created_at,
                "last_activity_at": p.last_activity_at,
                "namespace": p.namespace.get("full_path") if p.namespace else None,
                "forks_count": p.forks_count,
                "star_count": p.star_count,
                "open_issues_count": getattr(p, "open_issues_count", None),
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_get_project error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def gitlab_search_projects(query: str, max_results: int = 10) -> str:
    """
    Search for GitLab projects by name or description.

    Args:
        query: Search query
        max_results: Maximum results to return

    Returns:
        JSON with matching projects
    """
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    logger.info(f"gitlab_search_projects: query={query}")

    try:
        gl = _get_gitlab_client()
        projects = gl.projects.list(search=query, per_page=max_results)

        project_list = []
        for p in projects:
            project_list.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "path_with_namespace": p.path_with_namespace,
                    "web_url": p.web_url,
                    "description": getattr(p, "description", None),
                    "visibility": p.visibility,
                }
            )

        return json.dumps(
            {"ok": True, "projects": project_list, "count": len(project_list)}
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_search_projects error: {e}")
        return json.dumps({"ok": False, "error": str(e), "query": query})


# =============================================================================
# Pipeline Tools (CI/CD)
# =============================================================================


@function_tool
def gitlab_get_pipelines(
    project: str,
    status: str = "",
    ref: str = "",
    max_results: int = 20,
) -> str:
    """
    Get CI/CD pipelines for a GitLab project.

    Args:
        project: Project ID or path (e.g., "group/project")
        status: Filter by status (running, pending, success, failed, canceled, skipped)
        ref: Filter by branch/tag name
        max_results: Maximum pipelines to return

    Returns:
        JSON with pipelines list
    """
    if not project:
        return json.dumps({"ok": False, "error": "project is required"})

    logger.info(f"gitlab_get_pipelines: project={project}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)

        kwargs = {"per_page": max_results}
        if status:
            kwargs["status"] = status
        if ref:
            kwargs["ref"] = ref

        pipelines = proj.pipelines.list(**kwargs)

        pipeline_list = []
        for p in pipelines:
            pipeline_list.append(
                {
                    "id": p.id,
                    "status": p.status,
                    "ref": p.ref,
                    "sha": p.sha,
                    "web_url": p.web_url,
                    "created_at": p.created_at,
                    "updated_at": p.updated_at,
                    "source": getattr(p, "source", None),
                }
            )

        return json.dumps(
            {"ok": True, "pipelines": pipeline_list, "count": len(pipeline_list)}
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_get_pipelines error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def gitlab_get_pipeline_jobs(project: str, pipeline_id: int) -> str:
    """
    Get jobs for a specific pipeline.

    Args:
        project: Project ID or path (e.g., "group/project")
        pipeline_id: Pipeline ID

    Returns:
        JSON with pipeline jobs list
    """
    if not project or not pipeline_id:
        return json.dumps(
            {"ok": False, "error": "project and pipeline_id are required"}
        )

    logger.info(
        f"gitlab_get_pipeline_jobs: project={project}, pipeline_id={pipeline_id}"
    )

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)
        pipeline = proj.pipelines.get(pipeline_id)
        jobs = pipeline.jobs.list(all=True)

        job_list = []
        for job in jobs:
            job_list.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "stage": job.stage,
                    "status": job.status,
                    "ref": job.ref,
                    "web_url": job.web_url,
                    "created_at": job.created_at,
                    "started_at": getattr(job, "started_at", None),
                    "finished_at": getattr(job, "finished_at", None),
                    "duration": getattr(job, "duration", None),
                    "failure_reason": getattr(job, "failure_reason", None),
                }
            )

        return json.dumps({"ok": True, "jobs": job_list, "count": len(job_list)})

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_get_pipeline_jobs error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


# =============================================================================
# Merge Request Tools
# =============================================================================


@function_tool
def gitlab_get_merge_requests(
    project: str,
    state: str = "opened",
    max_results: int = 20,
) -> str:
    """
    List merge requests for a GitLab project.

    Args:
        project: Project ID or path (e.g., "group/project")
        state: Filter by state (opened, closed, merged, all)
        max_results: Maximum MRs to return

    Returns:
        JSON with merge requests list
    """
    if not project:
        return json.dumps({"ok": False, "error": "project is required"})

    logger.info(f"gitlab_get_merge_requests: project={project}, state={state}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)
        mrs = proj.mergerequests.list(state=state, per_page=max_results)

        mr_list = []
        for mr in mrs:
            mr_list.append(
                {
                    "iid": mr.iid,
                    "title": mr.title,
                    "state": mr.state,
                    "source_branch": mr.source_branch,
                    "target_branch": mr.target_branch,
                    "author": mr.author.get("name") if mr.author else None,
                    "web_url": mr.web_url,
                    "created_at": mr.created_at,
                    "updated_at": mr.updated_at,
                    "merged_at": getattr(mr, "merged_at", None),
                    "labels": getattr(mr, "labels", []),
                }
            )

        return json.dumps(
            {"ok": True, "merge_requests": mr_list, "count": len(mr_list)}
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_get_merge_requests error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def gitlab_get_mr(project: str, mr_iid: int) -> str:
    """
    Get detailed information about a specific merge request.

    Args:
        project: Project ID or path (e.g., "group/project")
        mr_iid: Merge request IID (internal ID shown in the UI)

    Returns:
        JSON with merge request details
    """
    if not project or not mr_iid:
        return json.dumps({"ok": False, "error": "project and mr_iid are required"})

    logger.info(f"gitlab_get_mr: project={project}, mr_iid={mr_iid}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)
        mr = proj.mergerequests.get(mr_iid)

        return json.dumps(
            {
                "ok": True,
                "iid": mr.iid,
                "title": mr.title,
                "description": mr.description,
                "state": mr.state,
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
                "author": mr.author.get("name") if mr.author else None,
                "assignees": [a.get("name") for a in getattr(mr, "assignees", [])],
                "reviewers": [r.get("name") for r in getattr(mr, "reviewers", [])],
                "labels": getattr(mr, "labels", []),
                "web_url": mr.web_url,
                "created_at": mr.created_at,
                "updated_at": mr.updated_at,
                "merged_at": getattr(mr, "merged_at", None),
                "merge_status": getattr(mr, "merge_status", None),
                "has_conflicts": getattr(mr, "has_conflicts", None),
                "changes_count": getattr(mr, "changes_count", None),
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_get_mr error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def gitlab_get_mr_changes(project: str, mr_iid: int) -> str:
    """
    Get the file changes (diff) for a merge request.

    Args:
        project: Project ID or path (e.g., "group/project")
        mr_iid: Merge request IID

    Returns:
        JSON with changed files and diffs
    """
    if not project or not mr_iid:
        return json.dumps({"ok": False, "error": "project and mr_iid are required"})

    logger.info(f"gitlab_get_mr_changes: project={project}, mr_iid={mr_iid}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)
        mr = proj.mergerequests.get(mr_iid)
        changes = mr.changes()

        file_changes = []
        for change in changes.get("changes", []):
            file_changes.append(
                {
                    "old_path": change.get("old_path"),
                    "new_path": change.get("new_path"),
                    "new_file": change.get("new_file"),
                    "deleted_file": change.get("deleted_file"),
                    "renamed_file": change.get("renamed_file"),
                    "diff": change.get("diff", "")[:2000],
                }
            )

        return json.dumps(
            {"ok": True, "changes": file_changes, "count": len(file_changes)}
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_get_mr_changes error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def gitlab_add_mr_comment(project: str, mr_iid: int, comment: str) -> str:
    """
    Add a comment (note) to a merge request.

    Args:
        project: Project ID or path (e.g., "group/project")
        mr_iid: Merge request IID
        comment: Comment text (supports GitLab-flavored markdown)

    Returns:
        JSON with created comment details
    """
    if not project or not mr_iid or not comment:
        return json.dumps(
            {"ok": False, "error": "project, mr_iid, and comment are required"}
        )

    logger.info(f"gitlab_add_mr_comment: project={project}, mr_iid={mr_iid}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)
        mr = proj.mergerequests.get(mr_iid)
        note = mr.notes.create({"body": comment})

        return json.dumps(
            {
                "ok": True,
                "id": note.id,
                "created_at": note.created_at,
                "body": comment,
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_add_mr_comment error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


# =============================================================================
# Commit Tools
# =============================================================================


@function_tool
def gitlab_list_commits(
    project: str,
    ref_name: str = "",
    path: str = "",
    since: str = "",
    until: str = "",
    max_results: int = 20,
) -> str:
    """
    List commits in a GitLab project.

    Args:
        project: Project ID or path (e.g., "group/project")
        ref_name: Branch or tag name (optional)
        path: File path to filter commits (optional)
        since: Only commits after this date (ISO 8601, optional)
        until: Only commits before this date (ISO 8601, optional)
        max_results: Maximum commits to return

    Returns:
        JSON with commits list
    """
    if not project:
        return json.dumps({"ok": False, "error": "project is required"})

    logger.info(f"gitlab_list_commits: project={project}, ref={ref_name}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)

        kwargs = {"per_page": max_results}
        if ref_name:
            kwargs["ref_name"] = ref_name
        if path:
            kwargs["path"] = path
        if since:
            kwargs["since"] = since
        if until:
            kwargs["until"] = until

        commits = proj.commits.list(**kwargs)

        commit_list = []
        for c in commits:
            commit_list.append(
                {
                    "id": c.id,
                    "short_id": c.short_id,
                    "title": c.title,
                    "message": c.message,
                    "author_name": c.author_name,
                    "author_email": c.author_email,
                    "created_at": c.created_at,
                    "web_url": c.web_url,
                }
            )

        return json.dumps(
            {"ok": True, "commits": commit_list, "count": len(commit_list)}
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_list_commits error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def gitlab_get_commit(project: str, sha: str) -> str:
    """
    Get detailed information about a specific commit.

    Args:
        project: Project ID or path (e.g., "group/project")
        sha: Commit SHA

    Returns:
        JSON with commit details including diff stats
    """
    if not project or not sha:
        return json.dumps({"ok": False, "error": "project and sha are required"})

    logger.info(f"gitlab_get_commit: project={project}, sha={sha[:7]}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)
        commit = proj.commits.get(sha)

        diff = commit.diff()
        files_changed = []
        for d in diff[:100]:
            files_changed.append(
                {
                    "old_path": d.get("old_path"),
                    "new_path": d.get("new_path"),
                    "new_file": d.get("new_file"),
                    "deleted_file": d.get("deleted_file"),
                    "diff": d.get("diff", "")[:1000],
                }
            )

        return json.dumps(
            {
                "ok": True,
                "id": commit.id,
                "short_id": commit.short_id,
                "title": commit.title,
                "message": commit.message,
                "author_name": commit.author_name,
                "author_email": commit.author_email,
                "created_at": commit.created_at,
                "web_url": commit.web_url,
                "parent_ids": commit.parent_ids,
                "stats": {
                    "additions": commit.stats.get("additions", 0),
                    "deletions": commit.stats.get("deletions", 0),
                    "total": commit.stats.get("total", 0),
                },
                "files_changed": files_changed,
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_get_commit error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


# =============================================================================
# Branch and Tag Tools
# =============================================================================


@function_tool
def gitlab_list_branches(project: str, search: str = "", max_results: int = 30) -> str:
    """
    List branches in a GitLab project.

    Args:
        project: Project ID or path (e.g., "group/project")
        search: Filter branches by name
        max_results: Maximum branches to return

    Returns:
        JSON with branches list
    """
    if not project:
        return json.dumps({"ok": False, "error": "project is required"})

    logger.info(f"gitlab_list_branches: project={project}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)

        kwargs = {"per_page": max_results}
        if search:
            kwargs["search"] = search

        branches = proj.branches.list(**kwargs)

        branch_list = []
        for b in branches:
            branch_list.append(
                {
                    "name": b.name,
                    "protected": b.protected,
                    "default": b.default,
                    "web_url": b.web_url,
                    "commit_sha": b.commit.get("id") if b.commit else None,
                    "commit_message": (b.commit.get("title") if b.commit else None),
                }
            )

        return json.dumps(
            {"ok": True, "branches": branch_list, "count": len(branch_list)}
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_list_branches error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def gitlab_list_tags(project: str, max_results: int = 30) -> str:
    """
    List tags in a GitLab project.

    Args:
        project: Project ID or path (e.g., "group/project")
        max_results: Maximum tags to return

    Returns:
        JSON with tags list
    """
    if not project:
        return json.dumps({"ok": False, "error": "project is required"})

    logger.info(f"gitlab_list_tags: project={project}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)
        tags = proj.tags.list(per_page=max_results)

        tag_list = []
        for t in tags:
            tag_list.append(
                {
                    "name": t.name,
                    "message": getattr(t, "message", None),
                    "commit_sha": t.commit.get("id") if t.commit else None,
                    "commit_message": t.commit.get("title") if t.commit else None,
                    "created_at": t.commit.get("created_at") if t.commit else None,
                }
            )

        return json.dumps({"ok": True, "tags": tag_list, "count": len(tag_list)})

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_list_tags error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


# =============================================================================
# Issue Tools
# =============================================================================


@function_tool
def gitlab_list_issues(
    project: str,
    state: str = "opened",
    labels: str = "",
    max_results: int = 20,
) -> str:
    """
    List issues in a GitLab project.

    Args:
        project: Project ID or path (e.g., "group/project")
        state: Filter by state (opened, closed, all)
        labels: Comma-separated label names to filter by
        max_results: Maximum issues to return

    Returns:
        JSON with issues list
    """
    if not project:
        return json.dumps({"ok": False, "error": "project is required"})

    logger.info(f"gitlab_list_issues: project={project}, state={state}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)

        kwargs = {"state": state, "per_page": max_results}
        if labels:
            kwargs["labels"] = labels.split(",")

        issues = proj.issues.list(**kwargs)

        issue_list = []
        for issue in issues:
            issue_list.append(
                {
                    "iid": issue.iid,
                    "title": issue.title,
                    "state": issue.state,
                    "author": issue.author.get("name") if issue.author else None,
                    "labels": issue.labels,
                    "created_at": issue.created_at,
                    "updated_at": issue.updated_at,
                    "closed_at": getattr(issue, "closed_at", None),
                    "web_url": issue.web_url,
                }
            )

        return json.dumps({"ok": True, "issues": issue_list, "count": len(issue_list)})

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_list_issues error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def gitlab_get_issue(project: str, issue_iid: int) -> str:
    """
    Get detailed information about a specific issue.

    Args:
        project: Project ID or path (e.g., "group/project")
        issue_iid: Issue IID (internal ID shown in the UI)

    Returns:
        JSON with issue details
    """
    if not project or not issue_iid:
        return json.dumps({"ok": False, "error": "project and issue_iid are required"})

    logger.info(f"gitlab_get_issue: project={project}, issue_iid={issue_iid}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)
        issue = proj.issues.get(issue_iid)

        return json.dumps(
            {
                "ok": True,
                "iid": issue.iid,
                "title": issue.title,
                "description": issue.description,
                "state": issue.state,
                "author": issue.author.get("name") if issue.author else None,
                "assignees": [a.get("name") for a in getattr(issue, "assignees", [])],
                "labels": issue.labels,
                "milestone": (
                    issue.milestone.get("title") if issue.milestone else None
                ),
                "created_at": issue.created_at,
                "updated_at": issue.updated_at,
                "closed_at": getattr(issue, "closed_at", None),
                "web_url": issue.web_url,
                "user_notes_count": getattr(issue, "user_notes_count", 0),
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_get_issue error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


@function_tool
def gitlab_create_issue(
    project: str,
    title: str,
    description: str = "",
    labels: str = "",
    assignee_ids: str = "",
) -> str:
    """
    Create a new issue in a GitLab project.

    Args:
        project: Project ID or path (e.g., "group/project")
        title: Issue title
        description: Issue description (supports GitLab-flavored markdown)
        labels: Comma-separated label names
        assignee_ids: Comma-separated user IDs to assign

    Returns:
        JSON with created issue details
    """
    if not project or not title:
        return json.dumps({"ok": False, "error": "project and title are required"})

    logger.info(f"gitlab_create_issue: project={project}, title={title}")

    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)

        issue_data = {"title": title}
        if description:
            issue_data["description"] = description
        if labels:
            issue_data["labels"] = labels
        if assignee_ids:
            issue_data["assignee_ids"] = [
                int(x.strip()) for x in assignee_ids.split(",")
            ]

        issue = proj.issues.create(issue_data)

        return json.dumps(
            {
                "ok": True,
                "iid": issue.iid,
                "title": issue.title,
                "web_url": issue.web_url,
                "state": issue.state,
                "created_at": issue.created_at,
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITLAB_TOKEN"})
    except Exception as e:
        logger.error(f"gitlab_create_issue error: {e}")
        return json.dumps({"ok": False, "error": str(e), "project": project})


# =============================================================================
# Register all tools
# =============================================================================

register_tool("gitlab_list_projects", gitlab_list_projects)
register_tool("gitlab_get_project", gitlab_get_project)
register_tool("gitlab_search_projects", gitlab_search_projects)
register_tool("gitlab_get_pipelines", gitlab_get_pipelines)
register_tool("gitlab_get_pipeline_jobs", gitlab_get_pipeline_jobs)
register_tool("gitlab_get_merge_requests", gitlab_get_merge_requests)
register_tool("gitlab_get_mr", gitlab_get_mr)
register_tool("gitlab_get_mr_changes", gitlab_get_mr_changes)
register_tool("gitlab_add_mr_comment", gitlab_add_mr_comment)
register_tool("gitlab_list_commits", gitlab_list_commits)
register_tool("gitlab_get_commit", gitlab_get_commit)
register_tool("gitlab_list_branches", gitlab_list_branches)
register_tool("gitlab_list_tags", gitlab_list_tags)
register_tool("gitlab_list_issues", gitlab_list_issues)
register_tool("gitlab_get_issue", gitlab_get_issue)
register_tool("gitlab_create_issue", gitlab_create_issue)
