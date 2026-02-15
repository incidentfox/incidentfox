"""Streaming SSE translator: OpenAI Chat Completions → Anthropic Messages.

Converts LiteLLM's streaming response (normalized OpenAI format) into
Anthropic SSE event format that the Claude SDK expects.

Anthropic SSE event lifecycle:
  message_start → (content_block_start → content_block_delta* → content_block_stop)*
  → message_delta → message_stop
"""

import json
import logging
from uuid import uuid4

from .llm_translator import _map_stop_reason

logger = logging.getLogger(__name__)


class StreamTranslator:
    """State machine that converts OpenAI-format streaming chunks to Anthropic SSE events.

    Usage:
        translator = StreamTranslator(model_name="openai/gpt-4o")

        # For each chunk from litellm.acompletion(stream=True):
        for sse_event in translator.translate_chunk(chunk):
            yield sse_event  # Already formatted as "event: ...\ndata: ...\n\n"

        # After stream ends:
        for sse_event in translator.finalize():
            yield sse_event
    """

    def __init__(self, model_name: str, message_id: str | None = None):
        self.model_name = model_name
        self.message_id = message_id or f"msg_{uuid4().hex[:24]}"

        self._message_started = False
        self._block_index = -1
        self._block_type: str | None = None  # "text" or "tool_use"

        # Tool call state: openai_index -> {id, name, block_index}
        self._tool_calls: dict[int, dict] = {}

        self._finish_reason: str | None = None
        self._usage = {"input_tokens": 0, "output_tokens": 0}

    def translate_chunk(self, chunk) -> list[str]:
        """Translate a single LiteLLM streaming chunk to Anthropic SSE events.

        Args:
            chunk: A litellm ModelResponse/ModelResponseStream object, or a dict.
                   Has .choices[0].delta with content/tool_calls/finish_reason.

        Returns:
            List of formatted SSE strings ready to send to the client.
        """
        events: list[str] = []

        # Normalize: litellm returns objects, but accept dicts too
        if hasattr(chunk, "model_dump"):
            chunk_dict = chunk.model_dump()
        elif isinstance(chunk, dict):
            chunk_dict = chunk
        else:
            return events

        # Emit message_start on first chunk
        if not self._message_started:
            events.extend(self._emit_message_start())
            self._message_started = True

        choices = chunk_dict.get("choices", [])
        if not choices:
            # Usage-only chunk (some providers send usage separately)
            if "usage" in chunk_dict:
                self._update_usage(chunk_dict["usage"])
            return events

        choice = choices[0]
        delta = choice.get("delta", {})

        # Text content
        text = delta.get("content")
        if text:
            events.extend(self._handle_text(text))

        # Tool calls
        tool_calls = delta.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                events.extend(self._handle_tool_call(tc))

        # Finish reason
        finish_reason = choice.get("finish_reason")
        if finish_reason:
            self._finish_reason = finish_reason

        # Usage (may appear on final chunk or separately)
        if "usage" in chunk_dict:
            self._update_usage(chunk_dict["usage"])

        return events

    def finalize(self) -> list[str]:
        """Emit closing events after the stream ends.

        Call this after iterating all chunks.
        """
        events: list[str] = []

        # Ensure message_start was emitted
        if not self._message_started:
            events.extend(self._emit_message_start())

        # Close any open content block
        if self._block_type is not None:
            events.append(
                self._format_sse(
                    "content_block_stop",
                    {
                        "type": "content_block_stop",
                        "index": self._block_index,
                    },
                )
            )
            self._block_type = None

        # message_delta with stop_reason and usage
        stop_reason = _map_stop_reason(self._finish_reason)
        events.append(
            self._format_sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason},
                    "usage": self._usage,
                },
            )
        )

        # message_stop
        events.append(
            self._format_sse(
                "message_stop",
                {
                    "type": "message_stop",
                },
            )
        )

        return events

    # -------------------------------------------------------------------
    # Internal handlers
    # -------------------------------------------------------------------

    def _handle_text(self, text: str) -> list[str]:
        """Handle a text content delta."""
        events: list[str] = []

        # If we're in a tool_use block, close it first
        if self._block_type == "tool_use":
            events.append(
                self._format_sse(
                    "content_block_stop",
                    {
                        "type": "content_block_stop",
                        "index": self._block_index,
                    },
                )
            )
            self._block_type = None

        # Start text block if not already open
        if self._block_type != "text":
            self._block_index += 1
            self._block_type = "text"
            events.append(
                self._format_sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": self._block_index,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            )

        # Emit text delta
        events.append(
            self._format_sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": self._block_index,
                    "delta": {"type": "text_delta", "text": text},
                },
            )
        )

        return events

    def _handle_tool_call(self, tc_delta: dict) -> list[str]:
        """Handle a tool call delta from the stream."""
        events: list[str] = []
        tc_index = tc_delta.get("index", 0)

        if tc_index not in self._tool_calls:
            # New tool call — close any open block
            if self._block_type is not None:
                events.append(
                    self._format_sse(
                        "content_block_stop",
                        {
                            "type": "content_block_stop",
                            "index": self._block_index,
                        },
                    )
                )

            self._block_index += 1
            self._block_type = "tool_use"

            tool_id = tc_delta.get("id", f"toolu_{uuid4().hex[:24]}")
            tool_name = tc_delta.get("function", {}).get("name", "")

            self._tool_calls[tc_index] = {
                "id": tool_id,
                "name": tool_name,
                "block_index": self._block_index,
            }

            # Emit content_block_start for tool_use
            events.append(
                self._format_sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": self._block_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": tool_name,
                            "input": {},
                        },
                    },
                )
            )

        # Stream argument fragment
        args_fragment = tc_delta.get("function", {}).get("arguments", "")
        if args_fragment:
            block_idx = self._tool_calls[tc_index]["block_index"]
            events.append(
                self._format_sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": block_idx,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": args_fragment,
                        },
                    },
                )
            )

        return events

    def _emit_message_start(self) -> list[str]:
        """Emit the initial message_start event."""
        return [
            self._format_sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": self.message_id,
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": self.model_name,
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
            )
        ]

    def _update_usage(self, usage: dict):
        """Update token usage from a chunk."""
        if "prompt_tokens" in usage:
            self._usage["input_tokens"] = usage["prompt_tokens"]
        if "completion_tokens" in usage:
            self._usage["output_tokens"] = usage["completion_tokens"]

    # -------------------------------------------------------------------
    # SSE formatting
    # -------------------------------------------------------------------

    @staticmethod
    def _format_sse(event_type: str, data: dict) -> str:
        """Format an SSE event string."""
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
