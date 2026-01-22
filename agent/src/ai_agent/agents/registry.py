"""
Agent registry with config service integration.

This module creates agents dynamically based on team configuration.
"""

from agents import Agent
from agents.exceptions import MaxTurnsExceeded

from ..core.agent_runner import get_agent_registry
from ..core.config import get_config
from ..core.logging import get_logger
from ..core.partial_work import summarize_partial_work
from ..integrations.a2a.agent_wrapper import get_remote_agents_for_team
from .aws_agent import create_aws_agent
from .base import TaskContext
from .ci_agent import create_ci_agent
from .coding_agent import create_coding_agent
from .investigation_agent import create_investigation_agent
from .k8s_agent import create_k8s_agent
from .log_analysis_agent import create_log_analysis_agent
from .metrics_agent import create_metrics_agent
from .planner import create_planner_agent

logger = get_logger(__name__)

# MCP server initialization removed - now handled per-request in api_server.py


def generate_sub_agent_instructions(sub_agent_tools: list, remote_agents: dict) -> str:
    """
    Generate dynamic instructions for available sub-agents.

    Args:
        sub_agent_tools: List of sub-agent tool functions
        remote_agents: Dict of remote agent tools

    Returns:
        Formatted instruction string to append to system prompt
    """
    if not sub_agent_tools:
        return ""

    instructions = ["\n\n## AVAILABLE SUB-AGENTS\n"]
    instructions.append("You can delegate tasks to these specialized agents:\n")

    for tool in sub_agent_tools:
        tool_name = getattr(tool, "__name__", "unknown")
        tool_doc = getattr(tool, "__doc__", "") or ""

        # Check if this is a remote agent
        is_remote = tool_name.replace("call_", "") in remote_agents
        icon = "🌐" if is_remote else "🤖"

        instructions.append(f"\n{icon} **{tool_name}**")
        if tool_doc:
            # Extract first line of docstring
            first_line = tool_doc.strip().split("\n")[0]
            instructions.append(f"   {first_line}")
        if is_remote:
            instructions.append("   (Remote A2A Agent)")

    return "".join(instructions)


# This ensures proper lifecycle management with async context managers


def create_generic_agent_from_config(agent_name: str, team_config=None) -> Agent:
    """
    Create a generic agent dynamically from team configuration.

    This factory allows creating custom agents defined only in config
    (like coordinator, news_searcher, joke_writer) without needing
    hardcoded Python implementations.

    Args:
        agent_name: Name of the agent from config (e.g., "coordinator")
        team_config: Team configuration containing agent definition

    Returns:
        Configured Agent instance
    """
    from agents import Agent, ModelSettings

    from ..tools.agent_tools import get_agent_tools

    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    if not team_cfg:
        raise ValueError(
            f"Cannot create agent '{agent_name}': no team config available"
        )

    # Get agent config from team configuration
    agent_config = team_cfg.get_agent_config(agent_name)

    if not agent_config.enabled:
        raise ValueError(f"Agent '{agent_name}' is disabled in config")

    # Get system prompt from config
    system_prompt = (
        agent_config.prompt.system if agent_config.prompt else None
    ) or f"You are {agent_config.name or agent_name}."

    # Get tools - for now use basic agent tools
    # TODO: Filter based on agent_config.tools
    tools = get_agent_tools()

    # Handle sub_agents (agent-as-tool pattern)
    sub_agent_tools = []  # Track sub-agent tools for instruction generation
    remote_agents_dict = {}

    if hasattr(agent_config, "sub_agents") and agent_config.sub_agents:
        import json

        from agents import function_tool

        logger.info(
            "creating_sub_agents",
            agent_name=agent_name,
            sub_agents=(
                list(agent_config.sub_agents.keys())
                if isinstance(agent_config.sub_agents, dict)
                else agent_config.sub_agents
            ),
        )

        # Load remote agents once for all sub-agents
        try:
            remote_agents_dict = get_remote_agents_for_team(team_cfg)
            if remote_agents_dict:
                logger.info(
                    "remote_agents_available_for_sub_agents",
                    count=len(remote_agents_dict),
                )
        except Exception as e:
            logger.warning("failed_to_load_remote_agents", error=str(e))

        # Create each sub-agent and wrap it as a tool
        for sub_agent_name in (
            agent_config.sub_agents.keys()
            if isinstance(agent_config.sub_agents, dict)
            else []
        ):
            # Check if sub-agent is enabled
            if not agent_config.sub_agents[sub_agent_name]:
                continue

            try:
                # Check if this is a remote A2A agent first
                if sub_agent_name in remote_agents_dict:
                    # Use the pre-wrapped A2A tool
                    remote_tool = remote_agents_dict[sub_agent_name]
                    tools.append(remote_tool)
                    sub_agent_tools.append(remote_tool)
                    logger.info(
                        "remote_agent_added_as_sub_agent",
                        parent_agent=agent_name,
                        remote_agent=sub_agent_name,
                    )
                    continue

                # Otherwise, recursively create the local sub-agent
                sub_agent = create_generic_agent_from_config(
                    sub_agent_name, team_config=team_cfg
                )

                # Create a wrapper function for this sub-agent
                def make_sub_agent_tool(sub_agent_obj, sub_name):
                    """Factory to create a closure that captures the sub-agent"""

                    @function_tool
                    def call_sub_agent(query: str) -> str:
                        f"""Delegate task to {sub_name} agent. The agent will handle the request and return results."""
                        try:
                            # Import Runner here to avoid circular imports
                            import asyncio
                            import threading

                            from agents import Runner

                            # Run sub-agent in a new thread with its own event loop
                            result_holder = {"result": None, "error": None, "partial": False}

                            def run_in_new_loop():
                                try:
                                    new_loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(new_loop)
                                    try:
                                        result = new_loop.run_until_complete(
                                            Runner().run(
                                                sub_agent_obj, query, max_turns=10
                                            )
                                        )
                                        result_holder["result"] = result
                                    except MaxTurnsExceeded as e:
                                        # Capture partial work instead of losing it
                                        logger.warning(
                                            "subagent_max_turns_exceeded",
                                            agent=sub_name,
                                            max_turns=10,
                                        )
                                        summary = summarize_partial_work(e, query, sub_name)
                                        result_holder["result"] = summary
                                        result_holder["partial"] = True
                                    finally:
                                        new_loop.close()
                                except Exception as e:
                                    result_holder["error"] = e

                            thread = threading.Thread(
                                target=run_in_new_loop, daemon=True
                            )
                            thread.start()
                            thread.join(timeout=300)  # 5 minute timeout

                            if thread.is_alive():
                                return json.dumps({"error": f"{sub_name} timed out", "agent": sub_name})

                            if result_holder["error"]:
                                return json.dumps(
                                    {"error": str(result_holder["error"]), "agent": sub_name}
                                )

                            # Check if result is a partial work summary
                            result = result_holder["result"]
                            if isinstance(result, dict) and result.get("status") == "incomplete":
                                logger.info(f"{sub_name}_agent_partial_results", findings=len(result.get("findings", [])))
                                return json.dumps(result)

                            # Extract output from result
                            output = getattr(result, "final_output", None) or getattr(
                                result, "output", None
                            )

                            if isinstance(output, str):
                                return output
                            elif hasattr(output, "model_dump_json"):
                                return output.model_dump_json()
                            elif hasattr(output, "dict"):
                                return json.dumps(output.dict())
                            else:
                                return json.dumps({"result": str(output)})

                        except Exception as e:
                            logger.error(f"{sub_name}_agent_failed", error=str(e))
                            return json.dumps({"error": str(e), "agent": sub_name})

                    # Set the function name and docstring dynamically
                    call_sub_agent.__name__ = f"call_{sub_name}"
                    call_sub_agent.__doc__ = f"Delegate task to {sub_name} agent. The agent will handle the request and return results. If max turns exceeded, returns partial findings with status='incomplete'."

                    return call_sub_agent

                # Create the tool and add to tools list
                sub_agent_tool = make_sub_agent_tool(sub_agent, sub_agent_name)
                tools.append(sub_agent_tool)
                sub_agent_tools.append(sub_agent_tool)

                logger.info(
                    "sub_agent_tool_created",
                    parent_agent=agent_name,
                    sub_agent=sub_agent_name,
                )

            except Exception as e:
                logger.error(
                    "failed_to_create_sub_agent",
                    parent_agent=agent_name,
                    sub_agent=sub_agent_name,
                    error=str(e),
                )

        # Auto-generate sub-agent instructions and append to system prompt
        if sub_agent_tools:
            sub_agent_instructions = generate_sub_agent_instructions(
                sub_agent_tools, remote_agents_dict
            )
            system_prompt = system_prompt + sub_agent_instructions
            logger.info(
                "sub_agent_instructions_generated",
                agent_name=agent_name,
                instructions_length=len(sub_agent_instructions),
            )

    # Get model settings
    model_name = agent_config.model.name if agent_config.model else config.openai.model
    temperature = (
        agent_config.model.temperature
        if agent_config.model
        else config.openai.temperature
    )
    max_tokens = (
        agent_config.model.max_tokens
        if agent_config.model
        else config.openai.max_tokens
    )

    # Create agent with config
    agent = Agent[TaskContext](
        name=agent_config.name or agent_name,
        model=model_name,
        model_settings=ModelSettings(
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        instructions=system_prompt,
        tools=tools,
    )

    logger.info(
        "generic_agent_created",
        agent_name=agent_name,
        model=model_name,
        prompt_length=len(system_prompt),
    )

    return agent


def create_agent_with_config(
    agent_name: str,
    base_agent_factory: callable,
) -> Agent | None:
    """
    Create an agent with configuration from config service applied.

    Args:
        agent_name: Name of the agent (e.g., "k8s_agent")
        base_agent_factory: Function that creates the base agent

    Returns:
        Configured agent or None if disabled
    """
    config = get_config()

    # Check if we have team config from config service
    if not config.team_config:
        logger.debug("no_team_config_using_defaults", agent_name=agent_name)
        return base_agent_factory()

    # Get agent-specific config
    agent_config = config.team_config.get_agent_config(agent_name)

    # Check if agent is disabled
    if not agent_config.enabled:
        logger.info("agent_disabled_by_config", agent_name=agent_name)
        return None

    # Create base agent
    agent = base_agent_factory()

    # Apply custom prompt if configured
    if agent_config.prompt:
        logger.info(
            "applying_custom_prompt",
            agent_name=agent_name,
            prompt_length=len(agent_config.prompt),
        )
        agent.instructions = agent_config.prompt

    # Apply timeout override
    if agent_config.timeout_seconds:
        logger.info(
            "applying_custom_timeout",
            agent_name=agent_name,
            timeout=agent_config.timeout_seconds,
        )
        # Note: This would need to be applied at runner level

    # Log tool restrictions (implementation would filter tools)
    if agent_config.disable_default_tools:
        logger.info(
            "tools_disabled",
            agent_name=agent_name,
            disabled_tools=agent_config.disable_default_tools,
        )
        # TODO: Filter tools from agent.tools list

    if agent_config.enable_extra_tools:
        logger.info(
            "extra_tools_enabled",
            agent_name=agent_name,
            extra_tools=agent_config.enable_extra_tools,
        )
        # TODO: Add extra tools based on config

    return agent


def initialize_all_agents() -> None:
    """
    Initialize and register all agents with config service integration.

    Agents are created with team-specific configuration applied.
    This includes both hardcoded agents and config-defined custom agents.
    """
    config = get_config()
    registry = get_agent_registry()

    logger.info("initializing_agents")

    # MCP servers are now created per-request (see api_server.py)
    # This ensures proper lifecycle management with async context managers

    # Hardcoded agent factory mappings (specialized agents with custom implementations)
    agent_factories = {
        "planner": create_planner_agent,
        "k8s_agent": create_k8s_agent,
        "aws_agent": create_aws_agent,
        "coding_agent": create_coding_agent,
        "metrics_agent": create_metrics_agent,
        "investigation_agent": create_investigation_agent,
        "ci_agent": create_ci_agent,
        "log_analysis_agent": create_log_analysis_agent,
    }

    # Register hardcoded agent factories
    for agent_name, factory in agent_factories.items():
        max_retries = 3
        if config.team_config:
            agent_cfg = config.team_config.get_agent_config(agent_name)
            max_retries = agent_cfg.max_retries or 3

        registry.register_factory(agent_name, factory, max_retries=max_retries)
        logger.info(
            "agent_factory_registered",
            agent_name=agent_name,
            max_retries=max_retries,
            type="hardcoded",
        )

    # Register config-defined custom agents (like coordinator, news_searcher, joke_writer)
    if config.team_config and hasattr(config.team_config, "agents_config"):
        for agent_name, agent_config in config.team_config.agents_config.items():
            # Skip if already registered as hardcoded agent
            if agent_name in agent_factories:
                continue

            # Skip if agent is disabled
            if not agent_config.get("enabled", True):
                logger.info("skipping_disabled_agent", agent_name=agent_name)
                continue

            # Create generic factory for this config-defined agent
            def make_factory(name):
                # Closure to capture agent_name
                return lambda team_config=None: create_generic_agent_from_config(
                    name, team_config
                )

            factory = make_factory(agent_name)
            max_retries = agent_config.get("max_retries", 3)

            registry.register_factory(agent_name, factory, max_retries=max_retries)
            logger.info(
                "agent_factory_registered",
                agent_name=agent_name,
                max_retries=max_retries,
                type="config_defined",
            )

    # Register remote A2A agents
    if config.team_config:
        try:
            remote_agents = get_remote_agents_for_team(config.team_config)
            logger.info("remote_agents_loaded", count=len(remote_agents))

            for agent_id, agent_tool in remote_agents.items():
                # Remote agents are already tool-wrapped by get_remote_agents_for_team
                # We register them as "callable tools" that can be used by other agents
                # They don't need agent factories since they're external
                logger.info(
                    "remote_agent_registered",
                    agent_id=agent_id,
                    agent_name=getattr(agent_tool, "__name__", agent_id),
                )

        except Exception as e:
            logger.warning("failed_to_load_remote_agents", error=str(e))

    logger.info(
        "agents_initialized",
        total_agents=len(registry.list_agents()),
        agents=registry.list_agents(),
    )


def reload_agents_on_config_change() -> None:
    """
    Callback for when config changes - reload agents with new config.

    This is called by the config reloader when team config changes.
    """
    logger.info("reloading_agents_due_to_config_change")

    # Clear existing agents
    registry = get_agent_registry()
    registry._factories.clear()
    registry._default_runners.clear()
    registry._team_runners.clear()

    # Re-initialize with new config
    initialize_all_agents()

    logger.info("agents_reloaded")
