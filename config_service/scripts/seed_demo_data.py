#!/usr/bin/env python3
import sys
from pathlib import Path

# Ensure repo root is on sys.path so `import src.*` works when running as a script.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import os
import uuid
from datetime import datetime

from sqlalchemy import select
from src.core.dotenv import load_dotenv
from src.db.config_models import NodeConfiguration
from src.db.models import NodeType, OrgNode
from src.db.session import db_session


def main() -> None:
    load_dotenv()
    # Minimal seed data so /me/effective has something to return.
    org_id = os.getenv("SEED_ORG_ID", "org1")
    root_id = os.getenv("SEED_ROOT_NODE_ID", "root")
    team_id = os.getenv("SEED_TEAM_NODE_ID", "teamA")
    team_name = os.getenv("SEED_TEAM_NAME", "Team A")

    with db_session() as s:
        # Root org node
        root = s.execute(
            select(OrgNode).where(OrgNode.org_id == org_id, OrgNode.node_id == root_id)
        ).scalar_one_or_none()
        if root is None:
            s.add(
                OrgNode(
                    org_id=org_id,
                    node_id=root_id,
                    parent_id=None,
                    node_type=NodeType.org,
                    name="Root Org",
                )
            )

        # Team node
        team = s.execute(
            select(OrgNode).where(OrgNode.org_id == org_id, OrgNode.node_id == team_id)
        ).scalar_one_or_none()
        if team is None:
            s.add(
                OrgNode(
                    org_id=org_id,
                    node_id=team_id,
                    parent_id=root_id,
                    node_type=NodeType.team,
                    name=team_name,
                )
            )

        # Ensure org_nodes are persisted before inserting node_configs (FK constraint).
        s.flush()

        # Root config
        root_cfg = s.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == org_id, NodeConfiguration.node_id == root_id
            )
        ).scalar_one_or_none()
        if root_cfg is None:
            s.add(
                NodeConfiguration(
                    id=f"cfg-{uuid.uuid4().hex[:12]}",
                    org_id=org_id,
                    node_id=root_id,
                    node_type="org",
                    config_json={
                        "knowledge_source": {"grafana": ["dash/org-default"]},
                        "mcp_servers": ["mcps://grafana"],
                        "alerts": {"disabled": []},
                    },
                    version=1,
                    updated_at=datetime.utcnow(),
                    updated_by="seed",
                )
            )

        # Team overrides
        team_cfg = s.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == org_id, NodeConfiguration.node_id == team_id
            )
        ).scalar_one_or_none()
        if team_cfg is None:
            s.add(
                NodeConfiguration(
                    id=f"cfg-{uuid.uuid4().hex[:12]}",
                    org_id=org_id,
                    node_id=team_id,
                    node_type="team",
                    config_json={
                        "team_name": team_name,
                        "knowledge_source": {"confluence": ["space:TEAM:runbooks"]},
                    },
                    version=1,
                    updated_at=datetime.utcnow(),
                    updated_by="seed",
                )
            )

    print(f"Seeded org_nodes/node_configs for org_id={org_id}, team_node_id={team_id}")


if __name__ == "__main__":
    main()
