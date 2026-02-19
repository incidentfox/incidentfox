"""
GitHub output handlers — posts agent results as PR/issue comments.

Ported from agent/src/ai_agent/core/output_handlers/github.py with simplifications:
- No initial "working on it" message or progress updates
- No comment updating — always creates a new comment
- Token resolution: config → team_config → GITHUB_TOKEN env
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from . import OutputHandler, OutputResult, _log

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
COMMENT_CHAR_LIMIT = 65536  # GitHub comment size limit


def _resolve_token(
    config: dict[str, Any],
    team_config: dict[str, Any] | None = None,
) -> str:
    """Resolve GitHub token from config, team config, or environment."""
    # 1. Explicit in destination config
    token = config.get("token")
    if token:
        return token

    # 2. From team integrations config
    if team_config:
        gh = team_config.get("integrations", {}).get("github", {})
        token = gh.get("token") or gh.get("app_private_key")
        if token:
            return token

    # 3. Environment fallback
    return os.getenv("GITHUB_TOKEN", "")


async def _post_comment(repo: str, endpoint: str, body: str, token: str) -> int | None:
    """Post a comment to GitHub, return comment ID."""
    url = f"{GITHUB_API}/repos/{repo}/{endpoint}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}", **GITHUB_HEADERS},
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json().get("id")


def _format_markdown(
    result_text: str,
    success: bool,
    agent_name: str,
    duration_seconds: float | None,
    error: str | None,
    run_id: str | None,
) -> str:
    """Format agent result as GitHub-flavored markdown comment."""
    lines: list[str] = []

    # Header
    status_emoji = "\u2705" if success else "\u274c"
    lines.append(f"## \U0001f98a {agent_name} {status_emoji}")
    lines.append("")

    if not success:
        lines.append(f"**Error:** {error or 'Unknown error'}")
        lines.append("")
        if duration_seconds:
            lines.append(f"*Duration: {duration_seconds:.1f}s*")
        if run_id:
            lines.append("")
            lines.append(f"<!-- incidentfox:run_id={run_id} -->")
        return "\n".join(lines)

    # Try to parse result_text as JSON for structured formatting
    structured = _try_parse_structured(result_text)
    if structured:
        lines.extend(_format_structured(structured))
    elif result_text:
        lines.append(result_text[:COMMENT_CHAR_LIMIT])
    else:
        lines.append("_No output returned_")

    # Footer
    lines.append("")
    if duration_seconds:
        lines.append(f"*Duration: {duration_seconds:.1f}s*")

    # Embed run_id for feedback tracking (react with thumbs up/down)
    if run_id:
        lines.append("")
        lines.append(f"<!-- incidentfox:run_id={run_id} -->")

    return "\n".join(lines)


def _try_parse_structured(text: str) -> dict | None:
    """Try to parse text as JSON with structured fields."""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # Only treat as structured if it has known fields
            known = {
                "summary",
                "result",
                "message",
                "root_cause",
                "cause",
                "recommendations",
                "next_steps",
                "confidence",
            }
            if known & data.keys():
                return data
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _format_structured(output: dict) -> list[str]:
    """Format dict with known fields as markdown sections."""
    lines: list[str] = []

    summary = output.get("summary") or output.get("result") or output.get("message")
    root_cause = output.get("root_cause") or output.get("cause")
    recommendations = output.get("recommendations") or output.get("next_steps") or []
    confidence = output.get("confidence")

    if summary:
        lines.append("### Summary")
        lines.append(str(summary))
        lines.append("")

    if root_cause:
        lines.append("### Root Cause")
        lines.append(str(root_cause))
        lines.append("")

    if recommendations:
        lines.append("### Recommendations")
        for rec in recommendations[:10]:
            lines.append(f"- {rec}")
        lines.append("")

    if confidence is not None:
        lines.append(f"**Confidence:** {confidence}%")

    # Fallback: no structured fields matched despite having known keys
    if not any([summary, root_cause, recommendations]):
        try:
            json_str = json.dumps(output, indent=2, default=str, ensure_ascii=False)
            lines.append("```json")
            lines.append(json_str[:COMMENT_CHAR_LIMIT])
            lines.append("```")
        except Exception:
            lines.append(str(output)[:COMMENT_CHAR_LIMIT])

    return lines


class GitHubPRCommentHandler(OutputHandler):
    """Posts agent results as a PR comment."""

    @property
    def destination_type(self) -> str:
        return "github_pr_comment"

    async def post_result(
        self,
        config: dict[str, Any],
        result_text: str,
        *,
        success: bool = True,
        agent_name: str = "IncidentFox",
        run_id: str | None = None,
        duration_seconds: float | None = None,
        error: str | None = None,
        team_config: dict[str, Any] | None = None,
    ) -> OutputResult:
        repo = config.get("repo")
        pr_number = config.get("pr_number")
        token = _resolve_token(config, team_config)

        if not repo or not pr_number or not token:
            return OutputResult(
                success=False,
                destination_type=self.destination_type,
                error=f"Missing config: repo={bool(repo)}, pr_number={bool(pr_number)}, token={bool(token)}",
            )

        try:
            body = _format_markdown(
                result_text=result_text,
                success=success,
                agent_name=agent_name,
                duration_seconds=duration_seconds,
                error=error,
                run_id=run_id,
            )

            comment_id = await _post_comment(
                repo=repo,
                endpoint=f"issues/{pr_number}/comments",
                body=body,
                token=token,
            )

            _log(
                "github_pr_comment_posted",
                repo=repo,
                pr_number=pr_number,
                comment_id=comment_id,
            )

            return OutputResult(
                success=True,
                destination_type=self.destination_type,
                message_id=str(comment_id) if comment_id else None,
            )

        except Exception as e:
            _log(
                "github_pr_comment_failed", repo=repo, pr_number=pr_number, error=str(e)
            )
            return OutputResult(
                success=False,
                destination_type=self.destination_type,
                error=str(e),
            )


class GitHubIssueCommentHandler(OutputHandler):
    """Posts agent results as an issue comment."""

    @property
    def destination_type(self) -> str:
        return "github_issue_comment"

    async def post_result(
        self,
        config: dict[str, Any],
        result_text: str,
        *,
        success: bool = True,
        agent_name: str = "IncidentFox",
        run_id: str | None = None,
        duration_seconds: float | None = None,
        error: str | None = None,
        team_config: dict[str, Any] | None = None,
    ) -> OutputResult:
        repo = config.get("repo")
        issue_number = config.get("issue_number")
        token = _resolve_token(config, team_config)

        if not repo or not issue_number or not token:
            return OutputResult(
                success=False,
                destination_type=self.destination_type,
                error=f"Missing config: repo={bool(repo)}, issue_number={bool(issue_number)}, token={bool(token)}",
            )

        try:
            body = _format_markdown(
                result_text=result_text,
                success=success,
                agent_name=agent_name,
                duration_seconds=duration_seconds,
                error=error,
                run_id=run_id,
            )

            comment_id = await _post_comment(
                repo=repo,
                endpoint=f"issues/{issue_number}/comments",
                body=body,
                token=token,
            )

            _log(
                "github_issue_comment_posted",
                repo=repo,
                issue_number=issue_number,
                comment_id=comment_id,
            )

            return OutputResult(
                success=True,
                destination_type=self.destination_type,
                message_id=str(comment_id) if comment_id else None,
            )

        except Exception as e:
            _log(
                "github_issue_comment_failed",
                repo=repo,
                issue_number=issue_number,
                error=str(e),
            )
            return OutputResult(
                success=False,
                destination_type=self.destination_type,
                error=str(e),
            )
