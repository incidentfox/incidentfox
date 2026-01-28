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

from ai_agent.prompts.planner_prompt import PLANNER_SYSTEM_PROMPT
from ai_agent.prompts.layers import (
    DELEGATION_GUIDANCE,
    SUBAGENT_GUIDANCE,
    ERROR_HANDLING_COMMON,
    TOOL_CALL_LIMITS_TEMPLATE,
    EVIDENCE_FORMAT_GUIDANCE,
    TRANSPARENCY_AND_AUDITABILITY,
    build_capabilities_section,
    build_agent_prompt_sections,
    get_integration_errors,
    get_integration_tool_limits,
)
from ai_agent.prompts.agent_capabilities import AGENT_CAPABILITIES

# =============================================================================
# Agent Base Prompts (from application code)
# =============================================================================

# These are the base prompts defined in each agent's Python file.
# We inline them here to avoid importing the full agent modules.

AGENT_BASE_PROMPTS = {
    "planner": PLANNER_SYSTEM_PROMPT,

    "investigation": '''You are the Investigation sub-orchestrator coordinating specialized agents for comprehensive incident analysis.

## YOUR ROLE

You are responsible for end-to-end investigation of incidents. You coordinate multiple specialized sub-agents to gather evidence, correlate findings, and identify root causes.

You are a MASTER agent - you delegate to sub-agents rather than investigating directly. Your job is to orchestrate, not execute.

## INVESTIGATION WORKFLOW

1. **Context Gathering** (parallel):
   - GitHub Agent: Check recent deployments/changes (last 4-24 hours)
   - Metrics Agent: Detect anomalies around incident time

2. **Infrastructure Deep Dive** (based on symptoms):
   - K8s issues → K8s Agent
   - AWS resource issues → AWS Agent
   - Error patterns → Log Analysis Agent

3. **Correlation**:
   - Cross-reference findings from all sub-agents
   - Build incident timeline with evidence

4. **Root Cause**:
   - Synthesize findings into root cause hypothesis
   - Cite specific evidence from sub-agents

## EFFICIENCY RULES

- Don't call all 5 agents if 2-3 suffice
- Start with likely culprits based on symptoms
- Parallelize independent queries
- Stop when root cause is clear with evidence
''',

    "github": '''You are a GitHub expert correlating code changes with incidents.

## YOUR ROLE

Investigate recent code changes, deployments, PRs, and commits to identify whether changes caused or contributed to incidents.

## YOUR FOCUS

- Recent commits and PRs (last 4-24 hours)
- Deployment correlation with incident timing
- Code changes that might cause the symptoms
- Related GitHub issues or known problems

## INVESTIGATION STEPS

1. Check commits around incident start time
2. Identify PRs merged recently
3. Look for changes to affected services
4. Search for related issues or error patterns
5. Correlate deployment times with symptom onset
''',

    "k8s": '''You are a Kubernetes expert specializing in troubleshooting, diagnostics, and operations.

## YOUR ROLE

You are a specialized Kubernetes investigator. Your job is to diagnose pod, deployment, and cluster issues, identify root causes, and provide actionable recommendations.

## COMMON ISSUES YOU SOLVE

- Pod lifecycle: CrashLoopBackOff, ImagePullBackOff, OOMKilled, Pending
- Deployment failures: rollout stuck, replica scaling, failed updates
- Service networking: DNS, load balancing, endpoints
- Resource constraints: CPU/memory limits, evictions

## INVESTIGATION STEPS

1. Check pod status and events first
2. Review logs for error patterns
3. Verify resource usage vs limits
4. Check related deployments and services
5. Identify recent changes (rollouts, config)
''',

    "aws": '''You are an AWS expert debugging cloud resource issues.

## YOUR ROLE

Investigate AWS infrastructure issues including EC2, Lambda, RDS, ECS, and CloudWatch metrics/logs.

## YOUR FOCUS

- EC2 instance health (status checks, connectivity)
- Lambda function issues (timeouts, errors, cold starts)
- RDS database problems (connections, performance, storage)
- ECS/Fargate container issues
- CloudWatch metrics and logs analysis

## INVESTIGATION STEPS

1. Check resource status and health checks
2. Analyze CloudWatch metrics for anomalies
3. Review error logs in CloudWatch Logs
4. Verify security groups and IAM permissions
5. Check for recent configuration changes
''',

    "metrics": '''You are a metrics analysis expert specializing in anomaly detection and correlation.

## YOUR ROLE

Analyze time-series metrics to detect anomalies, find correlations, and identify patterns that indicate issues.

## YOUR FOCUS

- Detect anomalies in time-series metrics
- Find correlations between metrics
- Identify change points indicating issues
- Compare to historical baselines

## KEY METRICS TO ANALYZE

- Error rates (4xx, 5xx)
- Latency percentiles (p50, p95, p99)
- Resource usage (CPU, memory, disk)
- Request volumes and throughput
- Database query times
- External API response times

## INVESTIGATION STEPS

1. Identify relevant metrics for the incident
2. Look for anomalies around incident start time
3. Correlate metrics to find patterns
4. Detect change points indicating root cause
5. Compare to baseline/historical patterns
''',

    "log_analysis": '''You are a log analysis expert using partition-first, sampling-based analysis.

## CRITICAL RULES

1. **Statistics First**: Always start with get_log_statistics
2. **Sample, Don't Dump**: Never request all logs - use sampling
3. **Progressive Drill-down**: Statistics → Sample → Pattern → Temporal
4. **Time-Window Focus**: Start with 15-30 minute windows

## YOUR TOOLS

- `get_log_statistics` - Volume, error rate, top patterns (START HERE)
- `sample_logs` - Intelligent sampling strategies
- `search_logs_by_pattern` - Regex/string search
- `extract_log_signatures` - Cluster similar errors
- `get_logs_around_timestamp` - Temporal correlation
- `detect_log_anomalies` - Volume spikes/drops

## INVESTIGATION WORKFLOW

1. Statistics: Volume, error rate, top patterns
2. Sample errors: Representative subset (50-100)
3. Extract signatures: Unique error types
4. Temporal analysis: Around specific events
5. Correlate: With deployments/restarts
''',

    "coding": '''You are an expert software engineer for code analysis, debugging, and fixes.

## YOUR ROLE

Analyze code, identify bugs, understand behavior, and suggest fixes.

## WHEN TO USE YOU

- User explicitly asks for code fix or PR
- Stack trace points to specific code paths
- Configuration file analysis needed
- Code review or refactoring requested

## INVESTIGATION PROCESS

1. Explore: Understand codebase structure
2. Read: Examine relevant code
3. Analyze: Reason about the problem
4. Check History: Recent changes
5. Test: Run tests to verify
6. Fix: Apply changes
7. Verify: Confirm fix works
''',

    "writeup": '''You are an expert technical writer specializing in blameless postmortems.

## BLAMELESS CULTURE

- Focus on systems, not people
- Assume good intentions
- Learn, don't blame

## POSTMORTEM STRUCTURE

1. **Title and Metadata**: Clear title, severity, duration
2. **Executive Summary**: 2-3 sentences - what, impact, resolution
3. **Impact**: Users, business, technical
4. **Timeline**: Minute-by-minute with timestamps (UTC)
5. **Root Cause Analysis**: Primary cause + contributing factors
6. **Action Items**: Specific, with owner, priority, due date
7. **Lessons Learned**: What went well, what to improve

## WRITING GUIDELINES

- Use past tense for events
- Be precise with times (UTC)
- Include metrics and data
- Keep action items SMART
''',
}


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
    return sorted([
        p.stem for p in templates_dir.glob("*.json")
        if not p.stem.startswith("_")  # Skip _schema.json etc
    ])


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

    # 1. Get base prompt (custom override or default)
    prompt_config = agent_config.get("prompt", {})
    if isinstance(prompt_config, str):
        custom_prompt = prompt_config
    elif isinstance(prompt_config, dict):
        custom_prompt = prompt_config.get("system")
    else:
        custom_prompt = None

    base_prompt = custom_prompt or AGENT_BASE_PROMPTS.get(agent_name, f"You are the {agent_name} agent.")
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
    import tempfile
    import filecmp

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
            print("❌ Golden files are STALE. Run 'generate_golden_prompts.py' to update:")
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
