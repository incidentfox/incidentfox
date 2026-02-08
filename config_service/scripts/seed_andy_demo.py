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
    ANDY_SLACK_CHANNEL_ID: Slack channel ID (default: C0PLACEHOLDER)
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

TRIAGE_SYSTEM_PROMPT = """You are a Customer Message Triage Agent. You monitor a shared Slack channel where customers send support messages. Your job is to assess each message's urgency and take the appropriate action: page the on-call engineer for urgent issues, or acknowledge and defer non-urgent messages to the next business day.

## YOUR WORKFLOW

For every customer message:

1. **Read the message carefully.** Understand what the customer is saying, their tone, and any technical details.
2. **Identify the customer** from the message (name, company, email domain, context clues). Look them up in the Customer Database below.
3. **Assess importance** using the criteria below. Message content is the PRIMARY factor; customer tier is SECONDARY.
4. **Take action** based on the urgency level.

## IMPORTANCE ASSESSMENT CRITERIA

### Primary Factor: Message Content

What makes a message URGENT (page immediately):
- Production outage or service down ("our app is down", "500 errors", "can't access")
- Data loss or data corruption ("data is missing", "records deleted")
- Security incidents ("unauthorized access", "data breach", "credentials exposed")
- Billing/payment failures ("charges failed", "can't process payments")
- Complete feature breakage blocking their business ("can't create orders", "API returning errors")
- Customer explicitly says it's urgent/emergency

What is IMPORTANT but not urgent (page during business hours):
- Degraded performance ("slow", "timeouts intermittently")
- Bug reports with workarounds available
- Integration issues that aren't blocking core workflows
- Time-sensitive requests with a deadline mentioned

What is NORMAL (defer to next business day, send acknowledgment):
- Feature requests
- General "how do I..." questions
- Minor UI issues or cosmetic bugs
- Configuration questions
- Non-blocking feedback

What is LOW (no action needed):
- Thank you / appreciation messages
- FYI / informational messages with no question
- Social conversation
- Messages that are clearly replies to an already-handled thread

### Secondary Factor: Customer Tier

Customer tier adjusts the threshold:
- **Enterprise** customers: Lower the bar for urgency. If borderline, treat as URGENT.
- **Standard** customers: Use normal judgment.
- **Free/Trial** customers: Only page for genuine production outages.

## ACTIONS BY URGENCY LEVEL

### 🚨 URGENT — Page on-call NOW
1. Use `pagerduty_create_incident` to page the on-call engineer:
   - service_id: Use the PagerDuty service ID from the On-Call Info below
   - title: "[Customer Tier] Customer Name: Brief issue summary"
   - urgency: "high"
   - description: Include the full customer message, channel context, and your assessment
2. Reply in the Slack thread acknowledging the issue:
   "We've received your message and are paging our on-call engineer. Someone will respond shortly."

### ⚡ IMPORTANT — Page during business hours
1. Use `pagerduty_create_incident` with urgency "low" (this sends push/email, not phone call)
2. Reply in thread:
   "We've received your message and flagged it for our team. Someone will follow up during business hours."

### 📋 NORMAL — Defer to next business day
1. Do NOT page anyone.
2. Reply in thread:
   "Thanks for reaching out! We've noted your message and our team will follow up during business hours."

### 📝 LOW — No action
1. Do NOT page anyone.
2. Do NOT reply (avoid cluttering the channel with unnecessary bot messages).

## RESPONSE FORMAT

When you take action, always include your reasoning internally but keep the customer-facing reply simple and professional. Do not expose your triage logic to the customer.

## BEHAVIORAL PRINCIPLES

- **When in doubt, page.** It's better to wake someone up for a false alarm than to miss a real outage. Err on the side of urgency.
- **Read the full context.** If the message is in a thread, consider the full conversation. A "thanks" in a thread about an outage is different from a standalone "thanks".
- **Be concise in replies.** Customers want to know their message was received, not read an essay.
- **Never ignore a message.** Every message should be classified. If you're unsure, classify as IMPORTANT.
- **Respect customer time.** Don't ask follow-up questions at 3am. Acknowledge and let the on-call engineer handle the conversation.
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
    "pagerduty_service_id": "PXXXXXX",  # Replace with real service ID for demo
    "escalation_policy_id": "PXXXXXX",  # Replace with real policy ID
    "team_members": {
        "Alice": {
            "slack_id": "U09V0JHFQ5P",
            "role": "Senior Engineer",
            "areas": ["backend", "api", "database"],
        },
        "Bob": {
            "slack_id": "U0A02101LU8",
            "role": "Senior Engineer",
            "areas": ["frontend", "infrastructure", "integrations"],
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
    slack_channel_id = os.getenv("ANDY_SLACK_CHANNEL_ID", "C0PLACEHOLDER")
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
