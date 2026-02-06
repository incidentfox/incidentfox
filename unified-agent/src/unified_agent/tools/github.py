"""
GitHub integration tools.

Provides GitHub API access for repositories, PRs, issues, commits, and actions.
"""

import base64
import json
import logging
import os
from typing import Optional

from ..core.agent import function_tool
from . import register_tool

logger = logging.getLogger(__name__)


def _get_github_client():
    """Get GitHub client."""
    try:
        from github import Github
    except ImportError:
        raise RuntimeError("PyGithub not installed: pip install PyGithub")

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable not set")

    return Github(token, timeout=30)


# =============================================================================
# Repository Tools
# =============================================================================


@function_tool
def github_get_repo_info(repo: str) -> str:
    """
    Get repository information.

    Args:
        repo: Repository (format: "owner/repo")

    Returns:
        JSON with repo details
    """
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})

    logger.info(f"github_get_repo_info: repo={repo}")

    try:
        g = _get_github_client()
        r = g.get_repo(repo)

        return json.dumps(
            {
                "ok": True,
                "name": r.name,
                "full_name": r.full_name,
                "description": r.description,
                "private": r.private,
                "default_branch": r.default_branch,
                "clone_url": r.clone_url,
                "html_url": r.html_url,
                "language": r.language,
                "stars": r.stargazers_count,
                "forks": r.forks_count,
                "open_issues": r.open_issues_count,
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set GITHUB_TOKEN"})
    except Exception as e:
        logger.error(f"github_get_repo_info error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_list_files(repo: str, path: str = "", ref: str = "") -> str:
    """
    List files in a repository directory.

    Args:
        repo: Repository (format: "owner/repo")
        path: Directory path (empty for root)
        ref: Branch/tag/commit

    Returns:
        JSON with files list
    """
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})

    logger.info(f"github_list_files: repo={repo}, path={path}")

    try:
        g = _get_github_client()
        repository = g.get_repo(repo)

        kwargs = {}
        if ref:
            kwargs["ref"] = ref

        contents = repository.get_contents(path or "", **kwargs)

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

        return json.dumps(
            {
                "ok": True,
                "files": file_list,
                "count": len(file_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_files error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_read_file(repo: str, file_path: str, ref: str = "main") -> str:
    """
    Read a file from GitHub repository.

    Args:
        repo: Repository (format: "owner/repo")
        file_path: Path to file in repo
        ref: Branch/tag/commit (default: "main")

    Returns:
        File contents
    """
    if not repo or not file_path:
        return json.dumps({"ok": False, "error": "repo and file_path are required"})

    logger.info(f"github_read_file: repo={repo}, file={file_path}")

    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        file_content = repository.get_contents(file_path, ref=ref)

        if isinstance(file_content, list):
            return json.dumps({"ok": False, "error": f"{file_path} is a directory"})

        content = base64.b64decode(file_content.content).decode("utf-8")
        return content

    except Exception as e:
        logger.error(f"github_read_file error: {e}")
        return json.dumps(
            {"ok": False, "error": str(e), "repo": repo, "file": file_path}
        )


@function_tool
def github_search_code(
    query: str,
    org: str = "",
    repo: str = "",
    max_results: int = 10,
) -> str:
    """
    Search code across GitHub repositories.

    Args:
        query: Search query (GitHub code search syntax)
        org: Optional organization to limit search
        repo: Optional specific repo (format: "owner/repo")
        max_results: Maximum results to return

    Returns:
        JSON with code matches
    """
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    logger.info(f"github_search_code: query={query}")

    try:
        g = _get_github_client()

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

        return json.dumps(
            {
                "ok": True,
                "matches": matches,
                "count": len(matches),
            }
        )

    except Exception as e:
        logger.error(f"github_search_code error: {e}")
        return json.dumps({"ok": False, "error": str(e), "query": query})


# =============================================================================
# Commits Tools
# =============================================================================


@function_tool
def github_list_commits(
    repo: str,
    branch: str = "",
    author: str = "",
    path: str = "",
    max_results: int = 10,
) -> str:
    """
    List recent commits from a GitHub repository.

    Args:
        repo: Repository (format: "owner/repo")
        branch: Branch name (optional)
        author: Filter by author username (optional)
        path: Filter by file path (optional)
        max_results: Maximum commits to return

    Returns:
        JSON with commits list
    """
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})

    logger.info(f"github_list_commits: repo={repo}")

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

        return json.dumps(
            {
                "ok": True,
                "commits": commit_list,
                "count": len(commit_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_commits error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_get_commit(repo: str, sha: str) -> str:
    """
    Get detailed information about a specific commit.

    Args:
        repo: Repository (format: "owner/repo")
        sha: Commit SHA

    Returns:
        JSON with commit details
    """
    if not repo or not sha:
        return json.dumps({"ok": False, "error": "repo and sha are required"})

    logger.info(f"github_get_commit: repo={repo}, sha={sha[:7]}")

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

        return json.dumps(
            {
                "ok": True,
                "sha": commit.sha,
                "message": commit.commit.message,
                "author": commit.commit.author.name if commit.commit.author else None,
                "author_email": (
                    commit.commit.author.email if commit.commit.author else None
                ),
                "date": (
                    str(commit.commit.author.date) if commit.commit.author else None
                ),
                "url": commit.html_url,
                "stats": {
                    "additions": commit.stats.additions,
                    "deletions": commit.stats.deletions,
                    "total": commit.stats.total,
                },
                "files_changed": files_changed,
                "parents": [p.sha for p in commit.parents],
            }
        )

    except Exception as e:
        logger.error(f"github_get_commit error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo, "sha": sha})


@function_tool
def github_compare_commits(repo: str, base: str, head: str) -> str:
    """
    Compare two commits, branches, or tags.

    Args:
        repo: Repository (format: "owner/repo")
        base: Base commit/branch/tag
        head: Head commit/branch/tag to compare

    Returns:
        JSON with comparison details
    """
    if not repo or not base or not head:
        return json.dumps({"ok": False, "error": "repo, base, and head are required"})

    logger.info(f"github_compare_commits: repo={repo}, base={base}, head={head}")

    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        comparison = repository.compare(base, head)

        commits = []
        for c in comparison.commits[:50]:
            commits.append(
                {
                    "sha": c.sha,
                    "message": c.commit.message.split("\n")[0],
                    "author": c.commit.author.name if c.commit.author else None,
                    "date": str(c.commit.author.date) if c.commit.author else None,
                }
            )

        files = []
        for f in comparison.files[:100]:
            files.append(
                {
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                }
            )

        return json.dumps(
            {
                "ok": True,
                "status": comparison.status,
                "ahead_by": comparison.ahead_by,
                "behind_by": comparison.behind_by,
                "total_commits": comparison.total_commits,
                "commits": commits,
                "files": files,
                "url": comparison.html_url,
            }
        )

    except Exception as e:
        logger.error(f"github_compare_commits error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_search_commits_by_timerange(
    repo: str,
    since: str,
    until: str = "",
    author: str = "",
    max_results: int = 50,
) -> str:
    """
    Search commits in a repository by time range.

    Args:
        repo: Repository (format: "owner/repo")
        since: Start datetime (ISO 8601 format)
        until: End datetime (optional)
        author: Filter by author username
        max_results: Maximum commits to return

    Returns:
        JSON with commits list
    """
    if not repo or not since:
        return json.dumps({"ok": False, "error": "repo and since are required"})

    logger.info(f"github_search_commits_by_timerange: repo={repo}, since={since}")

    try:
        from datetime import datetime

        g = _get_github_client()
        repository = g.get_repo(repo)

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

        return json.dumps(
            {
                "ok": True,
                "commits": commit_list,
                "count": len(commit_list),
            }
        )

    except Exception as e:
        logger.error(f"github_search_commits_by_timerange error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


# =============================================================================
# Branches and Tags
# =============================================================================


@function_tool
def github_list_branches(repo: str, max_results: int = 30) -> str:
    """
    List branches in a repository.

    Args:
        repo: Repository (format: "owner/repo")
        max_results: Maximum branches to return

    Returns:
        JSON with branches list
    """
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})

    logger.info(f"github_list_branches: repo={repo}")

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

        return json.dumps(
            {
                "ok": True,
                "branches": branch_list,
                "count": len(branch_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_branches error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_list_tags(repo: str, max_results: int = 30) -> str:
    """
    List tags in a repository.

    Args:
        repo: Repository (format: "owner/repo")
        max_results: Maximum tags to return

    Returns:
        JSON with tags list
    """
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})

    logger.info(f"github_list_tags: repo={repo}")

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

        return json.dumps(
            {
                "ok": True,
                "tags": tag_list,
                "count": len(tag_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_tags error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_list_releases(
    repo: str,
    include_prereleases: bool = True,
    max_results: int = 10,
) -> str:
    """
    List releases in a repository.

    Args:
        repo: Repository (format: "owner/repo")
        include_prereleases: Include pre-release versions
        max_results: Maximum releases to return

    Returns:
        JSON with releases list
    """
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})

    logger.info(f"github_list_releases: repo={repo}")

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
                    "url": release.html_url,
                }
            )

        return json.dumps(
            {
                "ok": True,
                "releases": release_list,
                "count": len(release_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_releases error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


# =============================================================================
# Pull Requests
# =============================================================================


@function_tool
def github_list_pull_requests(
    repo: str,
    state: str = "open",
    max_results: int = 10,
) -> str:
    """
    List pull requests in a repository.

    Args:
        repo: Repository (format: "owner/repo")
        state: PR state (open, closed, all)
        max_results: Maximum PRs to return

    Returns:
        JSON with PRs list
    """
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})

    logger.info(f"github_list_pull_requests: repo={repo}, state={state}")

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

        return json.dumps(
            {
                "ok": True,
                "pull_requests": pr_list,
                "count": len(pr_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_pull_requests error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_get_pr(repo: str, pr_number: int) -> str:
    """
    Get details of a specific pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: PR number

    Returns:
        JSON with PR details
    """
    if not repo or not pr_number:
        return json.dumps({"ok": False, "error": "repo and pr_number are required"})

    logger.info(f"github_get_pr: repo={repo}, pr_number={pr_number}")

    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)

        return json.dumps(
            {
                "ok": True,
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
        )

    except Exception as e:
        logger.error(f"github_get_pr error: {e}")
        return json.dumps(
            {"ok": False, "error": str(e), "repo": repo, "pr_number": pr_number}
        )


@function_tool
def github_get_pr_files(repo: str, pr_number: int, max_results: int = 100) -> str:
    """
    Get files changed in a pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: Pull request number
        max_results: Maximum files to return

    Returns:
        JSON with files list
    """
    if not repo or not pr_number:
        return json.dumps({"ok": False, "error": "repo and pr_number are required"})

    logger.info(f"github_get_pr_files: repo={repo}, pr_number={pr_number}")

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

        return json.dumps(
            {
                "ok": True,
                "files": file_list,
                "count": len(file_list),
            }
        )

    except Exception as e:
        logger.error(f"github_get_pr_files error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_list_pr_commits(repo: str, pr_number: int, max_results: int = 100) -> str:
    """
    List all commits in a pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: Pull request number
        max_results: Maximum commits to return

    Returns:
        JSON with commits list
    """
    if not repo or not pr_number:
        return json.dumps({"ok": False, "error": "repo and pr_number are required"})

    logger.info(f"github_list_pr_commits: repo={repo}, pr_number={pr_number}")

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
                    "date": (
                        str(commit.commit.author.date) if commit.commit.author else None
                    ),
                    "url": commit.html_url,
                }
            )

        return json.dumps(
            {
                "ok": True,
                "commits": commit_list,
                "count": len(commit_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_pr_commits error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_list_pr_reviews(repo: str, pr_number: int) -> str:
    """
    List reviews on a pull request.

    Args:
        repo: Repository (format: "owner/repo")
        pr_number: Pull request number

    Returns:
        JSON with reviews list
    """
    if not repo or not pr_number:
        return json.dumps({"ok": False, "error": "repo and pr_number are required"})

    logger.info(f"github_list_pr_reviews: repo={repo}, pr_number={pr_number}")

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

        return json.dumps(
            {
                "ok": True,
                "reviews": review_list,
                "count": len(review_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_pr_reviews error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_search_prs(
    query: str,
    repo: str = "",
    state: str = "",
    max_results: int = 20,
) -> str:
    """
    Search pull requests across GitHub.

    Args:
        query: Search query (GitHub search syntax)
        repo: Limit to specific repo
        state: Filter by state (open, closed, merged)
        max_results: Maximum results to return

    Returns:
        JSON with PRs list
    """
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    logger.info(f"github_search_prs: query={query}")

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

        return json.dumps(
            {
                "ok": True,
                "pull_requests": pr_list,
                "count": len(pr_list),
            }
        )

    except Exception as e:
        logger.error(f"github_search_prs error: {e}")
        return json.dumps({"ok": False, "error": str(e), "query": query})


# =============================================================================
# Issues
# =============================================================================


@function_tool
def github_list_issues(
    repo: str,
    state: str = "open",
    labels: str = "",
    max_results: int = 20,
) -> str:
    """
    List issues in a repository.

    Args:
        repo: Repository (format: "owner/repo")
        state: Issue state (open, closed, all)
        labels: Comma-separated label names
        max_results: Maximum issues to return

    Returns:
        JSON with issues list
    """
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})

    logger.info(f"github_list_issues: repo={repo}, state={state}")

    try:
        g = _get_github_client()
        repository = g.get_repo(repo)

        label_list = [l.strip() for l in labels.split(",")] if labels else []
        issues = repository.get_issues(state=state, labels=label_list)

        issue_list = []
        for i, issue in enumerate(issues):
            if i >= max_results:
                break
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

        return json.dumps(
            {
                "ok": True,
                "issues": issue_list,
                "count": len(issue_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_issues error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_get_issue(repo: str, issue_number: int) -> str:
    """
    Get detailed information about a specific issue.

    Args:
        repo: Repository (format: "owner/repo")
        issue_number: Issue number

    Returns:
        JSON with issue details
    """
    if not repo or not issue_number:
        return json.dumps({"ok": False, "error": "repo and issue_number are required"})

    logger.info(f"github_get_issue: repo={repo}, issue_number={issue_number}")

    try:
        g = _get_github_client()
        repository = g.get_repo(repo)
        issue = repository.get_issue(issue_number)

        return json.dumps(
            {
                "ok": True,
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
        )

    except Exception as e:
        logger.error(f"github_get_issue error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_list_issue_comments(
    repo: str,
    issue_number: int,
    max_results: int = 50,
) -> str:
    """
    List comments on an issue.

    Args:
        repo: Repository (format: "owner/repo")
        issue_number: Issue number
        max_results: Maximum comments to return

    Returns:
        JSON with comments list
    """
    if not repo or not issue_number:
        return json.dumps({"ok": False, "error": "repo and issue_number are required"})

    logger.info(f"github_list_issue_comments: repo={repo}, issue={issue_number}")

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
                    "url": comment.html_url,
                }
            )

        return json.dumps(
            {
                "ok": True,
                "comments": comment_list,
                "count": len(comment_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_issue_comments error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_search_issues(
    query: str,
    repo: str = "",
    state: str = "",
    max_results: int = 20,
) -> str:
    """
    Search issues across GitHub.

    Args:
        query: Search query (GitHub issue search syntax)
        repo: Limit to specific repo
        state: Filter by state (open, closed)
        max_results: Maximum results to return

    Returns:
        JSON with issues list
    """
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    logger.info(f"github_search_issues: query={query}")

    try:
        g = _get_github_client()

        search_query = query
        if repo:
            search_query += f" repo:{repo}"
        if state:
            search_query += f" state:{state}"
        search_query += " is:issue"

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

        return json.dumps(
            {
                "ok": True,
                "issues": issue_list,
                "count": len(issue_list),
            }
        )

    except Exception as e:
        logger.error(f"github_search_issues error: {e}")
        return json.dumps({"ok": False, "error": str(e), "query": query})


# =============================================================================
# Workflow Runs (GitHub Actions)
# =============================================================================


@function_tool
def github_list_workflow_runs(
    repo: str,
    workflow_id: str = "",
    status: str = "",
    max_results: int = 10,
) -> str:
    """
    List recent workflow runs.

    Args:
        repo: Repository (format: "owner/repo")
        workflow_id: Filter by workflow
        status: Filter by status (queued, in_progress, completed)
        max_results: Maximum runs to return

    Returns:
        JSON with workflow runs list
    """
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})

    logger.info(f"github_list_workflow_runs: repo={repo}")

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

        return json.dumps(
            {
                "ok": True,
                "workflow_runs": run_list,
                "count": len(run_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_workflow_runs error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


@function_tool
def github_list_contributors(repo: str, max_results: int = 30) -> str:
    """
    List contributors to a repository.

    Args:
        repo: Repository (format: "owner/repo")
        max_results: Maximum contributors to return

    Returns:
        JSON with contributors list
    """
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})

    logger.info(f"github_list_contributors: repo={repo}")

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
                }
            )

        return json.dumps(
            {
                "ok": True,
                "contributors": contributor_list,
                "count": len(contributor_list),
            }
        )

    except Exception as e:
        logger.error(f"github_list_contributors error: {e}")
        return json.dumps({"ok": False, "error": str(e), "repo": repo})


# Register tools
register_tool("github_get_repo_info", github_get_repo_info)
register_tool("github_list_files", github_list_files)
register_tool("github_read_file", github_read_file)
register_tool("github_search_code", github_search_code)
register_tool("github_list_commits", github_list_commits)
register_tool("github_get_commit", github_get_commit)
register_tool("github_compare_commits", github_compare_commits)
register_tool("github_search_commits_by_timerange", github_search_commits_by_timerange)
register_tool("github_list_branches", github_list_branches)
register_tool("github_list_tags", github_list_tags)
register_tool("github_list_releases", github_list_releases)
register_tool("github_list_pull_requests", github_list_pull_requests)
register_tool("github_get_pr", github_get_pr)
register_tool("github_get_pr_files", github_get_pr_files)
register_tool("github_list_pr_commits", github_list_pr_commits)
register_tool("github_list_pr_reviews", github_list_pr_reviews)
register_tool("github_search_prs", github_search_prs)
register_tool("github_list_issues", github_list_issues)
register_tool("github_get_issue", github_get_issue)
register_tool("github_list_issue_comments", github_list_issue_comments)
register_tool("github_search_issues", github_search_issues)
register_tool("github_list_workflow_runs", github_list_workflow_runs)
register_tool("github_list_contributors", github_list_contributors)
