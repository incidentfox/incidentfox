from __future__ import annotations

"""
Minimal DB migration runner for orchestrator (enterprise-safe MVP).

We intentionally avoid auto-creating tables on service startup in production.
Instead, run this as a Helm Job / init step.

This is safe to run repeatedly (CREATE TABLE IF NOT EXISTS).
"""

from sqlalchemy import text as sql_text

from incidentfox_orchestrator.config import load_settings
from incidentfox_orchestrator.db import db_session, get_engine, init_engine

MIGRATIONS: list[tuple[str, str]] = [
    (
        "001_create_orchestrator_tables",
        """
        CREATE TABLE IF NOT EXISTS orchestrator_team_slack_channels (
          slack_channel_id varchar(64) PRIMARY KEY,
          org_id varchar(128) NOT NULL,
          team_node_id varchar(128) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_team_slack_channels_team
          ON orchestrator_team_slack_channels (org_id, team_node_id);

        CREATE TABLE IF NOT EXISTS orchestrator_provisioning_runs (
          id uuid PRIMARY KEY,
          org_id varchar(128) NOT NULL,
          team_node_id varchar(128) NOT NULL,
          idempotency_key varchar(128),
          status varchar(32) NOT NULL DEFAULT 'running',
          steps jsonb NOT NULL DEFAULT '{}'::jsonb,
          error text,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_orch_provision_runs_team
          ON orchestrator_provisioning_runs (org_id, team_node_id);

        CREATE UNIQUE INDEX IF NOT EXISTS ux_orch_provision_idempotency
          ON orchestrator_provisioning_runs (org_id, team_node_id, idempotency_key)
          WHERE idempotency_key IS NOT NULL;
        """,
    ),
    (
        "002_add_idempotency_key_if_missing",
        """
        ALTER TABLE orchestrator_provisioning_runs
          ADD COLUMN IF NOT EXISTS idempotency_key varchar(128);

        CREATE UNIQUE INDEX IF NOT EXISTS ux_orch_provision_idempotency
          ON orchestrator_provisioning_runs (org_id, team_node_id, idempotency_key)
          WHERE idempotency_key IS NOT NULL;
        """,
    ),
    (
        "003_drop_team_slack_channels",
        """
        -- TD-006: Drop deprecated orchestrator_team_slack_channels table.
        -- Slack channel routing is now fully handled by Config Service.
        DROP TABLE IF EXISTS orchestrator_team_slack_channels;
        """,
    ),
]


def main() -> None:
    s = load_settings()
    init_engine(s.db_url)
    get_engine()
    with db_session() as sess:
        for name, sql in MIGRATIONS:
            sess.execute(sql_text(sql))


if __name__ == "__main__":
    main()
