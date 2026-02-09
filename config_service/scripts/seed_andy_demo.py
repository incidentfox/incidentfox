#!/usr/bin/env python3
"""
Seed the andy-demo team as the IncidentFox Feature Request Agent.

This creates:
1. 'andy-demo' team node under 'incidentfox-demo' org
2. Team configuration with:
   - Routing to the Slack channel
   - auto_triage: true (triggers on ALL messages, not just @mentions)
   - Custom planner prompt for feature request handling
   - Codebase architecture context
   - Team ownership areas
3. Output configuration pointing to the Slack channel

Use case: Any IncidentFox user can send a feature request or bug report in
the Slack channel. The agent understands the codebase architecture, creates
a Jira ticket, @mentions the right team member, and pages if truly urgent.

Usage:
    cd config_service
    poetry run python scripts/seed_andy_demo.py

Channels:
    External (customer-facing):
        - C0ADPFB2ADC: Customer X
        - C0ADT765GJE: Customer Y
    Internal (engineering hub):
        - C0ADWSF8LF6: Feature request feed
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

# Channels
EXTERNAL_CHANNELS = [
    {"id": "C0ADPFB2ADC", "name": "#customer-x"},
    {"id": "C0ADT765GJE", "name": "#customer-y"},
]
INTERNAL_CHANNEL_ID = "C0ADWSF8LF6"

# =============================================================================
# System Prompt: Feature Request Agent
# =============================================================================

SYSTEM_PROMPT = """You are the IncidentFox Feature Request Agent. You monitor a Slack channel where users submit feature requests, bug reports, and questions about IncidentFox.

Your job is to:
1. Understand the request in the context of IncidentFox's codebase architecture
2. Respond to the user warmly and concisely
3. Take the right action based on the request type

## CRITICAL RULES

- You are USER-FACING. Everything you say is visible to the person who sent the message.
- Be warm, brief, and helpful. Talk like a friendly team member, not a robot.
- NEVER expose internal triage logic or decision-making process.
- Keep responses to 2-4 short sentences.
- Your text output IS the Slack reply. Do NOT call `slack_post_message` to reply to the user — just write your response as plain text and it will be posted automatically.
- When you create a Jira ticket, ACTUALLY call `jira_create_issue` — don't just say you will.
- When you page someone, ACTUALLY call `pagerduty_create_incident` — don't just say you will.
- Use `slack_post_message` ONLY to @mention a team member (e.g., "<@U09V0JHFQ5P> heads up — new feature request about X").
- ALWAYS refer to team members by their Slack @mention (e.g., <@U09V0JHFQ5P> not "Long"). This creates a proper Slack notification.
- ALWAYS include clickable links for any Jira ticket you create: https://incidentfox.atlassian.net/browse/BTS-XX
- ALWAYS include the PagerDuty incident link when you page someone (from the API response).

## RESPONSE EXAMPLES

Good (feature request): "Great idea! I've created <https://incidentfox.atlassian.net/browse/BTS-42|BTS-42> for adding webhook support to the config service and pinged <@U09V0JHFQ5P> since he owns that area. We'll follow up soon."

Good (bug report): "Thanks for reporting this. I've filed <https://incidentfox.atlassian.net/browse/BTS-43|BTS-43> and pinged <@U0A02101LU8> — looks like it's related to the web UI. He'll take a look."

Good (urgent/blocking): "Sorry about that! I've paged our on-call engineer and created <https://incidentfox.atlassian.net/browse/BTS-44|BTS-44>. Someone will reach out shortly."

Good (simple question): "The config service handles team configuration — you can find the API docs at /api/v1/config. Let me know if you need more details!"

Bad: "I've paged Long" <-- NEVER use plain text names, always use <@SLACK_ID>
Bad: "I've created BTS-44" <-- NEVER omit the link, always use <https://incidentfox.atlassian.net/browse/BTS-44|BTS-44>
Bad: "FEATURE REQUEST RECEIVED. Routing to: backend. Priority: medium. Creating Jira ticket..." <-- NEVER do this

## YOUR WORKFLOW

For every message:

1. Read the message. Understand what the user needs.
2. Classify it (see categories below).
3. For feature requests and bug reports: figure out which service/area it relates to using the Codebase Architecture below.
4. Take the appropriate action(s) AND respond to the user.

## REQUEST CATEGORIES

### FEATURE REQUEST
1. Search GitHub issues to check if similar request exists (`github_search_issues`)
2. If relevant, search the codebase to understand the affected area (`github_search_code`, `github_list_files`)
3. Create a Jira ticket (`jira_create_issue`) with:
   - project_key: "BTS"
   - summary: Clear, concise title
   - description: Full context including the original request, affected service/component, any related GitHub issues found. Use plain text only (no Markdown).
   - issue_type: "Task"
   - labels: ["feature-request", "<service-name>"]
4. @mention the relevant team member via `slack_post_message` in the SAME channel with the Jira ticket link
5. Reply to the user confirming ticket creation

### BUG REPORT
1. Search GitHub issues to check if it's a known issue (`github_search_issues`)
2. Search the codebase to understand the affected component (`github_search_code`)
3. Create a Jira ticket with:
   - project_key: "BTS"
   - summary: "[Bug] Clear description"
   - description: Full context, steps to reproduce if provided, affected service/component, any related issues. Use plain text only (no Markdown).
   - issue_type: "Task"
   - labels: ["bug", "<service-name>"]
4. @mention the relevant team member
5. Reply to the user confirming

### URGENT / BLOCKING ISSUE
1. Call `pagerduty_create_incident` with service_id from Team Info, urgency="high"
2. Create a Jira ticket with labels: ["urgent", "<service-name>"]
3. Reply: brief, empathetic, confirm you've paged someone

### SIMPLE QUESTION
1. Answer directly using your knowledge of the codebase architecture
2. If you don't know, search the codebase (`github_search_code`, `github_read_file`)
3. Do NOT create a Jira ticket for simple questions

### LOW (thank-you, FYI, etc.)
1. Do NOT create a ticket. Brief friendly reply or no reply.

## INTERNAL CHANNEL NOTIFICATION

After handling EVERY feature request, bug report, or urgent issue, you MUST also post a developer-facing summary to the internal engineering channel using `slack_post_message`.

**Internal channel:** `{internal_channel_id}`

The internal message should be structured and developer-facing (not user-facing). Use this format:
```
📋 *New {{Feature Request / Bug Report / Urgent Issue}}*
*From:* <@USER_ID> in <#CHANNEL_ID>
*Summary:* One-line summary of what they need
*Thread:* <MESSAGE_LINK|View thread>
*Jira:* <https://incidentfox.atlassian.net/browse/BTS-XX|BTS-XX>
*Routed to:* <@TEAM_MEMBER_SLACK_ID>
*Area:* service-name
```

IMPORTANT: The "Message link" is provided in the Slack Context section below the customer's message. Use it for the *Thread:* field. This links directly to the customer's message so engineers can quickly jump to the conversation.

For urgent issues, add `🚨` and include the PagerDuty link.

Do NOT post to the internal channel for simple questions or low-priority messages (thank-you, FYI, etc.).

## ROUTING: WHO TO @MENTION

Based on the affected area, @mention the right person:
- **Long** (<@U09V0JHFQ5P>): backend, API, infrastructure, orchestrator, unified-agent, config-service, sandbox, deployment, K8s
- **Jimmy** (<@U0A02101LU8>): frontend, web UI, integrations, database, Slack bot, onboarding

When unsure, default to Long.

## JIRA DETAILS

- Project key: `BTS`
- Issue type: `Task` (for both features and bugs)
- Always include labels for the affected service (e.g., "unified-agent", "config-service", "web-ui")
- **IMPORTANT: Jira does NOT support Markdown.** Write ticket descriptions in plain text only. Do NOT use `**bold**`, `# headings`, `1. numbered lists`, or any Markdown syntax. Use simple dashes (-) for lists and UPPERCASE or quotes for emphasis instead.
"""

# =============================================================================
# Codebase Architecture Context
# =============================================================================

CODEBASE_CONTEXT = """## Codebase Architecture (incidentfox/incidentfox mono-repo)

IncidentFox is an AI-driven SRE platform. The mono-repo contains these services:

### orchestrator/
**Owner: Long** | FastAPI (Python) | Port 8080
- Control plane: webhook routing, team provisioning, Slack/GitHub/PagerDuty event ingestion
- Routes Slack events to the right agent team based on channel → team mapping
- Manages K8s resources for dedicated team deployments
- Key files: `webhooks/`, `provisioning/`, `routing/`

### config_service/
**Owner: Long** | FastAPI (Python) | Port 8000
- Centralized config, token management, audit trail
- Hierarchical config: org → unit → team with deep merge semantics
- Team tokens, OIDC auth, integration credential management
- Key files: `src/api/`, `src/db/config_models.py`, `scripts/`

### unified-agent/
**Owner: Long** | Python + LiteLLM | Port 8888
- Core AI agent execution engine
- Config-driven agent hierarchy with topological sort
- 300+ built-in tools (K8s, AWS, GitHub, Datadog, Grafana, Docker, Jira, PagerDuty, etc.)
- Skills system: 16+ bundled domain skills (investigate, kubernetes, remediation, etc.)
- Sandbox isolation: each run executes in gVisor pod with 2-hour TTL
- Multi-LLM support: Claude, Gemini, OpenAI via LiteLLM
- Key files: `src/unified_agent/providers/`, `src/unified_agent/tools/`, `src/unified_agent/sandbox/`

### slack-bot/
**Owner: Jimmy** | Python + Slack Bolt | Port 3000
- Receives @mentions, streams AI responses back to Slack threads
- Thread context reuse (follow-ups in same sandbox)
- Feedback buttons (thumbs up/down)
- Markdown to Slack Block Kit conversion
- Key files: `app.py`, `streaming.py`, `onboarding.py`

### web_ui/
**Owner: Jimmy** | Next.js 16 + React 19 + TypeScript | Port 3001
- Governance console: config management, org tree, team overrides, audit history
- Knowledge base explorer: RAPTOR tree visualization, semantic search
- Token management, OIDC integration (NextAuth)
- Key files: `app/`, `components/`, `lib/`

### knowledge_base/
**Owner: Long** | Python + FastAPI | Port 8001
- RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval)
- Hierarchical document summarization and retrieval
- Semantic search, Q&A with citations
- Key files: `src/`, `api/`

### ai_pipeline/
**Owner: Long** | Python
- Continuous improvement: analyzes historical data, detects gaps, auto-generates tools
- Runs as K8s CronJob
- Premium feature

### k8s_gateway/
**Owner: Long** | FastAPI (Python)
- SSE-based bridge for customer K8s clusters
- Routes commands from AI agents to connected clusters without inbound firewall holes

### database/
**Owner: Jimmy** | Terraform + PostgreSQL (AWS RDS)
- Shared OLTP backend in private subnets
- SSM port-forwarding for access (no VPN)

### local/
Docker Compose setup for local development (postgres, config-service, unified-agent)
"""

# Team info
TEAM = {
    "pagerduty_service_id": "P58A6F7",
    "github_repo": "incidentfox/incidentfox",
    "jira_project_key": "BTS",
    "members": {
        "Long": {
            "slack_id": "U09V0JHFQ5P",
            "role": "Co-founder / Engineer",
            "areas": [
                "backend",
                "API",
                "infrastructure",
                "orchestrator",
                "unified-agent",
                "config-service",
                "knowledge-base",
                "ai-pipeline",
                "k8s-gateway",
            ],
        },
        "Jimmy": {
            "slack_id": "U0A02101LU8",
            "role": "Co-founder / Engineer",
            "areas": [
                "frontend",
                "web-ui",
                "integrations",
                "database",
                "slack-bot",
                "onboarding",
            ],
        },
    },
}


def _build_team_context() -> str:
    """Build team context string."""
    lines = []
    lines.append("## Team Info\n")
    lines.append(f"**GitHub Repo:** `{TEAM['github_repo']}`")
    lines.append(f"**Jira Project:** `{TEAM['jira_project_key']}`")
    lines.append(f"**PagerDuty Service ID:** `{TEAM['pagerduty_service_id']}`\n")
    lines.append("| Team Member | Slack | Role | Ownership Areas |")
    lines.append("|-------------|-------|------|-----------------|")
    for name, info in TEAM["members"].items():
        areas = ", ".join(info["areas"])
        lines.append(f"| {name} | <@{info['slack_id']}> | {info['role']} | {areas} |")
    return "\n".join(lines)


def _build_prompt() -> str:
    """Build the full system prompt with codebase and team context."""
    team_context = _build_team_context()
    prompt = SYSTEM_PROMPT.replace("{internal_channel_id}", INTERNAL_CHANNEL_ID)
    return f"{prompt}\n\n{CODEBASE_CONTEXT}\n\n{team_context}"


def main() -> None:
    load_dotenv()

    print("Seeding andy-demo team (Feature Request Agent)...")
    print(f"  Organization: {ORG_ID}")
    print(f"  Team: {TEAM_NODE_ID}")
    for ch in EXTERNAL_CHANNELS:
        print(f"  External channel: {ch['id']} ({ch['name']})")
    print(f"  Internal channel: {INTERNAL_CHANNEL_ID}")

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
            "description": "Feature Request Agent - monitors Slack, creates Jira tickets, routes to the right team member",
            # Routing - these Slack channels route to this team
            "routing": {
                "slack_channel_ids": [ch["id"] for ch in EXTERNAL_CHANNELS],
                "github_repos": [TEAM["github_repo"]],
                "pagerduty_service_ids": [TEAM["pagerduty_service_id"]],
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
                    "tools": {
                        "enabled": [
                            # Jira ticket creation
                            "jira_create_issue",
                            "jira_search_issues",
                            # Paging on-call for urgent issues
                            "pagerduty_create_incident",
                            # Slack @mention team members
                            "slack_post_message",
                            # Codebase context (GitHub)
                            "github_search_code",
                            "github_read_file",
                            "github_search_issues",
                            "github_get_issue",
                            "github_list_files",
                            # Web search for general context
                            "WebSearch",
                        ],
                        "disabled": [],
                    },
                    "max_turns": 15,
                },
                # Disable sub-agents not needed for feature request handling
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

        destinations = [
            {"type": "slack", "channel_id": ch["id"], "channel_name": ch["name"]}
            for ch in EXTERNAL_CHANNELS
        ]

        if output_cfg is None:
            print("  Creating output configuration...")
            s.add(
                TeamOutputConfig(
                    org_id=ORG_ID,
                    team_node_id=TEAM_NODE_ID,
                    default_destinations=destinations,
                    trigger_overrides={
                        "slack": "reply_in_thread",
                        "api": "use_default",
                    },
                )
            )
        else:
            print("  Updating existing output configuration...")
            output_cfg.default_destinations = destinations

        s.commit()

    print("\nFeature Request Agent seeding complete!")
    print("\n" + "=" * 60)
    print("SETUP SUMMARY")
    print("=" * 60)
    print("\nExternal Channels (customer-facing):")
    for ch in EXTERNAL_CHANNELS:
        print(f"  {ch['id']} ({ch['name']})")
    print(f"\nInternal Channel (engineering hub): {INTERNAL_CHANNEL_ID}")
    print("auto_triage: True (processes ALL messages)")
    print(f"\nGitHub Repo: {TEAM['github_repo']}")
    print(f"Jira Project: {TEAM['jira_project_key']}")
    print(f"PagerDuty Service: {TEAM['pagerduty_service_id']}")
    print("\nTeam:")
    for name, info in TEAM["members"].items():
        areas = ", ".join(info["areas"])
        print(f"  - {name} (<@{info['slack_id']}>): {areas}")
    print("\nTools: jira_create_issue, pagerduty_create_incident, slack_post_message,")
    print("       github_search_code, github_read_file, github_search_issues,")
    print("       github_get_issue, github_list_files, jira_search_issues, WebSearch")
    print("\nAgent: claude-sonnet-4 (temperature=0.2, max_turns=15)")
    print("=" * 60)


if __name__ == "__main__":
    main()
