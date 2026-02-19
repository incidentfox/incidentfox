"""
Default system prompts for all agents.

Single source of truth: config_service/templates/01_slack_incident_triage.json

Prompts are loaded at module import time from the JSON template file.
If the template cannot be found, a RuntimeError is raised immediately
to catch misconfigured deployments at startup.

The DEFAULT_PROMPTS dict and get_default_prompt() function maintain
backward-compatible interfaces consumed by hierarchical_config.py.
"""

import json
from pathlib import Path


def _load_prompts_from_template() -> dict[str, str]:
    """Load agent system prompts from 01_slack_incident_triage.json.

    Path resolution (works in both Docker and local dev):
      Docker: /app/src/core/default_prompts.py -> /app/templates/
      Local:  config_service/src/core/default_prompts.py -> config_service/templates/
    """
    # Path: src/core/ -> src/ -> app_root/ -> templates/
    app_root = Path(__file__).parent.parent.parent
    template_path = app_root / "templates" / "01_slack_incident_triage.json"

    if not template_path.exists():
        raise RuntimeError(
            f"Default prompts template not found at: {template_path}\n"
            f"Resolved app_root: {app_root}\n"
            "Ensure the templates/ directory is present and the file exists."
        )

    with open(template_path, encoding="utf-8") as f:
        template = json.load(f)

    return {
        name: agent.get("prompt", {}).get("system", "")
        for name, agent in template.get("agents", {}).items()
    }


# Load at module import time. Fails fast if template is missing.
DEFAULT_PROMPTS: dict[str, str] = _load_prompts_from_template()


def get_default_prompt(agent_name: str) -> str:
    """Get the default prompt for an agent."""
    return DEFAULT_PROMPTS.get(agent_name, "")
