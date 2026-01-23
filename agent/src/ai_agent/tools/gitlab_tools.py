"""GitLab integration tools for source code and CI/CD."""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_gitlab_config() -> dict:
    """Get GitLab configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("gitlab")
        if config and config.get("token"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("GITLAB_TOKEN"):
        return {
            "token": os.getenv("GITLAB_TOKEN"),
            "url": os.getenv("GITLAB_URL", "https://gitlab.com"),
            "default_project": os.getenv("GITLAB_DEFAULT_PROJECT"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="gitlab", tool_id="gitlab_tools", missing_fields=["token"]
    )


def _get_gitlab_client():
    """Get GitLab API client."""
    try:
        import gitlab

        config = _get_gitlab_config()

        return gitlab.Gitlab(
            url=config.get("url", "https://gitlab.com"), private_token=config["token"]
        )

    except ImportError:
        raise ToolExecutionError(
            "gitlab",
            "python-gitlab not installed. Install with: pip install python-gitlab",
        )


def gitlab_list_projects(visibility: str | None = None) -> list[dict[str, Any]]:
    """
    List GitLab projects.

    Args:
        visibility: Filter by visibility (public, internal, private)

    Returns:
        List of projects
    """
    try:
        gl = _get_gitlab_client()

        kwargs = {"all": True}
        if visibility:
            kwargs["visibility"] = visibility

        projects = []
        for project in gl.projects.list(**kwargs):
            projects.append(
                {
                    "id": project.id,
                    "name": project.name,
                    "path_with_namespace": project.path_with_namespace,
                    "web_url": project.web_url,
                    "default_branch": project.default_branch,
                    "visibility": project.visibility,
                }
            )

        logger.info("gitlab_projects_listed", count=len(projects))
        return projects

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "gitlab_list_projects", "gitlab")
    except Exception as e:
        logger.error("gitlab_list_projects_failed", error=str(e))
        raise ToolExecutionError("gitlab_list_projects", str(e), e)


def gitlab_get_pipelines(
    project: str, status: str | None = None, ref: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """
    Get CI/CD pipelines for a project.

    Args:
        project: Project ID or path (e.g., "group/project")
        status: Filter by status (running, pending, success, failed, canceled, skipped)
        ref: Filter by branch/tag name
        limit: Max pipelines to return

    Returns:
        List of pipelines
    """
    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)

        kwargs = {}
        if status:
            kwargs["status"] = status
        if ref:
            kwargs["ref"] = ref

        pipelines = []
        for pipeline in proj.pipelines.list(per_page=limit, **kwargs):
            pipelines.append(
                {
                    "id": pipeline.id,
                    "status": pipeline.status,
                    "ref": pipeline.ref,
                    "sha": pipeline.sha,
                    "web_url": pipeline.web_url,
                    "created_at": pipeline.created_at,
                    "updated_at": pipeline.updated_at,
                }
            )

        logger.info("gitlab_pipelines_retrieved", project=project, count=len(pipelines))
        return pipelines

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "gitlab_get_pipelines", "gitlab")
    except Exception as e:
        logger.error("gitlab_get_pipelines_failed", error=str(e), project=project)
        raise ToolExecutionError("gitlab_get_pipelines", str(e), e)


def gitlab_get_merge_requests(
    project: str, state: str = "opened", limit: int = 20
) -> list[dict[str, Any]]:
    """
    Get merge requests for a project.

    Args:
        project: Project ID or path
        state: Filter by state (opened, closed, merged, all)
        limit: Max MRs to return

    Returns:
        List of merge requests
    """
    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)

        mrs = []
        for mr in proj.mergerequests.list(state=state, per_page=limit):
            mrs.append(
                {
                    "iid": mr.iid,
                    "title": mr.title,
                    "state": mr.state,
                    "source_branch": mr.source_branch,
                    "target_branch": mr.target_branch,
                    "author": mr.author.get("name"),
                    "web_url": mr.web_url,
                    "created_at": mr.created_at,
                    "updated_at": mr.updated_at,
                    "merged_at": getattr(mr, "merged_at", None),
                }
            )

        logger.info("gitlab_merge_requests_listed", project=project, count=len(mrs))
        return mrs

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "gitlab_get_merge_requests", "gitlab"
        )
    except Exception as e:
        logger.error("gitlab_get_merge_requests_failed", error=str(e), project=project)
        raise ToolExecutionError("gitlab_get_merge_requests", str(e), e)


def gitlab_add_mr_comment(project: str, mr_iid: int, comment: str) -> dict[str, Any]:
    """
    Add a comment to a merge request.

    Args:
        project: Project ID or path
        mr_iid: Merge request IID (internal ID)
        comment: Comment text (supports markdown)

    Returns:
        Created comment details
    """
    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)
        mr = proj.mergerequests.get(mr_iid)

        note = mr.notes.create({"body": comment})

        logger.info("gitlab_mr_comment_added", project=project, mr_iid=mr_iid)

        return {
            "id": note.id,
            "created_at": note.created_at,
            "body": comment,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "gitlab_add_mr_comment", "gitlab")
    except Exception as e:
        logger.error(
            "gitlab_mr_comment_failed", error=str(e), project=project, mr_iid=mr_iid
        )
        raise ToolExecutionError("gitlab_add_mr_comment", str(e), e)


def gitlab_get_pipeline_jobs(project: str, pipeline_id: int) -> list[dict[str, Any]]:
    """
    Get jobs for a specific pipeline.

    Args:
        project: Project ID or path
        pipeline_id: Pipeline ID

    Returns:
        List of pipeline jobs
    """
    try:
        gl = _get_gitlab_client()
        proj = gl.projects.get(project)
        pipeline = proj.pipelines.get(pipeline_id)

        jobs = []
        for job in pipeline.jobs.list(all=True):
            jobs.append(
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
                }
            )

        logger.info(
            "gitlab_pipeline_jobs_retrieved",
            project=project,
            pipeline_id=pipeline_id,
            count=len(jobs),
        )
        return jobs

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "gitlab_get_pipeline_jobs", "gitlab"
        )
    except Exception as e:
        logger.error(
            "gitlab_get_pipeline_jobs_failed",
            error=str(e),
            project=project,
            pipeline_id=pipeline_id,
        )
        raise ToolExecutionError("gitlab_get_pipeline_jobs", str(e), e)


# List of all GitLab tools for registration
GITLAB_TOOLS = [
    gitlab_list_projects,
    gitlab_get_pipelines,
    gitlab_get_merge_requests,
    gitlab_add_mr_comment,
    gitlab_get_pipeline_jobs,
]
