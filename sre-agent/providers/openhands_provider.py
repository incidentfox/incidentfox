"""
OpenHands SDK Provider for SRE Agent.

This module implements the LLMProvider interface using OpenHands SDK,
enabling multi-LLM support (Claude, Gemini, OpenAI, etc.).
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from events import (
    StreamEvent,
    error_event,
    question_event,
    result_event,
    thought_event,
    tool_end_event,
    tool_start_event,
)

from providers.base import LLMProvider, ProviderConfig

logger = logging.getLogger(__name__)


class OpenHandsProvider(LLMProvider):
    """
    LLM Provider using OpenHands SDK.

    Supports multiple LLM backends via LiteLLM:
    - anthropic/claude-sonnet-4-20250514
    - gemini/gemini-2.0-flash
    - openai/gpt-4o
    """

    def __init__(self, config: ProviderConfig):
        super().__init__(config)

        # OpenHands components (lazily initialized)
        self._agent = None
        self._workspace = None
        self._conversation = None
        self._events_captured: list = []
        self._pending_tool_ends: list = []
        self._answer_callback: Optional[Callable] = None
        self._pending_answer_event: Optional[asyncio.Event] = None
        self._pending_answer: Optional[dict] = None

        # LLM configuration from environment
        self._model = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-20250514")
        self._api_key = self._get_api_key()

    def _get_api_key(self) -> str:
        """Get API key based on model provider."""
        model = self._model.lower()
        if model.startswith("anthropic/"):
            return os.getenv("ANTHROPIC_API_KEY", "")
        elif model.startswith("gemini/"):
            return os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
        elif model.startswith("openai/"):
            return os.getenv("OPENAI_API_KEY", "")
        else:
            # Try generic key
            return os.getenv("LLM_API_KEY", "")

    def _build_system_prompt(self) -> str:
        """Build system prompt including skills."""
        base_prompt = """You are an AI SRE (Site Reliability Engineering) agent.
Your job is to investigate incidents, analyze logs, debug infrastructure issues,
and help with remediation.

## Available Skills
You have access to skills in the .claude/skills/ directory. Read these to learn
methodologies for specific tasks like Kubernetes debugging, log analysis, etc.

## Core Principles
- Always investigate before acting
- Use dry-run mode for dangerous operations
- Report findings clearly and concisely
- Ask for clarification when needed
"""
        return base_prompt

    async def start(self) -> None:
        """Initialize the OpenHands session."""
        try:
            from openhands.sdk import (
                LLM,
                Agent,
                LocalConversation,
                LocalWorkspace,
                Tool,
            )

            # Create LLM
            self._llm = LLM(model=self._model, api_key=self._api_key)
            logger.info(f"[OpenHands] LLM configured: {self._model}")

            # Create workspace
            workspace_dir = Path(self.config.cwd)
            workspace_dir.mkdir(parents=True, exist_ok=True)
            self._workspace = LocalWorkspace(working_dir=workspace_dir)
            logger.info(f"[OpenHands] Workspace: {workspace_dir}")

            # Map tools
            tools = self._map_tools()

            # Create agent
            self._agent = Agent(
                llm=self._llm,
                tools=tools,
                system_prompt_kwargs={
                    "custom_instructions": self._build_system_prompt()
                },
            )
            logger.info(f"[OpenHands] Agent created with {len(tools)} tools")

        except ImportError as e:
            raise ImportError(
                f"OpenHands SDK not installed. Install with: pip install openhands-sdk>=1.7.0\n"
                f"Error: {e}"
            )

    def _map_tools(self) -> list:
        """Map allowed tools to OpenHands Tool objects."""
        from openhands.sdk import Tool

        # Mapping from Claude SDK tool names to OpenHands tool names
        tool_mapping = {
            "Bash": "TerminalTool",
            "Read": "FileEditorTool",
            "Write": "FileEditorTool",
            "Edit": "FileEditorTool",
            "Glob": "TerminalTool",  # Use terminal for glob
            "Grep": "TerminalTool",  # Use terminal for grep
            "WebFetch": "WebBrowserTool",
            "WebSearch": "WebBrowserTool",
            # "Skill" - handled via prompt injection
            # "Task" - handled via manual multi-agent orchestration
            # "AskUserQuestion" - needs custom implementation
        }

        # Deduplicate tools
        openhands_tools = set()
        for tool_name in self.config.allowed_tools:
            if tool_name in tool_mapping:
                openhands_tools.add(tool_mapping[tool_name])

        return [Tool(name=t) for t in openhands_tools]

    async def execute(
        self,
        prompt: str,
        images: Optional[list[dict]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Execute a query and stream events."""
        if self._agent is None:
            raise RuntimeError("Session not started. Call start() first.")

        from openhands.sdk import LocalConversation

        self.is_running = True
        self._was_interrupted = False
        self._events_captured = []
        self._pending_tool_ends = []
        final_text = ""
        success = False
        error_occurred = False

        # Create event callback
        def event_callback(event):
            """Capture OpenHands events."""
            self._events_captured.append(event)

        try:
            # Create conversation for this execution
            self._conversation = LocalConversation(
                agent=self._agent,
                workspace=self._workspace,
                callbacks=[event_callback],
            )

            # Build prompt with images if provided
            full_prompt = prompt
            if images:
                # OpenHands doesn't have the same image input pattern
                # For now, note the images in the prompt
                logger.warning(
                    f"[OpenHands] Image input not fully supported yet. {len(images)} image(s) provided."
                )
                full_prompt = f"[Note: {len(images)} image(s) were provided but image processing is limited]\n\n{prompt}"

            # Send message and run
            logger.info(f"[OpenHands] Executing prompt for thread {self.thread_id}")
            self._conversation.send_message(full_prompt)

            # Run in thread to allow async streaming
            # OpenHands run() is blocking, so we need to handle this carefully
            import concurrent.futures

            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Start run in background
                future = loop.run_in_executor(executor, self._conversation.run)

                # Stream events as they come in
                last_event_count = 0
                while not future.done():
                    # Yield any new events
                    current_events = self._events_captured[last_event_count:]
                    for event in current_events:
                        async for stream_event in self._convert_event(event):
                            yield stream_event
                    last_event_count = len(self._events_captured)

                    # Small sleep to avoid busy waiting
                    await asyncio.sleep(0.1)

                # Get result (may raise exception)
                try:
                    future.result()
                    success = True
                except Exception as e:
                    logger.error(f"[OpenHands] Execution error: {e}")
                    error_occurred = True
                    yield error_event(self.thread_id, str(e), recoverable=False)

            # Process any remaining events
            remaining_events = self._events_captured[last_event_count:]
            for event in remaining_events:
                async for stream_event in self._convert_event(event):
                    yield stream_event
                    # Capture final text
                    if hasattr(event, "action") and hasattr(event.action, "message"):
                        if event.action.message:
                            final_text = event.action.message

            # Yield final result if we haven't already
            if success and not error_occurred:
                yield result_event(
                    self.thread_id,
                    final_text or "Task completed.",
                    success=True,
                    subtype="success",
                )

        except Exception as e:
            error_occurred = True
            import traceback

            logger.error(f"[OpenHands] Exception: {e}")
            traceback.print_exc()
            yield error_event(self.thread_id, str(e), recoverable=False)

        finally:
            self.is_running = False
            if self._conversation:
                try:
                    self._conversation.close()
                except Exception:
                    pass
                self._conversation = None

    async def _convert_event(self, event) -> AsyncIterator[StreamEvent]:
        """Convert OpenHands event to StreamEvent."""
        # Check for action events
        if hasattr(event, "action"):
            action = event.action
            action_type = type(action).__name__

            # Thought/thinking events
            if hasattr(action, "thought") and action.thought:
                yield thought_event(self.thread_id, action.thought)

            # Final message (FinishAction)
            elif hasattr(action, "message") and action.message:
                # This is captured separately for final result
                pass

            # Tool calls
            else:
                # Extract tool info
                tool_name = action_type.replace("Action", "")
                tool_input = {}

                # Try to extract command/input
                if hasattr(action, "command"):
                    tool_input = {"command": action.command}
                elif hasattr(action, "path"):
                    tool_input = {"path": action.path}

                yield tool_start_event(
                    self.thread_id,
                    tool_name,
                    tool_input,
                )

        # Check for observation events (tool results)
        if hasattr(event, "observation"):
            observation = event.observation
            obs_type = type(observation).__name__

            # Extract output
            output = ""
            if hasattr(observation, "content"):
                if isinstance(observation.content, list):
                    output = " ".join(
                        str(c.text) if hasattr(c, "text") else str(c)
                        for c in observation.content
                    )
                else:
                    output = str(observation.content)

            is_error = getattr(observation, "is_error", False)
            tool_name = obs_type.replace("Observation", "")

            yield tool_end_event(
                self.thread_id,
                tool_name,
                success=not is_error,
                output=output[:10000] if output else None,  # Truncate
            )

    async def interrupt(self) -> AsyncIterator[StreamEvent]:
        """Interrupt current execution."""
        # OpenHands doesn't have a direct interrupt mechanism like Claude SDK
        # We can only stop the conversation
        self._was_interrupted = True
        self.is_running = False

        if self._conversation:
            try:
                self._conversation.close()
            except Exception:
                pass
            self._conversation = None

        yield thought_event(self.thread_id, "Interrupting current task...")
        yield result_event(
            self.thread_id,
            "Task interrupted. Send a new message to continue.",
            success=True,
            subtype="interrupted",
        )

    async def close(self) -> None:
        """Clean up the session."""
        if self._conversation:
            try:
                self._conversation.close()
            except Exception:
                pass
            self._conversation = None

        self._agent = None
        self._workspace = None

    def set_answer_callback(self, callback: Callable[[dict], None]) -> None:
        """Set callback for receiving user answers."""
        self._answer_callback = callback

    async def provide_answer(self, answers: dict) -> None:
        """Provide answer to pending question."""
        # OpenHands doesn't have built-in AskUserQuestion
        # This would need custom tool implementation
        if self._pending_answer_event is not None:
            self._pending_answer = answers
            self._pending_answer_event.set()
        else:
            logger.warning("[OpenHands] No pending question to answer")
