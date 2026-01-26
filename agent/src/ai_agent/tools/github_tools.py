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
def github_list_commits(
    repo: str,
    branch: str | None = None,
    author: str | None = None,
    path: str | None = None,
    max_results: int = 10,
) -> list[dict[str, Any]] | str:
    """
    List recent commits from a remote GitHub repository.

    This is the simplest way to get recent commits - no time range required.

    Args:
        repo: Repository (format: "owner/repo")
        branch: Branch name (optional, defaults to default branch)
        author: Filter by author username (optional)
        path: Filter by file path (optional)
        max_results: Maximum commits to return (default 10)

    Returns:
        List of commits or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)

        kwargs = {}
        if branch:
            kwargs["sha"] = branch
        if author:
            kwargs["author"] = author
        if path:
            kwargs["path"] = path

        commits = repository.get_commits(**kwargs)

        commit_list = []
        for i, commit in enumerate(commits):
            if i >= max_results:
                break
            commit_list.append(
                {
                    "sha": commit.sha,
                    "short_sha": commit.sha[:7],
                    "message": commit.commit.message,
                    "author": (
                        commit.commit.author.name if commit.commit.author else None
                    ),
                    "author_login": commit.author.login if commit.author else None,
                    "date": (
                        str(commit.commit.author.date) if commit.commit.author else None
                    ),
                    "url": commit.html_url,
                }
            )

        logger.info("github_commits_listed", repo=repo, count=len(commit_list))
        return commit_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_list_commits")
        return _github_config_required_response("github_list_commits")

    except Exception as e:
        logger.error("github_list_commits_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def github_get_commit(repo: str, sha: str) -> dict[str, Any] | str:
    """
    Get detailed information about a specific commit.

    Args:
        repo: Repository (format: "owner/repo")
        sha: Commit SHA (full or short)

    Returns:
        Commit details including files changed, stats, etc.
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        commit = repository.get_commit(sha)

        files_changed = []
        for f in commit.files:
            files_changed.append(
                {
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "changes": f.changes,
                    "patch": f.patch[:2000] if f.patch else None,
                }
            )

        logger.info("github_commit_fetched", repo=repo, sha=sha[:7])
        return {
            "sha": commit.sha,
            "message": commit.commit.message,
            "author": commit.commit.author.name if commit.commit.author else None,
            "author_email": (
                commit.commit.author.email if commit.commit.author else None
            ),
            "author_login": commit.author.login if commit.author else None,
            "date": str(commit.commit.author.date) if commit.commit.author else None,
            "url": commit.html_url,
            "stats": {
                "additions": commit.stats.additions,
                "deletions": commit.stats.deletions,
                "total": commit.stats.total,
            },
            "files_changed": files_changed,
            "parents": [p.sha for p in commit.parents],
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_get_commit")
        return _github_config_required_response("github_get_commit")

    except Exception as e:
        logger.error("github_get_commit_failed", error=str(e), repo=repo, sha=sha)
        return json.dumps({"error": str(e), "repo": repo, "sha": sha})


@function_tool
def github_compare_commits(repo: str, base: str, head: str) -> dict[str, Any] | str:
    """
    Compare two commits, branches, or tags.

    Args:
        repo: Repository (format: "owner/repo")
        base: Base commit/branch/tag
        head: Head commit/branch/tag to compare

    Returns:
        Comparison including commits between, files changed, stats
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        comparison = repository.compare(base, head)

        commits = []
        for c in comparison.commits[:50]:  # Limit to 50 commits
            commits.append(
                {
                    "sha": c.sha,
                    "message": c.commit.message.split("\n")[0],  # First line only
                    "author": c.commit.author.name if c.commit.author else None,
                    "date": str(c.commit.author.date) if c.commit.author else None,
                }
            )

        files = []
        for f in comparison.files[:100]:  # Limit to 100 files
            files.append(
                {
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                }
            )

        logger.info("github_compare_completed", repo=repo, base=base, head=head)
        return {
            "status": comparison.status,
            "ahead_by": comparison.ahead_by,
            "behind_by": comparison.behind_by,
            "total_commits": comparison.total_commits,
            "commits": commits,
            "files": files,
            "url": comparison.html_url,
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_compare_commits")
        return _github_config_required_response("github_compare_commits")

    except Exception as e:
        logger.error("github_compare_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo, "base": base, "head": head})


@function_tool
def github_list_tags(repo: str, max_results: int = 30) -> list[dict[str, Any]] | str:
    """
    List tags in a repository.

    Args:
        repo: Repository (format: "owner/repo")
        max_results: Maximum tags to return

    Returns:
        List of tags with their commit info
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        tags = repository.get_tags()

        tag_list = []
        for i, tag in enumerate(tags):
            if i >= max_results:
                break
            tag_list.append(
                {
                    "name": tag.name,
                    "sha": tag.commit.sha,
                    "url": f"https://github.com/{repo}/releases/tag/{tag.name}",
                }
            )

        logger.info("github_tags_listed", repo=repo, count=len(tag_list))
        return tag_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_list_tags")
        return _github_config_required_response("github_list_tags")

    except Exception as e:
        logger.error("github_list_tags_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def github_list_releases(
    repo: str, include_prereleases: bool = True, max_results: int = 10
) -> list[dict[str, Any]] | str:
    """
    List releases in a repository.

    Args:
        repo: Repository (format: "owner/repo")
        include_prereleases: Include pre-release versions
        max_results: Maximum releases to return

    Returns:
        List of releases with version info
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        releases = repository.get_releases()

        release_list = []
        for i, release in enumerate(releases):
            if i >= max_results:
                break
            if not include_prereleases and release.prerelease:
                continue
            release_list.append(
                {
                    "id": release.id,
                    "tag_name": release.tag_name,
                    "name": release.title,
                    "body": release.body[:500] if release.body else None,
                    "draft": release.draft,
                    "prerelease": release.prerelease,
                    "created_at": str(release.created_at),
                    "published_at": (
                        str(release.published_at) if release.published_at else None
                    ),
                    "url": release.html_url,
                    "author": release.author.login if release.author else None,
                }
            )

        logger.info("github_releases_listed", repo=repo, count=len(release_list))
        return release_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_list_releases")
        return _github_config_required_response("github_list_releases")

    except Exception as e:
        logger.error("github_list_releases_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def github_get_pr_files(
    repo: str, pr_number: int, max_results: int = 100
) -> list[dict[str, Any]] | str:
    """
    Get files changed in a pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: Pull request number
        max_results: Maximum files to return

    Returns:
        List of files with change stats
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)
        files = pr.get_files()

        file_list = []
        for i, f in enumerate(files):
            if i >= max_results:
                break
            file_list.append(
                {
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "changes": f.changes,
                    "patch": f.patch[:1000] if f.patch else None,
                }
            )

        logger.info(
            "github_pr_files_fetched",
            repo=repo,
            pr_number=pr_number,
            count=len(file_list),
        )
        return file_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_get_pr_files")
        return _github_config_required_response("github_get_pr_files")

    except Exception as e:
        logger.error(
            "github_get_pr_files_failed", error=str(e), repo=repo, pr_number=pr_number
        )
        return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})


@function_tool
def github_list_pr_reviews(repo: str, pr_number: int) -> list[dict[str, Any]] | str:
    """
    List reviews on a pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: Pull request number

    Returns:
        List of reviews with reviewer info and state
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)
        reviews = pr.get_reviews()

        review_list = []
        for review in reviews:
            review_list.append(
                {
                    "id": review.id,
                    "user": review.user.login if review.user else None,
                    "state": review.state,
                    "body": review.body,
                    "submitted_at": (
                        str(review.submitted_at) if review.submitted_at else None
                    ),
                    "url": review.html_url,
                }
            )

        logger.info(
            "github_pr_reviews_listed",
            repo=repo,
            pr_number=pr_number,
            count=len(review_list),
        )
        return review_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_list_pr_reviews")
        return _github_config_required_response("github_list_pr_reviews")

    except Exception as e:
        logger.error(
            "github_list_pr_reviews_failed",
            error=str(e),
            repo=repo,
            pr_number=pr_number,
        )
        return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})


@function_tool
def github_get_issue(repo: str, issue_number: int) -> dict[str, Any] | str:
    """
    Get detailed information about a specific issue.

    Args:
        repo: Repository (format: "owner/repo")
        issue_number: Issue number

    Returns:
        Issue details including body, labels, assignees, etc.
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        issue = repository.get_issue(issue_number)

        logger.info("github_issue_fetched", repo=repo, issue_number=issue_number)
        return {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body,
            "state": issue.state,
            "author": issue.user.login if issue.user else None,
            "labels": [l.name for l in issue.labels],
            "assignees": [a.login for a in issue.assignees],
            "milestone": issue.milestone.title if issue.milestone else None,
            "created_at": str(issue.created_at),
            "updated_at": str(issue.updated_at),
            "closed_at": str(issue.closed_at) if issue.closed_at else None,
            "comments_count": issue.comments,
            "url": issue.html_url,
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_get_issue")
        return _github_config_required_response("github_get_issue")

    except Exception as e:
        logger.error(
            "github_get_issue_failed",
            error=str(e),
            repo=repo,
            issue_number=issue_number,
        )
        return json.dumps({"error": str(e), "repo": repo, "issue_number": issue_number})


@function_tool
def github_list_issue_comments(
    repo: str, issue_number: int, max_results: int = 50
) -> list[dict[str, Any]] | str:
    """
    List comments on an issue.

    Args:
        repo: Repository (format: "owner/repo")
        issue_number: Issue number
        max_results: Maximum comments to return

    Returns:
        List of comments with author and body
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        issue = repository.get_issue(issue_number)
        comments = issue.get_comments()

        comment_list = []
        for i, comment in enumerate(comments):
            if i >= max_results:
                break
            comment_list.append(
                {
                    "id": comment.id,
                    "author": comment.user.login if comment.user else None,
                    "body": comment.body,
                    "created_at": str(comment.created_at),
                    "updated_at": str(comment.updated_at),
                    "url": comment.html_url,
                }
            )

        logger.info(
            "github_issue_comments_listed",
            repo=repo,
            issue_number=issue_number,
            count=len(comment_list),
        )
        return comment_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_list_issue_comments")
        return _github_config_required_response("github_list_issue_comments")

    except Exception as e:
        logger.error(
            "github_list_issue_comments_failed",
            error=str(e),
            repo=repo,
            issue_number=issue_number,
        )
        return json.dumps({"error": str(e), "repo": repo, "issue_number": issue_number})


@function_tool
def github_add_issue_comment(
    repo: str, issue_number: int, body: str
) -> dict[str, Any] | str:
    """
    Add a comment to an issue.

    Args:
        repo: Repository (format: "owner/repo")
        issue_number: Issue number
        body: Comment body (Markdown supported)

    Returns:
        Created comment info
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        issue = repository.get_issue(issue_number)
        comment = issue.create_comment(body)

        logger.info("github_issue_comment_added", repo=repo, issue_number=issue_number)
        return {
            "id": comment.id,
            "body": comment.body,
            "url": comment.html_url,
            "created_at": str(comment.created_at),
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_add_issue_comment")
        return _github_config_required_response("github_add_issue_comment")

    except Exception as e:
        logger.error(
            "github_add_issue_comment_failed",
            error=str(e),
            repo=repo,
            issue_number=issue_number,
        )
        return json.dumps({"error": str(e), "repo": repo, "issue_number": issue_number})


@function_tool
def github_add_pr_comment(repo: str, pr_number: int, body: str) -> dict[str, Any] | str:
    """
    Add a comment to a pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: Pull request number
        body: Comment body (Markdown supported)

    Returns:
        Created comment info
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)
        # PR comments are issue comments in GitHub's API
        comment = pr.create_issue_comment(body)

        logger.info("github_pr_comment_added", repo=repo, pr_number=pr_number)
        return {
            "id": comment.id,
            "body": comment.body,
            "url": comment.html_url,
            "created_at": str(comment.created_at),
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_add_pr_comment")
        return _github_config_required_response("github_add_pr_comment")

    except Exception as e:
        logger.error(
            "github_add_pr_comment_failed", error=str(e), repo=repo, pr_number=pr_number
        )
        return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})


@function_tool
def github_list_contributors(
    repo: str, max_results: int = 30
) -> list[dict[str, Any]] | str:
    """
    List contributors to a repository.

    Args:
        repo: Repository (format: "owner/repo")
        max_results: Maximum contributors to return

    Returns:
        List of contributors with contribution counts
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        contributors = repository.get_contributors()

        contributor_list = []
        for i, c in enumerate(contributors):
            if i >= max_results:
                break
            contributor_list.append(
                {
                    "login": c.login,
                    "contributions": c.contributions,
                    "url": c.html_url,
                    "avatar_url": c.avatar_url,
                }
            )

        logger.info(
            "github_contributors_listed", repo=repo, count=len(contributor_list)
        )
        return contributor_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_list_contributors")
        return _github_config_required_response("github_list_contributors")

    except Exception as e:
        logger.error("github_list_contributors_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def github_search_issues(
    query: str,
    repo: str | None = None,
    state: str | None = None,
    max_results: int = 20,
) -> list[dict[str, Any]] | str:
    """
    Search issues across GitHub repositories.

    Args:
        query: Search query (GitHub issue search syntax)
        repo: Limit to specific repo (format: "owner/repo")
        state: Filter by state (open, closed)
        max_results: Maximum results to return

    Returns:
        List of matching issues
    """
    try:
        g = _get_github_client()

        search_query = query
        if repo:
            search_query += f" repo:{repo}"
        if state:
            search_query += f" state:{state}"
        search_query += " is:issue"  # Exclude PRs

        results = g.search_issues(search_query)

        issue_list = []
        for i, issue in enumerate(results):
            if i >= max_results:
                break
            issue_list.append(
                {
                    "number": issue.number,
                    "title": issue.title,
                    "state": issue.state,
                    "repository": issue.repository.full_name,
                    "author": issue.user.login if issue.user else None,
                    "labels": [l.name for l in issue.labels],
                    "created_at": str(issue.created_at),
                    "url": issue.html_url,
                }
            )

        logger.info("github_issues_searched", query=query, count=len(issue_list))
        return issue_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_search_issues")
        return _github_config_required_response("github_search_issues")

    except Exception as e:
        logger.error("github_search_issues_failed", error=str(e), query=query)
        return json.dumps({"error": str(e), "query": query})


@function_tool
def github_search_prs(
    query: str,
    repo: str | None = None,
    state: str | None = None,
    max_results: int = 20,
) -> list[dict[str, Any]] | str:
    """
    Search pull requests across GitHub repositories.

    Args:
        query: Search query (GitHub search syntax)
        repo: Limit to specific repo (format: "owner/repo")
        state: Filter by state (open, closed, merged)
        max_results: Maximum results to return

    Returns:
        List of matching pull requests
    """
    try:
        g = _get_github_client()

        search_query = query
        if repo:
            search_query += f" repo:{repo}"
        if state:
            if state == "merged":
                search_query += " is:merged"
            else:
                search_query += f" state:{state}"
        search_query += " is:pr"

        results = g.search_issues(search_query)

        pr_list = []
        for i, pr in enumerate(results):
            if i >= max_results:
                break
            pr_list.append(
                {
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "repository": pr.repository.full_name,
                    "author": pr.user.login if pr.user else None,
                    "labels": [l.name for l in pr.labels],
                    "created_at": str(pr.created_at),
                    "url": pr.html_url,
                }
            )

        logger.info("github_prs_searched", query=query, count=len(pr_list))
        return pr_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="github_search_prs")
        return _github_config_required_response("github_search_prs")

    except Exception as e:
        logger.error("github_search_prs_failed", error=str(e), query=query)
        return json.dumps({"error": str(e), "query": query})


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


# ============================================================================
# Repository Structure Tools
# ============================================================================


@function_tool
def get_repo_tree(
    repo: str,
    ref: str = "main",
    path_filter: str | None = None,
    max_items: int = 1000,
) -> dict[str, Any] | str:
    """
    Get full recursive tree structure of a repository.

    Much more efficient than calling list_files multiple times when you need
    to understand the overall codebase structure.

    Args:
        repo: Repository (format: "owner/repo")
        ref: Branch/tag/commit (default: "main")
        path_filter: Optional path prefix to filter results (e.g., "src/")
        max_items: Maximum items to return (default 1000)

    Returns:
        Dict with total counts and tree structure, or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)

        # Get the commit to find the tree SHA
        commit = repository.get_commit(ref)
        tree_sha = commit.commit.tree.sha

        # Get the full tree recursively
        tree = repository.get_git_tree(tree_sha, recursive=True)

        items = []
        files_count = 0
        dirs_count = 0

        for item in tree.tree:
            # Apply path filter if specified
            if path_filter and not item.path.startswith(path_filter):
                continue

            if len(items) >= max_items:
                break

            item_data = {
                "path": item.path,
                "type": "file" if item.type == "blob" else "directory",
                "size": item.size if item.type == "blob" else None,
            }
            items.append(item_data)

            if item.type == "blob":
                files_count += 1
            else:
                dirs_count += 1

        logger.info(
            "github_repo_tree_fetched",
            repo=repo,
            ref=ref,
            files=files_count,
            dirs=dirs_count,
        )

        return {
            "repo": repo,
            "ref": ref,
            "total_files": files_count,
            "total_directories": dirs_count,
            "truncated": tree.truncated or len(items) >= max_items,
            "tree": items,
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="get_repo_tree")
        return _github_config_required_response("get_repo_tree")

    except Exception as e:
        logger.error("github_get_tree_failed", error=str(e), repo=repo, ref=ref)
        return json.dumps({"error": str(e), "repo": repo, "ref": ref})


# ============================================================================
# GitHub Actions - Enhanced Tools
# ============================================================================


@function_tool
def get_workflow_run_jobs(
    repo: str, run_id: int, filter_status: str | None = None, max_results: int = 50
) -> list[dict[str, Any]] | str:
    """
    Get jobs for a specific workflow run.

    Use this to see individual job statuses within a workflow run,
    especially useful when a workflow has multiple jobs and you need
    to identify which specific job failed.

    Args:
        repo: Repository (format: "owner/repo")
        run_id: Workflow run ID
        filter_status: Filter by status (queued, in_progress, completed)
        max_results: Maximum jobs to return

    Returns:
        List of jobs with status, conclusion, and timing info
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        run = repository.get_workflow_run(run_id)

        jobs = run.jobs()

        job_list = []
        for i, job in enumerate(jobs):
            if i >= max_results:
                break

            if filter_status and job.status != filter_status:
                continue

            # Get step information
            steps = []
            if hasattr(job, "steps") and job.steps:
                for step in job.steps:
                    steps.append(
                        {
                            "name": step.name,
                            "status": step.status,
                            "conclusion": step.conclusion,
                            "number": step.number,
                        }
                    )

            job_list.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "status": job.status,
                    "conclusion": job.conclusion,
                    "started_at": str(job.started_at) if job.started_at else None,
                    "completed_at": str(job.completed_at) if job.completed_at else None,
                    "url": job.html_url,
                    "steps": steps,
                }
            )

        logger.info(
            "github_workflow_jobs_listed", repo=repo, run_id=run_id, count=len(job_list)
        )
        return job_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="get_workflow_run_jobs")
        return _github_config_required_response("get_workflow_run_jobs")

    except Exception as e:
        logger.error(
            "github_get_workflow_jobs_failed", error=str(e), repo=repo, run_id=run_id
        )
        return json.dumps({"error": str(e), "repo": repo, "run_id": run_id})


@function_tool
def get_workflow_run_logs(repo: str, run_id: int) -> dict[str, Any] | str:
    """
    Get logs download URL for a workflow run.

    Note: GitHub's API provides a URL to download logs as a zip file.
    This tool returns the download URL which can be used to fetch logs.

    Args:
        repo: Repository (format: "owner/repo")
        run_id: Workflow run ID

    Returns:
        Dict with logs_url for downloading, or config_required response
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        run = repository.get_workflow_run(run_id)

        # Get the logs URL - this is a redirect URL to download logs
        logs_url = run.logs_url

        logger.info("github_workflow_logs_url_fetched", repo=repo, run_id=run_id)

        return {
            "repo": repo,
            "run_id": run_id,
            "run_name": run.name,
            "status": run.status,
            "conclusion": run.conclusion,
            "logs_url": logs_url,
            "html_url": run.html_url,
            "note": "Use the logs_url to download logs as a zip file. The URL requires authentication.",
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="get_workflow_run_logs")
        return _github_config_required_response("get_workflow_run_logs")

    except Exception as e:
        logger.error(
            "github_get_workflow_logs_failed", error=str(e), repo=repo, run_id=run_id
        )
        return json.dumps({"error": str(e), "repo": repo, "run_id": run_id})


@function_tool
def get_failed_workflow_annotations(
    repo: str, run_id: int
) -> list[dict[str, Any]] | str:
    """
    Get error annotations from a failed workflow run.

    This is often more useful than full logs - it extracts just the
    error messages and warnings that GitHub detected in the workflow output.

    Args:
        repo: Repository (format: "owner/repo")
        run_id: Workflow run ID

    Returns:
        List of annotations (errors, warnings) from the run
    """
    try:
        import requests

        config = _get_github_config()
        headers = {
            "Authorization": f"Bearer {config['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # Get check runs for this workflow run
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        jobs_data = response.json()
        annotations = []

        for job in jobs_data.get("jobs", []):
            job_id = job.get("id")

            # Get annotations for each job via check-run API
            check_url = (
                f"https://api.github.com/repos/{repo}/check-runs/{job_id}/annotations"
            )
            ann_response = requests.get(check_url, headers=headers, timeout=30)

            if ann_response.status_code == 200:
                job_annotations = ann_response.json()
                for ann in job_annotations:
                    annotations.append(
                        {
                            "job_name": job.get("name"),
                            "job_conclusion": job.get("conclusion"),
                            "level": ann.get("annotation_level"),
                            "message": ann.get("message"),
                            "path": ann.get("path"),
                            "start_line": ann.get("start_line"),
                            "end_line": ann.get("end_line"),
                            "title": ann.get("title"),
                        }
                    )

        logger.info(
            "github_workflow_annotations_fetched",
            repo=repo,
            run_id=run_id,
            count=len(annotations),
        )

        return annotations

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="get_failed_workflow_annotations")
        return _github_config_required_response("get_failed_workflow_annotations")

    except Exception as e:
        logger.error(
            "github_get_annotations_failed", error=str(e), repo=repo, run_id=run_id
        )
        return json.dumps({"error": str(e), "repo": repo, "run_id": run_id})


# ============================================================================
# Check Runs / CI Status
# ============================================================================


@function_tool
def get_check_runs(
    repo: str, ref: str, check_name: str | None = None, max_results: int = 50
) -> list[dict[str, Any]] | str:
    """
    Get check runs (CI status) for a commit or branch.

    Use this to see which CI checks passed or failed for a PR or commit.
    This shows GitHub Actions checks, as well as external CI integrations.

    Args:
        repo: Repository (format: "owner/repo")
        ref: Commit SHA or branch name
        check_name: Filter by check name (optional)
        max_results: Maximum check runs to return

    Returns:
        List of check runs with status and conclusion
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)

        # Get the commit
        commit = repository.get_commit(ref)

        # Get check runs
        check_runs = commit.get_check_runs()

        run_list = []
        for i, run in enumerate(check_runs):
            if i >= max_results:
                break

            if check_name and run.name != check_name:
                continue

            run_list.append(
                {
                    "id": run.id,
                    "name": run.name,
                    "status": run.status,
                    "conclusion": run.conclusion,
                    "started_at": str(run.started_at) if run.started_at else None,
                    "completed_at": str(run.completed_at) if run.completed_at else None,
                    "url": run.html_url,
                    "app": run.app.name if run.app else None,
                }
            )

        logger.info("github_check_runs_listed", repo=repo, ref=ref, count=len(run_list))
        return run_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="get_check_runs")
        return _github_config_required_response("get_check_runs")

    except Exception as e:
        logger.error("github_get_check_runs_failed", error=str(e), repo=repo, ref=ref)
        return json.dumps({"error": str(e), "repo": repo, "ref": ref})


@function_tool
def get_combined_status(repo: str, ref: str) -> dict[str, Any] | str:
    """
    Get combined commit status (legacy status API + check runs summary).

    This provides a quick overview of whether a commit/branch is passing
    all checks, without needing to look at individual check runs.

    Args:
        repo: Repository (format: "owner/repo")
        ref: Commit SHA or branch name

    Returns:
        Combined status with overall state and individual statuses
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        commit = repository.get_commit(ref)

        # Get combined status (legacy API)
        combined = commit.get_combined_status()

        statuses = []
        for status in combined.statuses:
            statuses.append(
                {
                    "context": status.context,
                    "state": status.state,
                    "description": status.description,
                    "target_url": status.target_url,
                }
            )

        logger.info("github_combined_status_fetched", repo=repo, ref=ref)

        return {
            "state": combined.state,  # success, pending, failure
            "total_count": combined.total_count,
            "statuses": statuses,
            "sha": combined.sha,
            "url": combined.url,
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="get_combined_status")
        return _github_config_required_response("get_combined_status")

    except Exception as e:
        logger.error(
            "github_get_combined_status_failed", error=str(e), repo=repo, ref=ref
        )
        return json.dumps({"error": str(e), "repo": repo, "ref": ref})


# ============================================================================
# Deployments
# ============================================================================


@function_tool
def list_deployments(
    repo: str,
    environment: str | None = None,
    ref: str | None = None,
    max_results: int = 20,
) -> list[dict[str, Any]] | str:
    """
    List deployments for a repository.

    Useful for correlating incidents with deployment events.
    Shows when code was deployed to different environments.

    Args:
        repo: Repository (format: "owner/repo")
        environment: Filter by environment name (e.g., "production", "staging")
        ref: Filter by ref (branch, tag, SHA)
        max_results: Maximum deployments to return

    Returns:
        List of deployments with status and environment info
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)

        kwargs = {}
        if environment:
            kwargs["environment"] = environment
        if ref:
            kwargs["ref"] = ref

        deployments = repository.get_deployments(**kwargs)

        deployment_list = []
        for i, dep in enumerate(deployments):
            if i >= max_results:
                break

            # Get latest status for this deployment
            statuses = list(dep.get_statuses())
            latest_status = statuses[0] if statuses else None

            deployment_list.append(
                {
                    "id": dep.id,
                    "ref": dep.ref,
                    "environment": dep.environment,
                    "description": dep.description,
                    "created_at": str(dep.created_at),
                    "creator": dep.creator.login if dep.creator else None,
                    "sha": dep.sha,
                    "status": latest_status.state if latest_status else "unknown",
                    "status_description": (
                        latest_status.description if latest_status else None
                    ),
                }
            )

        logger.info("github_deployments_listed", repo=repo, count=len(deployment_list))
        return deployment_list

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="list_deployments")
        return _github_config_required_response("list_deployments")

    except Exception as e:
        logger.error("github_list_deployments_failed", error=str(e), repo=repo)
        return json.dumps({"error": str(e), "repo": repo})


@function_tool
def get_deployment_status(repo: str, deployment_id: int) -> dict[str, Any] | str:
    """
    Get detailed status history for a specific deployment.

    Shows all status updates for a deployment, useful for understanding
    deployment progress and any failures.

    Args:
        repo: Repository (format: "owner/repo")
        deployment_id: Deployment ID

    Returns:
        Deployment details with full status history
    """
    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        deployment = repository.get_deployment(deployment_id)

        statuses = []
        for status in deployment.get_statuses():
            statuses.append(
                {
                    "id": status.id,
                    "state": status.state,
                    "description": status.description,
                    "environment": status.environment,
                    "created_at": str(status.created_at),
                    "creator": status.creator.login if status.creator else None,
                    "log_url": status.log_url,
                    "environment_url": status.environment_url,
                }
            )

        logger.info(
            "github_deployment_status_fetched",
            repo=repo,
            deployment_id=deployment_id,
        )

        return {
            "id": deployment.id,
            "ref": deployment.ref,
            "sha": deployment.sha,
            "environment": deployment.environment,
            "description": deployment.description,
            "created_at": str(deployment.created_at),
            "creator": deployment.creator.login if deployment.creator else None,
            "statuses": statuses,
        }

    except IntegrationNotConfiguredError:
        logger.warning("github_not_configured", tool="get_deployment_status")
        return _github_config_required_response("get_deployment_status")

    except Exception as e:
        logger.error(
            "github_get_deployment_status_failed",
            error=str(e),
            repo=repo,
            deployment_id=deployment_id,
        )
        return json.dumps(
            {"error": str(e), "repo": repo, "deployment_id": deployment_id}
        )


# List of all GitHub tools for registration
GITHUB_TOOLS = [
    # Repository info
    get_repo_info,
    list_files,
    get_repo_tree,  # NEW: Full recursive tree structure
    read_github_file,
    search_github_code,
    github_list_contributors,
    # Commits
    github_list_commits,
    github_get_commit,
    github_compare_commits,
    github_search_commits_by_timerange,
    # Branches and tags
    list_branches,
    create_branch,
    github_list_tags,
    github_list_releases,
    # Pull requests
    list_pull_requests,
    github_get_pr,
    create_pull_request,
    merge_pull_request,
    github_get_pr_files,
    github_list_pr_commits,
    github_list_pr_reviews,
    github_create_pr_review,
    github_add_pr_comment,
    github_search_prs,
    # Issues
    list_issues,
    github_get_issue,
    github_create_issue,
    close_issue,
    github_list_issue_comments,
    github_add_issue_comment,
    github_search_issues,
    # GitHub Actions
    trigger_workflow,
    list_workflow_runs,
    get_workflow_run_jobs,  # NEW: Individual job statuses
    get_workflow_run_logs,  # NEW: Logs download URL
    get_failed_workflow_annotations,  # NEW: Error annotations
    # CI Status / Check Runs
    get_check_runs,  # NEW: CI check status for commits/PRs
    get_combined_status,  # NEW: Overall commit status
    # Deployments
    list_deployments,  # NEW: Deployment history
    get_deployment_status,  # NEW: Deployment details
]
