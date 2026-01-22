"""
Git tools for repository operations.

Ported from cto-ai-agent, adapted for OpenAI Agents SDK.
"""

from __future__ import annotations

import json
import subprocess

from agents import function_tool

from ..core.logging import get_logger

logger = get_logger(__name__)


def _run_git(
    args: list[str],
    cwd: str | None = None,
    timeout_s: float = 60.0,
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

    Use cases:
    - Check for uncommitted changes before operations
    - See which files are staged/unstaged
    - Verify clean working directory

    Args:
        cwd: Directory to check (default: current directory)

    Returns:
        JSON with ok, branch, clean, and status info
    """
    logger.info("git_status", cwd=cwd)
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
    staged: bool = False, path: str = "", ref1: str = "", ref2: str = "", cwd: str = "."
) -> str:
    """
    Show changes between commits, working tree, etc.

    Use cases:
    - Review changes before commit
    - Compare branches
    - Check specific file changes

    Args:
        staged: Show staged changes only
        path: Specific file/directory to diff
        ref1: First reference (commit/branch)
        ref2: Second reference (commit/branch)
        cwd: Working directory

    Returns:
        JSON with ok and diff content
    """
    logger.info("git_diff", staged=staged, path=path)

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
    limit: int = 10, oneline: bool = True, path: str = "", cwd: str = "."
) -> str:
    """
    Show commit history.

    Use cases:
    - Review recent commits
    - Find when a change was introduced
    - Check who made changes

    Args:
        limit: Number of commits to show (default 10)
        oneline: Compact format (default True)
        path: Filter by file path
        cwd: Working directory

    Returns:
        JSON with ok and commits list
    """
    logger.info("git_log", limit=limit, path=path)

    args = ["log", f"-{limit}"]
    if oneline:
        args.append("--oneline")
    else:
        args.extend(["--pretty=format:%H|%an|%ae|%s|%ci"])
    if path:
        args.extend(["--", path])

    result = _run_git(args, cwd=cwd or None)

    if result.get("ok"):
        lines = result.get("stdout", "").strip().split("\n")
        commits = []
        for line in lines:
            if line:
                if oneline:
                    parts = line.split(" ", 1)
                    commits.append(
                        {
                            "hash": parts[0],
                            "message": parts[1] if len(parts) > 1 else "",
                        }
                    )
                else:
                    parts = line.split("|")
                    if len(parts) >= 5:
                        commits.append(
                            {
                                "hash": parts[0],
                                "author": parts[1],
                                "email": parts[2],
                                "message": parts[3],
                                "date": parts[4],
                            }
                        )
        result["commits"] = commits

    return json.dumps(result)


@function_tool
def git_blame(path: str, cwd: str = ".") -> str:
    """
    Show what revision and author last modified each line of a file.

    Use cases:
    - Find who introduced a bug
    - Understand code history

    Args:
        path: File path to blame
        cwd: Working directory

    Returns:
        JSON with blame output
    """
    if not path:
        return json.dumps({"ok": False, "error": "path is required"})

    logger.info("git_blame", path=path)
    result = _run_git(["blame", "--line-porcelain", path], cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_show(ref: str = "HEAD", path: str = "", cwd: str = ".") -> str:
    """
    Show commit details or file contents at a specific revision.

    Use cases:
    - View commit details
    - See file at specific version

    Args:
        ref: Commit/branch reference (default HEAD)
        path: Optional file path
        cwd: Working directory

    Returns:
        JSON with show output
    """
    logger.info("git_show", ref=ref, path=path)

    args = ["show", ref]
    if path:
        args.append(f":{path}")

    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_branch_list(all_branches: bool = False, cwd: str = ".") -> str:
    """
    List branches in the repository.

    Args:
        all_branches: Include remote branches
        cwd: Working directory

    Returns:
        JSON with branches list and current branch
    """
    logger.info("git_branch_list", all_branches=all_branches)

    args = ["branch"]
    if all_branches:
        args.append("-a")

    result = _run_git(args, cwd=cwd or None)

    if result.get("ok"):
        branches = []
        current = ""
        for line in result.get("stdout", "").strip().split("\n"):
            line = line.strip()
            if line.startswith("* "):
                current = line[2:]
                branches.append(current)
            elif line:
                branches.append(line)
        result["branches"] = branches
        result["current"] = current

    return json.dumps(result)


@function_tool
def git_add(paths: str = ".", cwd: str = ".") -> str:
    """
    Stage files for commit.

    Use cases:
    - Stage changes before committing
    - Add new files to tracking
    - Stage specific files or directories

    Args:
        paths: Files/directories to add (default: "." for all changes)
        cwd: Working directory

    Returns:
        JSON with ok status and added files info
    """
    logger.info("git_add", paths=paths, cwd=cwd)

    args = ["add", paths]
    result = _run_git(args, cwd=cwd or None)

    # Get what was added by checking status
    if result.get("ok"):
        status_result = _run_git(["status", "--porcelain"], cwd=cwd or None)
        if status_result.get("ok"):
            staged = []
            for line in status_result.get("stdout", "").split("\n"):
                if line and (line.startswith("A ") or line.startswith("M ")):
                    staged.append(line[3:])
            result["staged_files"] = staged

    return json.dumps(result)


@function_tool
def git_commit(message: str, cwd: str = ".") -> str:
    """
    Create a commit with staged changes.

    Use cases:
    - Commit staged changes with a message
    - Create snapshots of work

    Args:
        message: Commit message
        cwd: Working directory

    Returns:
        JSON with ok status, commit hash, and files changed
    """
    if not message:
        return json.dumps({"ok": False, "error": "commit message is required"})

    logger.info("git_commit", message_preview=message[:50], cwd=cwd)

    args = ["commit", "-m", message]
    result = _run_git(args, cwd=cwd or None, timeout_s=120.0)

    # Extract commit hash from output if successful
    if result.get("ok"):
        # Try to get the commit hash
        log_result = _run_git(["rev-parse", "HEAD"], cwd=cwd or None)
        if log_result.get("ok"):
            result["commit_hash"] = log_result.get("stdout", "").strip()

        # Parse commit output for files changed
        stdout = result.get("stdout", "")
        if "files changed" in stdout or "file changed" in stdout:
            result["summary"] = stdout.strip()

    return json.dumps(result)


@function_tool
def git_push(
    remote: str = "origin", branch: str = "", force: bool = False, cwd: str = "."
) -> str:
    """
    Push commits to remote repository.

    Use cases:
    - Push local commits to remote
    - Sync changes with team
    - Deploy via git push

    Args:
        remote: Remote name (default: "origin")
        branch: Branch to push (empty = current branch)
        force: Force push (use with caution!)
        cwd: Working directory

    Returns:
        JSON with ok status and push result
    """
    logger.info("git_push", remote=remote, branch=branch, force=force, cwd=cwd)

    args = ["push", remote]
    if branch:
        args.append(branch)
    if force:
        args.append("--force")
        logger.warning("git_push_force_enabled", remote=remote, branch=branch)

    result = _run_git(args, cwd=cwd or None, timeout_s=180.0)

    # Parse output for success indicators
    if result.get("ok"):
        stdout = result.get("stdout", "") + result.get("stderr", "")
        if "Everything up-to-date" in stdout:
            result["status"] = "up_to_date"
        elif "->" in stdout:
            result["status"] = "pushed"

    return json.dumps(result)


@function_tool
def git_pull(
    remote: str = "origin", branch: str = "", rebase: bool = False, cwd: str = "."
) -> str:
    """
    Pull changes from remote repository.

    Use cases:
    - Get latest changes from remote
    - Sync with team's work
    - Update local branch

    Args:
        remote: Remote name (default: "origin")
        branch: Branch to pull (empty = current branch)
        rebase: Use rebase instead of merge
        cwd: Working directory

    Returns:
        JSON with ok status and pull result
    """
    logger.info("git_pull", remote=remote, branch=branch, rebase=rebase, cwd=cwd)

    args = ["pull"]
    if rebase:
        args.append("--rebase")
    args.append(remote)
    if branch:
        args.append(branch)

    result = _run_git(args, cwd=cwd or None, timeout_s=180.0)

    if result.get("ok"):
        stdout = result.get("stdout", "")
        if "Already up to date" in stdout:
            result["status"] = "up_to_date"
        elif "Fast-forward" in stdout:
            result["status"] = "fast_forward"
        else:
            result["status"] = "merged"

    return json.dumps(result)


@function_tool
def git_fetch(
    remote: str = "origin",
    prune: bool = False,
    all_remotes: bool = False,
    cwd: str = ".",
) -> str:
    """
    Fetch changes from remote without merging.

    Use cases:
    - Check what's new on remote
    - Update remote tracking branches
    - Prepare for merge/rebase

    Args:
        remote: Remote name (default: "origin")
        prune: Remove stale tracking branches
        all_remotes: Fetch from all remotes
        cwd: Working directory

    Returns:
        JSON with ok status and fetch result
    """
    logger.info(
        "git_fetch", remote=remote, prune=prune, all_remotes=all_remotes, cwd=cwd
    )

    args = ["fetch"]
    if all_remotes:
        args.append("--all")
    else:
        args.append(remote)
    if prune:
        args.append("--prune")

    result = _run_git(args, cwd=cwd or None, timeout_s=180.0)
    return json.dumps(result)


@function_tool
def git_checkout(
    ref: str, create: bool = False, force: bool = False, cwd: str = "."
) -> str:
    """
    Checkout a branch, tag, or commit.

    Use cases:
    - Switch branches
    - Create and switch to new branch
    - Checkout specific commit

    Args:
        ref: Branch name, tag, or commit to checkout
        create: Create new branch (git checkout -b)
        force: Force checkout, discarding local changes
        cwd: Working directory

    Returns:
        JSON with ok status
    """
    logger.info("git_checkout", ref=ref, create=create, force=force, cwd=cwd)

    args = ["checkout"]
    if create:
        args.append("-b")
    if force:
        args.append("-f")
    args.append(ref)

    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_branch_create(name: str, start_point: str = "", cwd: str = ".") -> str:
    """
    Create a new branch.

    Use cases:
    - Start new feature branch
    - Create branch from specific commit

    Args:
        name: New branch name
        start_point: Starting commit/branch (default: HEAD)
        cwd: Working directory

    Returns:
        JSON with ok status
    """
    if not name:
        return json.dumps({"ok": False, "error": "branch name is required"})

    logger.info("git_branch_create", name=name, start_point=start_point, cwd=cwd)

    args = ["branch", name]
    if start_point:
        args.append(start_point)

    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_branch_delete(name: str, force: bool = False, cwd: str = ".") -> str:
    """
    Delete a branch.

    Use cases:
    - Clean up merged branches
    - Remove obsolete feature branches

    Args:
        name: Branch name to delete
        force: Force delete unmerged branch (-D)
        cwd: Working directory

    Returns:
        JSON with ok status
    """
    if not name:
        return json.dumps({"ok": False, "error": "branch name is required"})

    logger.info("git_branch_delete", name=name, force=force, cwd=cwd)

    args = ["branch", "-D" if force else "-d", name]
    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_merge(
    branch: str, no_ff: bool = False, message: str = "", cwd: str = "."
) -> str:
    """
    Merge a branch into current branch.

    Use cases:
    - Merge feature branch into main
    - Integrate changes from another branch

    Args:
        branch: Branch to merge
        no_ff: Create merge commit even if fast-forward possible
        message: Custom merge commit message
        cwd: Working directory

    Returns:
        JSON with ok status and merge result
    """
    if not branch:
        return json.dumps({"ok": False, "error": "branch name is required"})

    logger.info("git_merge", branch=branch, no_ff=no_ff, cwd=cwd)

    args = ["merge"]
    if no_ff:
        args.append("--no-ff")
    if message:
        args.extend(["-m", message])
    args.append(branch)

    result = _run_git(args, cwd=cwd or None, timeout_s=120.0)

    if result.get("ok"):
        stdout = result.get("stdout", "")
        if "Already up to date" in stdout:
            result["status"] = "up_to_date"
        elif "Fast-forward" in stdout:
            result["status"] = "fast_forward"
        else:
            result["status"] = "merged"

    return json.dumps(result)


@function_tool
def git_stash_list(cwd: str = ".") -> str:
    """
    List all stashes.

    Use cases:
    - See saved work-in-progress
    - Find stash to apply

    Args:
        cwd: Working directory

    Returns:
        JSON with stash list
    """
    logger.info("git_stash_list", cwd=cwd)

    result = _run_git(["stash", "list"], cwd=cwd or None)

    if result.get("ok"):
        stashes = []
        for line in result.get("stdout", "").strip().split("\n"):
            if line:
                # Parse: stash@{0}: WIP on main: abc123 message
                parts = line.split(":", 2)
                stashes.append(
                    {
                        "ref": parts[0].strip() if parts else line,
                        "description": parts[2].strip() if len(parts) > 2 else line,
                    }
                )
        result["stashes"] = stashes

    return json.dumps(result)


@function_tool
def git_stash_save(
    message: str = "", include_untracked: bool = False, cwd: str = "."
) -> str:
    """
    Save changes to stash.

    Use cases:
    - Save work-in-progress before switching branches
    - Temporarily set aside changes

    Args:
        message: Optional stash message
        include_untracked: Include untracked files
        cwd: Working directory

    Returns:
        JSON with ok status
    """
    logger.info(
        "git_stash_save", message=message, include_untracked=include_untracked, cwd=cwd
    )

    args = ["stash", "push"]
    if include_untracked:
        args.append("-u")
    if message:
        args.extend(["-m", message])

    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_stash_pop(index: int = 0, cwd: str = ".") -> str:
    """
    Apply and remove a stash.

    Use cases:
    - Restore stashed changes
    - Continue work-in-progress

    Args:
        index: Stash index (default: 0, most recent)
        cwd: Working directory

    Returns:
        JSON with ok status
    """
    logger.info("git_stash_pop", index=index, cwd=cwd)

    args = ["stash", "pop", f"stash@{{{index}}}"]
    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_stash_apply(index: int = 0, cwd: str = ".") -> str:
    """
    Apply a stash without removing it.

    Use cases:
    - Apply stash to multiple branches
    - Test stashed changes without losing them

    Args:
        index: Stash index (default: 0, most recent)
        cwd: Working directory

    Returns:
        JSON with ok status
    """
    logger.info("git_stash_apply", index=index, cwd=cwd)

    args = ["stash", "apply", f"stash@{{{index}}}"]
    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_reset(
    ref: str = "HEAD", mode: str = "mixed", paths: str = "", cwd: str = "."
) -> str:
    """
    Reset current HEAD to specified state.

    Use cases:
    - Unstage files (soft/mixed reset)
    - Undo commits (soft reset)
    - Discard changes (hard reset)

    Args:
        ref: Commit to reset to (default: HEAD)
        mode: Reset mode - soft, mixed, hard (default: mixed)
        paths: Specific paths to reset (for unstaging)
        cwd: Working directory

    Returns:
        JSON with ok status
    """
    if mode not in ["soft", "mixed", "hard"]:
        return json.dumps({"ok": False, "error": "mode must be soft, mixed, or hard"})

    logger.info("git_reset", ref=ref, mode=mode, paths=paths, cwd=cwd)

    args = ["reset", f"--{mode}"]
    if paths:
        args.extend(["--", paths])
    else:
        args.append(ref)

    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_revert(commit: str, no_commit: bool = False, cwd: str = ".") -> str:
    """
    Revert a commit by creating a new commit that undoes changes.

    Use cases:
    - Undo a specific commit safely
    - Back out a change without rewriting history

    Args:
        commit: Commit SHA to revert
        no_commit: Stage changes but don't commit
        cwd: Working directory

    Returns:
        JSON with ok status
    """
    if not commit:
        return json.dumps({"ok": False, "error": "commit SHA is required"})

    logger.info("git_revert", commit=commit, no_commit=no_commit, cwd=cwd)

    args = ["revert", "--no-edit"]
    if no_commit:
        args.append("--no-commit")
    args.append(commit)

    result = _run_git(args, cwd=cwd or None, timeout_s=120.0)
    return json.dumps(result)


@function_tool
def git_cherry_pick(commit: str, no_commit: bool = False, cwd: str = ".") -> str:
    """
    Apply changes from a specific commit.

    Use cases:
    - Backport a fix to another branch
    - Apply specific commit from another branch

    Args:
        commit: Commit SHA to cherry-pick
        no_commit: Stage changes but don't commit
        cwd: Working directory

    Returns:
        JSON with ok status
    """
    if not commit:
        return json.dumps({"ok": False, "error": "commit SHA is required"})

    logger.info("git_cherry_pick", commit=commit, no_commit=no_commit, cwd=cwd)

    args = ["cherry-pick"]
    if no_commit:
        args.append("--no-commit")
    args.append(commit)

    result = _run_git(args, cwd=cwd or None, timeout_s=120.0)
    return json.dumps(result)


@function_tool
def git_tag_list(pattern: str = "", cwd: str = ".") -> str:
    """
    List tags in the repository.

    Use cases:
    - See all version tags
    - Find specific tag pattern

    Args:
        pattern: Filter tags by pattern (e.g., "v1.*")
        cwd: Working directory

    Returns:
        JSON with tags list
    """
    logger.info("git_tag_list", pattern=pattern, cwd=cwd)

    args = ["tag", "-l"]
    if pattern:
        args.append(pattern)

    result = _run_git(args, cwd=cwd or None)

    if result.get("ok"):
        tags = [t for t in result.get("stdout", "").strip().split("\n") if t]
        result["tags"] = tags

    return json.dumps(result)


@function_tool
def git_tag_create(
    name: str, message: str = "", ref: str = "HEAD", cwd: str = "."
) -> str:
    """
    Create a new tag.

    Use cases:
    - Mark release versions
    - Create annotated tags for important points

    Args:
        name: Tag name
        message: Tag message (creates annotated tag)
        ref: Commit to tag (default: HEAD)
        cwd: Working directory

    Returns:
        JSON with ok status
    """
    if not name:
        return json.dumps({"ok": False, "error": "tag name is required"})

    logger.info("git_tag_create", name=name, message=message, ref=ref, cwd=cwd)

    args = ["tag"]
    if message:
        args.extend(["-a", name, "-m", message])
    else:
        args.append(name)
    args.append(ref)

    result = _run_git(args, cwd=cwd or None)
    return json.dumps(result)


@function_tool
def git_remote_list(verbose: bool = True, cwd: str = ".") -> str:
    """
    List remote repositories.

    Use cases:
    - See configured remotes
    - Check remote URLs

    Args:
        verbose: Show remote URLs
        cwd: Working directory

    Returns:
        JSON with remotes list
    """
    logger.info("git_remote_list", verbose=verbose, cwd=cwd)

    args = ["remote"]
    if verbose:
        args.append("-v")

    result = _run_git(args, cwd=cwd or None)

    if result.get("ok"):
        remotes = {}
        for line in result.get("stdout", "").strip().split("\n"):
            if line:
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[0]
                    url = parts[1]
                    if name not in remotes:
                        remotes[name] = {"fetch": None, "push": None}
                    if "(fetch)" in line:
                        remotes[name]["fetch"] = url
                    elif "(push)" in line:
                        remotes[name]["push"] = url
                    else:
                        remotes[name]["url"] = url
        result["remotes"] = remotes

    return json.dumps(result)


@function_tool
def git_rev_parse(ref: str = "HEAD", cwd: str = ".") -> str:
    """
    Get the full SHA of a reference.

    Use cases:
    - Get current commit SHA
    - Resolve branch/tag to commit
    - Verify reference exists

    Args:
        ref: Reference to parse (branch, tag, HEAD, etc.)
        cwd: Working directory

    Returns:
        JSON with ok status and SHA
    """
    logger.info("git_rev_parse", ref=ref, cwd=cwd)

    result = _run_git(["rev-parse", ref], cwd=cwd or None)

    if result.get("ok"):
        result["sha"] = result.get("stdout", "").strip()

    return json.dumps(result)


@function_tool
def git_ls_files(
    pattern: str = "", untracked: bool = False, modified: bool = False, cwd: str = "."
) -> str:
    """
    List tracked files in the repository.

    Use cases:
    - See all tracked files
    - Find files matching pattern
    - List modified or untracked files

    Args:
        pattern: Filter files by pattern
        untracked: Show untracked files
        modified: Show modified files
        cwd: Working directory

    Returns:
        JSON with files list
    """
    logger.info(
        "git_ls_files", pattern=pattern, untracked=untracked, modified=modified, cwd=cwd
    )

    args = ["ls-files"]
    if untracked:
        args.append("--others")
        args.append("--exclude-standard")
    elif modified:
        args.append("--modified")
    if pattern:
        args.append(pattern)

    result = _run_git(args, cwd=cwd or None)

    if result.get("ok"):
        files = [f for f in result.get("stdout", "").strip().split("\n") if f]
        result["files"] = files

    return json.dumps(result)


@function_tool
def git_shortlog(
    since: str = "", until: str = "", max_results: int = 20, cwd: str = "."
) -> str:
    """
    Summarize git log output by author.

    Use cases:
    - See contribution summary
    - Find who contributed what
    - Generate changelog by author

    Args:
        since: Start date (e.g., "2024-01-01", "1 week ago")
        until: End date
        max_results: Max entries per author
        cwd: Working directory

    Returns:
        JSON with author summaries
    """
    logger.info("git_shortlog", since=since, until=until, cwd=cwd)

    args = ["shortlog", "-sn", "--no-merges"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")

    result = _run_git(args, cwd=cwd or None)

    if result.get("ok"):
        authors = []
        for line in result.get("stdout", "").strip().split("\n")[:max_results]:
            if line:
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    authors.append(
                        {"commits": int(parts[0].strip()), "author": parts[1].strip()}
                    )
        result["authors"] = authors

    return json.dumps(result)


@function_tool
def git_reflog(limit: int = 20, cwd: str = ".") -> str:
    """
    Show reference logs (history of HEAD changes).

    Use cases:
    - Recover lost commits
    - See branch/checkout history
    - Undo accidental operations

    Args:
        limit: Number of entries to show
        cwd: Working directory

    Returns:
        JSON with reflog entries
    """
    logger.info("git_reflog", limit=limit, cwd=cwd)

    args = ["reflog", f"-{limit}", "--format=%h|%gd|%gs|%ci"]
    result = _run_git(args, cwd=cwd or None)

    if result.get("ok"):
        entries = []
        for line in result.get("stdout", "").strip().split("\n"):
            if line:
                parts = line.split("|")
                if len(parts) >= 4:
                    entries.append(
                        {
                            "sha": parts[0],
                            "ref": parts[1],
                            "action": parts[2],
                            "date": parts[3],
                        }
                    )
        result["entries"] = entries

    return json.dumps(result)
