"""Tests for llm_translator.py — Anthropic ↔ OpenAI format translation."""

import json

from credential_resolver.llm_translator import (
    _convert_tool_choice,
    _map_stop_reason,
    anthropic_to_openai_request,
    openai_error_to_anthropic,
    openai_to_anthropic_response,
)

# ---------------------------------------------------------------------------
# Request translation: Anthropic → OpenAI
# ---------------------------------------------------------------------------


class TestAnthropicToOpenAIRequest:
    def test_simple_text_message(self):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": "Hello"},
            ],
        }
        result = anthropic_to_openai_request(body)
        assert result["messages"] == [{"role": "user", "content": "Hello"}]
        assert result["max_tokens"] == 1024

    def test_system_message_string(self):
        body = {
            "system": "You are an SRE assistant.",
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = anthropic_to_openai_request(body)
        assert result["messages"][0] == {
            "role": "system",
            "content": "You are an SRE assistant.",
        }
        assert result["messages"][1] == {"role": "user", "content": "Hi"}

    def test_system_message_blocks(self):
        body = {
            "system": [
                {"type": "text", "text": "You are helpful."},
                {"type": "text", "text": "Be concise."},
            ],
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = anthropic_to_openai_request(body)
        assert result["messages"][0]["role"] == "system"
        assert "You are helpful." in result["messages"][0]["content"]
        assert "Be concise." in result["messages"][0]["content"]

    def test_multi_turn_conversation(self):
        body = {
            "messages": [
                {"role": "user", "content": "What is k8s?"},
                {"role": "assistant", "content": "Kubernetes is..."},
                {"role": "user", "content": "How do I scale pods?"},
            ],
        }
        result = anthropic_to_openai_request(body)
        assert len(result["messages"]) == 3
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][1]["role"] == "assistant"
        assert result["messages"][2]["role"] == "user"

    def test_tool_use_message(self):
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Let me check."},
                        {
                            "type": "tool_use",
                            "id": "toolu_123",
                            "name": "get_pods",
                            "input": {"namespace": "default"},
                        },
                    ],
                }
            ],
        }
        result = anthropic_to_openai_request(body)
        msg = result["messages"][0]
        assert msg["role"] == "assistant"
        assert msg["content"] == "Let me check."
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["id"] == "toolu_123"
        assert msg["tool_calls"][0]["function"]["name"] == "get_pods"
        assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {
            "namespace": "default"
        }

    def test_tool_result_message(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_123",
                            "content": "pod-1\npod-2\npod-3",
                        }
                    ],
                }
            ],
        }
        result = anthropic_to_openai_request(body)
        msg = result["messages"][0]
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "toolu_123"
        assert "pod-1" in msg["content"]

    def test_tool_result_with_content_blocks(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_456",
                            "content": [
                                {"type": "text", "text": "Result line 1"},
                                {"type": "text", "text": "Result line 2"},
                            ],
                        }
                    ],
                }
            ],
        }
        result = anthropic_to_openai_request(body)
        msg = result["messages"][0]
        assert msg["role"] == "tool"
        assert "Result line 1" in msg["content"]
        assert "Result line 2" in msg["content"]

    def test_image_base64(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "iVBOR...",
                            },
                        },
                        {"type": "text", "text": "What's in this image?"},
                    ],
                }
            ],
        }
        result = anthropic_to_openai_request(body)
        msg = result["messages"][0]
        assert msg["role"] == "user"
        # Should have image_url and text parts
        assert isinstance(msg["content"], list)
        image_part = msg["content"][0]
        assert image_part["type"] == "image_url"
        assert image_part["image_url"]["url"].startswith("data:image/png;base64,")

    def test_image_url(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": "https://example.com/img.png",
                            },
                        },
                    ],
                }
            ],
        }
        result = anthropic_to_openai_request(body)
        msg = result["messages"][0]
        image_part = msg["content"][0]
        assert image_part["image_url"]["url"] == "https://example.com/img.png"

    def test_tools_conversion(self):
        body = {
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [
                {
                    "name": "get_pods",
                    "description": "Get Kubernetes pods",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                        },
                    },
                }
            ],
        }
        result = anthropic_to_openai_request(body)
        assert len(result["tools"]) == 1
        tool = result["tools"][0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "get_pods"
        assert tool["function"]["description"] == "Get Kubernetes pods"
        assert "namespace" in tool["function"]["parameters"]["properties"]

    def test_server_tools_filtered(self):
        body = {
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [
                {"name": "get_pods", "description": "Get pods", "input_schema": {}},
                {"name": "web_search", "description": "Search web", "input_schema": {}},
                {
                    "name": "computer",
                    "type": "computer_20241022",
                    "description": "Computer use",
                },
            ],
        }
        result = anthropic_to_openai_request(body)
        # web_search and computer should be filtered out
        assert len(result["tools"]) == 1
        assert result["tools"][0]["function"]["name"] == "get_pods"

    def test_streaming_params(self):
        body = {
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
        }
        result = anthropic_to_openai_request(body)
        assert result["stream"] is True
        assert result["stream_options"] == {"include_usage": True}

    def test_stop_sequences(self):
        body = {
            "messages": [{"role": "user", "content": "Hi"}],
            "stop_sequences": ["\n\n", "END"],
        }
        result = anthropic_to_openai_request(body)
        assert result["stop"] == ["\n\n", "END"]

    def test_optional_params(self):
        body = {
            "messages": [{"role": "user", "content": "Hi"}],
            "temperature": 0.7,
            "top_p": 0.9,
        }
        result = anthropic_to_openai_request(body)
        assert result["temperature"] == 0.7
        assert result["top_p"] == 0.9

    def test_tool_use_without_text(self):
        """Assistant message with only tool_use blocks (no text)."""
        body = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_abc",
                            "name": "search_logs",
                            "input": {"query": "error"},
                        },
                    ],
                }
            ],
        }
        result = anthropic_to_openai_request(body)
        msg = result["messages"][0]
        assert msg["role"] == "assistant"
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["function"]["name"] == "search_logs"


# ---------------------------------------------------------------------------
# Tool choice conversion
# ---------------------------------------------------------------------------


class TestToolChoice:
    def test_auto_string(self):
        assert _convert_tool_choice("auto") == "auto"

    def test_any_string(self):
        assert _convert_tool_choice("any") == "required"

    def test_none_string(self):
        assert _convert_tool_choice("none") == "none"

    def test_tool_dict(self):
        result = _convert_tool_choice({"type": "tool", "name": "get_pods"})
        assert result == {"type": "function", "function": {"name": "get_pods"}}

    def test_any_dict(self):
        assert _convert_tool_choice({"type": "any"}) == "required"

    def test_auto_dict(self):
        assert _convert_tool_choice({"type": "auto"}) == "auto"


# ---------------------------------------------------------------------------
# Response translation: OpenAI → Anthropic
# ---------------------------------------------------------------------------


class TestOpenAIToAnthropicResponse:
    def test_simple_text_response(self):
        response = {
            "id": "chatcmpl-123",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        result = openai_to_anthropic_response(response, "openai/gpt-4o")
        assert result["type"] == "message"
        assert result["role"] == "assistant"
        assert result["model"] == "openai/gpt-4o"
        assert result["content"] == [{"type": "text", "text": "Hello!"}]
        assert result["stop_reason"] == "end_turn"
        assert result["usage"]["input_tokens"] == 10
        assert result["usage"]["output_tokens"] == 5

    def test_tool_call_response(self):
        response = {
            "id": "chatcmpl-456",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "get_pods",
                                    "arguments": '{"namespace": "default"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 15},
        }
        result = openai_to_anthropic_response(response, "openai/gpt-4o")
        assert result["stop_reason"] == "tool_use"
        # Should have tool_use block
        tool_blocks = [b for b in result["content"] if b["type"] == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0]["name"] == "get_pods"
        assert tool_blocks[0]["input"] == {"namespace": "default"}

    def test_text_and_tool_call_response(self):
        response = {
            "id": "chatcmpl-789",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Let me check the pods.",
                        "tool_calls": [
                            {
                                "id": "call_xyz",
                                "type": "function",
                                "function": {
                                    "name": "get_pods",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }
        result = openai_to_anthropic_response(response, "gemini/gemini-2.5-flash")
        text_blocks = [b for b in result["content"] if b["type"] == "text"]
        tool_blocks = [b for b in result["content"] if b["type"] == "tool_use"]
        assert len(text_blocks) == 1
        assert text_blocks[0]["text"] == "Let me check the pods."
        assert len(tool_blocks) == 1

    def test_empty_choices(self):
        response = {"choices": []}
        result = openai_to_anthropic_response(response, "openai/gpt-4o")
        assert result["type"] == "error"

    def test_max_tokens_stop_reason(self):
        response = {
            "choices": [
                {
                    "message": {"content": "Truncated..."},
                    "finish_reason": "length",
                }
            ],
            "usage": {},
        }
        result = openai_to_anthropic_response(response, "openai/gpt-4o")
        assert result["stop_reason"] == "max_tokens"


# ---------------------------------------------------------------------------
# Stop reason mapping
# ---------------------------------------------------------------------------


class TestStopReasonMapping:
    def test_stop(self):
        assert _map_stop_reason("stop") == "end_turn"

    def test_tool_calls(self):
        assert _map_stop_reason("tool_calls") == "tool_use"

    def test_length(self):
        assert _map_stop_reason("length") == "max_tokens"

    def test_none(self):
        assert _map_stop_reason(None) == "end_turn"

    def test_unknown(self):
        assert _map_stop_reason("unknown_reason") == "end_turn"


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


class TestErrorTranslation:
    def test_auth_error(self):
        result = openai_error_to_anthropic(
            401,
            {"error": {"type": "authentication_error", "message": "Invalid API key"}},
        )
        assert result["type"] == "error"
        assert result["error"]["type"] == "authentication_error"
        assert "Invalid API key" in result["error"]["message"]

    def test_rate_limit_error(self):
        result = openai_error_to_anthropic(
            429,
            {"error": {"type": "rate_limit_error", "message": "Too many requests"}},
        )
        assert result["error"]["type"] == "rate_limit_error"

    def test_server_error(self):
        result = openai_error_to_anthropic(
            500, {"error": {"type": "server_error", "message": "Internal error"}}
        )
        assert result["error"]["type"] == "api_error"
