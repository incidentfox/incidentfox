"""
A2A Agent Wrapper

Wraps remote A2A agents as callable tools/sub-agents for IncidentFox agents.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from ...core.agent import function_tool
from .client import A2AClient, create_a2a_client_from_config

logger = logging.getLogger(__name__)


def create_a2a_agent_tool(
    agent_id: str,
    agent_config: dict[str, Any],
    max_wait_time: float = 300.0,
) -> Callable:
    """
    Create a callable tool from an A2A remote agent configuration.

    Args:
        agent_id: Agent identifier (e.g., "openai_assistant")
        agent_config: Remote agent configuration
        max_wait_time: Maximum time to wait for task completion (seconds)

    Returns:
        Callable tool function decorated with @function_tool

    Example config:
        {
            "id": "security_scanner",
            "name": "Security Scanner Agent",
            "url": "https://security.example.com/a2a",
            "auth": {"type": "bearer", "token": "..."},
            "description": "Scans code for security vulnerabilities"
        }
    """
    # Create A2A client
    client = create_a2a_client_from_config(agent_config)
    agent_name = agent_config.get("name", agent_id)
    agent_desc = agent_config.get("description", f"Remote A2A agent: {agent_name}")

    @function_tool
    def call_remote_agent(query: str) -> str:
        """
        Call a remote A2A agent with a natural language query.

        The remote agent will process your request and return results.

        Args:
            query: Natural language description of what to investigate or execute

        Returns:
            JSON with the agent's response, findings, or error message
        """
        try:
            # Run async call in sync context
            result = asyncio.run(_call_agent_async(client, query, max_wait_time))
            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error("A2A agent call failed (agent=%s): %s", agent_id, e)
            return json.dumps(
                {
                    "error": str(e),
                    "agent": agent_name,
                }
            )

    # Customize tool name and docstring
    call_remote_agent.__name__ = f"call_{agent_id}_agent"
    call_remote_agent.__doc__ = f"""
Call the remote {agent_name} agent.

{agent_desc}

Send a natural language query describing what you need.
The remote agent will process it and return structured results.

Args:
    query: Natural language description of the task

Returns:
    JSON response from the remote agent
"""

    logger.info("A2A agent tool created: %s (%s)", agent_id, agent_name)
    return call_remote_agent


async def _call_agent_async(
    client: A2AClient,
    query: str,
    max_wait_time: float,
) -> dict[str, Any]:
    """
    Async helper to call A2A agent and wait for completion.

    Args:
        client: A2A client
        query: User query
        max_wait_time: Max wait time in seconds

    Returns:
        Agent response dict
    """
    # Send task
    task_response = await client.send_task(query)
    task_id = task_response.get("id")
    status = task_response.get("status", {})
    state = status.get("state")

    logger.debug("A2A task sent to %s: task_id=%s, state=%s", client.agent_name, task_id, state)

    # If immediately completed, return
    if state in ("completed", "failed"):
        return _extract_result(task_response)

    # Poll for completion
    poll_interval = 2.0  # Start with 2 seconds
    elapsed = 0.0

    while elapsed < max_wait_time:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        task_response = await client.get_task_status(task_id)
        status = task_response.get("status", {})
        state = status.get("state")

        logger.debug(
            "A2A task poll: agent=%s, task_id=%s, state=%s, elapsed=%.1f",
            client.agent_name, task_id, state, elapsed,
        )

        if state in ("completed", "failed", "canceled"):
            return _extract_result(task_response)

        # Exponential backoff (cap at 10 seconds)
        poll_interval = min(poll_interval * 1.5, 10.0)

    # Timeout
    logger.warning(
        "A2A task timeout: agent=%s, task_id=%s, elapsed=%.1f",
        client.agent_name, task_id, elapsed,
    )

    return {
        "error": "Task timed out",
        "task_id": task_id,
        "elapsed": elapsed,
    }


def _extract_result(task_response: dict[str, Any]) -> dict[str, Any]:
    """
    Extract result from task response.

    Args:
        task_response: Full task response from A2A agent

    Returns:
        Extracted result dict
    """
    status = task_response.get("status", {})
    state = status.get("state")
    message = status.get("message", {})
    artifacts = task_response.get("artifacts", [])

    # Extract text from message parts
    message_text = ""
    if message.get("parts"):
        message_text = "\n".join(
            part.get("text", "") for part in message["parts"] if part.get("text")
        )

    result = {
        "status": state,
        "message": message_text,
    }

    if artifacts:
        result["artifacts"] = artifacts

    return result


def get_remote_agents_for_team(team_config) -> dict[str, Callable]:
    """
    Load all remote A2A agents configured for a team.

    Args:
        team_config: TeamLevelConfig object with merged remote_agents dict

    Returns:
        Dict mapping agent_id to callable tool function
    """
    remote_agents_dict = {}

    if not team_config:
        return remote_agents_dict

    remote_agents_config = getattr(team_config, "remote_agents", {})

    logger.debug("Loading remote agents: %d configured", len(remote_agents_config))

    for agent_id, agent_config in remote_agents_config.items():
        if not isinstance(agent_config, dict):
            logger.warning("Invalid remote agent config: %s", agent_id)
            continue

        agent_type = agent_config.get("type")
        enabled = agent_config.get("enabled", True)

        if agent_type != "a2a":
            logger.debug("Remote agent %s is not A2A type (type=%s)", agent_id, agent_type)
            continue

        if not enabled:
            logger.debug("Remote agent %s is disabled", agent_id)
            continue

        try:
            tool = create_a2a_agent_tool(agent_id, agent_config)
            remote_agents_dict[agent_id] = tool

            logger.info("Remote agent loaded: %s (%s)", agent_id, agent_config.get("name"))

        except Exception as e:
            logger.error("Remote agent load failed for %s: %s", agent_id, e)

    logger.info("Remote agents loaded: %d", len(remote_agents_dict))

    return remote_agents_dict
