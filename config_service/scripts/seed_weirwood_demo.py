#!/usr/bin/env python3
"""
Seed the weirwood-demo team for feature request triage demo.

This creates:
1. 'weirwood-demo' team node under 'incidentfox-demo' org
2. Team configuration with:
   - Routing to the weirwood-demo Slack channel
   - Custom planner prompt for feature request triage
   - Customer tier database (enterprise/standard/free)
   - Feature owner mappings
   - Codebase context for complexity estimation
3. Output configuration pointing to the Slack channel

Usage:
    cd config_service
    poetry run python scripts/seed_weirwood_demo.py

Environment variables:
    WEIRWOOD_SLACK_CHANNEL_ID: Slack channel ID (default: C0ADSDTFF41)
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path so `import src.*` works when running as a script.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import os
import uuid

from sqlalchemy import select
from src.core.dotenv import load_dotenv
from src.db.config_models import NodeConfiguration
from src.db.models import (
    NodeType,
    OrgNode,
    TeamOutputConfig,
)
from src.db.session import db_session

# Weirwood demo configuration
ORG_ID = "incidentfox-demo"
TEAM_NODE_ID = "weirwood-demo"
TEAM_NAME = "Weirwood Demo"

# Feature request triage planner prompt
# NOTE: business_context (customer/owner/codebase data) is built dynamically
# and appended to this prompt in _build_prompt().
FEATURE_TRIAGE_PROMPT_HEADER = """You are a Feature Request Triage Agent for a fast-moving startup. Your job is to quickly assess incoming customer feature requests and route them to the right team member.

## QUICK REFERENCE

**Your Role:** Triage customer feature requests - assess priority, estimate complexity, find owner, and page them
**Core Principle:** Speed matters. Enterprise customers have 1-hour SLAs. Get the right person on it FAST.

## TRIAGE WORKFLOW

For every feature request:

1. **Identify the customer** from the message (name, email domain, context clues)
2. **Look up their tier** from the Customer Database below to determine SLA and priority
3. **Understand the request** - what feature/change, which system area
4. **Check codebase context** from the Codebase Reference below for complexity estimation
5. **Estimate complexity** using the scale below
6. **Find the owner** from the Owner Mappings below
7. **Post triage summary** and @mention the owner

## COMPLEXITY SCALE

| Complexity | Time Estimate | Examples |
|------------|---------------|----------|
| **Trivial** | Minutes | Config change, feature flag toggle, copy update |
| **Low** | Hours (1-4h) | Small UI tweak, simple bug fix, add validation |
| **Medium** | Hours to 1 day | New API endpoint, moderate frontend work, integration |
| **High** | Days (2-5d) | New feature, architecture change, complex integration |
| **Very High** | Week+ | Major feature, redesign, multi-system changes |

## RESPONSE FORMAT

Always respond with this structure:

[PRIORITY EMOJI] **[PRIORITY LEVEL] - [Customer Tier] Customer**

**Customer:** [Name]
**SLA:** [X hours]

**Feature Request:** [Brief description]

**Triage Assessment:**
- **Area:** [System area]
- **Owner:** [Name] (<@SLACK_ID>)
- **Complexity:** [Level] ([Time estimate])
- **Reasoning:** [Why this complexity level]

**Codebase Context:**
- Key paths: [file paths]
- Notes: [relevant context]

<@SLACK_ID> - [Urgency message based on priority]

## PRIORITY EMOJIS

- 🚨 URGENT (Enterprise customer)
- ⚡ HIGH (Standard customer, complex request)
- 📋 NORMAL (Standard customer, simple request)
- 📝 LOW (Free tier)

## BEHAVIORAL PRINCIPLES

**Speed Over Perfection:** A good triage now is better than a perfect triage later. Enterprise customers have 1-hour SLAs.

**Err on the Side of Urgency:** If uncertain about priority, round UP. Better to over-communicate than miss an SLA.

**Be Specific:** "Medium complexity" is useless. Say "Medium (1-2 days) - needs new DB table and API endpoint."

**Always Page Someone:** Every request needs an owner. If you can't find one, escalate to the team.
"""

# Demo customer data
CUSTOMERS = {
    "acme-corp": {
        "tier": "enterprise",
        "sla_hours": 1,
        "contact": "john@acme-corp.com",
    },
    "acme": {
        "tier": "enterprise",
        "sla_hours": 1,
        "contact": "john@acme-corp.com",
    },
    "bigco": {
        "tier": "enterprise",
        "sla_hours": 1,
        "contact": "enterprise@bigco.io",
    },
    "startup-xyz": {
        "tier": "standard",
        "sla_hours": 24,
        "contact": "founder@startup-xyz.com",
    },
    "smallbiz": {
        "tier": "standard",
        "sla_hours": 24,
        "contact": "owner@smallbiz.com",
    },
    "free-user": {
        "tier": "free",
        "sla_hours": 72,
        "contact": None,
    },
    "trial-company": {
        "tier": "free",
        "sla_hours": 72,
        "contact": "trial@example.com",
    },
}

# Demo owner mappings
OWNERS = {
    "payments": {
        "name": "Alice",
        "slack_id": "U09V0JHFQ5P",
        "github": "alice",
        "backup": "Bob",
    },
    "billing": {
        "name": "Alice",
        "slack_id": "U09V0JHFQ5P",
        "github": "alice",
    },
    "auth": {
        "name": "Bob",
        "slack_id": "U0A02101LU8",
        "github": "bob",
        "backup": "Alice",
    },
    "authentication": {
        "name": "Bob",
        "slack_id": "U0A02101LU8",
        "github": "bob",
    },
    "frontend": {
        "name": "Alice",
        "slack_id": "U09V0JHFQ5P",
        "github": "alice",
    },
    "ui": {
        "name": "Alice",
        "slack_id": "U09V0JHFQ5P",
        "github": "alice",
    },
    "api": {
        "name": "Bob",
        "slack_id": "U0A02101LU8",
        "github": "bob",
    },
    "backend": {
        "name": "Bob",
        "slack_id": "U0A02101LU8",
        "github": "bob",
    },
    "database": {
        "name": "Bob",
        "slack_id": "U0A02101LU8",
        "github": "bob",
    },
    "infrastructure": {
        "name": "Bob",
        "slack_id": "U0A02101LU8",
        "github": "bob",
    },
}

# Demo codebase context
CODEBASE = {
    "repo": "weirwood/main-app",
    "areas": {
        "payments": {
            "paths": ["src/payments/", "src/billing/", "src/webhooks/stripe/"],
            "complexity": "high",
            "notes": "Stripe integration, webhook handlers, PCI compliance considerations",
            "dependencies": ["Stripe API", "PostgreSQL", "Redis for job queues"],
        },
        "auth": {
            "paths": ["src/auth/", "src/middleware/auth.py", "src/oauth/"],
            "complexity": "medium",
            "notes": "JWT-based auth, OAuth integrations (Google, GitHub), session management",
            "dependencies": ["PostgreSQL", "Redis for sessions"],
        },
        "frontend": {
            "paths": ["web/src/", "web/src/components/", "web/src/pages/"],
            "complexity": "medium",
            "notes": "React + TypeScript, TailwindCSS, component library",
            "dependencies": ["React", "Next.js", "TailwindCSS"],
        },
        "api": {
            "paths": ["src/api/", "src/routes/", "src/handlers/"],
            "complexity": "medium",
            "notes": "FastAPI-based REST API, OpenAPI spec",
            "dependencies": ["FastAPI", "PostgreSQL", "Redis"],
        },
        "database": {
            "paths": ["src/db/", "migrations/", "src/models/"],
            "complexity": "high",
            "notes": "PostgreSQL with SQLAlchemy ORM, Alembic migrations",
            "dependencies": ["PostgreSQL", "SQLAlchemy", "Alembic"],
        },
        "infrastructure": {
            "paths": ["terraform/", "k8s/", "docker/"],
            "complexity": "high",
            "notes": "AWS EKS, Terraform IaC, Kubernetes manifests",
            "dependencies": ["AWS", "Kubernetes", "Terraform"],
        },
    },
}


def _build_business_context() -> str:
    """Build business_context string from customer, owner, and codebase data."""
    lines = []

    lines.append("## Customer Database\n")
    lines.append("| Customer | Tier | SLA | Priority | Contact |")
    lines.append("|----------|------|-----|----------|---------|")
    priority_map = {"enterprise": "URGENT", "standard": "normal", "free": "low"}
    seen = set()
    for name, info in CUSTOMERS.items():
        # Dedupe aliases (acme / acme-corp)
        key = (info["tier"], info.get("contact"))
        if key in seen and info["tier"] == "enterprise":
            continue
        seen.add(key)
        tier = info["tier"]
        sla = f'{info["sla_hours"]}h'
        priority = priority_map.get(tier, "normal")
        contact = info.get("contact") or "—"
        lines.append(f"| {name} | {tier} | {sla} | {priority} | {contact} |")

    lines.append("\n## Owner Mappings\n")
    lines.append("| Area | Owner | Slack ID | GitHub | Backup |")
    lines.append("|------|-------|----------|--------|--------|")
    seen_areas = set()
    for area, info in OWNERS.items():
        if area in seen_areas:
            continue
        seen_areas.add(area)
        backup = info.get("backup", "—")
        github = info.get("github", "—")
        lines.append(
            f'| {area} | {info["name"]} | <@{info["slack_id"]}> | {github} | {backup} |'
        )

    lines.append(f"\n## Codebase Reference\n")
    lines.append(f"**Repo:** {CODEBASE['repo']}\n")
    lines.append("| Area | Paths | Complexity | Notes | Dependencies |")
    lines.append("|------|-------|------------|-------|--------------|")
    for area, info in CODEBASE["areas"].items():
        paths = ", ".join(info["paths"])
        deps = ", ".join(info.get("dependencies", []))
        lines.append(
            f'| {area} | {paths} | {info["complexity"]} | {info.get("notes", "")} | {deps} |'
        )

    return "\n".join(lines)


def main() -> None:
    load_dotenv()

    # Allow overriding Slack config via environment
    slack_channel_id = os.getenv("WEIRWOOD_SLACK_CHANNEL_ID", "C0ADSDTFF41")
    slack_channel_name = os.getenv("WEIRWOOD_SLACK_CHANNEL_NAME", "#weirwood-demo")

    print("Seeding weirwood-demo team...")
    print(f"  Organization: {ORG_ID}")
    print(f"  Team: {TEAM_NODE_ID}")
    print(f"  Slack channel: {slack_channel_id} ({slack_channel_name})")

    with db_session() as s:
        # 1. Check that incidentfox-demo org exists
        org = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == ORG_ID,
                OrgNode.node_id == ORG_ID,
            )
        ).scalar_one_or_none()

        if org is None:
            print(f"  ERROR: Organization '{ORG_ID}' not found!")
            print("  Please create the organization first or use a different org_id.")
            sys.exit(1)
        else:
            print(f"  Found organization: {org.name}")

        # 2. Create weirwood-demo team node
        team = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == ORG_ID,
                OrgNode.node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if team is None:
            print("  Creating weirwood-demo team...")
            s.add(
                OrgNode(
                    org_id=ORG_ID,
                    node_id=TEAM_NODE_ID,
                    parent_id=ORG_ID,
                    node_type=NodeType.team,
                    name=TEAM_NAME,
                )
            )
        else:
            print("  Weirwood-demo team already exists, skipping creation...")

        # Flush to satisfy FK constraints
        s.flush()

        # 3. Create/update team configuration
        team_cfg = s.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == ORG_ID,
                NodeConfiguration.node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        business_context = _build_business_context()
        # Build the full system prompt: workflow instructions + inline data
        full_prompt = FEATURE_TRIAGE_PROMPT_HEADER + "\n" + business_context

        config_json = {
            "team_name": TEAM_NAME,
            "description": "Feature request triage demo for startup support",
            # Routing - this Slack channel routes to this team
            "routing": {
                "slack_channel_ids": [slack_channel_id],
                "github_repos": [],
                "pagerduty_service_ids": [],
                "services": ["weirwood-demo"],
            },
            # Business context stored for reference
            "business_context": business_context,
            # Agent configuration
            "agents": {
                "planner": {
                    "enabled": True,
                    "model": {"name": "gpt-4o", "temperature": 0.3},
                    "prompt": {
                        "system": full_prompt,
                        "prefix": "",
                        "suffix": "",
                    },
                },
                # Disable sub-agents not needed for feature triage
                "investigation": {"enabled": False},
                "coding": {"enabled": False},
                "writeup": {"enabled": False},
            },
        }

        if team_cfg is None:
            print("  Creating team configuration...")
            s.add(
                NodeConfiguration(
                    id=f"cfg-{uuid.uuid4().hex[:12]}",
                    org_id=ORG_ID,
                    node_id=TEAM_NODE_ID,
                    node_type="team",
                    config_json=config_json,
                    updated_by="seed_weirwood_demo",
                )
            )
        else:
            print("  Updating existing team configuration...")
            team_cfg.config_json = config_json
            team_cfg.updated_by = "seed_weirwood_demo"

        # 4. Create/update output configuration
        output_cfg = s.execute(
            select(TeamOutputConfig).where(
                TeamOutputConfig.org_id == ORG_ID,
                TeamOutputConfig.team_node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if output_cfg is None:
            print("  Creating output configuration...")
            s.add(
                TeamOutputConfig(
                    org_id=ORG_ID,
                    team_node_id=TEAM_NODE_ID,
                    default_destinations=[
                        {
                            "type": "slack",
                            "channel_id": slack_channel_id,
                            "channel_name": slack_channel_name,
                        }
                    ],
                    trigger_overrides={
                        "slack": "reply_in_thread",
                        "api": "use_default",
                    },
                )
            )
        else:
            print("  Updating existing output configuration...")
            output_cfg.default_destinations = [
                {
                    "type": "slack",
                    "channel_id": slack_channel_id,
                    "channel_name": slack_channel_name,
                }
            ]

        s.commit()

    print("\nWeirwood demo seeding complete!")
    print("\n" + "=" * 60)
    print("DEMO SETUP SUMMARY")
    print("=" * 60)
    print(f"\nSlack Channel: {slack_channel_id} ({slack_channel_name})")
    print("\nCustomers configured:")
    for name, info in CUSTOMERS.items():
        print(f"  - {name}: {info['tier']} ({info['sla_hours']}h SLA)")
    print("\nOwners configured:")
    for area, info in OWNERS.items():
        print(f"  - {area}: {info['name']} (<@{info['slack_id']}>)")
    print("\nCodebase areas:")
    for area, info in CODEBASE["areas"].items():
        print(f"  - {area}: {info['complexity']} complexity")
    print("\n" + "=" * 60)
    print("\nNext steps:")
    print("  1. Deploy the updated agent with feature_triage_tools")
    print("  2. Invite the bot to the #weirwood-demo channel")
    print("  3. Test with: '@bot Acme Corp wants dark mode in the frontend'")
    print("  4. Update OWNERS slack_ids with real user IDs from your workspace")


if __name__ == "__main__":
    main()
