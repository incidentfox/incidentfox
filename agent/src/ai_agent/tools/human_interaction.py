"""
Human interaction tools for requesting input or actions from users.

This module provides a channel-agnostic way for agents to request human input.
The actual interaction mechanism (CLI, Slack, GitHub, etc.) is handled by
the channel layer, not the tool itself.
"""

import json
from typing import Literal

from agents import function_tool

from ..core.logging import get_logger

logger = get_logger(__name__)


# Response type literals
ResponseType = Literal["text", "yes_no", "choice", "action_done"]


@function_tool
def ask_human(
    question: str,
    context: str | None = None,
    action_required: str | None = None,
    response_type: ResponseType = "text",
    choices: list[str] | None = None,
) -> str:
    """
    Ask the human for input or to perform an action.

    Use this tool when you need information from the user or need them to
    take an action before you can continue. The conversation will pause
    until the human responds, then resume automatically.

    WHEN TO USE THIS TOOL:
    - You hit a blocker that requires human action (e.g., invalid credentials)
    - You need clarification or additional information
    - You need confirmation before a potentially impactful action
    - You need the user to provide a secret, token, or other sensitive info

    Args:
        question: The question to ask the human. Be clear and specific.
        context: Optional background context to help the human understand
                 why you're asking. Include relevant details from your investigation.
        action_required: If the human needs to do something external (e.g., run a
                        command, regenerate a token), describe exactly what they
                        need to do. Be specific with commands they should run.
        response_type: Type of response expected:
            - "text": Free-form text input (default)
            - "yes_no": Simple Yes or No confirmation
            - "choice": Select from provided choices
            - "action_done": Human confirms they've completed an action
        choices: For response_type="choice", the list of options to choose from.

    Returns:
        A JSON string with `human_input_required: true` and the request details.
        This signals to the system that human input is needed. The actual human
        response will come in a follow-up message after the session resumes.

        IMPORTANT: After calling this tool, your session is effectively complete.
        Do not call any more tools or continue working - stop immediately.

    Examples:
        # Ask for information
        ask_human(
            question="What namespace should I investigate?",
            context="I found multiple namespaces with similar names.",
            response_type="text"
        )

        # Ask for confirmation
        ask_human(
            question="Should I restart this pod?",
            context="Pod 'web-abc123' has been in CrashLoopBackOff for 2 hours.",
            response_type="yes_no"
        )

        # Ask human to take an action (common for auth issues)
        ask_human(
            question="I need valid Kubernetes credentials to continue the investigation.",
            context="The current credentials are being treated as 'system:anonymous', which doesn't have permission to list pods.",
            action_required="Please regenerate your kubeconfig token and type 'done' when ready. For EKS: aws eks update-kubeconfig --name <cluster>",
            response_type="action_done"
        )

        # Ask to choose from options
        ask_human(
            question="Which environment should I investigate?",
            choices=["production", "staging", "development"],
            response_type="choice"
        )
    """
    # Build the structured request
    request_data = {
        "human_input_required": True,
        "question": question,
        "response_type": response_type,
    }

    if context:
        request_data["context"] = context

    if action_required:
        request_data["action_required"] = action_required

    if choices and response_type == "choice":
        request_data["choices"] = choices

    # Emit event to the current stream (if streaming)
    try:
        from ..core.stream_events import (
            emit_raw_event_to_current_stream,
            get_current_stream_id,
        )

        stream_id = get_current_stream_id()
        if stream_id:
            emitted = emit_raw_event_to_current_stream(
                {
                    "type": "human_input_required",
                    **request_data,
                }
            )
            if emitted:
                logger.info(
                    "human_input_requested_via_stream",
                    question=question[:100],
                    response_type=response_type,
                    stream_id=stream_id,
                )
    except Exception as e:
        logger.debug("stream_event_emission_skipped", reason=str(e))

    logger.info(
        "human_input_requested",
        question=question[:100],
        response_type=response_type,
        has_action_required=action_required is not None,
    )

    # Return structured response
    # The agent should recognize this and pause for human input
    # The CLI/channel will handle the actual interaction and resume
    return json.dumps(request_data)


# ============================================================================
# Abstract Channel Interface (for future Slack/GitHub/WebUI support)
# ============================================================================


class HumanInteractionChannel:
    """
    Abstract base class for human interaction channels.

    Each channel (CLI, Slack, GitHub, WebUI) implements this interface
    to handle the actual user interaction.
    """

    async def ask(
        self,
        question: str,
        context: str | None = None,
        action_required: str | None = None,
        response_type: ResponseType = "text",
        choices: list[str] | None = None,
        timeout: float | None = None,
    ) -> str:
        """
        Ask the human a question and wait for response.

        Args:
            question: The question to ask
            context: Optional context
            action_required: Action the human needs to take
            response_type: Expected response type
            choices: Options for choice response type
            timeout: Optional timeout in seconds

        Returns:
            The human's response

        Raises:
            TimeoutError: If timeout expires before response
            ChannelError: If channel-specific error occurs
        """
        raise NotImplementedError("Subclasses must implement ask()")

    async def notify(
        self,
        message: str,
        level: Literal["info", "warning", "error"] = "info",
    ) -> None:
        """
        Send a notification to the human (no response expected).

        Args:
            message: The message to send
            level: Severity level for formatting
        """
        raise NotImplementedError("Subclasses must implement notify()")

    @property
    def channel_name(self) -> str:
        """Return the name of this channel (e.g., 'cli', 'slack', 'github')."""
        raise NotImplementedError("Subclasses must implement channel_name")


class TerminalChannel(HumanInteractionChannel):
    """
    Terminal/CLI channel for human interaction.

    This is a stub - the actual implementation is in the CLI code
    since it needs access to prompt_toolkit and the terminal.
    """

    @property
    def channel_name(self) -> str:
        return "terminal"

    async def ask(self, question: str, **kwargs) -> str:
        # The actual terminal interaction happens in the CLI
        # This is just a marker/interface
        raise NotImplementedError(
            "Terminal channel interaction is handled by the CLI directly"
        )

    async def notify(self, message: str, level: str = "info") -> None:
        # Notifications in terminal are just prints
        print(f"[{level.upper()}] {message}")


class SlackChannel(HumanInteractionChannel):
    """
    Slack channel for human interaction.

    Posts messages to Slack and waits for thread replies.
    """

    def __init__(
        self,
        bot_token: str,
        channel_id: str,
        thread_ts: str | None = None,
    ):
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.thread_ts = thread_ts

    @property
    def channel_name(self) -> str:
        return "slack"

    async def ask(self, question: str, **kwargs) -> str:
        # TODO: Implement Slack interaction
        # 1. Post message to channel/thread
        # 2. Wait for reply (via webhook or polling)
        # 3. Return reply text
        raise NotImplementedError("Slack channel not yet implemented")

    async def notify(self, message: str, level: str = "info") -> None:
        # TODO: Post to Slack
        raise NotImplementedError("Slack channel not yet implemented")


class GitHubChannel(HumanInteractionChannel):
    """
    GitHub channel for human interaction.

    Posts comments on issues/PRs and waits for replies.
    """

    def __init__(
        self,
        token: str,
        repo: str,
        issue_number: int,
    ):
        self.token = token
        self.repo = repo
        self.issue_number = issue_number

    @property
    def channel_name(self) -> str:
        return "github"

    async def ask(self, question: str, **kwargs) -> str:
        # TODO: Implement GitHub interaction
        # 1. Post comment on issue/PR
        # 2. Wait for reply (via webhook)
        # 3. Return reply text
        raise NotImplementedError("GitHub channel not yet implemented")

    async def notify(self, message: str, level: str = "info") -> None:
        # TODO: Post comment to GitHub
        raise NotImplementedError("GitHub channel not yet implemented")


# Channel registry for runtime selection
_current_channel: HumanInteractionChannel | None = None


def set_current_channel(channel: HumanInteractionChannel) -> None:
    """Set the current human interaction channel."""
    global _current_channel
    _current_channel = channel
    logger.info("human_interaction_channel_set", channel=channel.channel_name)


def get_current_channel() -> HumanInteractionChannel | None:
    """Get the current human interaction channel."""
    return _current_channel
