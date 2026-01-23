"""Git tools for deployment history.

Provides tools for correlating incidents with code changes:
- git_log: Get recent commit history
"""

import json
import subprocess

from mcp.server.fastmcp import FastMCP


def _run_git(args: list[str], cwd: str | None = None) -> tuple[bool, str]:
    """Run a git command and return (success, output)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except FileNotFoundError:
        return False, "git not found in PATH"
    except Exception as e:
        return False, str(e)


def register_tools(mcp: FastMCP):
    """Register git tools with the MCP server."""

    @mcp.tool()
    def git_log(
        count: int = 10,
        path: str | None = None,
        since: str | None = None,
        author: str | None = None,
    ) -> str:
        """Get recent git commit history.

        Useful for correlating incidents with recent deployments.

        Args:
            count: Number of commits to show (default: 10)
            path: Optional path to filter commits (e.g., "src/api/")
            since: Optional date filter (e.g., "2024-01-01", "1 week ago")
            author: Optional author filter

        Returns:
            JSON with commit history including hash, author, date, message
        """
        args = [
            "log",
            f"-{count}",
            "--pretty=format:%H|%an|%ae|%aI|%s",
        ]

        if since:
            args.append(f"--since={since}")
        if author:
            args.append(f"--author={author}")
        if path:
            args.append("--")
            args.append(path)

        success, output = _run_git(args)

        if not success:
            return json.dumps({"error": output})

        commits = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 4)
            if len(parts) >= 5:
                commits.append(
                    {
                        "hash": parts[0][:8],  # Short hash
                        "full_hash": parts[0],
                        "author": parts[1],
                        "email": parts[2],
                        "date": parts[3],
                        "message": parts[4],
                    }
                )

        return json.dumps(
            {
                "commit_count": len(commits),
                "commits": commits,
            },
            indent=2,
        )

    @mcp.tool()
    def git_diff(
        ref1: str = "HEAD~1",
        ref2: str = "HEAD",
        path: str | None = None,
        stat_only: bool = False,
    ) -> str:
        """Show changes between two commits.

        Args:
            ref1: First reference (default: "HEAD~1")
            ref2: Second reference (default: "HEAD")
            path: Optional path filter
            stat_only: If True, only show file statistics (default: False)

        Returns:
            Diff output or file change statistics.
        """
        args = ["diff"]
        if stat_only:
            args.append("--stat")
        args.extend([ref1, ref2])
        if path:
            args.extend(["--", path])

        success, output = _run_git(args)

        if not success:
            return json.dumps({"error": output})

        if stat_only:
            return json.dumps(
                {
                    "ref1": ref1,
                    "ref2": ref2,
                    "stat": output,
                },
                indent=2,
            )

        return json.dumps(
            {
                "ref1": ref1,
                "ref2": ref2,
                "diff": output[:10000] if len(output) > 10000 else output,  # Limit size
                "truncated": len(output) > 10000,
            },
            indent=2,
        )

    @mcp.tool()
    def git_show(commit: str = "HEAD") -> str:
        """Show details of a specific commit.

        Args:
            commit: Commit reference (hash, tag, branch, HEAD)

        Returns:
            JSON with commit details and changes.
        """
        # Get commit info
        args = ["show", commit, "--stat", "--format=%H|%an|%ae|%aI|%s|%b"]
        success, output = _run_git(args)

        if not success:
            return json.dumps({"error": output})

        lines = output.split("\n", 1)
        if not lines:
            return json.dumps({"error": "No output from git show"})

        parts = lines[0].split("|", 5)
        body_and_stat = lines[1] if len(lines) > 1 else ""

        result = {
            "hash": parts[0][:8] if parts else "",
            "full_hash": parts[0] if parts else "",
            "author": parts[1] if len(parts) > 1 else "",
            "email": parts[2] if len(parts) > 2 else "",
            "date": parts[3] if len(parts) > 3 else "",
            "subject": parts[4] if len(parts) > 4 else "",
            "body": parts[5].strip() if len(parts) > 5 else "",
            "stat": body_and_stat,
        }

        return json.dumps(result, indent=2)

    @mcp.tool()
    def correlate_with_deployment(
        incident_time: str,
        hours_before: int = 24,
    ) -> str:
        """Find commits that might correlate with an incident time.

        Useful for "what changed before this incident?" queries.

        Args:
            incident_time: Incident time (ISO format or relative like "2 hours ago")
            hours_before: How many hours before to look (default: 24)

        Returns:
            JSON with commits in the time window.
        """
        from datetime import datetime, timedelta

        # Parse incident time
        try:
            if "ago" in incident_time.lower():
                # Relative time - let git handle it
                since = f"{hours_before} hours ago"
                until = incident_time
            else:
                # ISO time
                incident_dt = datetime.fromisoformat(
                    incident_time.replace("Z", "+00:00")
                )
                window_start = incident_dt - timedelta(hours=hours_before)
                since = window_start.isoformat()
                until = incident_dt.isoformat()
        except Exception:
            since = f"{hours_before} hours ago"
            until = "now"

        args = [
            "log",
            f"--since={since}",
            f"--until={until}",
            "--pretty=format:%H|%an|%aI|%s",
        ]

        success, output = _run_git(args)

        if not success:
            return json.dumps({"error": output})

        commits = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) >= 4:
                commits.append(
                    {
                        "hash": parts[0][:8],
                        "author": parts[1],
                        "date": parts[2],
                        "message": parts[3],
                    }
                )

        # Identify potentially risky commits
        risky_keywords = [
            "fix",
            "hotfix",
            "bug",
            "revert",
            "urgent",
            "critical",
            "breaking",
        ]
        for commit in commits:
            msg_lower = commit["message"].lower()
            commit["risk_indicators"] = [kw for kw in risky_keywords if kw in msg_lower]

        return json.dumps(
            {
                "incident_time": incident_time,
                "search_window": f"{hours_before} hours before",
                "commit_count": len(commits),
                "commits": commits,
                "recommendation": (
                    "Review commits with risk indicators first"
                    if any(c["risk_indicators"] for c in commits)
                    else None
                ),
            },
            indent=2,
        )

    @mcp.tool()
    def git_blame(
        file_path: str,
        line_start: int | None = None,
        line_end: int | None = None,
    ) -> str:
        """Show what revision and author last modified each line.

        Args:
            file_path: Path to the file
            line_start: Start line (optional)
            line_end: End line (optional)

        Returns:
            JSON with blame information per line.
        """
        args = ["blame", "--line-porcelain"]
        if line_start and line_end:
            args.extend([f"-L{line_start},{line_end}"])
        args.append(file_path)

        success, output = _run_git(args)

        if not success:
            return json.dumps({"error": output, "file": file_path})

        # Parse porcelain output
        lines = []
        current = {}

        for line in output.split("\n"):
            if line.startswith("\t"):
                current["content"] = line[1:]
                lines.append(current)
                current = {}
            elif line.startswith("author "):
                current["author"] = line[7:]
            elif line.startswith("author-time "):
                from datetime import datetime

                ts = int(line[12:])
                current["date"] = datetime.fromtimestamp(ts).isoformat()
            elif line.startswith("summary "):
                current["message"] = line[8:]
            elif len(line) == 40:  # Commit hash
                current["hash"] = line[:8]

        return json.dumps(
            {
                "file": file_path,
                "line_count": len(lines),
                "lines": lines[:100],  # Limit output
                "truncated": len(lines) > 100,
            },
            indent=2,
        )

    @mcp.tool()
    def git_recent_changes(hours: int = 24, path: str | None = None) -> str:
        """Get files changed in the recent time period.

        Useful for understanding what changed before an incident.

        Args:
            hours: Number of hours to look back (default: 24)
            path: Optional path filter

        Returns:
            JSON with changed files and their change frequency.
        """
        args = [
            "log",
            f"--since={hours} hours ago",
            "--name-only",
            "--pretty=format:",
        ]
        if path:
            args.extend(["--", path])

        success, output = _run_git(args)

        if not success:
            return json.dumps({"error": output})

        # Count file changes
        file_counts = {}
        for line in output.strip().split("\n"):
            if line:
                file_counts[line] = file_counts.get(line, 0) + 1

        # Sort by change count
        sorted_files = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)

        return json.dumps(
            {
                "hours": hours,
                "path_filter": path,
                "files_changed": len(sorted_files),
                "most_changed": [
                    {"file": f, "changes": c} for f, c in sorted_files[:20]
                ],
            },
            indent=2,
        )
