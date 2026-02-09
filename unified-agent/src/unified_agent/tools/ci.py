"""CI/CD tools for GitHub Actions integration, failure analysis, and auto-fixes.

Ported and enhanced from incidentfox-bot for integration with the multi-agent system.
"""

import contextvars
import hashlib
import hmac
import os
import zipfile
from io import BytesIO
from typing import Any

import logging

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)

# Context variable for GitHub installation ID
# Set this before running the agent to make it available to all tool calls
_github_installation_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "github_installation_id", default=None
)


@function_tool
def set_github_installation_id(installation_id: int) -> contextvars.Token:
    """Set the GitHub installation ID for the current context.

    Use this before running the CI agent to make installation_id available to tools.
    Returns a token that can be used to reset the value.
    """
    return _github_installation_id.set(installation_id)


@function_tool
def get_github_installation_id() -> int | None:
    """Get the GitHub installation ID from context, or from env var fallback."""
    ctx_id = _github_installation_id.get()
    if ctx_id:
        return ctx_id
    # Fallback to environment variable
    env_id = os.getenv("GITHUB_INSTALLATION_ID")
    return int(env_id) if env_id else None


def _sanitize_ref(ref: str | None) -> str | None:
    """Sanitize branch/ref name to remove any garbage characters.

    Sometimes LLMs output malformed JSON that appends garbage to parameter values.
    This function cleans up common issues.
    """
    if not ref:
        return ref

    # Remove any JSON-like garbage that might be appended
    # Valid git refs only contain: alphanumeric, /, -, _, .
    import re

    # Match valid git ref pattern and stop at first invalid character
    match = re.match(r"^[a-zA-Z0-9/_.\-]+", ref)
    if match:
        cleaned = match.group(0)
        if cleaned != ref:
            logger.warning("ref_sanitized", original=ref[:100], cleaned=cleaned)
        return cleaned

    logger.warning("ref_invalid", ref=ref[:100])
    return None  # Invalid ref, use default branch


# ============================================================================
# GitHub App Authentication
# ============================================================================


def _get_github_app_client(installation_id: int):
    """Get GitHub client authenticated as a GitHub App installation."""
    try:
        from github import Github, GithubIntegration

        app_id = os.getenv("GITHUB_APP_ID")
        # Support both env var names for private key
        private_key = os.getenv("GITHUB_APP_PRIVATE_KEY") or os.getenv(
            "GITHUB_PRIVATE_KEY_B64"
        )

        if not app_id or not private_key:
            raise ValueError(
                "GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY (or GITHUB_PRIVATE_KEY_B64) must be set"
            )

        # Handle private key formatting (may be base64 encoded or raw)
        if not private_key.startswith("-----BEGIN"):
            import base64

            try:
                # Try utf-8 first, then latin-1 as fallback
                decoded = base64.b64decode(private_key)
                try:
                    private_key = decoded.decode("utf-8")
                except UnicodeDecodeError:
                    private_key = decoded.decode("latin-1")
            except Exception as e:
                logger.warning("private_key_decode_failed", error=str(e))
                pass  # Assume it's already in correct format

        integration = GithubIntegration(int(app_id), private_key)
        auth = integration.get_access_token(installation_id)
        return Github(auth.token), auth.token

    except ImportError:
        return json.dumps({"ok": False, "error": "Tool execution error"})
            "github_app_client",
            "PyGithub not installed. Install with: poetry add PyGithub",
        )


def _get_github_token_client():
    """Get GitHub client using personal access token (fallback)."""
    try:
        from github import Github

        token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN not set")
        return Github(token), token
    except ImportError:
        return json.dumps({"ok": False, "error": "Tool execution error"})
            "github_token_client",
            "PyGithub not installed. Install with: poetry add PyGithub",
        )


def _get_github_client(installation_id: int | None = None):
    """Get appropriate GitHub client based on available credentials.

    If installation_id is not provided, tries to get it from context or env var.
    """
    # Use provided ID, or get from context/env
    effective_id = installation_id or get_github_installation_id()

    if effective_id and os.getenv("GITHUB_APP_ID"):
        return _get_github_app_client(effective_id)
    return _get_github_token_client()


# ============================================================================
# Workflow Log Tools
# ============================================================================


@function_tool
def download_workflow_run_logs(
    repo: str,
    run_id: int,
    installation_id: int | None = None,
    max_chars: int = 200_000,
) -> str:
    """
    Download GitHub Actions workflow run logs as text.

    Uses GitHub REST API: GET /repos/{owner}/{repo}/actions/runs/{run_id}/logs

    Args:
        repo: Repository in format "owner/repo"
        run_id: The workflow run ID
        installation_id: GitHub App installation ID (optional)
        max_chars: Maximum characters to return

    Returns:
        Concatenated log text from the workflow run
    """
    try:
        import httpx

        _, token = _get_github_client(installation_id)

        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/logs"

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }

        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            zip_bytes = resp.content

        # Parse the ZIP file
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            parts: list[str] = []
            names = [n for n in zf.namelist() if not n.endswith("/")]

            for name in names:
                # Focus on log files
                if not (name.endswith(".txt") or name.endswith(".log") or "/" in name):
                    continue
                try:
                    raw = zf.read(name)
                    text = raw.decode("utf-8", errors="replace")
                    parts.append(f"\n===== {name} =====\n{text}")
                except Exception:
                    continue

            if not parts:
                # Fallback: include first few files
                for name in names[:10]:
                    try:
                        raw = zf.read(name)
                        text = raw.decode("utf-8", errors="replace")
                        parts.append(f"\n===== {name} =====\n{text}")
                    except Exception:
                        continue

            combined = "\n".join(parts).strip()
            if len(combined) > max_chars:
                combined = combined[-max_chars:]

            logger.info(
                "workflow_logs_downloaded",
                repo=repo,
                run_id=run_id,
                size=len(combined),
            )
            return combined or "No logs found in workflow run."

    except Exception as e:
        logger.error(
            "download_workflow_logs_failed", repo=repo, run_id=run_id, error=str(e)
        )
        return json.dumps({"ok": False, "error": "download_workflow_run_logs"})


@function_tool
def get_workflow_run_info(
    repo: str,
    run_id: int,
    installation_id: int | None = None,
) -> str:
    """
    Get information about a specific workflow run.

    Args:
        repo: Repository in format "owner/repo"
        run_id: The workflow run ID
        installation_id: GitHub App installation ID (optional)

    Returns:
        Workflow run information
    """
    try:
        g, _ = _get_github_client(installation_id)
        repository = g.get_repo(repo)
        run = repository.get_workflow_run(run_id)

        # Get failed jobs info
        jobs = run.jobs()
        failed_jobs = []
        for job in jobs:
            if job.conclusion == "failure":
                failed_steps = []
                for step in job.steps:
                    if step.conclusion == "failure":
                        failed_steps.append(
                            {
                                "name": step.name,
                                "conclusion": step.conclusion,
                            }
                        )
                failed_jobs.append(
                    {
                        "name": job.name,
                        "conclusion": job.conclusion,
                        "failed_steps": failed_steps,
                    }
                )

        result = {
            "id": run.id,
            "name": run.name,
            "status": run.status,
            "conclusion": run.conclusion,
            "workflow_name": run.name,
            "head_branch": run.head_branch,
            "head_sha": run.head_sha,
            "event": run.event,
            "url": run.html_url,
            "created_at": str(run.created_at),
            "updated_at": str(run.updated_at),
            "run_attempt": run.run_attempt,
            "failed_jobs": failed_jobs,
        }

        # Get associated PR if exists
        if run.pull_requests:
            result["pull_requests"] = [
                {"number": pr.number, "url": pr.html_url} for pr in run.pull_requests
            ]

        logger.info("workflow_run_info_fetched", repo=repo, run_id=run_id)
        return result

    except Exception as e:
        logger.error(
            "get_workflow_run_info_failed", repo=repo, run_id=run_id, error=str(e)
        )
        return json.dumps({"ok": False, "error": "get_workflow_run_info"})


@function_tool
def list_failed_workflow_runs(
    repo: str,
    branch: str | None = None,
    workflow_name: str | None = None,
    installation_id: int | None = None,
    max_results: int = 10,
) -> str:
    """
    List recent failed workflow runs.

    Args:
        repo: Repository in format "owner/repo"
        branch: Filter by branch name
        workflow_name: Filter by workflow name/file
        installation_id: GitHub App installation ID (optional)
        max_results: Maximum results to return

    Returns:
        List of failed workflow runs
    """
    try:
        g, _ = _get_github_client(installation_id)
        repository = g.get_repo(repo)

        kwargs = {"status": "completed"}
        if branch:
            kwargs["branch"] = branch

        if workflow_name:
            workflow = repository.get_workflow(workflow_name)
            runs = workflow.get_runs(**kwargs)
        else:
            runs = repository.get_workflow_runs(**kwargs)

        failed_runs = []
        for run in runs:
            if run.conclusion == "failure":
                failed_runs.append(
                    {
                        "id": run.id,
                        "name": run.name,
                        "conclusion": run.conclusion,
                        "head_branch": run.head_branch,
                        "head_sha": run.head_sha[:8],
                        "url": run.html_url,
                        "created_at": str(run.created_at),
                    }
                )
                if len(failed_runs) >= max_results:
                    break

        logger.info("failed_workflow_runs_listed", repo=repo, count=len(failed_runs))
        return failed_runs

    except Exception as e:
        logger.error("list_failed_workflow_runs_failed", repo=repo, error=str(e))
        return json.dumps({"ok": False, "error": "list_failed_workflow_runs"})


# ============================================================================
# PR Comment Tools
# ============================================================================


@function_tool
def post_pr_comment(
    repo: str,
    pr_number: int,
    comment: str,
    installation_id: int | None = None,
) -> str:
    """
    Post a comment on a pull request.

    Args:
        repo: Repository in format "owner/repo"
        pr_number: Pull request number
        comment: Comment text (Markdown supported)
        installation_id: GitHub App installation ID (optional)

    Returns:
        Created comment info
    """
    try:
        g, _ = _get_github_client(installation_id)
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)
        comment_obj = pr.create_issue_comment(comment)

        logger.info(
            "pr_comment_posted",
            repo=repo,
            pr_number=pr_number,
            comment_id=comment_obj.id,
        )

        return {
            "ok": True,
            "comment_id": comment_obj.id,
            "url": comment_obj.html_url,
        }

    except Exception as e:
        logger.error(
            "post_pr_comment_failed", repo=repo, pr_number=pr_number, error=str(e)
        )
        return json.dumps({"ok": False, "error": "post_pr_comment"})


@function_tool
def get_pr_comments(
    repo: str,
    pr_number: int,
    installation_id: int | None = None,
) -> str:
    """
    Get all comments on a pull request.

    Args:
        repo: Repository in format "owner/repo"
        pr_number: Pull request number
        installation_id: GitHub App installation ID (optional)

    Returns:
        List of comments
    """
    try:
        g, _ = _get_github_client(installation_id)
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)
        comments = pr.get_issue_comments()

        comment_list = []
        for comment in comments:
            comment_list.append(
                {
                    "id": comment.id,
                    "author": comment.user.login,
                    "body": comment.body,
                    "created_at": str(comment.created_at),
                    "url": comment.html_url,
                }
            )

        logger.info(
            "pr_comments_fetched",
            repo=repo,
            pr_number=pr_number,
            count=len(comment_list),
        )
        return comment_list

    except Exception as e:
        logger.error(
            "get_pr_comments_failed", repo=repo, pr_number=pr_number, error=str(e)
        )
        return json.dumps({"ok": False, "error": "get_pr_comments"})


@function_tool
def update_or_create_pr_comment(
    repo: str,
    pr_number: int,
    comment: str,
    marker: str = "<!-- incidentfox-analysis -->",
    installation_id: int | None = None,
) -> str:
    """
    Update existing bot comment or create new one (sticky comment behavior).

    Args:
        repo: Repository in format "owner/repo"
        pr_number: Pull request number
        comment: Comment text (should include marker for updates)
        marker: HTML comment marker to identify bot comments
        installation_id: GitHub App installation ID (optional)

    Returns:
        Created or updated comment info
    """
    try:
        g, _ = _get_github_client(installation_id)
        repository = g.get_repo(repo)
        pr = repository.get_pull(pr_number)

        # Search for existing comment with marker
        existing_comment = None
        for c in pr.get_issue_comments():
            if marker in c.body:
                existing_comment = c
                break

        if existing_comment:
            existing_comment.edit(comment)
            logger.info(
                "pr_comment_updated",
                repo=repo,
                pr_number=pr_number,
                comment_id=existing_comment.id,
            )
            return {
                "ok": True,
                "action": "updated",
                "comment_id": existing_comment.id,
                "url": existing_comment.html_url,
            }
        else:
            comment_obj = pr.create_issue_comment(comment)
            logger.info(
                "pr_comment_created",
                repo=repo,
                pr_number=pr_number,
                comment_id=comment_obj.id,
            )
            return {
                "ok": True,
                "action": "created",
                "comment_id": comment_obj.id,
                "url": comment_obj.html_url,
            }

    except Exception as e:
        logger.error(
            "update_or_create_pr_comment_failed",
            repo=repo,
            pr_number=pr_number,
            error=str(e),
        )
        return json.dumps({"ok": False, "error": "update_or_create_pr_comment"})


# ============================================================================
# Code Fix and Commit Tools
# ============================================================================


@function_tool
def commit_file_changes(
    repo: str,
    branch: str,
    file_changes_json: str,
    commit_message: str,
    installation_id: int | None = None,
) -> str:
    """
    Commit file changes to a branch.

    Args:
        repo: Repository in format "owner/repo"
        branch: Branch name to commit to
        file_changes_json: JSON string of {file_path: new_content} e.g. '{"path/to/file.py": "content here"}'
        commit_message: Commit message
        installation_id: GitHub App installation ID (optional)

    Returns:
        JSON string with commit result including SHA
    """
    import json as json_module

    try:
        from github import InputGitTreeElement

        # Parse the JSON string
        file_changes: dict[str, str] = json_module.loads(file_changes_json)

        g, _ = _get_github_client(installation_id)
        repository = g.get_repo(repo)

        # Get current commit SHA
        ref = repository.get_git_ref(f"heads/{branch}")
        current_sha = ref.object.sha

        # Get base tree
        base_tree = repository.get_git_commit(current_sha).tree

        # Create new tree with file changes
        tree_elements = []
        for file_path, content in file_changes.items():
            blob = repository.create_git_blob(content, "utf-8")
            tree_elements.append(
                InputGitTreeElement(
                    path=file_path,
                    mode="100644",  # Regular file
                    type="blob",
                    sha=blob.sha,
                )
            )

        new_tree = repository.create_git_tree(tree_elements, base_tree)

        # Create commit
        new_commit = repository.create_git_commit(
            commit_message, new_tree, [repository.get_git_commit(current_sha)]
        )

        # Update reference
        ref.edit(new_commit.sha)

        logger.info(
            "files_committed",
            repo=repo,
            branch=branch,
            commit_sha=new_commit.sha,
            files_changed=list(file_changes.keys()),
        )

        return json_module.dumps(
            {
                "ok": True,
                "commit_sha": new_commit.sha,
                "commit_url": f"https://github.com/{repo}/commit/{new_commit.sha}",
                "files_changed": list(file_changes.keys()),
            }
        )

    except Exception as e:
        logger.error(
            "commit_file_changes_failed", repo=repo, branch=branch, error=str(e)
        )
        return json.dumps({"ok": False, "error": "commit_file_changes"})


@function_tool
def get_file_content(
    repo: str,
    file_path: str,
    ref: str = "main",
    installation_id: int | None = None,
) -> str:
    """
    Get file content from a repository.

    Args:
        repo: Repository in format "owner/repo"
        file_path: Path to the file
        ref: Branch/tag/commit reference
        installation_id: GitHub App installation ID (optional)

    Returns:
        File content as string
    """
    try:
        g, _ = _get_github_client(installation_id)
        repository = g.get_repo(repo)

        # Sanitize ref to remove any garbage characters from LLM output
        clean_ref = _sanitize_ref(ref)
        kwargs = {"ref": clean_ref} if clean_ref else {}

        file_content = repository.get_contents(file_path, **kwargs)

        if isinstance(file_content, list):
            raise ValueError(f"{file_path} is a directory, not a file")

        import base64

        content = base64.b64decode(file_content.content).decode("utf-8")

        logger.info(
            "file_content_fetched", repo=repo, file_path=file_path, size=len(content)
        )
        return content

    except Exception as e:
        logger.error(
            "get_file_content_failed", repo=repo, file_path=file_path, error=str(e)
        )
        return json.dumps({"ok": False, "error": "get_file_content"})


@function_tool
def list_repo_directory(
    repo: str,
    directory_path: str = "",
    ref: str | None = None,
    installation_id: int | None = None,
) -> str:
    """
    List files and directories in a repository path.

    Args:
        repo: Repository in format "owner/repo"
        directory_path: Directory path (empty for root)
        ref: Branch/tag/commit reference
        installation_id: GitHub App installation ID (optional)

    Returns:
        List of files and directories
    """
    try:
        g, _ = _get_github_client(installation_id)
        repository = g.get_repo(repo)

        kwargs = {}
        clean_ref = _sanitize_ref(ref)
        if clean_ref:
            kwargs["ref"] = clean_ref

        contents = repository.get_contents(directory_path or "", **kwargs)

        if not isinstance(contents, list):
            contents = [contents]

        items = []
        for item in contents:
            items.append(
                {
                    "name": item.name,
                    "path": item.path,
                    "type": "dir" if item.type == "dir" else "file",
                    "size": item.size if item.type == "file" else None,
                }
            )

        logger.info(
            "repo_directory_listed", repo=repo, path=directory_path, count=len(items)
        )
        return items

    except Exception as e:
        logger.error(
            "list_repo_directory_failed", repo=repo, path=directory_path, error=str(e)
        )
        return json.dumps({"ok": False, "error": "list_repo_directory"})


# ============================================================================
# CI Failure Analysis Helpers
# ============================================================================


@function_tool
def detect_ci_framework(logs: str) -> str:
    """
    Detect the CI test framework from logs.

    Args:
        logs: CI log output

    Returns:
        Detected framework: 'jest', 'cypress', 'pytest', 'unknown'
    """
    lower = logs.lower()

    if "cypress" in lower or "cypresserror" in lower:
        return "cypress"
    if "jest" in lower or "\nfail " in lower or "test suites:" in lower:
        return "jest"
    if "pytest" in lower or "====" in lower and "passed" in lower:
        return "pytest"
    if "mocha" in lower:
        return "mocha"
    if "rspec" in lower:
        return "rspec"

    return "unknown"


@function_tool
def extract_failure_snippet(logs: str, max_chars: int = 12000) -> str:
    """
    Extract the most relevant failure section from CI logs.

    Args:
        logs: Full CI log output
        max_chars: Maximum characters to return

    Returns:
        Relevant log snippet focused on the failure
    """
    if not logs:
        return logs

    # Patterns that indicate failure points
    patterns = [
        "AssertionError",
        "CypressError",
        "Timed out retrying",
        "1 failing",
        "0 passing",
        "FAIL",
        "FAILED",
        "Error: Process completed with exit code",
        "Error:",
        "Exception:",
        "Traceback",
    ]

    # Find first occurrence of any failure marker
    lower = logs.lower()
    hit_idx = None

    for p in patterns:
        idx = lower.find(p.lower())
        if idx != -1:
            hit_idx = idx
            break

    if hit_idx is None:
        # Fallback: keep the tail (often includes stack traces)
        return logs[-max_chars:] if len(logs) > max_chars else logs

    # Include context before and after the first hit
    start = max(0, hit_idx - 4000)
    end = min(len(logs), hit_idx + 8000)
    snippet = logs[start:end]

    if len(snippet) > max_chars:
        snippet = snippet[-max_chars:]

    return snippet


# ============================================================================
# Webhook Verification
# ============================================================================


@function_tool
def verify_github_webhook_signature(
    payload: bytes,
    signature_header: str,
    secret: str | None = None,
) -> bool:
    """
    Verify GitHub webhook signature.

    Args:
        payload: Raw request body
        signature_header: X-Hub-Signature-256 header value
        secret: Webhook secret (defaults to GITHUB_WEBHOOK_SECRET env var)

    Returns:
        True if signature is valid
    """
    webhook_secret = secret or os.getenv("GITHUB_WEBHOOK_SECRET")

    if not webhook_secret:
        logger.warning("github_webhook_secret_not_configured")
        return True  # Skip verification in dev mode

    if not signature_header:
        logger.warning("webhook_signature_missing")
        return False

    try:
        hash_algorithm, signature = signature_header.split("=", 1)
    except ValueError:
        logger.warning("webhook_signature_invalid_format")
        return False

    if hash_algorithm != "sha256":
        logger.warning("webhook_signature_wrong_algorithm", algorithm=hash_algorithm)
        return False

    mac = hmac.new(webhook_secret.encode(), msg=payload, digestmod=hashlib.sha256)
    expected_signature = mac.hexdigest()

    is_valid = hmac.compare_digest(signature, expected_signature)

    if not is_valid:
        logger.warning("webhook_signature_mismatch")

    return is_valid


# Register tools
register_tool("set_github_installation_id", set_github_installation_id)
register_tool("get_github_installation_id", get_github_installation_id)
register_tool("download_workflow_run_logs", download_workflow_run_logs)
register_tool("get_workflow_run_info", get_workflow_run_info)
register_tool("list_failed_workflow_runs", list_failed_workflow_runs)
register_tool("post_pr_comment", post_pr_comment)
register_tool("get_pr_comments", get_pr_comments)
register_tool("update_or_create_pr_comment", update_or_create_pr_comment)
register_tool("commit_file_changes", commit_file_changes)
register_tool("get_file_content", get_file_content)
register_tool("list_repo_directory", list_repo_directory)
register_tool("detect_ci_framework", detect_ci_framework)
register_tool("extract_failure_snippet", extract_failure_snippet)
register_tool("verify_github_webhook_signature", verify_github_webhook_signature)
