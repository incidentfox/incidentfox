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
from src.core.tools_catalog import BUILT_IN_TOOLS_METADATA
from src.db.models import Template
from src.db.session import get_session_maker

# Template metadata mapping (icons and detailed descriptions)
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
        "detailed_description": """# Cloud Cost Optimization

FinOps agent that finds cost savings opportunities across your cloud infrastructure.

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
- Supports multiple databases (Postgres, MySQL, Snowflake)

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
        "detailed_description": """# News Comedian (Non Production, Demo Only)

Fun demo agent that turns tech news into witty jokes.

## What It Does
- Searches for latest tech news using web search
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
        "detailed_description": """# Alert Fatigue Analyzer

Data-driven alert optimization using multi-source analysis (PagerDuty, Prometheus, Datadog, Opsgenie).

## What It Does
- Analyzes historical alert data across multiple platforms
- Identifies high-frequency low-value alerts
- Detects flapping, redundant, and stale alerts
- Calculates statistical baselines and recommends threshold tuning
- Generates prioritized remediation plan with estimated noise reduction

## Best For
- Teams drowning in alerts
- On-call fatigue reduction
- Alert optimization projects
- Platform teams managing monitoring

## Example Scenarios
- "Analyze our alerts for the last 30 days"
- "Which alerts should we delete or tune?"
- "Reduce alert volume by 40%"
- "Find redundant alerts that can be consolidated"
        """,
    },
    "10_observability_advisor.json": {
        "icon_url": "https://cdn.incidentfox.ai/icons/observability.svg",
        "detailed_description": """# Observability Advisor

Enterprise-grade observability setup and optimization using SRE best practices.

## What It Does
- Analyzes historical metrics to compute statistical baselines
- Generates data-driven alert thresholds (not arbitrary numbers)
- Uses RED/USE/Golden Signals methodology
- Outputs Prometheus, Datadog, or CloudWatch configurations
- Creates proposal documents for review

## Best For
- Teams building observability from scratch
- Organizations with noisy or insensitive alerts
- SRE teams implementing data-driven alerting
- Platform teams managing monitoring

## Example Scenarios
- "Set up alerting for our checkout service"
- "Optimize our current alert thresholds based on actual data"
- "Generate Prometheus alerting rules for the API gateway"
- "Create an observability proposal for the new microservice"
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
    # Extract tools from all agents
    # Tools are defined as {"tool_name": true/false} in agent config
    all_tools = set()
    agents = template_json.get("agents", {})
    for agent in agents.values():
        tools_config = agent.get("tools", {})
        # Tools are defined as dict with tool_name: true/false
        if isinstance(tools_config, dict):
            enabled_tools = [
                tool_name
                for tool_name, enabled in tools_config.items()
                if enabled is True
            ]
            all_tools.update(enabled_tools)

    # Derive required MCPs/integrations from tool names
    # Map tool prefixes to integration names
    required_mcps = derive_integrations_from_tools(all_tools)

    return required_mcps, list(all_tools)


def derive_integrations_from_tools(tools: set) -> list:
    """
    Derive required integrations from tool names using the tools catalog.

    Uses the authoritative BUILT_IN_TOOLS_METADATA to look up each tool's
    required_integrations, then maps integration IDs to display names.
    """
    # Build lookup dict from tools catalog: tool_id -> required_integrations
    tool_to_integrations = {
        tool["id"]: tool.get("required_integrations", [])
        for tool in BUILT_IN_TOOLS_METADATA
    }

    # Map integration IDs to human-readable display names
    integration_display_names = {
        "kubernetes": "Kubernetes",
        "aws": "AWS",
        "github": "GitHub",
        "gitlab": "GitLab",
        "slack": "Slack",
        "pagerduty": "PagerDuty",
        "opsgenie": "Opsgenie",
        "incidentio": "Incident.io",
        "datadog": "Datadog",
        "prometheus": "Prometheus",
        "grafana": "Grafana",
        "newrelic": "New Relic",
        "sentry": "Sentry",
        "splunk": "Splunk",
        "elasticsearch": "Elasticsearch",
        "coralogix": "Coralogix",
        "snowflake": "Snowflake",
        "bigquery": "BigQuery",
        "postgresql": "PostgreSQL",
        "mysql": "MySQL",
        "kafka": "Kafka",
        "schema_registry": "Schema Registry",
        "kafka_connect": "Kafka Connect",
        "confluence": "Confluence",
        "jira": "Jira",
        "linear": "Linear",
        "notion": "Notion",
        "google_docs": "Google Docs",
        "msteams": "Microsoft Teams",
        "gcp": "GCP",
        "sourcegraph": "Sourcegraph",
    }

    # Collect all integration IDs from the tools
    integration_ids = set()
    for tool in tools:
        if tool in tool_to_integrations:
            integration_ids.update(tool_to_integrations[tool])

    # Convert to display names
    integrations = set()
    for integration_id in integration_ids:
        display_name = integration_display_names.get(
            integration_id, integration_id.title()
        )
        integrations.add(display_name)

    # Sort for consistent display order (most relevant first)
    priority_order = [
        "Slack",
        "GitHub",
        "Kubernetes",
        "AWS",
        "Datadog",
        "Prometheus",
        "PagerDuty",
        "Grafana",
    ]
    sorted_integrations = []
    for integration in priority_order:
        if integration in integrations:
            sorted_integrations.append(integration)
            integrations.remove(integration)
    # Add remaining integrations alphabetically
    sorted_integrations.extend(sorted(integrations))

    return sorted_integrations


def count_agents(template_json: dict) -> int:
    """Count enabled agents in a template."""
    agents = template_json.get("agents", {})
    return sum(1 for agent in agents.values() if agent.get("enabled", True))


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

    # Create new template record (usage_count defaults to 0)
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
    )

    db.add(template)
    agent_count = count_agents(template_json)
    tool_count = len(required_tools)
    print(
        f"  ✅ Created template '{metadata['name']}' v{metadata['version']} "
        f"({agent_count} agents, {tool_count} tools)"
    )


def cleanup_deleted_templates(db: Session, valid_slugs: set) -> int:
    """
    Remove templates from database that no longer exist in the filesystem.

    Args:
        db: Database session
        valid_slugs: Set of slugs that exist in the templates directory

    Returns:
        Number of templates deleted
    """
    # Find templates in DB that don't have corresponding files
    all_templates = db.query(Template).filter(Template.is_system_template == True).all()
    deleted_count = 0

    for template in all_templates:
        if template.slug not in valid_slugs:
            print(f"  🗑️  Removing deleted template: {template.name} ({template.slug})")
            db.delete(template)
            deleted_count += 1

    return deleted_count


def seed_all_templates(force_update: bool = False, cleanup: bool = True):
    """
    Seed all templates from the templates directory.

    Args:
        force_update: If True, update all templates regardless of version.
                      If False (default), only update if version changed.
        cleanup: If True (default), remove templates from DB that don't exist in filesystem.
    """
    print("=" * 60)
    print("Seeding Templates")
    if force_update:
        print("Mode: FORCE UPDATE (will update all templates)")
    else:
        print("Mode: Version-based (will skip unchanged templates)")
    if cleanup:
        print("Cleanup: ENABLED (will remove deleted templates from DB)")
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
    stats = {"created": 0, "updated": 0, "skipped": 0, "errors": 0, "deleted": 0}

    try:
        # Collect valid slugs from filesystem
        valid_slugs = set()
        for file_path in template_files:
            try:
                template_json = load_template_json(file_path)
                slug = template_json.get("$template_slug", "")
                if slug:
                    valid_slugs.add(slug)
            except Exception:
                pass

        # Cleanup deleted templates first
        if cleanup:
            print("Cleaning up deleted templates...")
            stats["deleted"] = cleanup_deleted_templates(db, valid_slugs)
            if stats["deleted"] > 0:
                print(f"  Removed {stats['deleted']} template(s)\n")
            else:
                print("  No templates to remove\n")

        # Seed templates
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
        if stats["deleted"] > 0:
            print(f"Templates removed: {stats['deleted']}")

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
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Don't remove templates that no longer exist in filesystem",
    )
    args = parser.parse_args()

    seed_all_templates(force_update=args.force, cleanup=not args.no_cleanup)
