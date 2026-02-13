"""Tests for llm_stream.py — SSE streaming state machine."""

import json

import pytest
from credential_resolver.llm_stream import StreamTranslator


def _parse_sse(sse_string: str) -> tuple[str, dict]:
    """Parse an SSE string into (event_type, data_dict)."""
    lines = sse_string.strip().split("\n")
    event_type = ""
    data = {}
    for line in lines:
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data = json.loads(line[6:])
    return event_type, data


def _make_chunk(
    content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
    usage: dict | None = None,
) -> dict:
    """Build a minimal OpenAI-format streaming chunk dict."""
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls

    chunk: dict = {
        "choices": [
            {
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage is not None:
        chunk["usage"] = usage
    return chunk


class TestStreamTranslator:
    def test_message_start_on_first_chunk(self):
        t = StreamTranslator(model_name="openai/gpt-4o")
        events = t.translate_chunk(_make_chunk(content="Hi"))
        assert len(events) >= 1
        event_type, data = _parse_sse(events[0])
        assert event_type == "message_start"
        assert data["type"] == "message_start"
        assert data["message"]["model"] == "openai/gpt-4o"
        assert data["message"]["role"] == "assistant"

    def test_text_streaming(self):
        t = StreamTranslator(model_name="openai/gpt-4o")
        all_events = []

        # First chunk: "Hello"
        all_events.extend(t.translate_chunk(_make_chunk(content="Hello")))
        # Second chunk: " world"
        all_events.extend(t.translate_chunk(_make_chunk(content=" world")))

        parsed = [_parse_sse(e) for e in all_events]

        # Should see: message_start, content_block_start, text_delta, text_delta
        types = [p[0] for p in parsed]
        assert types[0] == "message_start"
        assert types[1] == "content_block_start"
        assert types[2] == "content_block_delta"
        assert types[3] == "content_block_delta"

        # Check text deltas
        assert parsed[2][1]["delta"]["text"] == "Hello"
        assert parsed[3][1]["delta"]["text"] == " world"

    def test_finalize_emits_stop_events(self):
        t = StreamTranslator(model_name="openai/gpt-4o")
        t.translate_chunk(_make_chunk(content="Hi"))
        t.translate_chunk(_make_chunk(finish_reason="stop"))

        events = t.finalize()
        parsed = [_parse_sse(e) for e in events]
        types = [p[0] for p in parsed]

        assert "content_block_stop" in types
        assert "message_delta" in types
        assert "message_stop" in types

        # Check stop_reason in message_delta
        msg_delta = next(p[1] for p in parsed if p[0] == "message_delta")
        assert msg_delta["delta"]["stop_reason"] == "end_turn"

    def test_tool_call_streaming(self):
        t = StreamTranslator(model_name="openai/gpt-4o")

        # First chunk: start tool call
        events = t.translate_chunk(
            _make_chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_abc",
                        "function": {"name": "get_pods", "arguments": ""},
                    }
                ]
            )
        )
        parsed = [_parse_sse(e) for e in events]
        types = [p[0] for p in parsed]
        assert "message_start" in types
        assert "content_block_start" in types

        # Check content_block_start has tool_use type
        block_start = next(p[1] for p in parsed if p[0] == "content_block_start")
        assert block_start["content_block"]["type"] == "tool_use"
        assert block_start["content_block"]["name"] == "get_pods"
        assert block_start["content_block"]["id"] == "call_abc"

        # Second chunk: stream arguments
        events = t.translate_chunk(
            _make_chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "function": {"arguments": '{"namespace"'},
                    }
                ]
            )
        )
        parsed = [_parse_sse(e) for e in events]
        assert len(parsed) == 1
        assert parsed[0][0] == "content_block_delta"
        assert parsed[0][1]["delta"]["type"] == "input_json_delta"
        assert parsed[0][1]["delta"]["partial_json"] == '{"namespace"'

    def test_text_then_tool_call(self):
        """Text followed by tool call should close text block first."""
        t = StreamTranslator(model_name="openai/gpt-4o")

        # Text chunk
        t.translate_chunk(_make_chunk(content="Let me check."))

        # Tool call chunk
        events = t.translate_chunk(
            _make_chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_xyz",
                        "function": {"name": "search", "arguments": ""},
                    }
                ]
            )
        )
        parsed = [_parse_sse(e) for e in events]
        types = [p[0] for p in parsed]

        # Should close text block, then start tool_use block
        assert "content_block_stop" in types
        assert "content_block_start" in types

    def test_multiple_tool_calls(self):
        """Multiple tool calls should each get their own block."""
        t = StreamTranslator(model_name="openai/gpt-4o")

        # First tool call
        t.translate_chunk(
            _make_chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "tool_a", "arguments": "{}"},
                    }
                ]
            )
        )

        # Second tool call
        events = t.translate_chunk(
            _make_chunk(
                tool_calls=[
                    {
                        "index": 1,
                        "id": "call_2",
                        "function": {"name": "tool_b", "arguments": "{}"},
                    }
                ]
            )
        )
        parsed = [_parse_sse(e) for e in events]
        types = [p[0] for p in parsed]

        # Should close first tool block, start second
        assert "content_block_stop" in types
        assert "content_block_start" in types

        block_start = next(p[1] for p in parsed if p[0] == "content_block_start")
        assert block_start["content_block"]["name"] == "tool_b"

    def test_usage_tracking(self):
        t = StreamTranslator(model_name="openai/gpt-4o")
        t.translate_chunk(_make_chunk(content="Hi"))
        t.translate_chunk(
            _make_chunk(
                finish_reason="stop",
                usage={"prompt_tokens": 100, "completion_tokens": 50},
            )
        )

        events = t.finalize()
        parsed = [_parse_sse(e) for e in events]

        msg_delta = next(p[1] for p in parsed if p[0] == "message_delta")
        assert msg_delta["usage"]["input_tokens"] == 100
        assert msg_delta["usage"]["output_tokens"] == 50

    def test_tool_calls_stop_reason(self):
        t = StreamTranslator(model_name="openai/gpt-4o")
        t.translate_chunk(
            _make_chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "tool_a", "arguments": "{}"},
                    }
                ]
            )
        )
        t.translate_chunk(_make_chunk(finish_reason="tool_calls"))

        events = t.finalize()
        parsed = [_parse_sse(e) for e in events]

        msg_delta = next(p[1] for p in parsed if p[0] == "message_delta")
        assert msg_delta["delta"]["stop_reason"] == "tool_use"

    def test_finalize_without_any_chunks(self):
        """Finalize on empty stream should still produce valid events."""
        t = StreamTranslator(model_name="openai/gpt-4o")
        events = t.finalize()
        parsed = [_parse_sse(e) for e in events]
        types = [p[0] for p in parsed]

        assert "message_start" in types
        assert "message_delta" in types
        assert "message_stop" in types

    def test_sse_format(self):
        """Verify SSE strings have correct format."""
        t = StreamTranslator(model_name="test")
        events = t.translate_chunk(_make_chunk(content="Hi"))

        for event in events:
            assert event.startswith("event: ")
            assert "\ndata: " in event
            assert event.endswith("\n\n")

    def test_content_block_indices_are_sequential(self):
        """Block indices should increment sequentially."""
        t = StreamTranslator(model_name="openai/gpt-4o")

        # Text block (index 0)
        t.translate_chunk(_make_chunk(content="Hi"))

        # Tool call (index 1)
        t.translate_chunk(
            _make_chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "tool_a", "arguments": "{}"},
                    }
                ]
            )
        )

        # Another tool call (index 2)
        events = t.translate_chunk(
            _make_chunk(
                tool_calls=[
                    {
                        "index": 1,
                        "id": "call_2",
                        "function": {"name": "tool_b", "arguments": "{}"},
                    }
                ]
            )
        )

        # Check the last content_block_start has index 2
        parsed = [_parse_sse(e) for e in events]
        block_start = next(p[1] for p in parsed if p[0] == "content_block_start")
        assert block_start["index"] == 2

    def test_usage_only_chunk(self):
        """Chunk with only usage (no choices) should not crash."""
        t = StreamTranslator(model_name="openai/gpt-4o")
        t.translate_chunk(_make_chunk(content="Hi"))

        # Usage-only chunk (some providers send this)
        events = t.translate_chunk(
            {"usage": {"prompt_tokens": 50, "completion_tokens": 25}}
        )
        # Should not produce any SSE events (just updates internal state)
        assert events == []

    def test_custom_message_id(self):
        t = StreamTranslator(model_name="test", message_id="msg_custom123")
        events = t.translate_chunk(_make_chunk(content="Hi"))
        _, data = _parse_sse(events[0])
        assert data["message"]["id"] == "msg_custom123"
