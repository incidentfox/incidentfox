"""
Default agent prompts loaded from 01_slack_incident_triage template.

The 01_slack template is the canonical source of truth for production-quality
agent prompts. This module provides functions to load those prompts at runtime.

Usage:
    from ai_agent.prompts.default_prompts import get_default_agent_prompt

    # Get default prompt for any agent
    prompt = get_default_agent_prompt("k8s")
    prompt = get_default_agent_prompt("github")
    prompt = get_default_agent_prompt("planner")
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


def _find_template_path() -> Path | None:
    """
    Find the 01_slack_incident_triage.json template file.

    Tries multiple locations to handle different execution contexts:
    1. Relative to this module (standard case)
    2. Relative to current working directory (some test cases)

    Returns:
        Path to template file, or None if not found
    """
    # Method 1: Relative to this module
    # agent/src/ai_agent/prompts/default_prompts.py -> config_service/templates/
    module_dir = Path(__file__).parent
    repo_root = module_dir.parent.parent.parent.parent  # Up to repo root
    template_path = (
        repo_root / "config_service" / "templates" / "01_slack_incident_triage.json"
    )
    if template_path.exists():
        return template_path

    # Method 2: Relative to current working directory
    template_path = Path("config_service/templates/01_slack_incident_triage.json")
    if template_path.exists():
        return template_path

    return None


@lru_cache(maxsize=1)
def _load_template() -> dict[str, Any]:
    """
    Load the 01_slack_incident_triage template.

    Returns:
        Template dict with all agent configurations

    Raises:
        FileNotFoundError: If template cannot be found
    """
    template_path = _find_template_path()
    if template_path is None:
        raise FileNotFoundError(
            "01_slack_incident_triage.json template not found. "
            "Ensure you're running from the repository root."
        )

    with open(template_path) as f:
        return json.load(f)


@lru_cache(maxsize=16)
def get_default_agent_prompt(agent_name: str) -> str:
    """
    Get the default prompt for an agent from 01_slack template.

    This is the canonical way to get default prompts for all agents.
    The 01_slack template contains production-quality prompts that
    serve as defaults when teams don't customize.

    Args:
        agent_name: Name of the agent (e.g., 'planner', 'k8s', 'github',
                   'aws', 'metrics', 'log_analysis', 'investigation',
                   'coding', 'writeup')

    Returns:
        The agent's system prompt string

    Example:
        >>> prompt = get_default_agent_prompt("k8s")
        >>> print(prompt[:50])
        You are a Kubernetes expert troubleshooting cluster
    """
    try:
        template = _load_template()
    except FileNotFoundError:
        # Return minimal fallback for isolated tests
        return f"You are the {agent_name} agent."

    # Extract prompt from template
    agent_config = template.get("agents", {}).get(agent_name, {})
    prompt_config = agent_config.get("prompt", {})

    if isinstance(prompt_config, dict):
        prompt = prompt_config.get("system", "")
    elif isinstance(prompt_config, str):
        prompt = prompt_config
    else:
        prompt = ""

    if prompt:
        return prompt

    # Fallback for agents not in template
    return f"You are the {agent_name} agent."


def get_all_default_prompts() -> dict[str, str]:
    """
    Get all default agent prompts from 01_slack template.

    Returns:
        Dict mapping agent name to prompt string
    """
    try:
        template = _load_template()
    except FileNotFoundError:
        return {}

    prompts = {}
    for agent_name in template.get("agents", {}):
        prompts[agent_name] = get_default_agent_prompt(agent_name)

    return prompts


# Convenience aliases for specific agents
def get_default_planner_prompt() -> str:
    """Get default planner prompt from 01_slack template."""
    return get_default_agent_prompt("planner")


def get_default_k8s_prompt() -> str:
    """Get default Kubernetes agent prompt from 01_slack template."""
    return get_default_agent_prompt("k8s")


def get_default_aws_prompt() -> str:
    """Get default AWS agent prompt from 01_slack template."""
    return get_default_agent_prompt("aws")


def get_default_github_prompt() -> str:
    """Get default GitHub agent prompt from 01_slack template."""
    return get_default_agent_prompt("github")


def get_default_metrics_prompt() -> str:
    """Get default metrics agent prompt from 01_slack template."""
    return get_default_agent_prompt("metrics")


def get_default_log_analysis_prompt() -> str:
    """Get default log analysis agent prompt from 01_slack template."""
    return get_default_agent_prompt("log_analysis")


def get_default_investigation_prompt() -> str:
    """Get default investigation agent prompt from 01_slack template."""
    return get_default_agent_prompt("investigation")


def get_default_coding_prompt() -> str:
    """Get default coding agent prompt from 01_slack template."""
    return get_default_agent_prompt("coding")


def get_default_writeup_prompt() -> str:
    """Get default writeup agent prompt from 01_slack template."""
    return get_default_agent_prompt("writeup")
