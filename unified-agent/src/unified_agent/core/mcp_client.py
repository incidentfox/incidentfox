"""
MCP (Model Context Protocol) client integration using official SDK.

This module connects to MCP servers configured in the team config and
dynamically discovers tools that agents can use.

Architecture:
- Uses official `mcp` SDK for protocol communication
- Supports stdio transport (subprocess-based MCP servers)
- Discovers tools at runtime (no hardcoded tool list)
- Integrates seamlessly with existing agent tool system

Usage:
    # At agent startup
    tools = await initialize_mcp_servers(team_config)

    # Get tools for specific agent
    agent_tools = get_mcp_tools_for_agent(team_id, agent_name)

    # At shutdown
    await cleanup_mcp_connections(team_id)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# MCP SDK imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent
from mcp.types import Tool as MCPTool

from .mcp_loader import (
    MCPServerConfig,
    prepare_mcp_env,
    resolve_mcp_config,
    validate_mcp_config,
)

logger = logging.getLogger(__name__)


@dataclass
class MCPClient:
    """
    Wrapper around an active MCP connection.

    Attributes:
        config: MCP server configuration
        session: Active ClientSession
        tools: List of agent-callable tool functions
        _context_managers: Stack of context managers for cleanup
    """

    config: MCPServerConfig
    session: ClientSession
    tools: list[Callable]
    _context_managers: list[Any]

    async def close(self):
        """Close the MCP connection and cleanup resources."""
        try:
            for cm in reversed(self._context_managers):
                try:
                    await cm.__aexit__(None, None, None)
                except Exception as e:
                    logger.warning("MCP context exit error for %s: %s", self.config.id, e)

            logger.debug("MCP client closed: %s", self.config.id)

        except Exception as e:
            logger.error("MCP close error for %s: %s", self.config.id, e, exc_info=True)


async def connect_to_mcp_server(config: MCPServerConfig) -> MCPClient | None:
    """
    Connect to a single MCP server and discover its tools.

    Args:
        config: MCP server configuration (from mcp_loader)

    Returns:
        MCPClient with discovered tools, or None if connection fails
    """
    validation = validate_mcp_config(config)
    if not validation["valid"]:
        logger.error(
            "MCP config invalid for %s: missing=%s, errors=%s",
            config.id, validation["missing"], validation["errors"],
        )
        return None

    context_managers = []

    try:
        env = prepare_mcp_env(config)

        params = StdioServerParameters(
            command=config.command, args=config.args, env=env
        )

        logger.info("Connecting to MCP: %s (command=%s, args=%s)", config.id, config.command, config.args)

        # Connect via stdio transport
        stdio_ctx = stdio_client(params)
        read, write = await stdio_ctx.__aenter__()
        context_managers.append(stdio_ctx)

        # Create client session
        session_ctx = ClientSession(read, write)
        session = await session_ctx.__aenter__()
        context_managers.append(session_ctx)

        # Perform MCP initialization handshake
        init_result = await session.initialize()

        logger.info(
            "MCP connected: %s (protocol=%s, server=%s)",
            config.id,
            init_result.protocolVersion,
            init_result.serverInfo.name if init_result.serverInfo else "unknown",
        )

        # Discover tools
        tools_response = await session.list_tools()

        logger.info("MCP tools discovered: %s (%d tools)", config.id, len(tools_response.tools))

        # Convert MCP tools to agent-callable functions
        tools = []
        for tool_def in tools_response.tools:
            tool_func = create_agent_tool_from_mcp(
                mcp_id=config.id, tool_def=tool_def, session=session
            )
            tools.append(tool_func)

            logger.debug(
                "MCP tool registered: %s/%s",
                config.id, tool_def.name,
            )

        return MCPClient(
            config=config,
            session=session,
            tools=tools,
            _context_managers=context_managers,
        )

    except Exception as e:
        logger.error("MCP connection failed for %s: %s", config.id, e, exc_info=True)

        for cm in reversed(context_managers):
            try:
                await cm.__aexit__(None, None, None)
            except:
                pass

        return None


def create_agent_tool_from_mcp(
    mcp_id: str, tool_def: MCPTool, session: ClientSession
) -> Callable:
    """
    Convert an MCP tool definition to an agent-callable function.

    Creates a wrapper function that:
    - Has the same name and description as the MCP tool
    - Accepts kwargs matching the MCP tool's input schema
    - Calls the MCP server via session.call_tool()
    - Returns the result as a string

    Args:
        mcp_id: MCP server ID (for logging and namespacing)
        tool_def: Tool definition from MCP server
        session: Active MCP ClientSession

    Returns:
        Function tool that agents can call
    """
    from .agent import function_tool

    tool_name = tool_def.name
    tool_description = tool_def.description or f"Tool from {mcp_id} MCP server"
    input_schema = tool_def.inputSchema

    async def mcp_tool_wrapper(**kwargs) -> str:
        """Dynamically generated wrapper for MCP tool."""
        try:
            logger.debug("MCP tool call: %s/%s (args=%s)", mcp_id, tool_name, kwargs)

            result = await session.call_tool(tool_name, arguments=kwargs)

            content_parts = []
            for content in result.content:
                if isinstance(content, TextContent):
                    content_parts.append(content.text)
                elif hasattr(content, "text"):
                    content_parts.append(content.text)
                else:
                    content_parts.append(str(content))

            response = "\n\n".join(content_parts)

            logger.debug(
                "MCP tool call success: %s/%s (response_len=%d)",
                mcp_id, tool_name, len(response),
            )

            return response

        except Exception as e:
            error_msg = f"Error calling MCP tool '{tool_name}' from {mcp_id}: {str(e)}"
            logger.error("MCP tool call failed: %s/%s: %s", mcp_id, tool_name, e, exc_info=True)
            return error_msg

    # Attach metadata for agent system
    tool_wrapper_name = f"{mcp_id}__{tool_name}".replace("-", "_")
    mcp_tool_wrapper.__name__ = tool_wrapper_name
    mcp_tool_wrapper.name = tool_wrapper_name
    mcp_tool_wrapper.__doc__ = tool_description
    mcp_tool_wrapper._mcp_id = mcp_id
    mcp_tool_wrapper._mcp_tool_name = tool_name
    mcp_tool_wrapper._mcp_schema = input_schema
    mcp_tool_wrapper._is_mcp_tool = True

    # Apply @function_tool decorator
    return function_tool(mcp_tool_wrapper)


# Global registry of active MCP clients per team
_team_mcp_clients: dict[str, list[MCPClient]] = {}


async def initialize_mcp_servers(team_config: dict[str, Any]) -> list[Callable]:
    """
    Initialize MCP connections for a team and return all discovered tools.

    Args:
        team_config: Team's effective configuration (with inheritance resolved)

    Returns:
        List of tool functions from all connected MCP servers
    """
    team_id = team_config.get("team_id", "unknown")

    mcp_configs = resolve_mcp_config(team_config)

    if not mcp_configs:
        logger.info("No MCP servers configured for team %s", team_id)
        return []

    logger.info("MCP initialization starting for team %s (%d servers)", team_id, len(mcp_configs))

    connection_tasks = [connect_to_mcp_server(config) for config in mcp_configs]

    clients = await asyncio.gather(*connection_tasks, return_exceptions=True)

    active_clients = []
    for i, client in enumerate(clients):
        if isinstance(client, MCPClient):
            active_clients.append(client)
        elif isinstance(client, Exception):
            logger.error(
                "MCP connection exception for %s in team %s: %s",
                mcp_configs[i].id, team_id, client,
            )

    _team_mcp_clients[team_id] = active_clients

    all_tools = []
    for client in active_clients:
        all_tools.extend(client.tools)

    logger.info(
        "MCP initialization complete for team %s: %d/%d servers, %d tools",
        team_id, len(active_clients), len(mcp_configs), len(all_tools),
    )

    return all_tools


def get_mcp_tools_for_agent(team_id: str, agent_name: str) -> list[Callable]:
    """
    Get MCP tools available for a specific agent.

    Supports per-agent tool filtering based on team configuration.

    Args:
        team_id: Team identifier
        agent_name: Agent name (for filtering)

    Returns:
        List of tool functions from MCP servers (filtered for this agent)
    """
    import fnmatch

    clients = _team_mcp_clients.get(team_id, [])

    if not clients:
        logger.debug("No MCP clients for team %s (agent=%s)", team_id, agent_name)
        return []

    all_tools = []
    for client in clients:
        all_tools.extend(client.tools)

    # Get team config for tool assignments
    from .config import get_config

    config = get_config()

    if not config.team_config:
        return all_tools

    # Check if there are agent-specific tool assignments
    agent_assignments = getattr(config.team_config, "agent_tool_assignments", {}) or {}
    agent_config = (
        agent_assignments.get(agent_name)
        if isinstance(agent_assignments, dict)
        else None
    )

    if not agent_config:
        return all_tools

    # Get allowed MCP tool patterns
    allowed_patterns = agent_config.get("mcp_tools", ["*"])

    if "*" in allowed_patterns:
        return all_tools

    # Filter tools by pattern matching
    filtered_tools = []
    for tool in all_tools:
        tool_name = tool.__name__

        for pattern in allowed_patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                filtered_tools.append(tool)
                break

    logger.info(
        "MCP tools filtered for agent %s: %d/%d (patterns=%s)",
        agent_name, len(filtered_tools), len(all_tools), allowed_patterns,
    )

    return filtered_tools


async def cleanup_mcp_connections(team_id: str):
    """
    Cleanup MCP connections for a team.

    Args:
        team_id: Team identifier
    """
    clients = _team_mcp_clients.pop(team_id, [])

    if not clients:
        logger.debug("No MCP connections to cleanup for team %s", team_id)
        return

    logger.info("MCP cleanup starting for team %s (%d clients)", team_id, len(clients))

    cleanup_tasks = [client.close() for client in clients]
    await asyncio.gather(*cleanup_tasks, return_exceptions=True)

    logger.info("MCP cleanup complete for team %s (%d closed)", team_id, len(clients))


def get_active_mcp_servers(team_id: str) -> list[str]:
    """Get list of active MCP server IDs for a team."""
    clients = _team_mcp_clients.get(team_id, [])
    return [client.config.id for client in clients]


def get_mcp_tool_count(team_id: str) -> int:
    """Get total count of MCP tools available for a team."""
    clients = _team_mcp_clients.get(team_id, [])
    return sum(len(client.tools) for client in clients)
