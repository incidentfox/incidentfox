#!/usr/bin/env python3
"""
Generate golden prompt files for all templates.

Golden files are read-only snapshots of the fully assembled prompts
that show exactly what the model receives at runtime.

Usage:
    python generate_golden_prompts.py                    # Generate all
    python generate_golden_prompts.py --template 01_slack_incident_triage
    python generate_golden_prompts.py --check            # Check if golden files are stale
"""

import argparse
import json
import sys
from pathlib import Path

# Add agent module to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from ai_agent.prompts.agent_capabilities import AGENT_CAPABILITIES
from ai_agent.prompts.default_prompts import get_default_agent_prompt
from ai_agent.prompts.layers import (
    BEHAVIORAL_PRINCIPLES,
    DELEGATION_GUIDANCE,
    ERROR_HANDLING_COMMON,
    EVIDENCE_FORMAT_GUIDANCE,
    SUBAGENT_GUIDANCE,
    TOOL_CALL_LIMITS_TEMPLATE,
    TRANSPARENCY_AND_AUDITABILITY,
    build_agent_prompt_sections,
    build_capabilities_section,
    get_integration_errors,
    get_integration_tool_limits,
)

# =============================================================================
# Template Parsing
# =============================================================================


def load_template(template_name: str) -> dict:
    """Load a template JSON file."""
    templates_dir = REPO_ROOT / "config_service" / "templates"
    template_path = templates_dir / f"{template_name}.json"

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    with open(template_path) as f:
        return json.load(f)


def get_all_templates() -> list[str]:
    """Get all template names (without .json extension)."""
    templates_dir = REPO_ROOT / "config_service" / "templates"
    return sorted(
        [
            p.stem
            for p in templates_dir.glob("*.json")
            if not p.stem.startswith("_")  # Skip _schema.json etc
        ]
    )


def get_template_agents(template: dict) -> dict:
    """Extract agent configurations from template."""
    return template.get("agents", {})


def get_entrance_agent(template: dict) -> str:
    """Get the entrance agent name from template."""
    return template.get("entrance_agent", "planner")


# =============================================================================
# Prompt Assembly
# =============================================================================


def assemble_agent_prompt(
    agent_name: str,
    agent_config: dict,
    template: dict,
    is_subagent: bool = False,
    is_master: bool = False,
) -> str:
    """
    Assemble the full prompt for an agent.

    This mirrors the assembly logic in the application code.
    """
    parts = []

    # 1. Get base prompt (custom override or default from 01_slack)
    prompt_config = agent_config.get("prompt", {})
    if isinstance(prompt_config, str):
        custom_prompt = prompt_config
    elif isinstance(prompt_config, dict):
        custom_prompt = prompt_config.get("system")
    else:
        custom_prompt = None

    # Get base prompt from 01_slack template (single source of truth)
    default_prompt = get_default_agent_prompt(agent_name)

    base_prompt = custom_prompt or default_prompt
    parts.append(base_prompt)

    # 2. Add capabilities section (for orchestrators)
    sub_agents = agent_config.get("sub_agents", {})
    if sub_agents and isinstance(sub_agents, dict):
        enabled_agents = [k for k, v in sub_agents.items() if v]
        if enabled_agents:
            # Filter AGENT_CAPABILITIES to only include enabled sub-agents
            capabilities = build_capabilities_section(
                enabled_agents=enabled_agents,
                agent_capabilities=AGENT_CAPABILITIES,
                remote_agents=None,  # Templates don't have remote agents
            )
            parts.append("\n\n" + capabilities)

    # 3. Add role-based sections
    if is_master:
        parts.append("\n\n" + DELEGATION_GUIDANCE)

    if is_subagent:
        parts.append("\n\n" + SUBAGENT_GUIDANCE)

    # 4. Add shared sections (error handling, tool limits, evidence, transparency)
    # Determine integration name for error handling
    integration_map = {
        "k8s": "kubernetes",
        "aws": "aws",
        "github": "github",
        "metrics": "metrics",
        "log_analysis": "logs",
        "coding": "coding",
    }
    integration_name = integration_map.get(agent_name, agent_name)

    shared_sections = build_agent_prompt_sections(
        integration_name=integration_name,
        include_error_handling=True,
        include_tool_limits=True,
        include_evidence_format=True,
        include_transparency=True,
    )
    parts.append("\n\n" + shared_sections)

    # 5. Add XML output format from template if present (avoid duplication)
    # Note: TRANSPARENCY_AND_AUDITABILITY already includes XML format,
    # so we DON'T add template's OUTPUT FORMAT section

    return "".join(parts)


def determine_agent_role(agent_name: str, template: dict) -> tuple[bool, bool]:
    """
    Determine if an agent is a sub-agent or master based on template structure.

    Returns:
        (is_subagent, is_master)
    """
    entrance_agent = get_entrance_agent(template)
    agents = get_template_agents(template)

    # Check if this agent has sub_agents (makes it a master)
    agent_config = agents.get(agent_name, {})
    sub_agents = agent_config.get("sub_agents", {})
    is_master = bool(sub_agents and any(sub_agents.values()))

    # Check if this agent is a sub-agent of another
    is_subagent = False
    for other_name, other_config in agents.items():
        if other_name == agent_name:
            continue
        other_sub_agents = other_config.get("sub_agents", {})
        if isinstance(other_sub_agents, dict) and other_sub_agents.get(agent_name):
            is_subagent = True
            break

    return is_subagent, is_master


# =============================================================================
# Golden File Generation
# =============================================================================


def generate_golden_for_template(template_name: str, output_dir: Path) -> list[str]:
    """
    Generate golden files for all agents in a template.

    Returns:
        List of generated file paths
    """
    template = load_template(template_name)
    agents = get_template_agents(template)

    template_dir = output_dir / template_name
    template_dir.mkdir(parents=True, exist_ok=True)

    generated_files = []

    for agent_name, agent_config in agents.items():
        # Skip disabled agents
        if not agent_config.get("enabled", True):
            continue

        # Determine role
        is_subagent, is_master = determine_agent_role(agent_name, template)

        # Assemble prompt
        prompt = assemble_agent_prompt(
            agent_name=agent_name,
            agent_config=agent_config,
            template=template,
            is_subagent=is_subagent,
            is_master=is_master,
        )

        # Write golden file
        output_path = template_dir / f"{agent_name}.md"

        # Add header with metadata
        header = f"""# Golden Prompt: {agent_name}

**Template:** {template_name}
**Role:** {"Master (orchestrator)" if is_master else "Sub-agent" if is_subagent else "Standalone"}
**Model:** {agent_config.get("model", {}).get("name", "default")}

---

"""

        with open(output_path, "w") as f:
            f.write(header + prompt)

        generated_files.append(str(output_path))
        print(f"  Generated: {output_path.relative_to(output_dir.parent)}")

    return generated_files


def generate_all_golden_files(output_dir: Path) -> int:
    """
    Generate golden files for all templates.

    Returns:
        Total number of files generated
    """
    templates = get_all_templates()
    total_files = 0

    for template_name in templates:
        print(f"\n📁 {template_name}")
        try:
            files = generate_golden_for_template(template_name, output_dir)
            total_files += len(files)
        except Exception as e:
            print(f"  ❌ Error: {e}")

    return total_files


def check_golden_files_stale(output_dir: Path) -> bool:
    """
    Check if golden files are stale (would change if regenerated).

    Returns:
        True if files are stale, False if up-to-date
    """
    import filecmp
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_output = Path(tmpdir)

        templates = get_all_templates()
        stale_files = []

        for template_name in templates:
            try:
                generate_golden_for_template(template_name, tmp_output)

                # Compare with existing files
                template_dir = output_dir / template_name
                tmp_template_dir = tmp_output / template_name

                if not template_dir.exists():
                    stale_files.append(f"{template_name}/ (missing)")
                    continue

                for tmp_file in tmp_template_dir.glob("*.md"):
                    existing_file = template_dir / tmp_file.name
                    if not existing_file.exists():
                        stale_files.append(f"{template_name}/{tmp_file.name} (missing)")
                    elif not filecmp.cmp(tmp_file, existing_file, shallow=False):
                        stale_files.append(f"{template_name}/{tmp_file.name} (changed)")

            except Exception as e:
                print(f"Error checking {template_name}: {e}")

        if stale_files:
            print(
                "❌ Golden files are STALE. Run 'generate_golden_prompts.py' to update:"
            )
            for f in stale_files:
                print(f"  - {f}")
            return True
        else:
            print("✅ Golden files are up-to-date")
            return False


# =============================================================================
# Main
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Generate golden prompt files")
    parser.add_argument(
        "--template",
        help="Generate for specific template only",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if golden files are stale (for CI)",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "config_service" / "golden_templates"),
        help="Output directory",
    )

    args = parser.parse_args()
    output_dir = Path(args.output)

    if args.check:
        stale = check_golden_files_stale(output_dir)
        sys.exit(1 if stale else 0)

    print("🔧 Generating golden prompt files...")
    print(f"   Output: {output_dir}")

    if args.template:
        print(f"\n📁 {args.template}")
        files = generate_golden_for_template(args.template, output_dir)
        print(f"\n✅ Generated {len(files)} files")
    else:
        total = generate_all_golden_files(output_dir)
        print(f"\n✅ Generated {total} files total")


if __name__ == "__main__":
    main()
