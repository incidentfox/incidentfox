#!/usr/bin/env python3
"""
Convert all template JSON files to canonical format.

Transformations:
1. Convert tools: {enabled: [], disabled: []} → {tool_id: bool}
2. Convert sub_agents: [] → {agent_id: bool}
3. Remove top-level mcps section
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict


def convert_tools_to_dict(tools_config: Any) -> Dict[str, bool]:
    """Convert tools from {enabled: [], disabled: []} format to {tool_id: bool} format."""
    if not tools_config:
        return {}

    if isinstance(tools_config, dict):
        # Check if it's the old format with enabled/disabled keys
        if "enabled" in tools_config or "disabled" in tools_config:
            result = {}
            for tool_id in tools_config.get("enabled", []):
                result[tool_id] = True
            for tool_id in tools_config.get("disabled", []):
                result[tool_id] = False
            return result
        else:
            # Already in dict format, return as-is
            return tools_config

    return {}


def convert_sub_agents_to_dict(sub_agents: Any) -> Dict[str, bool]:
    """Convert sub_agents from [] format to {agent_id: bool} format."""
    if not sub_agents:
        return {}

    if isinstance(sub_agents, list):
        return {agent_id: True for agent_id in sub_agents}
    elif isinstance(sub_agents, dict):
        # Already in dict format
        return sub_agents

    return {}


def convert_template_to_canonical(template: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a template to canonical format."""

    # 1. Remove top-level mcps section (not used by agent runtime)
    if "mcps" in template:
        print("  ✓ Removed top-level 'mcps' section")
        template.pop("mcps")

    # 2. Convert agents section
    if "agents" in template and isinstance(template["agents"], dict):
        for agent_id, agent_config in template["agents"].items():
            if not isinstance(agent_config, dict):
                continue

            # Convert tools format
            if "tools" in agent_config:
                old_tools = agent_config["tools"]
                new_tools = convert_tools_to_dict(old_tools)
                if old_tools != new_tools:
                    agent_config["tools"] = new_tools
                    print(f"  ✓ Converted tools for agent '{agent_id}'")

            # Convert sub_agents format
            if "sub_agents" in agent_config:
                old_sub_agents = agent_config["sub_agents"]
                new_sub_agents = convert_sub_agents_to_dict(old_sub_agents)
                if old_sub_agents != new_sub_agents:
                    agent_config["sub_agents"] = new_sub_agents
                    print(f"  ✓ Converted sub_agents for agent '{agent_id}'")

    return template


def main():
    # Get the config_service directory
    script_dir = Path(__file__).parent
    config_service_dir = script_dir.parent
    templates_dir = config_service_dir / "templates"

    print("=" * 60)
    print("Converting Templates to Canonical Format")
    print("=" * 60)
    print()

    # Convert all template JSON files
    template_files = sorted(templates_dir.glob("*.json"))
    print(f"Found {len(template_files)} template files\n")

    for template_file in template_files:
        print(f"Processing: {template_file.name}")

        try:
            # Read template
            with open(template_file, "r") as f:
                template = json.load(f)

            # Convert to canonical format
            original_json = json.dumps(template, indent=2, sort_keys=True)
            convert_template_to_canonical(template)
            canonical_json = json.dumps(template, indent=2, sort_keys=True)

            # Only write if changed
            if original_json != canonical_json:
                with open(template_file, "w") as f:
                    json.dump(template, f, indent=2)
                    f.write("\n")  # Add trailing newline
                print(f"  ✓ Updated: {template_file.name}\n")
            else:
                print("  ✓ No changes needed\n")

        except Exception as e:
            print(f"  ✗ ERROR: {e}\n")
            sys.exit(1)

    print("=" * 60)
    print("Conversion Complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
