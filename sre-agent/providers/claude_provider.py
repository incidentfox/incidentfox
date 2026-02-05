"""
Claude SDK Provider for SRE Agent.

This module implements the LLMProvider interface using Claude Agent SDK.
It extracts the Claude-specific logic from the original agent.py.
"""

import asyncio
import logging
import os
from typing import Any, AsyncIterator, Callable, Optional

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
)
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny
from events import (
    StreamEvent,
    error_event,
    question_event,
    question_timeout_event,
    result_event,
    thought_event,
    tool_end_event,
    tool_start_event,
)

from providers.base import LLMProvider, ProviderConfig

logger = logging.getLogger(__name__)


class ClaudeProvider(LLMProvider):
    """
    LLM Provider using Claude Agent SDK.

    This maintains the exact behavior of the original InteractiveAgentSession
    but through the provider abstraction.
    """

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.client: ClaudeSDKClient | None = None
        self._pending_tool_ends: list = []
        self._tool_parent_map: dict = {}
        self._pending_events: list = []
        self._pending_answer_event: Optional[asyncio.Event] = None
        self._pending_answer: Optional[dict] = None
        self._answer_callback: Optional[Callable] = None

        # Build Claude SDK options
        self.options = self._build_options()

    def _build_options(self) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions from config."""

        # Create capture_tool_output hook
        async def capture_tool_output(input_data, tool_use_id, context):
            """Hook to capture tool outputs - queues tool_end event when tool completes."""
            if input_data["hook_event_name"] == "PostToolUse":
                tool_name = input_data.get("tool_name", "Unknown")
                tool_response = input_data.get("tool_response", "")
                response_preview = (
                    str(tool_response)[:200] if tool_response else "(empty)"
                )
                logger.info(
                    f"[Hook] PostToolUse: tool={tool_name}, id={tool_use_id}, output_preview={response_preview}"
                )

                # Look up parent_tool_use_id from tracking map
                parent_tool_use_id = self._tool_parent_map.get(tool_use_id)

                # Truncate large outputs (SDK has 1MB limit)
                MAX_OUTPUT_LEN = 50000
                output_str = str(tool_response) if tool_response else None
                if output_str and len(output_str) > MAX_OUTPUT_LEN:
                    output_str = (
                        output_str[:MAX_OUTPUT_LEN]
                        + f"... [truncated, {len(str(tool_response))} total chars]"
                    )

                # Queue tool_end event
                self._pending_tool_ends.append(
                    {
                        "name": tool_name,
                        "tool_use_id": tool_use_id,
                        "parent_tool_use_id": parent_tool_use_id,
                        "output": output_str,
                    }
                )

                # Clean up mapping
                self._tool_parent_map.pop(tool_use_id, None)
            return {}

        # Create can_use_tool handler
        async def can_use_tool_handler(tool_name: str, input_data: dict, context):
            """Handle tool permission requests, including AskUserQuestion."""
            if tool_name == "AskUserQuestion":
                questions = input_data.get("questions", [])
                logger.info(
                    f"[AskUserQuestion] Agent asked {len(questions)} question(s)"
                )

                # Store event for answer waiting
                event = asyncio.Event()
                self._pending_answer_event = event
                self._pending_answer = None

                logger.info("[AskUserQuestion] Waiting up to 60s for answer...")

                try:
                    await asyncio.wait_for(event.wait(), timeout=60.0)
                    answer = self._pending_answer

                    # Cleanup
                    self._pending_answer_event = None
                    self._pending_answer = None

                    logger.info(f"[AskUserQuestion] Received answer: {answer}")
                    return PermissionResultAllow(
                        updated_input={"questions": questions, "answers": answer}
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "[AskUserQuestion] Timeout - continuing without answer"
                    )

                    # Emit timeout event
                    self._pending_events.append(question_timeout_event(self.thread_id))

                    # Cleanup
                    self._pending_answer_event = None
                    self._pending_answer = None

                    return PermissionResultDeny(
                        message="User did not respond. Continue without this information."
                    )

            # Auto-approve other tools
            return PermissionResultAllow(updated_input=input_data)

        # Build subagent definitions
        subagents = {}
        for name, subagent_config in self.config.subagents.items():
            subagents[name] = AgentDefinition(
                description=subagent_config.description,
                prompt=subagent_config.prompt,
                tools=subagent_config.tools,
                model=subagent_config.model,
            )

        return ClaudeAgentOptions(
            cwd=self.config.cwd,
            allowed_tools=self.config.allowed_tools,
            permission_mode=self.config.permission_mode,
            can_use_tool=can_use_tool_handler,
            include_partial_messages=self.config.include_partial_messages,
            setting_sources=self.config.setting_sources,
            agents=subagents,
            hooks={"PostToolUse": [HookMatcher(hooks=[capture_tool_output])]},
        )

    async def start(self) -> None:
        """Initialize the Claude client session."""
        if self.client is None:
            self.client = ClaudeSDKClient(options=self.options)
            await self.client.__aenter__()
            logger.info(f"[Claude] Started session for thread {self.thread_id}")

    async def execute(
        self,
        prompt: str,
        images: Optional[list[dict]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Execute a query and stream events."""
        if self.client is None:
            raise RuntimeError("Session not started. Call start() first.")

        self.is_running = True
        self._was_interrupted = False
        self._pending_tool_ends = []
        self._pending_events = []
        self._tool_parent_map = {}
        success = False
        error_occurred = False
        final_text = ""

        # Timeout for receive_response
        RESPONSE_TIMEOUT = int(os.getenv("AGENT_TIMEOUT_SECONDS", "600"))

        try:
            # Build message generator
            async def message_generator():
                if images:
                    content = [{"type": "text", "text": prompt}]
                    for img in images:
                        content.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": img["media_type"],
                                    "data": img["data"],
                                },
                            }
                        )
                    logger.info(
                        f"[Claude] Sending multimodal message with {len(images)} image(s)"
                    )
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": content},
                    }
                else:
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": prompt},
                    }

            logger.debug(f"[Claude] Calling client.query() for thread {self.thread_id}")
            await self.client.query(message_generator())

            # Receive response with timeout
            try:
                message_count = 0
                async with asyncio.timeout(RESPONSE_TIMEOUT):
                    async for message in self.client.receive_response():
                        message_count += 1
                        parent_tool_use_id = getattr(
                            message, "parent_tool_use_id", None
                        )

                        # Emit pending tool_end events
                        while self._pending_tool_ends:
                            pending = self._pending_tool_ends.pop(0)
                            yield tool_end_event(
                                self.thread_id,
                                pending["name"],
                                success=True,
                                output=pending.get("output"),
                                tool_use_id=pending.get("tool_use_id"),
                                parent_tool_use_id=pending.get("parent_tool_use_id"),
                            )

                        # Emit pending events
                        while self._pending_events:
                            yield self._pending_events.pop(0)

                        if isinstance(message, AssistantMessage):
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    yield thought_event(
                                        self.thread_id,
                                        block.text,
                                        parent_tool_use_id=parent_tool_use_id,
                                    )
                                    if final_text:
                                        final_text += "\n\n"
                                    final_text += block.text
                                elif hasattr(block, "name"):
                                    tool_input = {}
                                    if hasattr(block, "input"):
                                        tool_input = (
                                            block.input
                                            if isinstance(block.input, dict)
                                            else {}
                                        )

                                    tool_use_id = getattr(block, "id", None)

                                    # Track parent for subagent
                                    if tool_use_id and parent_tool_use_id:
                                        self._tool_parent_map[tool_use_id] = (
                                            parent_tool_use_id
                                        )

                                    yield tool_start_event(
                                        self.thread_id,
                                        block.name,
                                        tool_input,
                                        tool_use_id=tool_use_id,
                                        parent_tool_use_id=parent_tool_use_id,
                                    )

                                    # Emit question event for AskUserQuestion
                                    if block.name == "AskUserQuestion":
                                        questions = tool_input.get("questions", [])
                                        yield question_event(self.thread_id, questions)

                        elif isinstance(message, ResultMessage):
                            # Emit remaining tool_end events
                            while self._pending_tool_ends:
                                pending = self._pending_tool_ends.pop(0)
                                yield tool_end_event(
                                    self.thread_id,
                                    pending["name"],
                                    success=True,
                                    output=pending.get("output"),
                                    tool_use_id=pending.get("tool_use_id"),
                                )

                            # Extract images and files from result
                            from agent import (
                                _extract_files_from_text,
                                _extract_images_from_text,
                            )

                            result_text, extracted_images = _extract_images_from_text(
                                final_text
                            )
                            _, extracted_files = _extract_files_from_text(final_text)

                            success = message.subtype == "success"
                            yield result_event(
                                self.thread_id,
                                result_text,
                                success=success,
                                subtype=message.subtype,
                                images=extracted_images if extracted_images else None,
                                files=extracted_files if extracted_files else None,
                            )

                logger.debug(f"[Claude] Completed. Messages: {message_count}")

            except asyncio.TimeoutError:
                logger.error(f"[Claude] Timeout after {RESPONSE_TIMEOUT}s")
                yield error_event(
                    self.thread_id,
                    "Response exceeded maximum time limit",
                    recoverable=False,
                )
                error_occurred = True

        except Exception as e:
            error_occurred = True
            import traceback

            error_msg = str(e)
            logger.error(f"[Claude] Exception: {error_msg}")
            traceback.print_exc()

            # User-friendly messages
            if "buffer size" in error_msg.lower() or "1048576" in error_msg:
                error_msg = "Subagent produced too much output (SDK buffer limit)."
            elif "decode" in error_msg.lower() and "json" in error_msg.lower():
                error_msg = "SDK JSON parsing error. Response too large or malformed."

            yield error_event(self.thread_id, error_msg, recoverable=False)

        finally:
            self.is_running = False

    async def interrupt(self) -> AsyncIterator[StreamEvent]:
        """Interrupt current execution."""
        if self.client is None:
            raise RuntimeError("Session not started. Call start() first.")

        try:
            yield thought_event(self.thread_id, "Interrupting current task...")
            await self.client.interrupt()
            self._was_interrupted = True
            self.is_running = False
            yield result_event(
                self.thread_id,
                "Task interrupted. Send a new message to continue.",
                success=True,
                subtype="interrupted",
            )
        except Exception as e:
            yield error_event(
                self.thread_id,
                f"Interrupt failed: {str(e)}",
                recoverable=False,
            )
            raise

    async def close(self) -> None:
        """Clean up the client session."""
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    def set_answer_callback(self, callback: Callable[[dict], None]) -> None:
        """Set callback for receiving user answers."""
        self._answer_callback = callback

    async def provide_answer(self, answers: dict) -> None:
        """Provide answer to pending AskUserQuestion."""
        if self._pending_answer_event is not None:
            self._pending_answer = answers
            self._pending_answer_event.set()
            logger.info(f"[Claude] Answer provided: {answers}")
        else:
            logger.warning("[Claude] No pending question to answer")
