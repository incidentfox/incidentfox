#!/usr/bin/env python3
"""
Seed the visitor playground organization and team.

This creates:
1. 'playground' organization
2. 'visitor-playground' team node
3. Team configuration with fixed Slack channel (C0ABE64UXQB)
4. Output configuration pointing to the playground Slack channel

Run this script before enabling visitor access to the web UI.

Usage:
    cd config_service
    poetry run python scripts/seed_visitor_playground.py

Environment variables:
    PLAYGROUND_SLACK_CHANNEL_ID: Slack channel ID for the playground (default: C0ABE64UXQB)
    PLAYGROUND_SLACK_CHANNEL_NAME: Slack channel name (default: #visitor-playground)
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

# Playground configuration constants
PLAYGROUND_ORG_ID = "playground"
PLAYGROUND_TEAM_NODE_ID = "visitor-playground"
PLAYGROUND_TEAM_NAME = "Visitor Playground"


def main() -> None:
    load_dotenv()

    # Allow overriding Slack config via environment
    slack_channel_id = os.getenv("PLAYGROUND_SLACK_CHANNEL_ID", "C0ABE64UXQB")
    slack_channel_name = os.getenv(
        "PLAYGROUND_SLACK_CHANNEL_NAME", "#visitor-playground"
    )

    print("Seeding visitor playground...")
    print(f"  Organization: {PLAYGROUND_ORG_ID}")
    print(f"  Team: {PLAYGROUND_TEAM_NODE_ID}")
    print(f"  Slack channel: {slack_channel_id} ({slack_channel_name})")

    with db_session() as s:
        # 1. Create playground organization (root org node)
        root = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == PLAYGROUND_ORG_ID,
                OrgNode.node_id == PLAYGROUND_ORG_ID,
            )
        ).scalar_one_or_none()

        if root is None:
            print("  Creating playground organization...")
            s.add(
                OrgNode(
                    org_id=PLAYGROUND_ORG_ID,
                    node_id=PLAYGROUND_ORG_ID,
                    parent_id=None,
                    node_type=NodeType.org,
                    name="Visitor Playground Org",
                )
            )
        else:
            print("  Playground organization already exists, skipping...")

        # 2. Create visitor-playground team node
        team = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == PLAYGROUND_ORG_ID,
                OrgNode.node_id == PLAYGROUND_TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if team is None:
            print("  Creating visitor-playground team...")
            s.add(
                OrgNode(
                    org_id=PLAYGROUND_ORG_ID,
                    node_id=PLAYGROUND_TEAM_NODE_ID,
                    parent_id=PLAYGROUND_ORG_ID,
                    node_type=NodeType.team,
                    name=PLAYGROUND_TEAM_NAME,
                )
            )
        else:
            print("  Visitor-playground team already exists, skipping...")

        # Flush to satisfy FK constraints
        s.flush()

        # 3. Create org-level configuration
        org_cfg = s.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == PLAYGROUND_ORG_ID,
                NodeConfiguration.node_id == PLAYGROUND_ORG_ID,
            )
        ).scalar_one_or_none()

        if org_cfg is None:
            print("  Creating org configuration...")
            s.add(
                NodeConfiguration(
                    id=f"cfg-{uuid.uuid4().hex[:12]}",
                    org_id=PLAYGROUND_ORG_ID,
                    node_id=PLAYGROUND_ORG_ID,
                    node_type="org",
                    config_json={
                        "description": "Public visitor playground for demoing IncidentFox",
                        # Minimal MCP servers for demo
                        "mcp_servers": [],
                    },
                    updated_by="seed_visitor_playground",
                )
            )
        else:
            print("  Org configuration already exists, skipping...")

        # 4. Create team configuration with fixed routing
        team_cfg = s.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == PLAYGROUND_ORG_ID,
                NodeConfiguration.node_id == PLAYGROUND_TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if team_cfg is None:
            print("  Creating team configuration...")
            s.add(
                NodeConfiguration(
                    id=f"cfg-{uuid.uuid4().hex[:12]}",
                    org_id=PLAYGROUND_ORG_ID,
                    node_id=PLAYGROUND_TEAM_NODE_ID,
                    node_type="team",
                    config_json={
                        "team_name": PLAYGROUND_TEAM_NAME,
                        "description": "Public playground team for visitors to try IncidentFox",
                        # Fixed routing - only this Slack channel routes to playground
                        "routing": {
                            "slack_channel_ids": [slack_channel_id],
                            "github_repos": [],
                            "pagerduty_service_ids": [],
                            "incidentio_team_ids": [],
                            "services": ["playground-demo"],
                        },
                        # Basic agent config
                        "agent": {
                            "model": "gpt-4o",
                            "max_tool_calls": 50,
                        },
                    },
                    updated_by="seed_visitor_playground",
                )
            )
        else:
            print("  Team configuration already exists, skipping...")

        # 5. Create output configuration (where agent results go)
        output_cfg = s.execute(
            select(TeamOutputConfig).where(
                TeamOutputConfig.org_id == PLAYGROUND_ORG_ID,
                TeamOutputConfig.team_node_id == PLAYGROUND_TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if output_cfg is None:
            print("  Creating output configuration...")
            s.add(
                TeamOutputConfig(
                    org_id=PLAYGROUND_ORG_ID,
                    team_node_id=PLAYGROUND_TEAM_NODE_ID,
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
            print("  Output configuration already exists, skipping...")

        s.commit()

    print("\nVisitor playground seeding complete!")
    print("\nNext steps:")
    print("  1. Create a Slack bot for the playground workspace")
    print("  2. Set the SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET for the playground")
    print("  3. Invite the bot to the playground channel")
    print("  4. Visitors can now log in with their email at the web UI")


if __name__ == "__main__":
    main()
