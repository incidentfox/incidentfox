"""Translate between Anthropic Messages API and OpenAI Chat Completions API.

Pure functions with no I/O — fully unit-testable.

Reference formats:
- Anthropic: https://docs.anthropic.com/en/api/messages
- OpenAI Chat Completions: https://platform.openai.com/docs/api-reference/chat
"""

import json
import logging
from uuid import uuid4

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request translation: Anthropic → OpenAI Chat Completions
# ---------------------------------------------------------------------------


def anthropic_to_openai_request(body: dict) -> dict:
    """Convert Anthropic Messages API request body to Chat Completions format.

    Args:
        body: Anthropic request body with keys like system, messages, tools, etc.

    Returns:
        Chat Completions request body ready for litellm.acompletion().
    """
    messages: list[dict] = []

    # System message
    system = body.get("system")
    if system:
        if isinstance(system, str):
            messages.append({"role": "system", "content": system})
        elif isinstance(system, list):
            # Anthropic supports [{type: "text", text: "..."}] blocks
            text = "\n".join(
                block["text"] for block in system if block.get("type") == "text"
            )
            if text:
                messages.append({"role": "system", "content": text})

    # Convert each message
    for msg in body.get("messages", []):
        messages.extend(_convert_message(msg))

    result: dict = {
        "messages": messages,
    }

    # Max tokens
    if "max_tokens" in body:
        result["max_tokens"] = body["max_tokens"]

    # Optional parameters
    if "temperature" in body:
        result["temperature"] = body["temperature"]
    if "top_p" in body:
        result["top_p"] = body["top_p"]
    if "stop_sequences" in body:
        result["stop"] = body["stop_sequences"]

    # Streaming
    if body.get("stream"):
        result["stream"] = True
        result["stream_options"] = {"include_usage": True}

    # Tools
    tools = body.get("tools")
    if tools:
        converted_tools = [_convert_tool(t) for t in tools if _is_client_tool(t)]
        if converted_tools:
            result["tools"] = converted_tools

    # Tool choice
    tool_choice = body.get("tool_choice")
    if tool_choice is not None:
        result["tool_choice"] = _convert_tool_choice(tool_choice)

    return result


def _convert_message(msg: dict) -> list[dict]:
    """Convert a single Anthropic message to one or more OpenAI messages.

    Anthropic packs tool_use and tool_result into content blocks.
    OpenAI uses separate message structures for these.
    """
    role = msg.get("role", "user")
    content = msg.get("content")

    # Simple string content
    if isinstance(content, str):
        return [{"role": role, "content": content}]

    if not isinstance(content, list):
        return [{"role": role, "content": content or ""}]

    # Complex content blocks — separate into categories
    text_parts: list[dict] = []
    tool_uses: list[dict] = []
    tool_results: list[dict] = []

    for block in content:
        block_type = block.get("type", "")

        if block_type == "text":
            text_parts.append({"type": "text", "text": block.get("text", "")})

        elif block_type == "image":
            source = block.get("source", {})
            if source.get("type") == "url":
                text_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": source["url"]},
                    }
                )
            elif source.get("type") == "base64":
                media_type = source.get("media_type", "image/png")
                data = source.get("data", "")
                data_uri = f"data:{media_type};base64,{data}"
                text_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri},
                    }
                )

        elif block_type == "tool_use":
            tool_uses.append(block)

        elif block_type == "tool_result":
            tool_results.append(block)

    out: list[dict] = []

    # Emit text/image content
    if text_parts and role == "assistant" and tool_uses:
        # Assistant message with both text and tool_use — combine into one message
        openai_msg: dict = {"role": "assistant"}
        # Extract text content
        if len(text_parts) == 1 and text_parts[0].get("type") == "text":
            openai_msg["content"] = text_parts[0]["text"]
        else:
            openai_msg["content"] = text_parts
        # Add tool_calls
        openai_msg["tool_calls"] = [
            {
                "id": tu.get("id", f"toolu_{uuid4().hex[:24]}"),
                "type": "function",
                "function": {
                    "name": tu["name"],
                    "arguments": _safe_json_dumps(tu.get("input", {})),
                },
            }
            for tu in tool_uses
        ]
        out.append(openai_msg)
    else:
        # Text/image content without tool_use
        if text_parts:
            if len(text_parts) == 1 and text_parts[0].get("type") == "text":
                out.append({"role": role, "content": text_parts[0]["text"]})
            else:
                out.append({"role": role, "content": text_parts})

        # Tool uses without text (assistant message)
        if tool_uses and not text_parts:
            out.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": tu.get("id", f"toolu_{uuid4().hex[:24]}"),
                            "type": "function",
                            "function": {
                                "name": tu["name"],
                                "arguments": _safe_json_dumps(tu.get("input", {})),
                            },
                        }
                        for tu in tool_uses
                    ],
                }
            )

    # Tool results — each becomes a separate "tool" role message
    for tr in tool_results:
        tool_content = tr.get("content", "")
        if isinstance(tool_content, list):
            # Extract text from content blocks
            tool_content = "\n".join(
                block.get("text", "")
                for block in tool_content
                if block.get("type") == "text"
            )
        out.append(
            {
                "role": "tool",
                "tool_call_id": tr.get("tool_use_id", ""),
                "content": str(tool_content) if tool_content else "",
            }
        )

    return out if out else [{"role": role, "content": ""}]


def _convert_tool(tool: dict) -> dict:
    """Convert Anthropic tool definition to OpenAI function tool."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {}),
        },
    }


def _is_client_tool(tool: dict) -> bool:
    """Check if a tool is a client-side tool (not a server tool).

    Server tools like WebSearch, WebFetch are Anthropic-specific and should
    be filtered out when translating to other providers.
    """
    name = tool.get("name", "")
    # Server tools have specific patterns — filter them out
    server_tools = {
        "web_search",
        "computer",
        "text_editor",
        "bash",
    }
    tool_type = tool.get("type", "")
    if tool_type in ("computer_20241022", "text_editor_20241022", "bash_20241022"):
        return False
    return name not in server_tools


def _convert_tool_choice(choice) -> str | dict:
    """Convert Anthropic tool_choice to OpenAI format."""
    if isinstance(choice, str):
        if choice == "any":
            return "required"
        return choice  # "auto", "none" pass through

    if isinstance(choice, dict):
        choice_type = choice.get("type", "")
        if choice_type == "tool":
            return {"type": "function", "function": {"name": choice["name"]}}
        if choice_type == "any":
            return "required"
        if choice_type == "auto":
            return "auto"
        if choice_type == "none":
            return "none"

    return "auto"


# ---------------------------------------------------------------------------
# Response translation: OpenAI Chat Completions → Anthropic Messages
# ---------------------------------------------------------------------------


def openai_to_anthropic_response(response: dict, model_name: str) -> dict:
    """Convert Chat Completions response to Anthropic Messages API format.

    Args:
        response: OpenAI response dict (or litellm ModelResponse as dict).
        model_name: The model name to include in the Anthropic response.

    Returns:
        Anthropic-format response dict.
    """
    choices = response.get("choices", [])
    if not choices:
        return _error_response("No choices in response")

    choice = choices[0]
    message = choice.get("message", {})
    content: list[dict] = []

    # Text content
    text = message.get("content")
    if text:
        content.append({"type": "text", "text": text})

    # Tool calls (may be None from model_dump())
    for tc in message.get("tool_calls") or []:
        func = tc.get("function", {})
        content.append(
            {
                "type": "tool_use",
                "id": tc.get("id", f"toolu_{uuid4().hex[:24]}"),
                "name": func.get("name", ""),
                "input": _safe_json_loads(func.get("arguments", "{}")),
            }
        )

    # If no content at all, add empty text
    if not content:
        content.append({"type": "text", "text": ""})

    # Stop reason mapping
    finish_reason = choice.get("finish_reason", "stop")
    stop_reason = _map_stop_reason(finish_reason)

    # Usage mapping
    usage_in = response.get("usage", {})
    usage = {
        "input_tokens": usage_in.get("prompt_tokens", 0),
        "output_tokens": usage_in.get("completion_tokens", 0),
    }

    return {
        "id": response.get("id", f"msg_{uuid4().hex[:24]}"),
        "type": "message",
        "role": "assistant",
        "model": model_name,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }


def openai_error_to_anthropic(status_code: int, error_body: dict) -> dict:
    """Convert OpenAI error response to Anthropic error format."""
    error = error_body.get("error", {})
    error_message = error.get("message", str(error_body))
    error_type = error.get("type", "api_error")

    # Map OpenAI error types to Anthropic types
    type_map = {
        "invalid_request_error": "invalid_request_error",
        "authentication_error": "authentication_error",
        "permission_error": "permission_error",
        "not_found_error": "not_found_error",
        "rate_limit_error": "rate_limit_error",
        "server_error": "api_error",
        "insufficient_quota": "rate_limit_error",
    }

    return {
        "type": "error",
        "error": {
            "type": type_map.get(error_type, "api_error"),
            "message": error_message,
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


STOP_REASON_MAP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",  # Older OpenAI format
    "length": "max_tokens",
    "content_filter": "end_turn",
}


def _map_stop_reason(finish_reason: str | None) -> str:
    """Map OpenAI finish_reason to Anthropic stop_reason."""
    if not finish_reason:
        return "end_turn"
    return STOP_REASON_MAP.get(finish_reason, "end_turn")


def _safe_json_dumps(obj) -> str:
    """Safely serialize to JSON string."""
    try:
        return json.dumps(obj)
    except (TypeError, ValueError):
        return "{}"


def _safe_json_loads(s: str):
    """Safely parse JSON string, returning raw string on failure."""
    if not s:
        return {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


def _error_response(message: str) -> dict:
    """Build an Anthropic-format error response."""
    return {
        "type": "error",
        "error": {
            "type": "api_error",
            "message": message,
        },
    }
