"""GitHub integration tools for deployment correlation and code investigation.

Provides comprehensive GitHub tools for:
- Repository information and file access
- Commit history and comparison (deployment correlation)
- Pull requests (reviews, files, commits)
- Issues and comments
- Branches, tags, releases
- GitHub Actions workflows

Essential for correlating incidents with deployments.
"""

import base64
import json
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from ..utils.config import get_env


class GitHubConfigError(Exception):
    """Raised when GitHub is not configured."""

    def __init__(self, message: str):
        super().__init__(message)


def _get_github_config():
    """Get GitHub configuration from environment or config file."""
    token = get_env("GITHUB_TOKEN")

    if not token:
        raise GitHubConfigError(
            "GitHub not configured. Missing: GITHUB_TOKEN. "
            "Use save_credential tool to set it, or export as environment variable."
        )

    return {"token": token}


def _get_github_client():
    """Get GitHub client."""
    try:
        from github import Github

        config = _get_github_config()
        return Github(config["token"], timeout=30)

    except ImportError:
        raise GitHubConfigError(
            "PyGithub not installed. Install with: pip install PyGithub"
        )


def register_tools(mcp: FastMCP):
    """Register GitHub tools with the MCP server."""

    # =========================================================================
    # Repository Information
    # =========================================================================

    @mcp.tool()
    def github_get_repo_info(repo: str) -> str:
        """Get repository information.

        Args:
            repo: Repository (format: "owner/repo")

        Returns:
            JSON with repository info including name, description, URLs, stats
        """
        try:
            g = _get_github_client()
            r = g.get_repo(repo)

            return json.dumps(
                {
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
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo})

    @mcp.tool()
    def github_list_files(repo: str, path: str = "", ref: str | None = None) -> str:
        """List files in a repository directory.

        Args:
            repo: Repository (format: "owner/repo")
            path: Directory path (empty for root)
            ref: Branch/tag/commit (optional)

        Returns:
            JSON with list of files and directories
        """
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
                {"path": path, "file_count": len(file_list), "files": file_list},
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo, "path": path})

    @mcp.tool()
    def github_read_file(repo: str, file_path: str, ref: str = "main") -> str:
        """Read a file from GitHub repository.

        Args:
            repo: Repository (format: "owner/repo")
            file_path: Path to file in repo
            ref: Branch/tag/commit (default: "main")

        Returns:
            File contents as string, or JSON error
        """
        try:
            g = _get_github_client()
            repository = g.get_repo(repo)
            file_content = repository.get_contents(file_path, ref=ref)

            if isinstance(file_content, list):
                return json.dumps({"error": f"{file_path} is a directory"})

            content = base64.b64decode(file_content.content).decode("utf-8")
            return content

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo, "file": file_path})

    @mcp.tool()
    def github_search_code(
        query: str,
        org: str | None = None,
        repo: str | None = None,
        max_results: int = 10,
    ) -> str:
        """Search code across GitHub repositories.

        Args:
            query: Search query (supports GitHub code search syntax)
            org: Optional organization to limit search
            repo: Optional specific repo (format: "owner/repo")
            max_results: Maximum results to return (default: 10)

        Returns:
            JSON with list of code matches including file paths and URLs
        """
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
                {"query": query, "match_count": len(matches), "matches": matches},
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "query": query})

    # =========================================================================
    # Commits - Critical for deployment correlation
    # =========================================================================

    @mcp.tool()
    def github_list_commits(
        repo: str,
        branch: str | None = None,
        author: str | None = None,
        path: str | None = None,
        max_results: int = 10,
    ) -> str:
        """List recent commits from a GitHub repository.

        This is the simplest way to get recent commits - essential for
        deployment correlation during incident investigation.

        Args:
            repo: Repository (format: "owner/repo")
            branch: Branch name (optional, defaults to default branch)
            author: Filter by author username (optional)
            path: Filter by file path (optional)
            max_results: Maximum commits to return (default: 10)

        Returns:
            JSON with list of commits
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
                            str(commit.commit.author.date)
                            if commit.commit.author
                            else None
                        ),
                        "url": commit.html_url,
                    }
                )

            return json.dumps(
                {
                    "repo": repo,
                    "commit_count": len(commit_list),
                    "commits": commit_list,
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo})

    @mcp.tool()
    def github_get_commit(repo: str, sha: str) -> str:
        """Get detailed information about a specific commit.

        Args:
            repo: Repository (format: "owner/repo")
            sha: Commit SHA (full or short)

        Returns:
            JSON with commit details including files changed and stats
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

            return json.dumps(
                {
                    "sha": commit.sha,
                    "message": commit.commit.message,
                    "author": (
                        commit.commit.author.name if commit.commit.author else None
                    ),
                    "author_email": (
                        commit.commit.author.email if commit.commit.author else None
                    ),
                    "author_login": commit.author.login if commit.author else None,
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
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo, "sha": sha})

    @mcp.tool()
    def github_compare_commits(repo: str, base: str, head: str) -> str:
        """Compare two commits, branches, or tags.

        Essential for understanding what changed between deployments.

        Args:
            repo: Repository (format: "owner/repo")
            base: Base commit/branch/tag
            head: Head commit/branch/tag to compare

        Returns:
            JSON with comparison including commits between and files changed
        """
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
                    "status": comparison.status,
                    "ahead_by": comparison.ahead_by,
                    "behind_by": comparison.behind_by,
                    "total_commits": comparison.total_commits,
                    "commits": commits,
                    "files": files,
                    "url": comparison.html_url,
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps(
                {"error": str(e), "repo": repo, "base": base, "head": head}
            )

    @mcp.tool()
    def github_search_commits_by_timerange(
        repo: str,
        since: str,
        until: str | None = None,
        author: str | None = None,
        max_results: int = 50,
    ) -> str:
        """Search commits in a repository by time range.

        Critical for finding "what changed before this incident started?"

        Args:
            repo: Repository (format: "owner/repo")
            since: Start datetime (ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)
            until: End datetime (optional, ISO 8601 format)
            author: Filter by author username (optional)
            max_results: Maximum commits to return (default: 50)

        Returns:
            JSON with list of commits in the time range
        """
        try:
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
                    "repo": repo,
                    "since": since,
                    "until": until,
                    "commit_count": len(commit_list),
                    "commits": commit_list,
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo})

    # =========================================================================
    # Branches, Tags, Releases
    # =========================================================================

    @mcp.tool()
    def github_list_branches(repo: str, max_results: int = 30) -> str:
        """List branches in a repository.

        Args:
            repo: Repository (format: "owner/repo")
            max_results: Maximum branches to return (default: 30)

        Returns:
            JSON with list of branches
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

            return json.dumps(
                {
                    "repo": repo,
                    "branch_count": len(branch_list),
                    "branches": branch_list,
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo})

    @mcp.tool()
    def github_list_tags(repo: str, max_results: int = 30) -> str:
        """List tags in a repository.

        Useful for finding release versions for deployment correlation.

        Args:
            repo: Repository (format: "owner/repo")
            max_results: Maximum tags to return (default: 30)

        Returns:
            JSON with list of tags
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

            return json.dumps(
                {"repo": repo, "tag_count": len(tag_list), "tags": tag_list}, indent=2
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo})

    @mcp.tool()
    def github_list_releases(
        repo: str, include_prereleases: bool = True, max_results: int = 10
    ) -> str:
        """List releases in a repository.

        Args:
            repo: Repository (format: "owner/repo")
            include_prereleases: Include pre-release versions (default: True)
            max_results: Maximum releases to return (default: 10)

        Returns:
            JSON with list of releases
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

            return json.dumps(
                {
                    "repo": repo,
                    "release_count": len(release_list),
                    "releases": release_list,
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo})

    # =========================================================================
    # Pull Requests
    # =========================================================================

    @mcp.tool()
    def github_list_pull_requests(
        repo: str, state: str = "open", max_results: int = 10
    ) -> str:
        """List pull requests in a repository.

        Args:
            repo: Repository (format: "owner/repo")
            state: PR state - "open", "closed", "all" (default: "open")
            max_results: Maximum PRs to return (default: 10)

        Returns:
            JSON with list of pull requests
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

            return json.dumps(
                {"repo": repo, "pr_count": len(pr_list), "pull_requests": pr_list},
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo})

    @mcp.tool()
    def github_get_pr(repo: str, pr_number: int) -> str:
        """Get details of a specific pull request.

        Args:
            repo: Repository (format: "owner/repo")
            pr_number: PR number

        Returns:
            JSON with pull request details
        """
        try:
            g = _get_github_client()
            repository = g.get_repo(repo)
            pr = repository.get_pull(pr_number)

            return json.dumps(
                {
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
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})

    @mcp.tool()
    def github_get_pr_files(repo: str, pr_number: int, max_results: int = 100) -> str:
        """Get files changed in a pull request.

        Args:
            repo: Repository (format: "owner/repo")
            pr_number: Pull request number
            max_results: Maximum files to return (default: 100)

        Returns:
            JSON with list of files and change stats
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

            return json.dumps(
                {
                    "repo": repo,
                    "pr_number": pr_number,
                    "file_count": len(file_list),
                    "files": file_list,
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})

    @mcp.tool()
    def github_list_pr_commits(
        repo: str, pr_number: int, max_results: int = 100
    ) -> str:
        """List all commits in a pull request.

        Args:
            repo: Repository (format: "owner/repo")
            pr_number: Pull request number
            max_results: Maximum commits to return (default: 100)

        Returns:
            JSON with list of commits in the PR
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
                        "date": (
                            str(commit.commit.author.date)
                            if commit.commit.author
                            else None
                        ),
                        "url": commit.html_url,
                    }
                )

            return json.dumps(
                {
                    "repo": repo,
                    "pr_number": pr_number,
                    "commit_count": len(commit_list),
                    "commits": commit_list,
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})

    @mcp.tool()
    def github_list_pr_reviews(repo: str, pr_number: int) -> str:
        """List reviews on a pull request.

        Args:
            repo: Repository (format: "owner/repo")
            pr_number: Pull request number

        Returns:
            JSON with list of reviews
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

            return json.dumps(
                {
                    "repo": repo,
                    "pr_number": pr_number,
                    "review_count": len(review_list),
                    "reviews": review_list,
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo, "pr_number": pr_number})

    @mcp.tool()
    def github_search_prs(
        query: str,
        repo: str | None = None,
        state: str | None = None,
        max_results: int = 20,
    ) -> str:
        """Search pull requests across GitHub repositories.

        Args:
            query: Search query (GitHub search syntax)
            repo: Limit to specific repo (format: "owner/repo")
            state: Filter by state - "open", "closed", "merged"
            max_results: Maximum results to return (default: 20)

        Returns:
            JSON with list of matching pull requests
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

            return json.dumps(
                {"query": query, "pr_count": len(pr_list), "pull_requests": pr_list},
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "query": query})

    # =========================================================================
    # Issues
    # =========================================================================

    @mcp.tool()
    def github_list_issues(
        repo: str,
        state: str = "open",
        labels: str | None = None,
        max_results: int = 20,
    ) -> str:
        """List issues in a repository.

        Args:
            repo: Repository (format: "owner/repo")
            state: Issue state - "open", "closed", "all" (default: "open")
            labels: Comma-separated label names to filter by
            max_results: Maximum issues to return (default: 20)

        Returns:
            JSON with list of issues
        """
        try:
            g = _get_github_client()
            repository = g.get_repo(repo)

            label_list = labels.split(",") if labels else []
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
                {"repo": repo, "issue_count": len(issue_list), "issues": issue_list},
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo})

    @mcp.tool()
    def github_get_issue(repo: str, issue_number: int) -> str:
        """Get detailed information about a specific issue.

        Args:
            repo: Repository (format: "owner/repo")
            issue_number: Issue number

        Returns:
            JSON with issue details
        """
        try:
            g = _get_github_client()
            repository = g.get_repo(repo)
            issue = repository.get_issue(issue_number)

            return json.dumps(
                {
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
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps(
                {"error": str(e), "repo": repo, "issue_number": issue_number}
            )

    @mcp.tool()
    def github_list_issue_comments(
        repo: str, issue_number: int, max_results: int = 50
    ) -> str:
        """List comments on an issue.

        Args:
            repo: Repository (format: "owner/repo")
            issue_number: Issue number
            max_results: Maximum comments to return (default: 50)

        Returns:
            JSON with list of comments
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

            return json.dumps(
                {
                    "repo": repo,
                    "issue_number": issue_number,
                    "comment_count": len(comment_list),
                    "comments": comment_list,
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps(
                {"error": str(e), "repo": repo, "issue_number": issue_number}
            )

    @mcp.tool()
    def github_search_issues(
        query: str,
        repo: str | None = None,
        state: str | None = None,
        max_results: int = 20,
    ) -> str:
        """Search issues across GitHub repositories.

        Args:
            query: Search query (GitHub issue search syntax)
            repo: Limit to specific repo (format: "owner/repo")
            state: Filter by state - "open", "closed"
            max_results: Maximum results to return (default: 20)

        Returns:
            JSON with list of matching issues
        """
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
                {"query": query, "issue_count": len(issue_list), "issues": issue_list},
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "query": query})

    # =========================================================================
    # GitHub Actions
    # =========================================================================

    @mcp.tool()
    def github_list_workflow_runs(
        repo: str,
        workflow_id: str | None = None,
        status: str | None = None,
        max_results: int = 10,
    ) -> str:
        """List recent workflow runs.

        Useful for correlating incidents with CI/CD pipeline status.

        Args:
            repo: Repository (format: "owner/repo")
            workflow_id: Filter by workflow filename (e.g., "ci.yml")
            status: Filter by status - "queued", "in_progress", "completed"
            max_results: Maximum runs to return (default: 10)

        Returns:
            JSON with list of workflow runs
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

            return json.dumps(
                {"repo": repo, "run_count": len(run_list), "workflow_runs": run_list},
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo})

    @mcp.tool()
    def github_list_contributors(repo: str, max_results: int = 30) -> str:
        """List contributors to a repository.

        Args:
            repo: Repository (format: "owner/repo")
            max_results: Maximum contributors to return (default: 30)

        Returns:
            JSON with list of contributors and contribution counts
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
                    }
                )

            return json.dumps(
                {
                    "repo": repo,
                    "contributor_count": len(contributor_list),
                    "contributors": contributor_list,
                },
                indent=2,
            )

        except GitHubConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "repo": repo})
