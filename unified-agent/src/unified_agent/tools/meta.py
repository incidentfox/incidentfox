"""
Meta tools for agent reasoning and web search.

These tools enhance the agent's capabilities beyond direct infrastructure operations.
"""

import json
import logging
from typing import Optional

from ..core.agent import function_tool
from . import register_tool

logger = logging.getLogger(__name__)


@function_tool
def think(thought: str) -> str:
    """
    Use this tool to think through complex problems step-by-step.

    This is a scratchpad for working through:
    - Multi-step reasoning
    - Hypothesis formation
    - Evidence correlation
    - Decision making

    Args:
        thought: Your reasoning process written out

    Returns:
        Confirmation that the thought was recorded
    """
    # This tool is essentially a no-op that allows the model to
    # "think out loud" in a structured way that gets recorded
    logger.debug(f"Agent thought: {thought[:200]}...")
    return json.dumps(
        {
            "status": "thought_recorded",
            "message": "Continue with your investigation based on this reasoning.",
        }
    )


@function_tool
def web_search(
    query: str,
    num_results: int = 5,
) -> str:
    """
    Search the web for information.

    Use this to find:
    - Documentation
    - Stack Overflow answers
    - Best practices
    - Error message explanations

    Args:
        query: Search query
        num_results: Number of results to return (max 10)

    Returns:
        Search results as JSON string
    """
    try:
        # Try to use DuckDuckGo search (lightweight, no API key needed)
        try:
            from duckduckgo_search import DDGS

            num_results = min(num_results, 10)
            results = []

            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=num_results):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                        }
                    )

            return json.dumps(
                {
                    "query": query,
                    "result_count": len(results),
                    "results": results,
                }
            )

        except ImportError:
            # Fall back to a simple response
            return json.dumps(
                {
                    "error": "Web search not available",
                    "message": "Install duckduckgo-search package: pip install duckduckgo-search",
                    "query": query,
                }
            )

    except Exception as e:
        logger.error(f"web_search error: {e}")
        return json.dumps(
            {
                "error": str(e),
                "query": query,
            }
        )


@function_tool
def web_fetch(
    url: str,
    extract_text: bool = True,
) -> str:
    """
    Fetch content from a URL.

    Use this to:
    - Read documentation pages
    - Fetch API responses
    - Get raw web content

    Args:
        url: URL to fetch
        extract_text: If True, extract plain text from HTML

    Returns:
        Fetched content as JSON string
    """
    try:
        import httpx

        response = httpx.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()

        content = response.text

        if extract_text and "text/html" in response.headers.get("content-type", ""):
            # Try to extract text from HTML
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(content, "html.parser")

                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()

                content = soup.get_text(separator="\n", strip=True)
                # Limit content size
                if len(content) > 50000:
                    content = content[:50000] + "\n... (truncated)"
            except ImportError:
                pass  # Use raw HTML if beautifulsoup not available

        return json.dumps(
            {
                "url": url,
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
                "content": content[:100000],  # Limit size
            }
        )

    except ImportError:
        return json.dumps(
            {
                "error": "httpx not installed",
                "message": "Install httpx: pip install httpx",
                "url": url,
            }
        )
    except Exception as e:
        logger.error(f"web_fetch error: {e}")
        return json.dumps(
            {
                "error": str(e),
                "url": url,
            }
        )


@function_tool
def llm_call(
    prompt: str,
    context: Optional[str] = None,
) -> str:
    """
    Make a direct LLM call for complex reasoning tasks.

    Use this when you need to:
    - Analyze complex data
    - Generate structured output
    - Get a second opinion on findings

    Args:
        prompt: The prompt to send to the LLM
        context: Optional additional context

    Returns:
        LLM response as JSON string
    """
    # This tool allows nested LLM calls for complex reasoning
    # In practice, it would use the configured LLM provider
    try:
        import os

        import litellm

        full_prompt = prompt
        if context:
            full_prompt = f"Context:\n{context}\n\nTask:\n{prompt}"

        # Use a fast model for nested calls
        response = litellm.completion(
            model=os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-20250514"),
            messages=[{"role": "user", "content": full_prompt}],
            max_tokens=4000,
        )

        return json.dumps(
            {
                "response": response.choices[0].message.content,
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                },
            }
        )

    except Exception as e:
        logger.error(f"llm_call error: {e}")
        return json.dumps(
            {
                "error": str(e),
                "prompt": prompt[:500],
            }
        )


# =============================================================================
# Register Tools
# =============================================================================

register_tool("think", think)
register_tool("web_search", web_search)
register_tool("web_fetch", web_fetch)
register_tool("llm_call", llm_call)
