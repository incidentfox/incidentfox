"""
Slack update hooks for OpenAI Agents SDK.

Provides real-time Slack updates during agent execution by hooking into
tool calls and agent lifecycle events.

Supports dynamic tool categorization - automatically groups tools by their
source module (e.g., kubernetes, aws_tools, postgres_tools) for the
investigation dashboard UI.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agents import RunHooks
from agents.run_context import RunContextWrapper
from agents.tool import Tool

from .logging import get_logger

logger = get_logger(__name__)


# Display configuration for tool categories (auto-detected from module names)
# Keys are the module name suffix (e.g., "kubernetes" from "ai_agent.tools.kubernetes")
CATEGORY_DISPLAY: dict[str, dict[str, str]] = {
    # Infrastructure
    "kubernetes": {
        "label": "Kubernetes: Pod health & events",
        "icon": "",
        "action_id": "view_kubernetes",
    },
    "aws_tools": {
        "label": "AWS: CloudWatch & resources",
        "icon": "",
        "action_id": "view_aws",
    },
    "azure_tools": {
        "label": "Azure: Cloud resources",
        "icon": "",
        "action_id": "view_azure",
    },
    "gcp_tools": {
        "label": "GCP: Cloud resources",
        "icon": "",
        "action_id": "view_gcp",
    },
    "docker_tools": {
        "label": "Docker: Container status",
        "icon": "",
        "action_id": "view_docker",
    },
    # Databases
    "postgres_tools": {
        "label": "PostgreSQL: Database queries",
        "icon": "",
        "action_id": "view_postgres",
    },
    "snowflake_tools": {
        "label": "Snowflake: Data warehouse",
        "icon": "",
        "action_id": "view_snowflake",
    },
    "bigquery_tools": {
        "label": "BigQuery: Data analysis",
        "icon": "",
        "action_id": "view_bigquery",
    },
    "elasticsearch_tools": {
        "label": "Elasticsearch: Search & logs",
        "icon": "",
        "action_id": "view_elasticsearch",
    },
    # Observability
    "coralogix_tools": {
        "label": "Coralogix: Logs & metrics",
        "icon": "",
        "action_id": "view_coralogix",
    },
    "datadog_tools": {
        "label": "Datadog: APM & metrics",
        "icon": "",
        "action_id": "view_datadog",
    },
    "grafana_tools": {
        "label": "Grafana: Dashboards & alerts",
        "icon": "",
        "action_id": "view_grafana",
    },
    "newrelic_tools": {
        "label": "New Relic: APM & traces",
        "icon": "",
        "action_id": "view_newrelic",
    },
    "splunk_tools": {
        "label": "Splunk: Log analysis",
        "icon": "",
        "action_id": "view_splunk",
    },
    "sentry_tools": {
        "label": "Sentry: Error tracking",
        "icon": "",
        "action_id": "view_sentry",
    },
    "log_analysis_tools": {
        "label": "Log Analysis: Patterns & anomalies",
        "icon": "",
        "action_id": "view_logs",
    },
    # Collaboration & Ticketing
    "slack_tools": {
        "label": "Slack: Message search",
        "icon": "",
        "action_id": "view_slack",
    },
    "github_tools": {
        "label": "GitHub: Code & PRs",
        "icon": "",
        "action_id": "view_github",
    },
    "github_app_tools": {
        "label": "GitHub: Code & PRs",
        "icon": "",
        "action_id": "view_github",
    },
    "gitlab_tools": {
        "label": "GitLab: Code & pipelines",
        "icon": "",
        "action_id": "view_gitlab",
    },
    "jira_tools": {
        "label": "Jira: Issue tracking",
        "icon": "",
        "action_id": "view_jira",
    },
    "linear_tools": {
        "label": "Linear: Issue tracking",
        "icon": "",
        "action_id": "view_linear",
    },
    "pagerduty_tools": {
        "label": "PagerDuty: Incidents & alerts",
        "icon": "",
        "action_id": "view_pagerduty",
    },
    "confluence_tools": {
        "label": "Confluence: Documentation",
        "icon": "",
        "action_id": "view_confluence",
    },
    "notion_tools": {
        "label": "Notion: Documentation",
        "icon": "",
        "action_id": "view_notion",
    },
    # CI/CD
    "ci_tools": {
        "label": "CI/CD: Pipeline status",
        "icon": "",
        "action_id": "view_ci",
    },
    "codepipeline_tools": {
        "label": "CodePipeline: AWS CI/CD",
        "icon": "",
        "action_id": "view_codepipeline",
    },
    # Analysis
    "anomaly_tools": {
        "label": "Anomaly Detection: Statistical analysis",
        "icon": "",
        "action_id": "view_anomaly",
    },
    "dependency_tools": {
        "label": "Dependencies: Service graph",
        "icon": "",
        "action_id": "view_dependencies",
    },
    "remediation_tools": {
        "label": "Remediation: Actions & rollbacks",
        "icon": "",
        "action_id": "view_remediation",
    },
    # Git
    "git_tools": {
        "label": "Git: Repository history",
        "icon": "",
        "action_id": "view_git",
    },
    # Other
    "knowledge_base_tools": {
        "label": "Knowledge Base: Documentation",
        "icon": "",
        "action_id": "view_kb",
    },
    "coding_tools": {
        "label": "Code Analysis: Files & search",
        "icon": "",
        "action_id": "view_code",
    },
    "sourcegraph_tools": {
        "label": "Sourcegraph: Code search",
        "icon": "",
        "action_id": "view_sourcegraph",
    },
    "meeting_tools": {
        "label": "Meetings: Transcripts & notes",
        "icon": "",
        "action_id": "view_meetings",
    },
    "msteams_tools": {
        "label": "MS Teams: Messages",
        "icon": "",
        "action_id": "view_msteams",
    },
    # Special: root cause analysis (added at the end)
    "root_cause_analysis": {
        "label": "Root cause analysis",
        "icon": "",
        "action_id": "view_rca",
    },
}

# Default display for unknown categories
DEFAULT_CATEGORY_DISPLAY = {
    "label": "Analysis",
    "icon": "",
    "action_id": "view_analysis",
}


def _extract_category_from_module(module: str) -> str | None:
    """Extract category from a module path like 'ai_agent.tools.kubernetes'."""
    if not module:
        return None
    parts = module.split(".")
    if "tools" in parts:
        idx = parts.index("tools")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def _extract_original_function_from_closure(tool: Tool):
    """
    Extract the original function from a FunctionTool's closure chain.

    OpenAI Agents SDK's FunctionTool stores the original function in a nested
    closure structure:
        tool.on_invoke_tool
            -> __closure__[0] = _on_invoke_tool_impl
                -> __closure__[1] = original_function

    Returns:
        The original function if found, None otherwise.
    """
    try:
        on_invoke = getattr(tool, "on_invoke_tool", None)
        if on_invoke is None or not hasattr(on_invoke, "__closure__"):
            return None

        closure = on_invoke.__closure__
        if not closure or len(closure) < 1:
            return None

        # Get _on_invoke_tool_impl from first closure cell
        impl = closure[0].cell_contents
        if not hasattr(impl, "__closure__") or not impl.__closure__:
            return None

        impl_closure = impl.__closure__
        if len(impl_closure) < 2:
            return None

        # Get original function from second closure cell of impl
        original_fn = impl_closure[1].cell_contents
        if callable(original_fn):
            return original_fn

        return None
    except (IndexError, ValueError, AttributeError):
        return None


def get_category_from_tool(tool: Tool) -> str | None:
    """
    Extract category from a tool's module path.

    For FunctionTool from OpenAI Agents SDK, extracts the original function
    from the closure chain to get its __module__.

    Examples:
        ai_agent.tools.kubernetes.list_pods -> "kubernetes"
        ai_agent.tools.aws_tools.get_cloudwatch_logs -> "aws_tools"
        ai_agent.tools.log_analysis_tools.get_log_statistics -> "log_analysis_tools"

    Returns:
        Category string or None if not determinable
    """
    try:
        tool_name = getattr(tool, "name", str(tool))
        tool_type = type(tool).__name__
        module = None

        # Method 1: Extract original function from FunctionTool closure chain
        # This is the primary method for tools created with @function_tool
        original_fn = _extract_original_function_from_closure(tool)
        if original_fn:
            module = getattr(original_fn, "__module__", None)

        # Method 2: Try direct function attributes (for other Tool types)
        if not module or "tools" not in module:
            for attr_name in ("fn", "func", "_fn", "function"):
                attr = getattr(tool, attr_name, None)
                if attr is not None and callable(attr):
                    attr_module = getattr(attr, "__module__", None)
                    if attr_module and "tools" in attr_module:
                        module = attr_module
                        break

        # Method 3: Check tool instance's own __module__
        if not module or "tools" not in module:
            tool_module = getattr(tool, "__module__", None)
            if tool_module and "tools" in tool_module:
                module = tool_module

        if not module:
            logger.debug(
                "get_category_no_module",
                tool=tool_name,
                tool_type=tool_type,
                has_original_fn=original_fn is not None,
            )
            return None

        # Extract category from module path
        category = _extract_category_from_module(module)

        if category:
            logger.debug(
                "get_category_from_module",
                tool=tool_name,
                module=module,
                category=category,
            )
            return category

        logger.debug(
            "get_category_no_tools_in_path",
            tool=tool_name,
            module=module,
        )
        return None

    except Exception as e:
        logger.debug(
            "get_category_exception",
            tool=getattr(tool, "name", str(tool)),
            error=str(e),
        )
        return None


def get_category_display(category: str) -> dict[str, str]:
    """Get display configuration for a category."""
    return CATEGORY_DISPLAY.get(
        category,
        {
            **DEFAULT_CATEGORY_DISPLAY,
            "label": f"{category.replace('_', ' ').title()}: Analysis",
        },
    )


@dataclass
class PhaseUpdate:
    """Represents an update for an investigation phase."""

    phase: str
    status: str  # 'running', 'done', 'failed'
    tool_name: str
    summary: str | None = None
    duration_seconds: float | None = None


@dataclass
class SlackUpdateState:
    """
    Tracks state for Slack updates during an investigation.

    Thread-safe: Uses a lock to protect concurrent access from multiple
    agent threads (planner, investigation, k8s, etc.).
    """

    channel_id: str
    message_ts: str
    thread_ts: str | None = None

    # Phase status tracking (category -> status)
    phase_status: dict[str, str] = field(default_factory=dict)
    # Phase results (category -> accumulated results text)
    phase_results: dict[str, str] = field(default_factory=dict)
    # Track which categories we've seen (in order of first appearance)
    discovered_categories: list[str] = field(default_factory=list)

    # Tool call tracking (for batching)
    pending_tool_updates: list[PhaseUpdate] = field(default_factory=list)
    tool_start_times: dict[str, float] = field(default_factory=dict)
    # Track tool -> category mapping for running tools
    tool_categories: dict[str, str] = field(default_factory=dict)

    # Debounce tracking
    last_update_time: float = 0
    update_debounce_seconds: float = 2.0  # Min time between Slack updates

    # Investigation metadata
    incident_id: str | None = None
    severity: str | None = None
    title: str = "IncidentFox Investigation"

    # Thread synchronization lock for multi-agent access
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get_active_phases(self) -> dict[str, dict[str, str]]:
        """
        Get the phases that have been used in this investigation.

        Returns dict of category -> display info, in order of first use.
        Always includes root_cause_analysis at the end.
        """
        phases = {}
        for cat in self.discovered_categories:
            phases[cat] = get_category_display(cat)

        # Always add RCA at the end if we have any phases
        if phases and "root_cause_analysis" not in phases:
            phases["root_cause_analysis"] = CATEGORY_DISPLAY["root_cause_analysis"]

        return phases


class SlackUpdateHooks(RunHooks):
    """
    RunHooks implementation that sends real-time updates to Slack.

    Key features:
    - Automatically groups tool calls by their source module (dynamic phases)
    - Debounces updates to avoid spamming Slack
    - Provides meaningful status updates without overwhelming detail
    """

    def __init__(
        self,
        state: SlackUpdateState,
        slack_client: Any,
        on_phase_complete: Callable[[str, str], Awaitable[None]] | None = None,
    ):
        """
        Initialize Slack update hooks.

        Args:
            state: SlackUpdateState with channel/message info
            slack_client: Slack WebClient for posting updates
            on_phase_complete: Optional callback when a phase completes
        """
        self.state = state
        self.slack_client = slack_client
        self.on_phase_complete = on_phase_complete
        # NOTE: We use threading.Lock for cross-event-loop safety.
        # asyncio.Lock() fails when hooks are called from subagent threads
        # that run in different event loops. Simple debounce without deferred
        # updates is sufficient for progress tracking.
        self._debounce_lock = threading.Lock()

    async def on_tool_start(
        self,
        context: RunContextWrapper,
        agent: Any,
        tool: Tool,
    ) -> None:
        """Called when a tool is about to run."""
        hook_start = time.time()
        tool_name = getattr(tool, "name", str(tool))
        try:

            # Auto-detect category from tool's module
            category = get_category_from_tool(tool)
            if not category:
                # Try to infer from tool name patterns
                category = self._infer_category_from_name(tool_name)

            if not category:
                logger.debug("slack_hook_tool_no_category", tool=tool_name)
                return

            # Thread-safe state update
            should_update = False
            with self.state._lock:
                self.state.tool_start_times[tool_name] = time.time()
                self.state.tool_categories[tool_name] = category

                # Track this category if we haven't seen it yet
                if category not in self.state.discovered_categories:
                    self.state.discovered_categories.append(category)

                # Mark phase as running if not already done
                if self.state.phase_status.get(category) != "done":
                    old_status = self.state.phase_status.get(category)
                    if old_status != "running":
                        self.state.phase_status[category] = "running"
                        should_update = True

            # Schedule update outside the lock to avoid deadlock
            if should_update:
                await self._schedule_update()

            hook_duration = int((time.time() - hook_start) * 1000)
            logger.debug(
                "slack_hook_tool_start",
                tool=tool_name,
                category=category,
                duration_ms=hook_duration,
            )
            # Warn if hook took too long
            if hook_duration > 500:
                logger.warning(
                    "slack_hook_tool_start_slow",
                    tool=tool_name,
                    duration_ms=hook_duration,
                )

        except Exception as e:
            hook_duration = int((time.time() - hook_start) * 1000)
            logger.warning(
                "slack_hook_error",
                error=str(e),
                hook="on_tool_start",
                tool=tool_name,
                duration_ms=hook_duration,
            )

    async def on_tool_end(
        self,
        context: RunContextWrapper,
        agent: Any,
        tool: Tool,
        result: str,
    ) -> None:
        """Called when a tool finishes."""
        hook_start = time.time()
        tool_name = getattr(tool, "name", str(tool))
        try:

            # Thread-safe state update
            with self.state._lock:
                # Get category from tracking (set in on_tool_start)
                category = self.state.tool_categories.pop(tool_name, None)
                if not category:
                    # Fallback: try to detect again
                    category = get_category_from_tool(tool)
                    if not category:
                        category = self._infer_category_from_name(tool_name)
                    if not category:
                        return

                # Calculate duration
                start_time = self.state.tool_start_times.pop(tool_name, None)
                duration = time.time() - start_time if start_time else None

                # Extract a brief summary from the result
                summary = self._extract_summary(tool_name, result)

                # Queue the update
                update = PhaseUpdate(
                    phase=category,
                    status="done",
                    tool_name=tool_name,
                    summary=summary,
                    duration_seconds=duration,
                )
                self.state.pending_tool_updates.append(update)

                # Store phase result
                if category not in self.state.phase_results:
                    self.state.phase_results[category] = ""
                self.state.phase_results[
                    category
                ] += f"\n\n**{tool_name}:**\n{result[:1000]}"

            await self._schedule_update()

            hook_duration = int((time.time() - hook_start) * 1000)
            logger.debug(
                "slack_hook_tool_end",
                tool=tool_name,
                category=category,
                tool_duration=duration,
                hook_duration_ms=hook_duration,
            )
            # Warn if hook took too long
            if hook_duration > 500:
                logger.warning(
                    "slack_hook_tool_end_slow",
                    tool=tool_name,
                    hook_duration_ms=hook_duration,
                    message="SlackUpdateHooks.on_tool_end took >500ms - may delay agent",
                )

        except Exception as e:
            hook_duration = int((time.time() - hook_start) * 1000)
            logger.warning(
                "slack_hook_error",
                error=str(e),
                hook="on_tool_end",
                tool=tool_name,
                hook_duration_ms=hook_duration,
            )

    def _infer_category_from_name(self, tool_name: str) -> str | None:
        """Infer category from tool name patterns when module detection fails."""
        name_lower = tool_name.lower()

        # Map common tool name patterns to categories
        patterns = {
            ("k8s", "pod", "deployment", "namespace", "kubectl"): "kubernetes",
            ("aws", "ec2", "cloudwatch", "lambda", "ecs", "rds"): "aws_tools",
            ("azure", "aks"): "azure_tools",
            ("gcp", "gcloud", "bigquery"): "gcp_tools",
            ("postgres", "pg_"): "postgres_tools",
            ("snowflake",): "snowflake_tools",
            ("coralogix",): "coralogix_tools",
            ("datadog",): "datadog_tools",
            ("grafana",): "grafana_tools",
            ("splunk",): "splunk_tools",
            ("elasticsearch", "es_"): "elasticsearch_tools",
            ("github", "gh_"): "github_tools",
            ("gitlab", "gl_"): "gitlab_tools",
            ("jira",): "jira_tools",
            ("slack",): "slack_tools",
            ("docker",): "docker_tools",
            ("git_", "git_log", "git_diff"): "git_tools",
            ("sentry",): "sentry_tools",
            ("pagerduty", "pd_"): "pagerduty_tools",
        }

        for keywords, category in patterns.items():
            if any(kw in name_lower for kw in keywords):
                return category

        return None

    def _extract_summary(self, tool_name: str, result: str) -> str | None:
        """Extract a one-line summary from tool result."""
        if not result:
            return None

        # Truncate and clean up
        result = result.strip()

        # Try to extract key info based on tool type
        if "error" in tool_name.lower():
            # Count errors
            error_count = result.lower().count("error")
            if error_count > 0:
                return f"Found {error_count} error(s)"

        if "incidents" in tool_name.lower() or "history" in tool_name.lower():
            # Try to count incidents
            import re

            matches = re.findall(r"(\d+)\s+incident", result.lower())
            if matches:
                return f"Found {matches[0]} related incident(s)"

        # Default: first line, truncated
        first_line = result.split("\n")[0][:80]
        return first_line if len(first_line) > 10 else None

    async def _schedule_update(self) -> None:
        """Schedule a debounced Slack update.

        Uses threading.Lock for cross-event-loop safety. Subagents run in
        separate threads with their own event loops, so asyncio.Lock would
        fail with "bound to a different event loop" error.

        Simple debounce: if enough time has passed, send immediately.
        Otherwise skip (next event will trigger update anyway).
        """
        now = time.time()
        should_update = False

        # Thread-safe check and update of debounce timing
        with self._debounce_lock:
            with self.state._lock:
                time_since_last = now - self.state.last_update_time
                debounce_seconds = self.state.update_debounce_seconds

                if time_since_last >= debounce_seconds:
                    # Mark that we're sending an update
                    self.state.last_update_time = now
                    should_update = True

        # Send update outside locks
        if should_update:
            await self._send_update()

    async def _send_update(self) -> None:
        """Send the actual Slack update."""
        try:
            from ..integrations.slack_ui import build_investigation_dashboard

            # Thread-safe state snapshot and update
            phase_complete_callbacks = []
            with self.state._lock:
                # Determine which phases are complete
                # A phase is "done" if we've received tool results from it
                # and there are no more tools running in that phase
                running_tools_by_category: dict[str, int] = {}
                for tool_name, category in self.state.tool_categories.items():
                    if tool_name in self.state.tool_start_times:
                        running_tools_by_category[category] = (
                            running_tools_by_category.get(category, 0) + 1
                        )

                for update in self.state.pending_tool_updates:
                    # If no more tools running in this category and we have results, mark done
                    if running_tools_by_category.get(update.phase, 0) == 0:
                        if update.phase in self.state.phase_results:
                            self.state.phase_status[update.phase] = "done"
                            if self.on_phase_complete:
                                # Queue callback to run outside lock
                                phase_complete_callbacks.append(
                                    (
                                        update.phase,
                                        self.state.phase_results[update.phase],
                                    )
                                )

                self.state.pending_tool_updates.clear()

                # Get the active phases for this investigation (dynamic)
                active_phases = self.state.get_active_phases()

                # Snapshot current state for building blocks
                phase_status_snapshot = dict(self.state.phase_status)
                title = self.state.title
                incident_id = self.state.incident_id
                severity = self.state.severity
                channel_id = self.state.channel_id
                message_ts = self.state.message_ts

            # Run callbacks outside the lock to avoid deadlock
            for phase, results in phase_complete_callbacks:
                await self.on_phase_complete(phase, results)

            # Build and send dashboard (outside lock - read-only operations)
            blocks = build_investigation_dashboard(
                phase_status=phase_status_snapshot,
                title=title,
                incident_id=incident_id,
                severity=severity,
                phases=active_phases,
            )

            # CRITICAL: This Slack API call can hang on network issues
            # Add timing to detect if this is causing stuck agents
            slack_call_start = time.time()
            logger.info(
                "slack_hook_api_call_starting",
                channel=channel_id,
                message_ts=message_ts,
                message="About to call slack_client.chat_update - if this hangs, check network/rate limits",
            )

            await self.slack_client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text="Investigation in progress...",
                blocks=blocks,
            )

            slack_call_duration = int((time.time() - slack_call_start) * 1000)
            logger.info(
                "slack_hook_api_call_completed",
                channel=channel_id,
                message_ts=message_ts,
                duration_ms=slack_call_duration,
            )

            # Warn if Slack call was slow
            if slack_call_duration > 2000:  # > 2 seconds
                logger.warning(
                    "slack_hook_api_call_slow",
                    channel=channel_id,
                    duration_ms=slack_call_duration,
                    message="Slack API call took >2s - may cause timing issues",
                )

            # Update timestamp (thread-safe)
            with self.state._lock:
                self.state.last_update_time = time.time()

            logger.debug("slack_update_sent", phases=phase_status_snapshot)

        except Exception as e:
            logger.error(
                "slack_update_failed",
                error=str(e),
                error_type=type(e).__name__,
                channel=channel_id if "channel_id" in dir() else "unknown",
            )

    async def finalize(
        self,
        findings: str | None = None,
        confidence: int | None = None,
    ) -> None:
        """
        Finalize the investigation and send the final update.

        Args:
            findings: Root cause analysis findings
            confidence: Confidence score 0-100
        """
        try:
            from ..integrations.slack_ui import build_investigation_dashboard

            # Thread-safe state update and snapshot
            with self.state._lock:
                # Mark all in-progress phases as done
                for phase in list(self.state.phase_status.keys()):
                    if self.state.phase_status[phase] == "running":
                        self.state.phase_status[phase] = "done"

                # Mark RCA phase as done
                self.state.phase_status["root_cause_analysis"] = "done"

                # Ensure RCA is in discovered categories
                if "root_cause_analysis" not in self.state.discovered_categories:
                    self.state.discovered_categories.append("root_cause_analysis")

                # Get the active phases for this investigation (dynamic)
                active_phases = self.state.get_active_phases()

                # Snapshot state for building blocks
                phase_status_snapshot = dict(self.state.phase_status)
                title = self.state.title
                incident_id = self.state.incident_id
                severity = self.state.severity
                channel_id = self.state.channel_id
                message_ts = self.state.message_ts

            # Build final dashboard with dynamic phases (outside lock)
            blocks = build_investigation_dashboard(
                phase_status=phase_status_snapshot,
                title=title,
                incident_id=incident_id,
                severity=severity,
                findings=findings,
                confidence=confidence,
                show_actions=True,
                phases=active_phases,
            )

            await self.slack_client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text="Investigation complete",
                blocks=blocks,
            )

            logger.info(
                "slack_investigation_finalized", incident_id=self.state.incident_id
            )

        except Exception as e:
            logger.error("slack_finalize_failed", error=str(e))
