"""
GitHub output handlers - posts agent results as PR/issue comments.

Supports:
- PR comments (for CI failures, code reviews)
- Issue comments (for bug analysis)
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..logging import get_logger
from ..output_handler import OutputHandler, OutputResult

logger = get_logger(__name__)


class GitHubOutputHandler(OutputHandler):
    """
    Base class for GitHub output handlers.

    Config:
        repo: Repository in "owner/repo" format (required)
        token: GitHub token (optional, defaults to GITHUB_TOKEN env)
    """

    def _get_token(self, config: dict[str, Any]) -> str:
        return config.get("token") or os.getenv("GITHUB_TOKEN", "")

    async def _post_comment(
        self,
        repo: str,
        endpoint: str,
        body: str,
        token: str,
    ) -> int | None:
        """Post a comment to GitHub, return comment ID."""
        import httpx

        url = f"https://api.github.com/repos/{repo}/{endpoint}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={"body": body},
            )
            resp.raise_for_status()
            return resp.json().get("id")

    async def _update_comment(
        self,
        repo: str,
        comment_id: int,
        body: str,
        token: str,
    ) -> None:
        """Update an existing comment."""
        import httpx

        url = f"https://api.github.com/repos/{repo}/issues/comments/{comment_id}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={"body": body},
            )
            resp.raise_for_status()

    def _format_markdown(
        self,
        output: Any,
        success: bool,
        agent_name: str,
        duration_seconds: float | None,
        error: str | None,
        run_id: str | None = None,
    ) -> str:
        """Format agent output as GitHub markdown."""
        lines = []

        # Header
        status_emoji = "✅" if success else "❌"
        lines.append(f"## 🦊 {agent_name} {status_emoji}")
        lines.append("")

        if not success:
            lines.append(f"**Error:** {error or 'Unknown error'}")
            lines.append("")
            if duration_seconds:
                lines.append(f"*Duration: {duration_seconds:.1f}s*")
            # Embed run_id for feedback tracking (even on errors)
            if run_id:
                lines.append("")
                lines.append(f"<!-- incidentfox:run_id={run_id} -->")
            return "\n".join(lines)

        # Format output
        if output is None:
            lines.append("_No output returned_")
        elif isinstance(output, str):
            lines.append(output)
        elif isinstance(output, dict):
            lines.extend(self._format_dict_markdown(output))
        elif hasattr(output, "summary"):
            lines.extend(self._format_structured_markdown(output))
        else:
            try:
                json_str = json.dumps(output, indent=2, default=str, ensure_ascii=False)
                lines.append("```json")
                lines.append(json_str[:10000])  # GitHub has comment size limits
                lines.append("```")
            except Exception:
                lines.append(str(output)[:10000])

        # Footer
        lines.append("")
        if duration_seconds:
            lines.append(f"*Duration: {duration_seconds:.1f}s*")

        # Embed run_id for feedback tracking (react with 👍 or 👎)
        if run_id:
            lines.append("")
            lines.append(f"<!-- incidentfox:run_id={run_id} -->")

        return "\n".join(lines)

    def _format_dict_markdown(self, output: dict) -> list[str]:
        """Format dict output as markdown."""
        lines = []

        summary = output.get("summary") or output.get("result") or output.get("message")
        root_cause = output.get("root_cause") or output.get("cause")
        recommendations = output.get("recommendations") or output.get("next_steps") or []
        confidence = output.get("confidence")

        if summary:
            lines.append("### Summary")
            lines.append(summary)
            lines.append("")

        if root_cause:
            lines.append("### Root Cause")
            lines.append(root_cause)
            lines.append("")

        if recommendations:
            lines.append("### Recommendations")
            for rec in recommendations[:10]:
                lines.append(f"- {rec}")
            lines.append("")

        if confidence is not None:
            lines.append(f"**Confidence:** {confidence}%")

        # If no structured fields, dump JSON
        if not any([summary, root_cause, recommendations]):
            try:
                json_str = json.dumps(output, indent=2, default=str, ensure_ascii=False)
                lines.append("```json")
                lines.append(json_str[:10000])
                lines.append("```")
            except Exception:
                lines.append(str(output)[:10000])

        return lines

    def _format_structured_markdown(self, output: Any) -> list[str]:
        """Format pydantic/structured output as markdown."""
        lines = []

        if hasattr(output, "summary") and output.summary:
            lines.append("### Summary")
            lines.append(output.summary)
            lines.append("")

        if hasattr(output, "root_cause"):
            rc = output.root_cause
            if hasattr(rc, "description"):
                lines.append("### Root Cause")
                lines.append(rc.description)
                lines.append("")
            elif rc:
                lines.append("### Root Cause")
                lines.append(str(rc))
                lines.append("")

        if hasattr(output, "recommendations") and output.recommendations:
            lines.append("### Recommendations")
            for rec in output.recommendations[:10]:
                lines.append(f"- {rec}")
            lines.append("")

        if hasattr(output, "confidence") and output.confidence is not None:
            lines.append(f"**Confidence:** {output.confidence}%")

        return lines


class GitHubPRCommentHandler(GitHubOutputHandler):
    """
    Posts agent output as a PR comment.

    Config:
        repo: Repository in "owner/repo" format (required)
        pr_number: Pull request number (required)
        token: GitHub token (optional)
    """

    @property
    def destination_type(self) -> str:
        return "github_pr_comment"

    async def post_initial(
        self,
        config: dict[str, Any],
        task_description: str,
        agent_name: str = "IncidentFox",
    ) -> str | None:
        """Post initial working comment."""
        repo = config.get("repo")
        pr_number = config.get("pr_number")
        token = self._get_token(config)

        if not repo or not pr_number or not token:
            logger.warning("github_pr_missing_config", repo=repo, pr_number=pr_number)
            return None

        try:
            body = f"## 🦊 {agent_name}\n\n⏳ Working on: _{task_description[:200]}_..."

            comment_id = await self._post_comment(
                repo=repo,
                endpoint=f"issues/{pr_number}/comments",
                body=body,
                token=token,
            )

            logger.info(
                "github_pr_initial_posted",
                repo=repo,
                pr_number=pr_number,
                comment_id=comment_id,
            )

            return str(comment_id) if comment_id else None

        except Exception as e:
            logger.error("github_pr_initial_failed", error=str(e))
            return None

    async def update_progress(
        self,
        config: dict[str, Any],
        message_id: str,
        status_text: str,
    ) -> None:
        """Update comment with progress (optional for GitHub)."""
        # GitHub comments don't need frequent updates
        pass

    async def post_final(
        self,
        config: dict[str, Any],
        message_id: str | None,
        output: Any,
        success: bool = True,
        duration_seconds: float | None = None,
        error: str | None = None,
        agent_name: str = "IncidentFox",
    ) -> OutputResult:
        """Post final result as PR comment."""
        repo = config.get("repo")
        pr_number = config.get("pr_number")
        token = self._get_token(config)
        run_id = config.get("run_id")

        if not repo or not pr_number or not token:
            return OutputResult(
                success=False,
                destination_type="github_pr_comment",
                error="Missing repo, pr_number, or token",
            )

        try:
            body = self._format_markdown(
                output=output,
                success=success,
                agent_name=agent_name,
                duration_seconds=duration_seconds,
                error=error,
                run_id=run_id,
            )

            if message_id:
                # Update existing comment
                await self._update_comment(
                    repo=repo,
                    comment_id=int(message_id),
                    body=body,
                    token=token,
                )
                final_id = message_id
            else:
                # Post new comment
                comment_id = await self._post_comment(
                    repo=repo,
                    endpoint=f"issues/{pr_number}/comments",
                    body=body,
                    token=token,
                )
                final_id = str(comment_id) if comment_id else None

            logger.info(
                "github_pr_final_posted",
                repo=repo,
                pr_number=pr_number,
                success=success,
            )

            return OutputResult(
                success=True,
                destination_type="github_pr_comment",
                message_id=final_id,
            )

        except Exception as e:
            logger.error("github_pr_final_failed", error=str(e))
            return OutputResult(
                success=False,
                destination_type="github_pr_comment",
                error=str(e),
            )


class GitHubIssueCommentHandler(GitHubOutputHandler):
    """
    Posts agent output as an issue comment.

    Config:
        repo: Repository in "owner/repo" format (required)
        issue_number: Issue number (required)
        token: GitHub token (optional)
    """

    @property
    def destination_type(self) -> str:
        return "github_issue_comment"

    async def post_initial(
        self,
        config: dict[str, Any],
        task_description: str,
        agent_name: str = "IncidentFox",
    ) -> str | None:
        """Post initial working comment."""
        repo = config.get("repo")
        issue_number = config.get("issue_number")
        token = self._get_token(config)

        if not repo or not issue_number or not token:
            logger.warning("github_issue_missing_config")
            return None

        try:
            body = f"## 🦊 {agent_name}\n\n⏳ Working on: _{task_description[:200]}_..."

            comment_id = await self._post_comment(
                repo=repo,
                endpoint=f"issues/{issue_number}/comments",
                body=body,
                token=token,
            )

            logger.info(
                "github_issue_initial_posted",
                repo=repo,
                issue_number=issue_number,
                comment_id=comment_id,
            )

            return str(comment_id) if comment_id else None

        except Exception as e:
            logger.error("github_issue_initial_failed", error=str(e))
            return None

    async def update_progress(
        self,
        config: dict[str, Any],
        message_id: str,
        status_text: str,
    ) -> None:
        """Update comment with progress."""
        pass  # Not needed for GitHub

    async def post_final(
        self,
        config: dict[str, Any],
        message_id: str | None,
        output: Any,
        success: bool = True,
        duration_seconds: float | None = None,
        error: str | None = None,
        agent_name: str = "IncidentFox",
    ) -> OutputResult:
        """Post final result as issue comment."""
        repo = config.get("repo")
        issue_number = config.get("issue_number")
        token = self._get_token(config)
        run_id = config.get("run_id")

        if not repo or not issue_number or not token:
            return OutputResult(
                success=False,
                destination_type="github_issue_comment",
                error="Missing repo, issue_number, or token",
            )

        try:
            body = self._format_markdown(
                output=output,
                success=success,
                agent_name=agent_name,
                duration_seconds=duration_seconds,
                error=error,
                run_id=run_id,
            )

            if message_id:
                await self._update_comment(
                    repo=repo,
                    comment_id=int(message_id),
                    body=body,
                    token=token,
                )
                final_id = message_id
            else:
                comment_id = await self._post_comment(
                    repo=repo,
                    endpoint=f"issues/{issue_number}/comments",
                    body=body,
                    token=token,
                )
                final_id = str(comment_id) if comment_id else None

            logger.info(
                "github_issue_final_posted",
                repo=repo,
                issue_number=issue_number,
                success=success,
            )

            return OutputResult(
                success=True,
                destination_type="github_issue_comment",
                message_id=final_id,
            )

        except Exception as e:
            logger.error("github_issue_final_failed", error=str(e))
            return OutputResult(
                success=False,
                destination_type="github_issue_comment",
                error=str(e),
            )
