"""
Partial Work Capture for MaxTurnsExceeded Exceptions.

This module provides functionality to extract meaningful summaries from
the run_data attached to MaxTurnsExceeded exceptions, so that partial
work is not lost when an agent hits its turn limit.

Usage:
    from agents.exceptions import MaxTurnsExceeded
    from ai_agent.core.partial_work import summarize_partial_work

    try:
        result = await Runner.run(agent, query, max_turns=15)
    except MaxTurnsExceeded as e:
        summary = summarize_partial_work(e, query, "agent_name")
        return json.dumps(summary)  # Contains findings, in_progress, next_steps
"""

import json
import os
from typing import Any

from openai import OpenAI

from .logging import get_logger

logger = get_logger(__name__)


def extract_content_from_run_data(run_data) -> dict[str, list[str]]:
    """
    Extract structured content from run_data.new_items.

    Args:
        run_data: The RunErrorDetails from MaxTurnsExceeded exception

    Returns:
        Dict with keys: 'messages', 'tool_calls', 'tool_outputs', 'reasoning'
    """
    # Import here to avoid circular imports
    from agents.items import (
        MessageOutputItem,
        ReasoningItem,
        ToolCallItem,
        ToolCallOutputItem,
    )

    content = {
        "messages": [],
        "tool_calls": [],
        "tool_outputs": [],
        "reasoning": [],
    }

    if not run_data or not hasattr(run_data, "new_items"):
        return content

    for item in run_data.new_items:
        try:
            if isinstance(item, MessageOutputItem):
                # Extract text from message content
                for c in item.raw_item.content:
                    if hasattr(c, "text") and c.text:
                        content["messages"].append(c.text[:1000])

            elif isinstance(item, ToolCallItem):
                # Extract tool call info
                raw = item.raw_item
                if hasattr(raw, "name"):
                    call_info = f"Called: {raw.name}"
                    if hasattr(raw, "arguments"):
                        args_preview = str(raw.arguments)[:200]
                        call_info += f" with args: {args_preview}"
                    content["tool_calls"].append(call_info)
                elif isinstance(raw, dict):
                    call_info = f"Called: {raw.get('name', 'unknown')}"
                    content["tool_calls"].append(call_info)

            elif isinstance(item, ToolCallOutputItem):
                # Extract tool output
                output = item.output
                if output:
                    output_str = str(output)[:500]
                    content["tool_outputs"].append(output_str)

            elif isinstance(item, ReasoningItem):
                # Extract reasoning
                if hasattr(item.raw_item, "summary") and item.raw_item.summary:
                    for s in item.raw_item.summary:
                        if hasattr(s, "text"):
                            content["reasoning"].append(s.text[:500])
        except Exception as e:
            logger.warning("failed_to_extract_item", error=str(e))
            continue

    return content


def summarize_partial_work(
    exception,
    original_query: str,
    agent_name: str = "agent",
    model: str = "gpt-4o",
) -> dict[str, Any]:
    """
    Use an LLM to summarize the partial work from a MaxTurnsExceeded exception.

    Args:
        exception: The MaxTurnsExceeded exception with run_data attached
        original_query: The original query/task given to the agent
        agent_name: Name of the agent for context
        model: Which model to use for summarization (default: gpt-4o)

    Returns:
        Dict with:
            - status: "incomplete"
            - findings: List of key findings discovered
            - in_progress: What the agent was doing when stopped
            - next_steps: Suggested next steps to continue
            - tools_used: List of tools that were called
            - turns_used: Number of turns before hitting limit
            - agent: Name of the agent
    """
    run_data = getattr(exception, "run_data", None)

    if not run_data or not getattr(run_data, "new_items", None):
        logger.warning(
            "no_run_data_for_partial_work",
            agent=agent_name,
            has_run_data=run_data is not None,
        )
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
        client = OpenAI()

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

        # Reasoning models (o1, o3, o4, gpt-5) don't support temperature
        reasoning_prefixes = ("o1", "o3", "o4", "gpt-5")
        if model.startswith(reasoning_prefixes):
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )
        else:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0,
            )

        # Parse the response
        try:
            summary = json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            # Fallback if LLM doesn't return valid JSON
            summary = {
                "findings": ["Unable to parse structured summary"],
                "in_progress": response.choices[0].message.content[:200],
                "next_steps": ["Retry the investigation"],
                "confidence": "low",
            }

        logger.info(
            "partial_work_summarized",
            agent=agent_name,
            findings_count=len(summary.get("findings", [])),
            tools_used=len(content["tool_calls"]),
        )

        return {
            "status": "incomplete",
            "findings": summary.get("findings", []),
            "in_progress": summary.get("in_progress", "Unknown"),
            "next_steps": summary.get("next_steps", []),
            "confidence": summary.get("confidence", "low"),
            "tools_used": content["tool_calls"],
            "turns_used": len(run_data.new_items),
            "agent": agent_name,
        }

    except Exception as e:
        logger.error("failed_to_summarize_partial_work", agent=agent_name, error=str(e))
        # Fallback: return what we can extract without LLM
        return {
            "status": "incomplete",
            "findings": content["messages"][-3:] if content["messages"] else [],
            "in_progress": "Summarization failed - returning raw messages",
            "next_steps": ["Review the tools_used list for investigation progress"],
            "confidence": "low",
            "tools_used": content["tool_calls"],
            "turns_used": len(run_data.new_items) if run_data.new_items else 0,
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
