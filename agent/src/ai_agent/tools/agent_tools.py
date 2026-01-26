"""
Meta-agent tools for reasoning, web search, and LLM calls.
"""

from __future__ import annotations

import json
import os
import uuid

import httpx
from agents import function_tool

from ..core.config_required import make_config_required_response
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger
from .human_interaction import ask_human

logger = get_logger(__name__)


@function_tool
def think(
    mode: str = "reflect",
    topic: str = "",
    context: str = "",
    notes: str = "",
) -> str:
    """
    Structured thinking/reflection helper.
    Use this tool to pause and think systematically before making decisions.

    Args:
        mode: One of "plan", "reflect", "self_critic", "diagnose"
        topic: What you're thinking about
        context: Relevant background information
        notes: Your observations and thoughts

    Returns:
        JSON string with thinking result
    """
    mode = (mode or "reflect").strip().lower()
    topic = (topic or "").strip()

    mode_configs = {
        "plan": {
            "checklist": [
                "What is the goal?",
                "What are the constraints?",
                "What could go wrong?",
            ],
            "summary": f"Planned approach for '{topic}'.",
            "next_actions": ["Gather info", "Execute plan", "Validate results"],
        },
        "reflect": {
            "checklist": ["What's accomplished?", "What's working?", "What's blocked?"],
            "summary": f"Reflected on '{topic}'.",
            "next_actions": ["Address blockers", "Continue execution"],
        },
        "self_critic": {
            "checklist": [
                "Does this solve the problem?",
                "Is analysis complete?",
                "What's missing?",
            ],
            "summary": f"Self-critique for '{topic}'.",
            "next_actions": ["Address gaps", "Gather more evidence if needed"],
        },
        "diagnose": {
            "checklist": [
                "What are symptoms?",
                "What changed?",
                "What are hypotheses?",
            ],
            "summary": f"Diagnosis for '{topic}'.",
            "next_actions": ["Test hypothesis", "Narrow down root cause"],
        },
    }

    config = mode_configs.get(mode, mode_configs["reflect"])
    thought_id = f"think_{uuid.uuid4().hex[:8]}"

    logger.info("agent_think", thought_id=thought_id, mode=mode, topic=topic)

    return json.dumps(
        {
            "thought_id": thought_id,
            "mode": mode,
            "topic": topic,
            "summary": config["summary"],
            "next_actions": config["next_actions"],
        }
    )


@function_tool
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web for information.

    Args:
        query: Search query string
        max_results: Maximum results (default 5)

    Returns:
        JSON string with search results
    """
    if not query:
        return json.dumps({"error": "Query required", "results": []})

    logger.info("web_search", query=query)

    # Get Tavily API key from integration config
    tavily_key = None

    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("tavily")
        tavily_key = config.get("api_key")

    # 2. Fallback to environment variable (dev/testing)
    if not tavily_key:
        tavily_key = os.getenv("TAVILY_API_KEY")

    # 3. If still not found, return config_required response
    if not tavily_key:
        logger.warning("tavily_not_configured", tool="web_search")
        return make_config_required_response(
            integration="tavily",
            tool="web_search",
            missing_config=["TAVILY_API_KEY"],
        )

    # Call Tavily API
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": tavily_key,
                "query": query,
                "max_results": min(max_results, 10),
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:300],
            }
            for r in data.get("results", [])[:max_results]
        ]
        return json.dumps(
            {"query": query, "answer": data.get("answer", ""), "results": results}
        )
    except Exception as e:
        logger.error("tavily_api_failed", error=str(e), query=query)
        return json.dumps(
            {"query": query, "error": f"Web search failed: {str(e)}", "results": []}
        )


@function_tool
def llm_call(prompt: str, system_prompt: str = "", purpose: str = "") -> str:
    """
    Make an LLM call for complex reasoning.

    Args:
        prompt: The main prompt
        system_prompt: Optional system prompt
        purpose: Brief description of purpose

    Returns:
        JSON string with LLM response
    """
    if not prompt:
        return json.dumps({"error": "Prompt required", "response": ""})

    logger.info("llm_call", purpose=purpose, prompt_length=len(prompt))

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return json.dumps({"error": "OPENAI_API_KEY not set", "response": ""})

    try:
        import openai

        client = openai.OpenAI(api_key=openai_key)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        model = os.getenv("OPENAI_MODEL", "gpt-4o")

        # Reasoning models (o1, o3, o4, gpt-5) don't support temperature
        reasoning_prefixes = ("o1", "o3", "o4", "gpt-5")
        if model.startswith(reasoning_prefixes):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=2000,
            )
        else:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
            )
        return json.dumps(
            {
                "purpose": purpose,
                "response": response.choices[0].message.content or "",
                "model": response.model,
            }
        )
    except Exception as e:
        logger.error("llm_call_failed", error=str(e))
        return json.dumps({"error": str(e), "response": ""})


@function_tool
def record_learning(
    category: str,
    subject: str,
    outcome: str,
    notes: str,
    severity: str = "medium",
) -> str:
    """
    Record a learning for future reference.

    Args:
        category: "tool" | "approach" | "agent" | "general"
        subject: What you learned about
        outcome: "success" | "failure" | "partial"
        notes: Your observation
        severity: "low" | "medium" | "high"

    Returns:
        JSON confirmation
    """
    if not subject or not notes:
        return json.dumps({"error": "Subject and notes required"})

    learning_id = f"learning_{uuid.uuid4().hex[:8]}"
    logger.info(
        "record_learning", learning_id=learning_id, category=category, subject=subject
    )

    return json.dumps(
        {
            "learning_id": learning_id,
            "category": category or "general",
            "subject": subject,
            "outcome": outcome or "observation",
            "summary": f"Recorded {outcome} learning for {category}:{subject}",
        }
    )


def get_agent_tools() -> list:
    """Get all meta-agent tools."""
    return [think, web_search, llm_call, record_learning, ask_human]
