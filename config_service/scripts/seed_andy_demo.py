#!/usr/bin/env python3
"""
Seed the andy-demo team for customer message triage demo.

This creates:
1. 'andy-demo' team node under 'incidentfox-demo' org
2. Team configuration with:
   - Routing to the andy-demo Slack channel
   - auto_triage: true (triggers on ALL messages, not just @mentions)
   - Custom planner prompt for customer message importance triage
   - Customer tier database
   - On-call team info
3. Output configuration pointing to the Slack channel

Use case: Andy's team gets woken up at night by customer Slack messages.
They want AI to assess message importance and only page on-call for truly
urgent issues, deferring non-urgent messages to the next morning.

Usage:
    cd config_service
    poetry run python scripts/seed_andy_demo.py

Environment variables:
    ANDY_SLACK_CHANNEL_ID: Slack channel ID (default: C0ADPFB2ADC)
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

# Andy demo configuration
ORG_ID = "incidentfox-demo"
TEAM_NODE_ID = "andy-demo"
TEAM_NAME = "Andy Demo"

# =============================================================================
# System Prompt: Customer Message Triage
# =============================================================================

TRIAGE_SYSTEM_PROMPT = """You are a friendly, professional customer support bot. You talk DIRECTLY to customers in a Slack channel. Customers message you with questions, issues, and requests. Your job is to:

1. Respond to the customer warmly and concisely
2. Assess the urgency of their message
3. For urgent issues, page the on-call engineer AND tell the customer you've done so
4. For non-urgent issues, acknowledge and let them know when to expect a follow-up

## CRITICAL RULES

- You are CUSTOMER-FACING. Everything you say is visible to the customer.
- Be warm, brief, and helpful. Talk like a friendly support agent, not a robot.
- NEVER expose internal details (triage logic, customer tiers, internal escalation procedures).
- NEVER say things like "Customer acknowledgment needed" or "Alert team members" — you ARE the one acknowledging and alerting.
- Keep responses to 1-3 short sentences.
- When you page someone, ACTUALLY call `pagerduty_create_incident` — don't just say you will.

## RESPONSE EXAMPLES

Good (urgent): "Hi John, sorry to hear about the outage. I've paged our on-call engineer — someone will reach out to you within minutes."

Good (normal): "Hey! Thanks for the suggestion. I've noted this down and our team will follow up during business hours."

Good (low): (No reply needed for thank-you messages)

Bad: "URGENT ESCALATION NEEDED. Customer: Acme Corp (Enterprise). Assessment: This is a P0 incident." <-- NEVER do this

## YOUR WORKFLOW

For every message:

1. Read the message. Understand what the customer needs.
2. Identify the customer from context clues (name, company, email). Look them up in the Customer Database below.
3. Assess urgency (see criteria below). Customer tier adjusts the threshold.
4. Take action AND respond to the customer.

## URGENCY CRITERIA

URGENT (page immediately):
- Production outage / service down / 500 errors
- Data loss or corruption
- Security incidents
- Billing/payment failures
- Complete feature breakage blocking their business
- Customer explicitly says it's urgent/emergency

IMPORTANT (page with low urgency):
- Degraded performance / intermittent timeouts
- Bug reports with workarounds available
- Integration issues not blocking core workflows

NORMAL (acknowledge, no page):
- Feature requests
- How-to questions
- Minor UI/cosmetic issues
- Configuration questions

LOW (no reply needed):
- Thank you / appreciation messages
- FYI / informational with no question

## CUSTOMER TIER ADJUSTMENTS

- Enterprise: Lower the bar for urgency. Borderline = URGENT.
- Standard: Normal judgment.
- Free/Trial: Only page for genuine production outages.

## ACTIONS

URGENT:
1. Call `pagerduty_create_incident` with service_id from On-Call Info, urgency="high", title="[Tier] Customer: issue summary"
2. Respond: brief, empathetic, confirm you've paged someone

IMPORTANT:
1. Call `pagerduty_create_incident` with urgency="low"
2. Respond: acknowledge, set expectation for business hours follow-up

NORMAL:
1. Do NOT page.
2. Respond: acknowledge, mention business hours follow-up

LOW:
1. Do NOT page. Do NOT reply.
"""


# Demo customer data
CUSTOMERS = {
    "acme-corp": {
        "tier": "enterprise",
        "contact": "john@acme-corp.com",
        "notes": "Largest customer, very sensitive to downtime",
    },
    "globaltech": {
        "tier": "enterprise",
        "contact": "ops@globaltech.io",
        "notes": "High-volume API user, 24/7 operations",
    },
    "startup-xyz": {
        "tier": "standard",
        "contact": "founder@startup-xyz.com",
        "notes": "Growing fast, often asks feature questions",
    },
    "smallbiz": {
        "tier": "standard",
        "contact": "owner@smallbiz.com",
        "notes": "Monthly billing, occasional support needs",
    },
    "free-user": {
        "tier": "free",
        "contact": "dev@free-user.com",
        "notes": "Trial user, evaluating product",
    },
}

# On-call team info
ONCALL_TEAM = {
    "pagerduty_service_id": "P58A6F7",
    "escalation_policy_id": "",  # Uses default escalation policy for the service
    "team_members": {
        "Long": {
            "slack_id": "U09V0JHFQ5P",
            "role": "Co-founder / Engineer",
            "areas": ["backend", "api", "infrastructure"],
        },
        "Jimmy": {
            "slack_id": "U0A02101LU8",
            "role": "Co-founder / Engineer",
            "areas": ["frontend", "integrations", "database"],
        },
    },
}


def _build_business_context() -> str:
    """Build business context string from customer and on-call data."""
    lines = []

    lines.append("## Customer Database\n")
    lines.append("| Customer | Tier | Contact | Notes |")
    lines.append("|----------|------|---------|-------|")
    for name, info in CUSTOMERS.items():
        contact = info.get("contact") or "—"
        notes = info.get("notes") or ""
        lines.append(f"| {name} | {info['tier']} | {contact} | {notes} |")

    lines.append("\n## On-Call Info\n")
    lines.append(f"**PagerDuty Service ID:** `{ONCALL_TEAM['pagerduty_service_id']}`")
    lines.append(f"**Escalation Policy ID:** `{ONCALL_TEAM['escalation_policy_id']}`\n")
    lines.append("| Team Member | Slack | Role | Areas |")
    lines.append("|-------------|-------|------|-------|")
    for name, info in ONCALL_TEAM["team_members"].items():
        areas = ", ".join(info["areas"])
        lines.append(f"| {name} | <@{info['slack_id']}> | {info['role']} | {areas} |")

    return "\n".join(lines)


def _build_prompt() -> str:
    """Build the full system prompt with business context."""
    business_context = _build_business_context()
    return f"{TRIAGE_SYSTEM_PROMPT}\n\n{business_context}"


def main() -> None:
    load_dotenv()

    # Allow overriding Slack config via environment
    slack_channel_id = os.getenv("ANDY_SLACK_CHANNEL_ID", "C0ADPFB2ADC")
    slack_channel_name = os.getenv("ANDY_SLACK_CHANNEL_NAME", "#andy-demo")

    print("Seeding andy-demo team...")
    print(f"  Organization: {ORG_ID}")
    print(f"  Team: {TEAM_NODE_ID}")
    print(f"  Slack channel: {slack_channel_id} ({slack_channel_name})")

    full_prompt = _build_prompt()

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

        # 2. Create andy-demo team node
        team = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == ORG_ID,
                OrgNode.node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if team is None:
            print("  Creating andy-demo team...")
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
            print("  Andy-demo team already exists, skipping...")

        # Flush to satisfy FK constraints
        s.flush()

        # 3. Create/update team configuration
        team_cfg = s.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == ORG_ID,
                NodeConfiguration.node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        config_json = {
            "team_name": TEAM_NAME,
            "description": "Customer message triage demo - AI monitors Slack channel, assesses urgency, pages on-call for critical issues",
            # Routing - this Slack channel routes to this team
            "routing": {
                "slack_channel_ids": [slack_channel_id],
                "github_repos": [],
                "pagerduty_service_ids": [],
                "services": ["andy-demo"],
            },
            # Auto-triage mode: process ALL messages, not just @mentions
            "auto_triage": True,
            # Agent configuration
            "agents": {
                "planner": {
                    "enabled": True,
                    "model": {
                        "name": "anthropic/claude-sonnet-4-20250514",
                        "temperature": 0.2,
                    },
                    "prompt": {
                        "system": full_prompt,
                        "prefix": "",
                        "suffix": "",
                    },
                    "max_turns": 15,
                },
                # Disable sub-agents not needed for message triage
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
                    updated_by="seed_andy_demo",
                )
            )
        else:
            print("  Updating existing team configuration...")
            team_cfg.config_json = config_json
            team_cfg.updated_by = "seed_andy_demo"

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

    print("\nAndy demo seeding complete!")
    print("\n" + "=" * 60)
    print("DEMO SETUP SUMMARY")
    print("=" * 60)
    print(f"\nSlack Channel: {slack_channel_id} ({slack_channel_name})")
    print("\nauto_triage: True (processes ALL messages, not just @mentions)")
    print("\nCustomers configured:")
    for name, info in CUSTOMERS.items():
        print(f"  - {name}: {info['tier']}")
    print("\nOn-call team:")
    for name, info in ONCALL_TEAM["team_members"].items():
        print(f"  - {name}: {info['role']} (<@{info['slack_id']}>)")
    print(f"\nPagerDuty Service ID: {ONCALL_TEAM['pagerduty_service_id']}")
    print("\nAgent Config:")
    print("  Model: anthropic/claude-sonnet-4 (temperature=0.2)")
    print("  Max turns: 15")
    print("  Entrance: planner only")
    print("\n" + "=" * 60)
    print("\nNext steps:")
    print("  1. Update ANDY_SLACK_CHANNEL_ID with the real channel ID")
    print("  2. Update pagerduty_service_id and escalation_policy_id in the script")
    print("  3. Update team member Slack IDs with real user IDs")
    print("  4. Run the seed script")
    print("  5. Deploy the updated orchestrator (with message event handler)")
    print("  6. Invite the bot to the Slack channel")
    print("  7. Test by sending messages in the channel (no @mention needed)")


if __name__ == "__main__":
    main()
