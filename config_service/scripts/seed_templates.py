#!/usr/bin/env python3
"""
Seed the templates table with initial system templates.

Usage:
    python scripts/seed_templates.py
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path so `import src.*` works when running as a script.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import json
import uuid

from sqlalchemy.orm import Session
from src.db.models import Template
from src.db.session import get_session_maker

# Template metadata mapping
TEMPLATE_METADATA = {
    "01_slack_incident_triage.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/incident-triage.svg",
        "detailed_description": """# Slack Incident Triage

Fast root cause analysis optimized for production incidents triggered via Slack.

## What It Does
- Correlates logs, metrics, and events across Kubernetes and AWS
- Identifies deployment regressions and resource issues
- Provides actionable remediation steps
- Posts real-time updates to Slack with Block Kit UI

## Best For
- 24/7 on-call teams
- Kubernetes + AWS infrastructure
- High-velocity deployment environments

## Example Scenarios
- "Payment service pods are crash-looping"
- "API latency spiked 10x after latest deployment"
- "Database connections exhausted"
        """,
    },
    "02_git_ci_auto_fix.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/ci-autofix.svg",
        "detailed_description": """# Git CI Issue Triage & Auto-Fix

Analyzes GitHub Actions and CodePipeline failures and can automatically fix common issues.

## What It Does
- Downloads and parses workflow logs
- Identifies test failures, build errors, and lint issues
- Distinguishes real failures from flaky tests
- Auto-commits fixes for simple issues (formatting, imports, type errors)
- Posts analysis to PR as comment

## Best For
- Teams with high PR velocity
- JavaScript/TypeScript, Python projects
- GitHub Actions or AWS CodePipeline

## Example Scenarios
- "Jest tests failing on main branch"
- "ESLint errors blocking merge"
- "Docker build failing due to missing dependency"
        """,
    },
    "03_aws_cost_reduction.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/finops.svg",
        "detailed_description": """# AWS Cost Reduction

FinOps agent that finds cost savings opportunities across your AWS infrastructure.

## What It Does
- Identifies idle resources (EC2, RDS, EBS)
- Finds oversized instances
- Recommends Reserved Instances and Savings Plans
- Analyzes S3 storage class optimization
- Calculates $ impact for each recommendation

## Best For
- Teams looking to reduce AWS spend
- Organizations with 100+ AWS resources
- FinOps and infrastructure teams

## Example Scenarios
- "Find all idle EC2 instances"
- "Recommend Reserved Instances for our workload"
- "Analyze S3 storage costs and optimization opportunities"
        """,
    },
    "09_incident_postmortem.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/postmortem.svg",
        "detailed_description": """# Incident Postmortem Generator

Automatically creates blameless postmortem reports by analyzing incident data.

## What It Does
- Scrapes Slack war room conversations for timeline
- Correlates PagerDuty alerts, logs, and metrics
- Generates minute-by-minute timeline with evidence
- Identifies root cause and contributing factors
- Creates actionable follow-up items
- Posts as GitHub issue or Slack summary

## Best For
- Teams required to write postmortems
- Organizations with incident response processes
- Learning and continuous improvement focus

## Example Scenarios
- "Generate postmortem for yesterday's outage"
- "Create incident report for P0 incident INC-1234"
- "Write postmortem from Slack channel #incident-2024-01-10"
        """,
    },
    "10_universal_telemetry.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/telemetry.svg",
        "detailed_description": """# Universal Telemetry Agent

Works with ANY observability platform - auto-detects your telemetry stack.

## What It Does
- Auto-detects Coralogix, Grafana, Datadog, New Relic
- Uses unified 3-layer approach: Metrics → Logs → Traces
- Correlates findings across platforms
- Cross-validates data if multiple platforms configured
- Presents platform-agnostic analysis

## Best For
- Teams using multiple observability tools
- Organizations migrating between platforms
- Platform-agnostic incident response

## Example Scenarios
- Works the same regardless of your observability stack
- "Investigate high error rate" (uses whatever platform you have)
- "Compare metrics between Grafana and Datadog"
        """,
    },
    "04_coding_assistant.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/coding.svg",
        "detailed_description": """# Coding Assistant

AI senior software engineer for code reviews, refactoring, and test generation.

## What It Does
- Reviews code for bugs, security issues, and performance problems
- Suggests refactorings to improve code quality
- Generates unit tests with edge cases
- Creates documentation for complex logic
- Posts findings as PR comments

## Best For
- Teams with high PR velocity
- Code quality improvement initiatives
- Junior developers learning best practices

## Example Scenarios
- "Review this PR for security issues"
- "Refactor this function to be more readable"
- "Generate tests for the UserService class"
- "Add documentation to this complex algorithm"
        """,
    },
    "05_data_migration.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/data-migration.svg",
        "detailed_description": """# Data Migration Assistant

Plans and executes database migrations with validation and rollback procedures.

## What It Does
- Analyzes source and target schemas
- Generates migration scripts (export, transform, load)
- Creates validation queries to ensure data integrity
- Produces detailed migration plans with rollback steps
- Supports multiple databases (Postgres, Snowflake, Elasticsearch)

## Best For
- Database migrations between platforms
- Schema upgrades
- Data warehouse migrations
- ETL pipeline development

## Example Scenarios
- "Plan migration from Postgres to Snowflake"
- "Generate ETL scripts for user data"
- "Validate data integrity after migration"
- "Create rollback plan for failed migration"
        """,
    },
    "06_news_comedian.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/comedy.svg",
        "detailed_description": """# News Comedian (Demo)

Fun demo agent that turns tech news into witty jokes.

## What It Does
- Searches for latest tech news
- Writes clever jokes about each story
- Posts daily digest to Slack
- Uses tech terminology for humor
- Great for team morale and demos

## Best For
- Product demos and showcases
- Team building and morale
- Demonstrating platform capabilities
- Lightening the mood in engineering channels

## Example Scenarios
- "Generate today's tech news digest"
- "Find funny stories about the latest AI announcement"
- "Write jokes about yesterday's tech outages"
        """,
    },
    "07_alert_fatigue.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/alert-optimization.svg",
        "detailed_description": """# Alert Fatigue Reduction

Analyzes alerting patterns to reduce noise and improve signal.

## What It Does
- Identifies high-frequency low-value alerts
- Detects flapping and redundant alerts
- Recommends threshold tuning
- Calculates potential alert reduction (30-50%)
- Generates implementation plan with PRs

## Best For
- Teams drowning in alerts
- On-call fatigue reduction
- Alert optimization projects
- Platform teams managing monitoring

## Example Scenarios
- "Analyze our alerts for noise"
- "Which alerts should we delete or tune?"
- "Reduce alert volume by 40%"
- "Find redundant alerts that can be consolidated"
        """,
    },
    "08_dr_validator.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/dr-testing.svg",
        "detailed_description": """# Disaster Recovery Validator

Tests backup restorability and validates DR procedures.

## What It Does
- Actually tests that backups are restorable (not just exist!)
- Measures real RTO/RPO vs targets
- Validates multi-region failover
- Tests runbook accuracy
- Generates comprehensive DR report with PASS/FAIL

## Best For
- Quarterly DR compliance testing
- SOC2/ISO27001 audit preparation
- Infrastructure teams
- Ensuring DR readiness

## Example Scenarios
- "Test RDS backup restore to staging"
- "Validate multi-region failover works"
- "Measure actual RTO for all critical systems"
- "Check if our DR runbooks are up to date"
        """,
    },
}


def load_template_json(file_path: Path) -> dict:
    """Load and parse a template JSON file."""
    with open(file_path, "r") as f:
        return json.load(f)


def extract_metadata(template_json: dict) -> dict:
    """Extract metadata from template JSON."""
    return {
        "name": template_json.get("$template_name", ""),
        "slug": template_json.get("$template_slug", ""),
        "description": template_json.get("$description", ""),
        "category": template_json.get("$category", ""),
        "version": template_json.get("$version", "1.0.0"),
    }


def extract_requirements(template_json: dict) -> tuple:
    """Extract required MCPs and tools from template JSON."""
    mcps = template_json.get("mcps", {})
    required_mcps = [
        mcp_name
        for mcp_name, config in mcps.items()
        if config.get("required", False) or config.get("enabled", False)
    ]

    # Extract tools from all agents
    all_tools = set()
    agents = template_json.get("agents", {})
    for agent in agents.values():
        tools_config = agent.get("tools", {})
        enabled_tools = tools_config.get("enabled", [])
        all_tools.update(enabled_tools)

    return required_mcps, list(all_tools)


def extract_example_scenarios(template_json: dict, filename: str) -> list:
    """Extract example scenarios from template or metadata."""
    # Try to get from metadata first
    if filename in TEMPLATE_METADATA:
        metadata = TEMPLATE_METADATA[filename]
        detailed_desc = metadata.get("detailed_description", "")
        if "## Example Scenarios" in detailed_desc:
            # Parse scenarios from markdown
            scenarios_section = detailed_desc.split("## Example Scenarios")[1]
            scenarios_section = scenarios_section.split("##")[
                0
            ]  # Get until next section
            scenarios = [
                line.strip("- \"'")
                for line in scenarios_section.strip().split("\n")
                if line.strip().startswith("-")
            ]
            return scenarios

    # Fallback to generic scenarios based on category
    category = template_json.get("$category", "")
    if category == "incident-response":
        return [
            "Investigate production outage",
            "Analyze service degradation",
            "Debug deployment regression",
        ]
    elif category == "ci-cd":
        return [
            "Analyze test failures",
            "Fix build errors",
            "Debug flaky tests",
        ]
    elif category == "finops":
        return [
            "Find cost savings opportunities",
            "Identify idle resources",
            "Recommend Reserved Instances",
        ]
    elif category == "observability":
        return [
            "Investigate metrics anomaly",
            "Correlate logs and traces",
            "Debug performance issue",
        ]
    else:
        return [
            "Analyze system behavior",
            "Provide recommendations",
            "Generate report",
        ]


def seed_template(db: Session, file_path: Path, force_update: bool = False) -> None:
    """
    Seed a single template from JSON file.

    Supports upsert behavior:
    - If template doesn't exist: create it
    - If template exists with older version: update it
    - If template exists with same version: skip (unless force_update=True)
    """
    print(f"Loading template: {file_path.name}")

    # Load template JSON
    template_json = load_template_json(file_path)

    # Extract metadata
    metadata = extract_metadata(template_json)

    # Extract requirements
    required_mcps, required_tools = extract_requirements(template_json)

    # Get additional metadata
    file_metadata = TEMPLATE_METADATA.get(file_path.name, {})

    # Extract example scenarios
    example_scenarios = extract_example_scenarios(template_json, file_path.name)

    # Check if template already exists
    existing = db.query(Template).filter(Template.slug == metadata["slug"]).first()

    if existing:
        # Compare versions to decide if update is needed
        existing_version = existing.version or "0.0.0"
        new_version = metadata["version"]

        if not force_update and existing_version == new_version:
            print(
                f"  ⏭️  Template '{metadata['slug']}' v{existing_version} already up-to-date, skipping..."
            )
            return

        # Update existing template
        print(
            f"  🔄 Updating template '{metadata['slug']}' from v{existing_version} to v{new_version}..."
        )
        existing.name = metadata["name"]
        existing.description = metadata["description"]
        existing.detailed_description = file_metadata.get("detailed_description")
        existing.use_case_category = metadata["category"]
        existing.template_json = template_json
        existing.icon_url = file_metadata.get("icon_url")
        existing.example_scenarios = example_scenarios
        existing.demo_video_url = file_metadata.get("demo_video_url")
        existing.version = new_version
        existing.required_mcps = required_mcps
        existing.required_tools = required_tools[:50]
        print(f"  ✅ Updated template '{metadata['name']}' to v{new_version}")
        return

    # Create new template record
    template = Template(
        id=f"tmpl_{uuid.uuid4().hex[:12]}",
        name=metadata["name"],
        slug=metadata["slug"],
        description=metadata["description"],
        detailed_description=file_metadata.get("detailed_description"),
        use_case_category=metadata["category"],
        template_json=template_json,
        icon_url=file_metadata.get("icon_url"),
        example_scenarios=example_scenarios,
        demo_video_url=file_metadata.get("demo_video_url"),
        is_system_template=True,
        is_published=True,  # Publish by default
        version=metadata["version"],
        required_mcps=required_mcps,
        required_tools=required_tools[:50],  # Limit to first 50 tools
        created_by="system",
        usage_count=0,
    )

    db.add(template)
    print(f"  ✅ Created template '{metadata['name']}' v{metadata['version']}")


def seed_all_templates(force_update: bool = False):
    """
    Seed all templates from the templates directory.

    Args:
        force_update: If True, update all templates regardless of version.
                      If False (default), only update if version changed.
    """
    print("=" * 60)
    print("Seeding Templates")
    if force_update:
        print("Mode: FORCE UPDATE (will update all templates)")
    else:
        print("Mode: Version-based (will skip unchanged templates)")
    print("=" * 60)

    # Find templates directory
    templates_dir = Path(__file__).parent.parent / "templates"

    if not templates_dir.exists():
        print(f"❌ Templates directory not found: {templates_dir}")
        return

    # Get all template JSON files
    template_files = sorted(templates_dir.glob("*.json"))

    if not template_files:
        print(f"❌ No template files found in {templates_dir}")
        return

    print(f"Found {len(template_files)} template files\n")

    # Create database session
    SessionLocal = get_session_maker()
    db = SessionLocal()

    # Statistics tracking
    stats = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}

    try:
        for file_path in template_files:
            try:
                seed_template(db, file_path, force_update=force_update)
            except Exception as e:
                print(f"  ❌ Error loading {file_path.name}: {e}")
                import traceback

                traceback.print_exc()
                stats["errors"] += 1

        # Commit all changes
        db.commit()
        print("\n" + "=" * 60)
        print("✅ Template seeding completed successfully!")
        print("=" * 60)

        # Print summary
        total_templates = db.query(Template).count()
        print(f"\nTotal templates in database: {total_templates}")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Error during seeding: {e}")
        import traceback

        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed templates into the database")
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force update all templates regardless of version",
    )
    args = parser.parse_args()

    seed_all_templates(force_update=args.force)
