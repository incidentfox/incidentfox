"""
Agent Runner implementation.

Executes agents using OpenHands/LiteLLM, providing the same interface
as OpenAI's Runner but with multi-model support.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional

import litellm

from .agent import Agent
from .events import StreamEvent

logger = logging.getLogger(__name__)

# Model alias mapping (short names to full LiteLLM model strings)
MODEL_ALIASES = {
    "sonnet": "anthropic/claude-sonnet-4-20250514",
    "opus": "anthropic/claude-opus-4-20250514",
    "haiku": "anthropic/claude-haiku-4-20250514",
    "gpt-5.2": "openai/gpt-5.2",
    "gpt-5.2-mini": "openai/gpt-5.2-mini",
    "gemini-flash": "gemini/gemini-2.0-flash",
    "gemini-pro": "gemini/gemini-1.5-pro",
}


@dataclass
class RunResult:
    """Result of running an agent."""

    final_output: Any
    messages: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    status: str = "complete"  # complete, incomplete, error


class MaxTurnsExceeded(Exception):
    """Raised when agent exceeds maximum turns."""

    def __init__(self, message: str, partial_messages: list[dict]):
        super().__init__(message)
        self.partial_messages = partial_messages


class Runner:
    """
    Runs an Agent to completion.

    The Runner handles:
    - LLM API calls via LiteLLM
    - Tool execution
    - Multi-turn conversation management
    - Sub-agent delegation

    Example:
        result = await Runner.run(
            agent,
            "Why is the checkout service slow?",
            max_turns=25,
        )
    """

    @staticmethod
    async def run(
        agent: Agent,
        query: str,
        max_turns: int = 25,
        context: Optional[dict] = None,
    ) -> RunResult:
        """
        Run an agent to completion.

        Args:
            agent: The agent to run
            query: User query/task
            max_turns: Maximum LLM turns before stopping
            context: Optional execution context (credentials, etc.)

        Returns:
            RunResult with final output and execution history
        """
        runner = Runner()
        return await runner._execute(agent, query, max_turns, context)

    @staticmethod
    async def run_streaming(
        agent: Agent,
        query: str,
        max_turns: int = 25,
        context: Optional[dict] = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Run an agent with streaming events.

        Yields StreamEvent objects for real-time UI updates.
        """
        runner = Runner()
        async for event in runner._execute_streaming(agent, query, max_turns, context):
            yield event

    async def _execute(
        self,
        agent: Agent,
        query: str,
        max_turns: int,
        context: Optional[dict],
    ) -> RunResult:
        """Internal execution implementation."""
        messages = [
            {"role": "system", "content": agent.instructions},
            {"role": "user", "content": query},
        ]

        tool_calls_history = []
        model = self._resolve_model(agent.model)
        api_key = self._get_api_key(model)

        for turn in range(max_turns):
            try:
                # Build tools schema
                tools = agent.get_tools_schema() if agent.tools else None

                # Make LLM call
                response = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    api_key=api_key,
                    tools=tools,
                    tool_choice="auto" if tools else None,
                    temperature=(
                        agent.model_settings.temperature
                        if agent.model_settings
                        else 0.4
                    ),
                    max_tokens=(
                        agent.model_settings.max_tokens
                        if agent.model_settings
                        else None
                    ),
                )

                assistant_message = response.choices[0].message

                # Add assistant message to history
                messages.append(assistant_message.model_dump())

                # Check if we're done (no tool calls)
                if not assistant_message.tool_calls:
                    return RunResult(
                        final_output=assistant_message.content,
                        messages=messages,
                        tool_calls=tool_calls_history,
                        status="complete",
                    )

                # Execute tool calls
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args_str = tool_call.function.arguments

                    try:
                        tool_args = json.loads(tool_args_str) if tool_args_str else {}
                    except json.JSONDecodeError:
                        tool_args = {}

                    logger.debug(f"Executing tool: {tool_name} with args: {tool_args}")

                    # Find and execute the tool
                    tool_func = agent.get_tool_by_name(tool_name)
                    if tool_func:
                        try:
                            # Execute tool (sync or async)
                            if asyncio.iscoroutinefunction(tool_func):
                                result = await tool_func(**tool_args)
                            else:
                                result = tool_func(**tool_args)

                            tool_output = str(result) if result is not None else "Done"
                        except Exception as e:
                            tool_output = f"Error: {str(e)}"
                            logger.error(f"Tool {tool_name} failed: {e}")
                    else:
                        tool_output = f"Error: Unknown tool '{tool_name}'"
                        logger.warning(f"Unknown tool requested: {tool_name}")

                    # Record tool call
                    tool_calls_history.append(
                        {
                            "name": tool_name,
                            "args": tool_args,
                            "output": tool_output[:10000],  # Truncate large outputs
                        }
                    )

                    # Add tool result to messages
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_output[:50000],  # Truncate for context
                        }
                    )

            except Exception as e:
                logger.error(f"LLM error on turn {turn}: {e}")
                return RunResult(
                    final_output=f"Error: {str(e)}",
                    messages=messages,
                    tool_calls=tool_calls_history,
                    status="error",
                )

        # Hit max turns
        raise MaxTurnsExceeded(
            f"Agent exceeded {max_turns} turns",
            partial_messages=messages,
        )

    async def _execute_streaming(
        self,
        agent: Agent,
        query: str,
        max_turns: int,
        context: Optional[dict],
    ) -> AsyncIterator[StreamEvent]:
        """Internal streaming execution implementation."""
        messages = [
            {"role": "system", "content": agent.instructions},
            {"role": "user", "content": query},
        ]

        model = self._resolve_model(agent.model)
        api_key = self._get_api_key(model)
        thread_id = context.get("thread_id", "default") if context else "default"

        for turn in range(max_turns):
            try:
                tools = agent.get_tools_schema() if agent.tools else None

                response = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    api_key=api_key,
                    tools=tools,
                    tool_choice="auto" if tools else None,
                    temperature=(
                        agent.model_settings.temperature
                        if agent.model_settings
                        else 0.4
                    ),
                )

                assistant_message = response.choices[0].message
                messages.append(assistant_message.model_dump())

                # Emit thought event
                if assistant_message.content:
                    yield StreamEvent(
                        type="thought",
                        data={"text": assistant_message.content},
                        thread_id=thread_id,
                    )

                # Check if done
                if not assistant_message.tool_calls:
                    yield StreamEvent(
                        type="result",
                        data={"text": assistant_message.content},
                        thread_id=thread_id,
                    )
                    return

                # Execute tools
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments or "{}")

                    yield StreamEvent(
                        type="tool_start",
                        data={"tool": tool_name, "args": tool_args},
                        thread_id=thread_id,
                    )

                    tool_func = agent.get_tool_by_name(tool_name)
                    if tool_func:
                        try:
                            if asyncio.iscoroutinefunction(tool_func):
                                result = await tool_func(**tool_args)
                            else:
                                result = tool_func(**tool_args)
                            tool_output = str(result) if result is not None else "Done"
                            success = True
                        except Exception as e:
                            tool_output = f"Error: {str(e)}"
                            success = False
                    else:
                        tool_output = f"Unknown tool: {tool_name}"
                        success = False

                    yield StreamEvent(
                        type="tool_end",
                        data={
                            "tool": tool_name,
                            "output": tool_output[:5000],
                            "success": success,
                        },
                        thread_id=thread_id,
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_output[:50000],
                        }
                    )

            except Exception as e:
                yield StreamEvent(
                    type="error",
                    data={"message": str(e)},
                    thread_id=thread_id,
                )
                return

        # Max turns exceeded
        yield StreamEvent(
            type="error",
            data={"message": f"Exceeded {max_turns} turns"},
            thread_id=thread_id,
        )

    def _resolve_model(self, model: str) -> str:
        """Resolve model alias to full LiteLLM model string."""
        # Check environment override first
        env_model = os.getenv("LLM_MODEL")
        if env_model:
            return env_model

        # Check alias map
        if model in MODEL_ALIASES:
            return MODEL_ALIASES[model]

        # Check if already a full model string (has /)
        if "/" in model:
            return model

        # Default to Claude Sonnet
        return MODEL_ALIASES.get("sonnet", "anthropic/claude-sonnet-4-20250514")

    def _get_api_key(self, model: str) -> str:
        """Get appropriate API key for the model."""
        model_lower = model.lower()

        if model_lower.startswith("anthropic/"):
            return os.getenv("ANTHROPIC_API_KEY", "")
        elif model_lower.startswith("gemini/"):
            return os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
        elif model_lower.startswith("openai/"):
            return os.getenv("OPENAI_API_KEY", "")
        else:
            # Try generic key
            return os.getenv("LLM_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
