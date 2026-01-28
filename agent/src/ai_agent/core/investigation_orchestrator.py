"""
Investigation orchestrator with real-time Slack updates.

Provides a high-level API for running investigations with:
- Progressive Slack dashboard updates
- Phase-based progress tracking
- Formatted output with RCA and action buttons
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from agents import Agent, Runner

from ..integrations.slack_mrkdwn import markdown_to_slack_mrkdwn
from ..integrations.slack_ui import (
    INVESTIGATION_PHASES,
    build_investigation_dashboard,
)
from .logging import get_logger
from .slack_hooks import SlackUpdateHooks, SlackUpdateState

logger = get_logger(__name__)


@dataclass
class InvestigationResult:
    """Result of an investigation."""

    success: bool
    findings: str | None = None
    root_cause: str | None = None
    confidence: int | None = None
    recommendations: list = None
    phase_results: dict[str, str] = None
    error: str | None = None
    duration_seconds: float = 0

    def __post_init__(self):
        if self.recommendations is None:
            self.recommendations = []
        if self.phase_results is None:
            self.phase_results = {}


class InvestigationOrchestrator:
    """
    Orchestrates investigations with real-time Slack updates.

    Usage:
        orchestrator = InvestigationOrchestrator(
            agent=investigation_agent,
            slack_client=slack_client,
        )

        result = await orchestrator.run_investigation(
            channel_id="C123...",
            prompt="Investigate service errors",
            incident_id="INC-123",
            severity="high",
        )
    """

    def __init__(
        self,
        agent: Agent,
        slack_client: Any,
        timeout: int = 900,
        max_turns: int = 500,
    ):
        """
        Initialize the orchestrator.

        Args:
            agent: The investigation agent to use
            slack_client: Slack WebClient for posting updates
            timeout: Max investigation time in seconds
            max_turns: Max LLM turns for the agent
        """
        self.agent = agent
        self.slack_client = slack_client
        self.timeout = timeout
        self.max_turns = max_turns
        self.runner = Runner()

    async def run_investigation(
        self,
        channel_id: str,
        prompt: str,
        *,
        thread_ts: str | None = None,
        incident_id: str | None = None,
        severity: str | None = None,
        title: str = "IncidentFox Investigation",
        context: str | None = None,
        run_id: str | None = None,
    ) -> InvestigationResult:
        """
        Run an investigation with real-time Slack updates.

        Args:
            channel_id: Slack channel ID to post to
            prompt: Investigation prompt/query
            thread_ts: Optional thread timestamp for replies
            incident_id: Optional incident ID for display
            severity: Optional severity level
            title: Dashboard title
            context: Optional additional context
            run_id: Optional agent run ID for tool call tracking

        Returns:
            InvestigationResult with findings and phase results
        """
        import time

        start_time = time.time()

        try:
            # 1. Post initial dashboard message
            initial_status = {phase: "pending" for phase in INVESTIGATION_PHASES}
            initial_blocks = build_investigation_dashboard(
                phase_status=initial_status,
                title=title,
                incident_id=incident_id,
                severity=severity,
                context_text=f"_Investigating: {prompt[:100]}{'...' if len(prompt) > 100 else ''}_",
                run_id=run_id,
            )

            result = await self.slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Starting investigation...",
                blocks=initial_blocks,
            )
            message_ts = result["ts"]

            logger.info(
                "investigation_started",
                channel=channel_id,
                message_ts=message_ts,
                incident_id=incident_id,
            )

            # 2. Set up Slack update hooks
            state = SlackUpdateState(
                channel_id=channel_id,
                message_ts=message_ts,
                thread_ts=thread_ts,
                run_id=run_id,
                incident_id=incident_id,
                severity=severity,
                title=title,
            )

            hooks = SlackUpdateHooks(
                state=state,
                slack_client=self.slack_client,
            )

            # 3. Build the full prompt
            full_prompt = prompt
            if context:
                full_prompt = f"{prompt}\n\nAdditional context:\n{context}"

            # 4. Run the agent with hooks
            agent_result = await asyncio.wait_for(
                self.runner.run(
                    self.agent,
                    full_prompt,
                    hooks=hooks,
                    max_turns=self.max_turns,
                ),
                timeout=self.timeout,
            )

            # 5. Extract findings from agent output
            output = getattr(agent_result, "final_output", None) or getattr(
                agent_result, "output", None
            )
            findings, root_cause, confidence, recommendations = self._extract_findings(
                output
            )

            # Convert findings to Slack mrkdwn
            findings_mrkdwn = markdown_to_slack_mrkdwn(findings) if findings else None

            # 6. Send final update with RCA
            await hooks.finalize(
                findings=findings_mrkdwn,
                confidence=confidence,
            )

            duration = time.time() - start_time

            logger.info(
                "investigation_completed",
                channel=channel_id,
                incident_id=incident_id,
                duration_seconds=round(duration, 2),
                confidence=confidence,
            )

            return InvestigationResult(
                success=True,
                findings=findings,
                root_cause=root_cause,
                confidence=confidence,
                recommendations=recommendations,
                phase_results=state.phase_results,
                duration_seconds=duration,
            )

        except TimeoutError:
            duration = time.time() - start_time
            error_msg = f"Investigation timed out after {self.timeout}s"

            logger.error(
                "investigation_timeout",
                channel=channel_id,
                incident_id=incident_id,
                timeout=self.timeout,
            )

            # Try to post error message
            await self._post_error(channel_id, message_ts, error_msg)

            return InvestigationResult(
                success=False,
                error=error_msg,
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.time() - start_time
            error_msg = str(e)

            logger.error(
                "investigation_failed",
                channel=channel_id,
                incident_id=incident_id,
                error=error_msg,
                exc_info=True,
            )

            # Try to post error message
            try:
                await self._post_error(channel_id, message_ts, error_msg)
            except Exception:
                pass

            return InvestigationResult(
                success=False,
                error=error_msg,
                duration_seconds=duration,
            )

    def _extract_findings(self, output: Any) -> tuple:
        """
        Extract findings from agent output.

        Returns:
            Tuple of (findings, root_cause, confidence, recommendations)
        """
        if output is None:
            return (None, None, None, [])

        # Handle Pydantic model output (InvestigationResult)
        if hasattr(output, "summary"):
            findings = output.summary
            root_cause = None
            confidence = None
            recommendations = []

            if hasattr(output, "root_cause") and output.root_cause:
                if hasattr(output.root_cause, "description"):
                    root_cause = output.root_cause.description
                    confidence = getattr(output.root_cause, "confidence", None)
                else:
                    root_cause = str(output.root_cause)

            if hasattr(output, "recommendations"):
                recommendations = output.recommendations or []

            # Build a formatted findings string
            parts = [f"*Summary:* {findings}"]
            if root_cause:
                parts.append(f"\n*Root Cause:* {root_cause}")
            if recommendations:
                parts.append("\n*Recommendations:*")
                for rec in recommendations[:5]:
                    parts.append(f"• {rec}")

            return ("\n".join(parts), root_cause, confidence, recommendations)

        # Handle InvestigationSummary (from planner)
        if hasattr(output, "summary") and hasattr(output, "confidence"):
            findings = output.summary
            root_cause = getattr(output, "root_cause", None)
            confidence = getattr(output, "confidence", None)
            recommendations = getattr(output, "recommendations", [])

            parts = [f"*Summary:* {findings}"]
            if root_cause:
                parts.append(f"\n*Root Cause:* {root_cause}")
            if recommendations:
                parts.append("\n*Recommendations:*")
                for rec in recommendations[:5]:
                    parts.append(f"• {rec}")

            return ("\n".join(parts), root_cause, confidence, recommendations)

        # Handle dict output
        if isinstance(output, dict):
            summary = output.get("summary", "")
            root_cause = output.get("root_cause", "")
            confidence = output.get("confidence")
            recommendations = output.get("recommendations", [])

            parts = []
            if summary:
                parts.append(f"*Summary:* {summary}")
            if root_cause:
                parts.append(f"\n*Root Cause:* {root_cause}")
            if recommendations:
                parts.append("\n*Recommendations:*")
                for rec in recommendations[:5]:
                    parts.append(f"• {rec}")

            return (
                "\n".join(parts) or str(output),
                root_cause,
                confidence,
                recommendations,
            )

        # Handle string output
        if isinstance(output, str):
            return (output, None, None, [])

        # Fallback
        return (str(output), None, None, [])

    async def _post_error(
        self,
        channel_id: str,
        message_ts: str,
        error_msg: str,
    ) -> None:
        """Post an error update to Slack."""
        try:
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🦊 IncidentFox Investigation",
                        "emoji": True,
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":x: *Investigation Error*\n\n```{error_msg[:500]}```",
                    },
                },
            ]

            await self.slack_client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text="Investigation failed",
                blocks=blocks,
            )
        except Exception as e:
            logger.error("error_post_failed", error=str(e))


async def run_slack_investigation(
    agent: Agent,
    slack_client: Any,
    channel_id: str,
    prompt: str,
    *,
    thread_ts: str | None = None,
    incident_id: str | None = None,
    severity: str | None = None,
    title: str = "IncidentFox Investigation",
    timeout: int = 900,
    max_turns: int = 500,
) -> InvestigationResult:
    """
    Convenience function to run an investigation with Slack updates.

    This is a simpler API that creates an orchestrator and runs the investigation.
    """
    orchestrator = InvestigationOrchestrator(
        agent=agent,
        slack_client=slack_client,
        timeout=timeout,
        max_turns=max_turns,
    )

    return await orchestrator.run_investigation(
        channel_id=channel_id,
        prompt=prompt,
        thread_ts=thread_ts,
        incident_id=incident_id,
        severity=severity,
        title=title,
    )
