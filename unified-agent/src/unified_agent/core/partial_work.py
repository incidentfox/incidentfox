"""
Partial Work Capture for MaxTurnsExceeded situations.

This module provides functionality to extract meaningful summaries when
an agent hits its turn limit, so that partial work is not lost.

Usage:
    from unified_agent.core.partial_work import summarize_partial_work

    try:
        result = await Runner.run(agent, query, max_turns=15)
    except MaxTurnsExceeded as e:
        summary = summarize_partial_work(e, query, "agent_name")
        return json.dumps(summary)
"""

import json
import logging
from typing import Any

import litellm

logger = logging.getLogger(__name__)


def extract_content_from_run_data(run_data) -> dict[str, list[str]]:
    """
    Extract structured content from run_data.

    Args:
        run_data: The run data from a max-turns-exceeded situation

    Returns:
        Dict with keys: 'messages', 'tool_calls', 'tool_outputs', 'reasoning'
    """
    content = {
        "messages": [],
        "tool_calls": [],
        "tool_outputs": [],
        "reasoning": [],
    }

    if not run_data:
        return content

    # Handle list of items (messages/tool calls)
    items = run_data if isinstance(run_data, list) else getattr(run_data, "new_items", None) or []

    for item in items:
        try:
            # Handle dict-style items (from litellm responses)
            if isinstance(item, dict):
                role = item.get("role", "")
                if role == "assistant":
                    msg_content = item.get("content", "")
                    if msg_content:
                        content["messages"].append(str(msg_content)[:1000])
                    # Check for tool calls
                    tool_calls = item.get("tool_calls", [])
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            func = tc.get("function", {})
                            call_info = f"Called: {func.get('name', 'unknown')}"
                            args_preview = str(func.get("arguments", ""))[:200]
                            call_info += f" with args: {args_preview}"
                            content["tool_calls"].append(call_info)
                elif role == "tool":
                    output = item.get("content", "")
                    if output:
                        content["tool_outputs"].append(str(output)[:500])

            # Handle object-style items (from SDK responses)
            elif hasattr(item, "raw_item"):
                raw = item.raw_item
                if hasattr(raw, "content"):
                    for c in raw.content:
                        if hasattr(c, "text") and c.text:
                            content["messages"].append(c.text[:1000])
                elif hasattr(raw, "name"):
                    call_info = f"Called: {raw.name}"
                    if hasattr(raw, "arguments"):
                        call_info += f" with args: {str(raw.arguments)[:200]}"
                    content["tool_calls"].append(call_info)

        except Exception as e:
            logger.warning("Failed to extract item from run data: %s", e)
            continue

    return content


def summarize_partial_work(
    exception,
    original_query: str,
    agent_name: str = "agent",
    model: str = "anthropic/claude-sonnet-4-20250514",
) -> dict[str, Any]:
    """
    Use an LLM to summarize the partial work from a max-turns-exceeded situation.

    Args:
        exception: The exception with run_data attached (or any object)
        original_query: The original query/task given to the agent
        agent_name: Name of the agent for context
        model: Which model to use for summarization

    Returns:
        Dict with status, findings, in_progress, next_steps, tools_used, etc.
    """
    run_data = getattr(exception, "run_data", None)

    if not run_data:
        logger.warning("No run data for partial work summary (agent=%s)", agent_name)
        return {
            "status": "incomplete",
            "findings": [],
            "in_progress": "No work captured - agent may have failed immediately",
            "next_steps": ["Retry with a simpler query", "Check agent configuration"],
            "tools_used": [],
            "turns_used": 0,
            "agent": agent_name,
        }

    # Extract content from run_data
    content = extract_content_from_run_data(run_data)

    # Build context for the summarizer LLM
    context_parts = []

    if content["messages"]:
        context_parts.append(
            "## Agent's Messages/Thoughts:\n" + "\n---\n".join(content["messages"][-3:])
        )

    if content["tool_calls"]:
        context_parts.append("## Tools Called:\n" + "\n".join(content["tool_calls"]))

    if content["tool_outputs"]:
        context_parts.append(
            "## Tool Results (truncated):\n"
            + "\n---\n".join(content["tool_outputs"][-5:])
        )

    if content["reasoning"]:
        context_parts.append(
            "## Agent's Reasoning:\n" + "\n".join(content["reasoning"][-3:])
        )

    context_text = (
        "\n\n".join(context_parts) if context_parts else "No content captured."
    )

    # Use LLM to summarize
    try:
        prompt = f"""You are summarizing the partial work of an AI agent that was stopped before completing its task.

## Original Task
{original_query[:2000]}

## Agent Name
{agent_name}

## Partial Work Captured
{context_text}

## Your Task
Summarize this partial work into a structured format. Be concise but capture all important findings.

Respond in this exact JSON format:
{{
    "findings": ["finding 1", "finding 2", ...],
    "in_progress": "what the agent was doing when stopped",
    "next_steps": ["suggested next step 1", "suggested next step 2", ...],
    "confidence": "low/medium/high - how complete was the investigation"
}}

Only output the JSON, no other text."""

        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0,
        )

        # Parse the response
        try:
            summary = json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            summary = {
                "findings": ["Unable to parse structured summary"],
                "in_progress": response.choices[0].message.content[:200],
                "next_steps": ["Retry the investigation"],
                "confidence": "low",
            }

        logger.info(
            "Partial work summarized for %s: %d findings, %d tools used",
            agent_name, len(summary.get("findings", [])), len(content["tool_calls"]),
        )

        items = run_data if isinstance(run_data, list) else getattr(run_data, "new_items", []) or []

        return {
            "status": "incomplete",
            "findings": summary.get("findings", []),
            "in_progress": summary.get("in_progress", "Unknown"),
            "next_steps": summary.get("next_steps", []),
            "confidence": summary.get("confidence", "low"),
            "tools_used": content["tool_calls"],
            "turns_used": len(items),
            "agent": agent_name,
        }

    except Exception as e:
        logger.error("Failed to summarize partial work for %s: %s", agent_name, e)
        items = run_data if isinstance(run_data, list) else getattr(run_data, "new_items", []) or []
        return {
            "status": "incomplete",
            "findings": content["messages"][-3:] if content["messages"] else [],
            "in_progress": "Summarization failed - returning raw messages",
            "next_steps": ["Review the tools_used list for investigation progress"],
            "confidence": "low",
            "tools_used": content["tool_calls"],
            "turns_used": len(items) if items else 0,
            "agent": agent_name,
            "summarization_error": str(e),
        }


def format_partial_result_for_logging(summary: dict[str, Any]) -> str:
    """
    Format the partial work summary as a string for logging.

    Args:
        summary: The dict returned by summarize_partial_work()

    Returns:
        Formatted string for logging
    """
    parts = [
        f"[{summary.get('agent', 'Agent')}] PARTIAL RESULTS (max turns exceeded)",
        f"Status: incomplete | Confidence: {summary.get('confidence', 'low')} | Turns: {summary.get('turns_used', '?')}",
    ]

    findings = summary.get("findings", [])
    if findings:
        parts.append(f"Findings: {len(findings)} items")
        for f in findings[:2]:
            parts.append(f"  - {f[:100]}...")

    in_progress = summary.get("in_progress")
    if in_progress:
        parts.append(f"Was working on: {in_progress[:100]}...")

    return " | ".join(parts)
