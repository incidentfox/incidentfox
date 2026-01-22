"""GitHub integration tools."""

import base64
import json
import os
from typing import Any

from agents import function_tool

from ..core.config_required import make_config_required_response
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_github_config() -> dict:
    """Get GitHub configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("github")
        if config and config.get("token"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("GITHUB_TOKEN"):
        return {
            "token": os.getenv("GITHUB_TOKEN"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="github", tool_id="github_tools", missing_fields=["token"]
    )


def _get_github_client():
    """Get GitHub client."""
    try:
        from github import Github

        config = _get_github_config()
        # Add timeout to prevent hanging on slow API calls
        return Github(config["token"], timeout=30)
    except ImportError:
        raise ToolExecutionError(
            "github", "PyGithub not installed. Install with: poetry add PyGithub"
        )


def _github_config_required_response(tool_name: str) -> str:
    """Create config_required response for GitHub tools."""
    return make_config_required_response(
        integration="github",
        tool=tool_name,
        missing_config=["GITHUB_TOKEN"],
    )


@function_tool
def search_github_code(
    query: str, org: str | None = None, repo: str | None = None, max_results: int = 10
) -> list[dict[str, Any]] | str:
    """
    Search code across GitHub repositories.

    Args:
        query: Search query (supports GitHub code search syntax)
        org: Optional organization to limit search
        repo: Optional specific repo (format: "owner/repo")
        max_results: Maximum results to return

    Returns:
        List of code matches or config_required response
    """
    try:
        g = _get_github_client()

        # Build search query
        search_query = query
        if org:
            search_query += f" org:{org}"
        if repo:
            search_query += f" repo:{repo}"

        results = g.search_code(search_query)

        matches = []
        for i, result in enumerate(results):
            if i >= max_results:
                break

            matches.append(
                {
                    "file_path": result.path,
                    "repository": result.repository.full_name,
                    "url": result.html_url,
                    "score": result.score,
                }
            )

        logger.info("github_search_completed", query=query, results=len(matches))
        return matches

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="search_github_code")
        return _github_config_required_response("search_github_code")

    except Exception as e:
        logger.error("github_search_failed", error=str(e), query=query)
        return json.dumps({"error": str(e), "query": query})


@function_tool
def read_github_file(repo: str, file_path: str, ref: str = "main") -> str:
    """
    Read a file from GitHub repository.

    Args:
        repo: Repository (format: "owner/repo")
        file_path: Path to file in repo
        ref: Branch/tag/commit (default: "main")

    Returns:
        File contents or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        file_content = repository.get_contents(file_path, ref=ref)

        if isinstance(file_content, list):
            return json.dumps({"error": f"{file_path} is a directory"})

        content = base64.b64decode(file_content.content).decode("utf-8")

        logger.info("github_file_read", repo=repo, file=file_path, size=len(content))
        return content

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="read_github_file")
        return _github_config_required_response("read_github_file")

    except Exception as e:
        logger.error("github_read_failed", error=str(e), repo=repo, file=file_path)
        return json.dumps({"error": str(e), "repo": repo, "file": file_path})


@function_tool
def create_pull_request(
    repo: str, title: str, head: str, base: str, body: str
) -> dict[str, Any] | str:
    """
    Create a pull request.

    Args:
        repo: Repository (format: "owner/repo")
        title: PR title
        head: Source branch
        base: Target branch
        body: PR description

    Returns:
        Created PR info or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)

        pr = repository.create_pull(title=title, body=body, head=head, base=base)

        logger.info("github_pr_created", repo=repo, pr_number=pr.number)

        return {
            "number": pr.number,
            "url": pr.html_url,
            "state": pr.state,
            "created_at": str(pr.created_at),
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="create_pull_request")
        return _github_config_required_response("create_pull_request")

    except Exception as e:
        logger.error("github_pr_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def list_pull_requests(
    repo: str, state: str = "open", max_results: int = 10
) -> list[dict[str, Any]] | str:
    """
    List pull requests in a repository.

    Args:
        repo: Repository (format: "owner/repo")
        state: PR state (open, closed, all)
        max_results: Maximum PRs to return

    Returns:
        List of PRs or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        prs = repository.get_pulls(state=state)

        pr_list = []
        for i, pr in enumerate(prs):
            if i >= max_results:
                break

            pr_list.append(
                {
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "author": pr.user.login,
                    "created_at": str(pr.created_at),
                    "url": pr.html_url,
                }
            )

        logger.info("github_prs_listed", repo=repo, count=len(pr_list))
        return pr_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="list_pull_requests")
        return _github_config_required_response("list_pull_requests")

    except Exception as e:
        logger.error("github_list_prs_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


# ============================================================================
# Enhanced GitHub Tools (ported from cto-ai-agent)
# ============================================================================


@function_tool
def merge_pull_request(
    repo: str, pr_number: int, merge_method: str = "merge"
) -> dict[str, Any] | str:
    """
    Merge a pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: PR number to merge
        merge_method: Merge method (merge, squash, rebase)

    Returns:
        Merge result with merged status and sha or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)
        result = pr.merge(merge_method=merge_method)

        logger.info("github_pr_merged", repo=repo, pr_number=pr_number)
        return {"ok": True, "merged": result.merged, "sha": result.sha}

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="merge_pull_request")
        return _github_config_required_response("merge_pull_request")

    except Exception as e:
        logger.error("github_merge_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})


@function_tool
def github_create_issue(
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
    assignees: list[str] | None = None,
) -> dict[str, Any] | str:
    """
    Create a new issue.

    Args:
        repo: Repository (format: "owner/repo")
        title: Issue title
        body: Issue description
        labels: List of label names
        assignees: List of assignee usernames

    Returns:
        Created issue info or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)

        issue = repository.create_issue(
            title=title, body=body, labels=labels or [], assignees=assignees or []
        )

        logger.info("github_issue_created", repo=repo, issue_number=issue.number)
        return {
            "number": issue.number,
            "url": issue.html_url,
            "state": issue.state,
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_create_issue")
        return _github_config_required_response("github_create_issue")

    except Exception as e:
        logger.error("github_issue_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def list_issues(
    repo: str,
    state: str = "open",
    labels: list[str] | None = None,
    max_results: int = 20,
) -> list[dict[str, Any]] | str:
    """
    List issues in a repository.

    Args:
        repo: Repository (format: "owner/repo")
        state: Issue state (open, closed, all)
        labels: Filter by labels
        max_results: Maximum issues to return

    Returns:
        List of issues or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        issues = repository.get_issues(state=state, labels=labels or [])

        issue_list = []
        for i, issue in enumerate(issues):
            if i >= max_results:
                break
            # Skip pull requests (they show up as issues too)
            if issue.pull_request:
                continue

            issue_list.append(
                {
                    "number": issue.number,
                    "title": issue.title,
                    "state": issue.state,
                    "author": issue.user.login,
                    "labels": [l.name for l in issue.labels],
                    "created_at": str(issue.created_at),
                    "url": issue.html_url,
                }
            )

        logger.info("github_issues_listed", repo=repo, count=len(issue_list))
        return issue_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="list_issues")
        return _github_config_required_response("list_issues")

    except Exception as e:
        logger.error("github_list_issues_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def close_issue(
    repo: str, issue_number: int, comment: str | None = None
) -> dict[str, Any] | str:
    """
    Close an issue.

    Args:
        repo: Repository (format: "owner/repo")
        issue_number: Issue number to close
        comment: Optional closing comment

    Returns:
        Closed issue info or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        issue = repository.get_issue(issue_number)

        if comment:
            issue.create_comment(comment)
        issue.edit(state="closed")

        logger.info("github_issue_closed", repo=repo, issue_number=issue_number)
        return {"ok": True, "number": issue_number, "closed": True}

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="close_issue")
        return _github_config_required_response("close_issue")

    except Exception as e:
        logger.error("github_close_issue_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo, "issue_number": issue_number})


@function_tool
def create_branch(
    repo: str, branch_name: str, source_branch: str = "main"
) -> dict[str, Any] | str:
    """
    Create a new branch.

    Args:
        repo: Repository (format: "owner/repo")
        branch_name: Name for the new branch
        source_branch: Branch to create from (default: main)

    Returns:
        Created branch info or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        source = repository.get_branch(source_branch)
        ref = repository.create_git_ref(
            ref=f"refs/heads/{branch_name}", sha=source.commit.sha
        )

        logger.info("github_branch_created", repo=repo, branch=branch_name)
        return {
            "ok": True,
            "branch": branch_name,
            "ref": ref.ref,
            "sha": source.commit.sha,
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="create_branch")
        return _github_config_required_response("create_branch")

    except Exception as e:
        logger.error("github_create_branch_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo, "branch": branch_name})


@function_tool
def list_branches(repo: str, max_results: int = 30) -> list[dict[str, Any]] | str:
    """
    List branches in a repository.

    Args:
        repo: Repository (format: "owner/repo")
        max_results: Maximum branches to return

    Returns:
        List of branches or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        branches = repository.get_branches()

        branch_list = []
        for i, branch in enumerate(branches):
            if i >= max_results:
                break
            branch_list.append(
                {
                    "name": branch.name,
                    "sha": branch.commit.sha,
                    "protected": branch.protected,
                }
            )

        logger.info("github_branches_listed", repo=repo, count=len(branch_list))
        return branch_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="list_branches")
        return _github_config_required_response("list_branches")

    except Exception as e:
        logger.error("github_list_branches_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def list_files(
    repo: str, path: str = "", ref: str | None = None
) -> list[dict[str, Any]] | str:
    """
    List files in a repository directory.

    Args:
        repo: Repository (format: "owner/repo")
        path: Directory path (empty for root)
        ref: Branch/tag/commit

    Returns:
        List of files and directories or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)

        kwargs = {}
        if ref:
            kwargs["ref"] = ref

        contents = (
            repository.get_contents(path, **kwargs)
            if path
            else repository.get_contents("", **kwargs)
        )

        if not isinstance(contents, list):
            contents = [contents]

        file_list = []
        for item in contents:
            file_list.append(
                {
                    "name": item.name,
                    "path": item.path,
                    "type": item.type,
                    "size": item.size if item.type == "file" else None,
                    "sha": item.sha,
                }
            )

        logger.info("github_files_listed", repo=repo, path=path, count=len(file_list))
        return file_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="list_files")
        return _github_config_required_response("list_files")

    except Exception as e:
        logger.error("github_list_files_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo, "path": path})


@function_tool
def get_repo_info(repo: str) -> dict[str, Any] | str:
    """
    Get repository information.

    Args:
        repo: Repository (format: "owner/repo")

    Returns:
        Repository info including name, description, URLs, etc. or config_required response
    """
    try:
        g = _get_github_client()
        r = g.get_repo(repo)

        return {
            "ok": True,
            "name": r.name,
            "full_name": r.full_name,
            "description": r.description,
            "private": r.private,
            "default_branch": r.default_branch,
            "clone_url": r.clone_url,
            "ssh_url": r.ssh_url,
            "html_url": r.html_url,
            "language": r.language,
            "stars": r.stargazers_count,
            "forks": r.forks_count,
            "open_issues": r.open_issues_count,
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="get_repo_info")
        return _github_config_required_response("get_repo_info")

    except Exception as e:
        logger.error("github_get_repo_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def trigger_workflow(
    repo: str, workflow_id: str, ref: str = "main", inputs: str = ""
) -> dict[str, Any] | str:
    """
    Trigger a GitHub Actions workflow.

    Args:
        repo: Repository (format: "owner/repo")
        workflow_id: Workflow filename (e.g., "ci.yml") or ID
        ref: Branch to run on
        inputs: Workflow input parameters as JSON string (e.g., '{"key": "value"}')

    Returns:
        Trigger result or config_required response
    """
    try:
        # Parse inputs JSON string
        inputs_dict = json.loads(inputs) if inputs else {}

        g = _get_github_client()
        repository = g.get_repo(repo)
        workflow = repository.get_workflow(workflow_id)
        result = workflow.create_dispatch(ref=ref, inputs=inputs_dict)

        logger.info(
            "github_workflow_triggered", repo=repo, workflow=workflow_id, ref=ref
        )
        return {"ok": result, "workflow_id": workflow_id, "ref": ref}

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="trigger_workflow")
        return _github_config_required_response("trigger_workflow")

    except Exception as e:
        logger.error("github_trigger_workflow_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo, "workflow_id": workflow_id})


@function_tool
def list_workflow_runs(
    repo: str,
    workflow_id: str | None = None,
    status: str | None = None,
    max_results: int = 10,
) -> list[dict[str, Any]] | str:
    """
    List recent workflow runs.

    Args:
        repo: Repository (format: "owner/repo")
        workflow_id: Filter by workflow
        status: Filter by status (queued, in_progress, completed)
        max_results: Maximum runs to return

    Returns:
        List of workflow runs or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)

        kwargs = {}
        if status:
            kwargs["status"] = status

        if workflow_id:
            workflow = repository.get_workflow(workflow_id)
            runs = workflow.get_runs(**kwargs)
        else:
            runs = repository.get_workflow_runs(**kwargs)

        run_list = []
        for i, run in enumerate(runs):
            if i >= max_results:
                break
            run_list.append(
                {
                    "id": run.id,
                    "name": run.name,
                    "status": run.status,
                    "conclusion": run.conclusion,
                    "url": run.html_url,
                    "created_at": str(run.created_at),
                    "head_branch": run.head_branch,
                }
            )

        logger.info("github_workflow_runs_listed", repo=repo, count=len(run_list))
        return run_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="list_workflow_runs")
        return _github_config_required_response("list_workflow_runs")

    except Exception as e:
        logger.error("github_list_runs_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def github_get_pr(repo: str, pr_number: int) -> dict[str, Any] | str:
    """
    Get details of a specific pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: PR number

    Returns:
        Pull request details or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)

        logger.info("github_pr_fetched", repo=repo, pr_number=pr_number)

        return {
            "number": pr.number,
            "title": pr.title,
            "body": pr.body,
            "state": pr.state,
            "author": pr.user.login,
            "head": pr.head.ref,
            "base": pr.base.ref,
            "mergeable": pr.mergeable,
            "merged": pr.merged,
            "created_at": str(pr.created_at),
            "updated_at": str(pr.updated_at),
            "url": pr.html_url,
            "labels": [l.name for l in pr.labels],
            "assignees": [a.login for a in pr.assignees],
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_get_pr")
        return _github_config_required_response("github_get_pr")

    except Exception as e:
        logger.error(
            "github_get_pr_failed", error=str(e), repo=repo, pr_number=pr_number
        )
        return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})


@function_tool
def github_search_commits_by_timerange(
    repo: str,
    since: str,
    until: str | None = None,
    author: str | None = None,
    max_results: int = 50,
) -> list[dict[str, Any]] | str:
    """
    Search commits in a repository by time range.

    Args:
        repo: Repository (format: "owner/repo")
        since: Start datetime (ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)
        until: End datetime (optional, ISO 8601 format)
        author: Filter by author username (optional)
        max_results: Maximum commits to return

    Returns:
        List of commits or config_required response
    """
    try:
        from datetime import datetime

        g = _get_github_client()
        repository = g.get_repo(repo)

        # Parse datetime strings
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))

        kwargs = {"since": since_dt}
        if until:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            kwargs["until"] = until_dt
        if author:
            kwargs["author"] = author

        commits = repository.get_commits(**kwargs)

        commit_list = []
        for i, commit in enumerate(commits):
            if i >= max_results:
                break
            commit_list.append(
                {
                    "sha": commit.sha,
                    "message": commit.commit.message,
                    "author": commit.commit.author.name,
                    "author_email": commit.commit.author.email,
                    "date": str(commit.commit.author.date),
                    "url": commit.html_url,
                }
            )

        logger.info("github_commits_searched", repo=repo, count=len(commit_list))
        return commit_list

    except IntegrationNotConfiguredError:
        logger.warning(
            "github_not_configured", tool="github_search_commits_by_timerange"
        )
        return _github_config_required_response("github_search_commits_by_timerange")

    except Exception as e:
        logger.error("github_search_commits_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def github_list_pr_commits(
    repo: str, pr_number: int, max_results: int = 100
) -> list[dict[str, Any]] | str:
    """
    List all commits in a pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: Pull request number
        max_results: Maximum commits to return

    Returns:
        List of commits in the PR or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)

        commits = pr.get_commits()

        commit_list = []
        for i, commit in enumerate(commits):
            if i >= max_results:
                break
            commit_list.append(
                {
                    "sha": commit.sha,
                    "message": commit.commit.message,
                    "author": (
                        commit.commit.author.name if commit.commit.author else None
                    ),
                    "author_email": (
                        commit.commit.author.email if commit.commit.author else None
                    ),
                    "date": (
                        str(commit.commit.author.date) if commit.commit.author else None
                    ),
                    "url": commit.html_url,
                    "files_changed": (
                        commit.files.totalCount
                        if hasattr(commit.files, "totalCount")
                        else (
                            len(list(commit.files))
                            if hasattr(commit, "files")
                            else None
                        )
                    ),
                }
            )

        logger.info(
            "github_pr_commits_listed",
            repo=repo,
            pr_number=pr_number,
            count=len(commit_list),
        )
        return commit_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_list_pr_commits")
        return _github_config_required_response("github_list_pr_commits")

    except Exception as e:
        logger.error(
            "github_list_pr_commits_failed",
            error=str(e),
            repo=repo,
            pr_number=pr_number,
        )
        return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})


@function_tool
def github_create_pr_review(
    repo: str, pr_number: int, body: str, event: str = "COMMENT"
) -> dict[str, Any] | str:
    """
    Create a review on a pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: Pull request number
        body: Review comment body (Markdown supported)
        event: Review event - "COMMENT", "APPROVE", "REQUEST_CHANGES"

    Returns:
        Created review info or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)

        # Validate event
        valid_events = ["COMMENT", "APPROVE", "REQUEST_CHANGES"]
        if event not in valid_events:
            raise ValueError(f"event must be one of {valid_events}, got: {event}")

        review = pr.create_review(body=body, event=event)

        logger.info(
            "github_pr_review_created", repo=repo, pr_number=pr_number, event=event
        )

        return {
            "id": review.id,
            "user": review.user.login,
            "body": review.body,
            "state": review.state,
            "submitted_at": str(review.submitted_at) if review.submitted_at else None,
            "url": review.html_url,
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_create_pr_review")
        return _github_config_required_response("github_create_pr_review")

    except Exception as e:
        logger.error(
            "github_create_pr_review_failed",
            error=str(e),
            repo=repo,
            pr_number=pr_number,
        )
        return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})


# List of all GitHub tools for registration
GITHUB_TOOLS = [
    search_github_code,
    read_github_file,
    create_pull_request,
    list_pull_requests,
    merge_pull_request,
    github_create_issue,
    list_issues,
    close_issue,
    create_branch,
    list_branches,
    list_files,
    get_repo_info,
    trigger_workflow,
    list_workflow_runs,
    github_get_pr,
    github_search_commits_by_timerange,
    github_list_pr_commits,
    github_create_pr_review,
]
