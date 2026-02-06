"""
Git tools for repository operations.

Provides Git CLI access for version control operations.
"""

import json
import logging
import subprocess
from typing import Optional

from ..core.agent import function_tool
from . import register_tool

logger = logging.getLogger(__name__)


def _run_git(
    args: list[str], cwd: Optional[str] = None, timeout_s: float = 60.0
) -> dict:
    """Run a git command and return structured output."""
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[-10000:] if result.stdout else "",
            "stderr": result.stderr[-5000:] if result.stderr else "",
            "cmd": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "cmd": " ".join(cmd)}
    except Exception as e:
        return {"ok": False, "error": str(e), "cmd": " ".join(cmd)}


@function_tool
def git_status(cwd: str = ".") -> str:
    """
    Get Git repository status.

    Args:
        cwd: Directory to check (default: current directory)

    Returns:
        JSON with branch, clean status, and file changes
    """
    logger.info(f"git_status: cwd={cwd}")
    result = _run_git(["status", "--porcelain", "-b"], cwd=cwd or None)

    if result.get("ok"):
        lines = result.get("stdout", "").strip().split("\n")
        branch = ""
        if lines and lines[0].startswith("## "):
            branch_line = lines[0][3:]
            branch = (
                branch_line.split("...")[0] if "..." in branch_line else branch_line
            )
        clean = len(lines) <= 1 or (len(lines) == 1 and lines[0].startswith("##"))
        result["branch"] = branch
        result["clean"] = clean

    return json.dumps(result)


@function_tool
def git_diff(
    staged: bool = False,
    path: str = "",
    ref1: str = "",
    ref2: str = "",
    cwd: str = ".",
) -> str:
    """
    Show changes between commits, working tree, etc.

    Args:
        staged: Show staged changes only
        path: Specific file/directory to diff
        ref1: First reference (commit/branch)
        ref2: Second reference (commit/branch)
        cwd: Working directory

    Returns:
        JSON with diff content
    """
    logger.info(f"git_diff: staged={staged}, path={path}")

    args = ["diff"]
    if staged:
        args.append("--staged")
    if ref1:
        args.append(ref1)
    if ref2:
        args.append(ref2)
    if path:
        args.extend(["--", path])

    result = _run_git(args, cwd=cwd or None)
    if result.get("ok"):
        result["diff"] = result.get("stdout", "")
    return json.dumps(result)


@function_tool
def git_log(
    limit: int = 10,
    oneline: bool = True,
    path: str = "",
    cwd: str = ".",
) -> str:
    """
    Show commit history.

    Args:
        limit: Number of commits to show (default 10)
        oneline: Compact format (default True)
        path: Filter by file path
        cwd: Working directory

    Returns:
        JSON with commits list
    """
    logger.info(f"git_log: limit={limit}, path={path}")

    args = ["log", f"-{limit}"]
    if oneline:
        args.append("--oneline")
    else:
        args.extend(["--pretty=format:%H|%an|%ae|%s|%ci"])
    if path:
        args.extend(["--", path])

    result = _run_git(args, cwd=cwd or None)

    if result.get("ok") and not oneline:
        commits = []
        for line in result.get("stdout", "").strip().split("\n"):
            if line and "|" in line:
                parts = line.split("|")
                if len(parts) >= 5:
                    commits.append(
                        {
                            "hash": parts[0],
                            "author": parts[1],
                            "email": parts[2],
                            "subject": parts[3],
                            "date": parts[4],
                        }
                    )
        result["commits"] = commits

    return json.dumps(result)


@function_tool
def git_blame(path: str, lines: str = "", cwd: str = ".") -> str:
    """
    Show what revision and author last modified each line.

    Args:
        path: File path to blame
        lines: Line range (e.g., "1,10" for lines 1-10)
        cwd: Working directory

    Returns:
        JSON with blame information
    """
    if not path:
        return json.dumps({"ok": False, "error": "path is required"})

    logger.info(f"git_blame: path={path}, lines={lines}")

    args = ["blame", "--line-porcelain"]
    if lines:
        args.extend(["-L", lines])
    args.append(path)

    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_show(ref: str, path: str = "", cwd: str = ".") -> str:
    """
    Show commit details and changes.

    Args:
        ref: Commit hash or reference
        path: Optional file path to limit output
        cwd: Working directory

    Returns:
        JSON with commit details
    """
    if not ref:
        return json.dumps({"ok": False, "error": "ref is required"})

    logger.info(f"git_show: ref={ref}, path={path}")

    args = ["show", ref, "--stat"]
    if path:
        args.extend(["--", path])

    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_branch_list(cwd: str = ".") -> str:
    """
    List all branches.

    Args:
        cwd: Working directory

    Returns:
        JSON with branches list
    """
    logger.info(f"git_branch_list: cwd={cwd}")

    result = _run_git(
        [
            "branch",
            "-a",
            "--format=%(refname:short)|%(upstream:short)|%(committerdate:relative)",
        ],
        cwd=cwd or None,
    )

    if result.get("ok"):
        branches = []
        for line in result.get("stdout", "").strip().split("\n"):
            if line:
                parts = line.split("|")
                branches.append(
                    {
                        "name": parts[0],
                        "upstream": parts[1] if len(parts) > 1 else "",
                        "last_commit": parts[2] if len(parts) > 2 else "",
                    }
                )
        result["branches"] = branches

    return json.dumps(result)


# Register tools
register_tool("git_status", git_status)
register_tool("git_diff", git_diff)
register_tool("git_log", git_log)
register_tool("git_blame", git_blame)
register_tool("git_show", git_show)
register_tool("git_branch_list", git_branch_list)
