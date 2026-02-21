#!/usr/bin/env python3
"""
Seed MochaCare team configuration.

MochaCare is a startup running AI agents as a service on Vercel.
They need monitoring for agent failures, error logs, and proactive alerting.

Creates:
1. Team node under the specified org
2. Team configuration with:
   - Slack + GitHub routing
   - Planner agent with Vercel/AI-agent monitoring prompt
3. Output configuration (Slack thread replies)
4. Two scheduled jobs: 8AM and 8PM status reports

Usage:
    cd config_service
    MOCHACARE_ORG_ID=mochacare \
    MOCHACARE_SLACK_CHANNEL_ID=C0... \
    poetry run python scripts/seed_mochacare.py

Environment variables:
    MOCHACARE_ORG_ID: Customer org ID (required)
    MOCHACARE_SLACK_CHANNEL_ID: Slack channel for reports (required)
    MOCHACARE_GITHUB_REPO: GitHub repo (optional, format: owner/repo)
    MOCHACARE_TEAM_ID: Team node ID (default: mochacare-sre)
    MOCHACARE_SLACK_CHANNEL_NAME: Slack channel name (default: #mochacare-ops)
    MOCHACARE_TIMEZONE: Timezone for scheduled reports (default: America/Los_Angeles)
    MOCHACARE_GRAFANA_URL: Grafana Cloud URL (optional)
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import os
import uuid
from datetime import datetime, timezone

from croniter import croniter
from sqlalchemy import select
from src.core.dotenv import load_dotenv
from src.db.config_models import NodeConfiguration
from src.db.models import (
    NodeType,
    OrgNode,
    TeamOutputConfig,
)
from src.db.scheduled_jobs import ScheduledJob
from src.db.session import db_session

# =============================================================================
# System Prompt: MochaCare SRE Agent
# =============================================================================

MOCHACARE_SRE_PROMPT = r"""You are an SRE agent monitoring MochaCare's infrastructure. MochaCare runs AI agents as a service on Vercel. Silent agent failures are unacceptable — catching errors early is the #1 priority.

## CONTEXT

MochaCare pivoted from selling software to providing a service using software in-house. Their AI agents handle customer-facing tasks. When agents fail silently, customers don't get served and revenue is lost.

Infrastructure: Vercel (serverless). Key signals: error logs, agent failure patterns, latency spikes.

## YOUR PRIORITIES

1. **Agent Failures** — Any agent crash, timeout, or unexpected error. This is critical.
2. **Error Rate Changes** — Sudden spikes in error logs, new error types appearing.
3. **Latency Degradation** — API response times increasing beyond normal ranges.
4. **Service Health** — Overall system availability and endpoint health.

## AMPLITUDE EVENT NAMES

MochaCare tracks these events in Amplitude (names are case-sensitive, use exactly as shown):
- `Agent Started` — fired when an agent invocation begins
- `Agent Completed` — fired when an agent finishes successfully
- `Agent Failed` — fired when an agent errors/crashes
- `API Error` — fired on 4xx/5xx API responses

Key properties: agent_id, user_id, duration_ms, error_type, error_message, status_code

## FOR STATUS REPORTS

When generating a status report, follow this structure:

### 1. Check Grafana dashboards
Use the Grafana skill to query dashboards and panels for the reporting period.

### 2. Check Amplitude for agent events
Use the Amplitude skill to query the events listed above. Focus on `Agent Failed` and `API Error` counts.

### 3. Check recent logs
Look for error patterns, new error types, and frequency changes.

### 4. Generate report

Format your report as:

**Status Report — {date} {time_range}**

🟢/🟡/🔴 **Overall Status**: [healthy/degraded/incident]

**Key Metrics** (last {hours}h):
- Errors: {count} ({trend} vs previous period)
- Agent failures: {count}
- Avg latency: {ms}ms

**Issues Found**:
- [List any anomalies, errors, or concerns]

**No Action Needed** / **Action Required**:
- [Clear next steps if any]

Keep reports concise. If everything is healthy, say so briefly. Only go into detail when there are actual issues.
"""

MORNING_REPORT_PROMPT = """\
Check Grafana and Amplitude for the last 12 hours (8PM-8AM overnight). \
Output ONLY the final result — no narration, no "I will check", no process description.

Always start with: "*IncidentFox Automatic Status Report*"

If healthy: one sentence. Example:
*IncidentFox Automatic Status Report*
All clear overnight — 142 agent runs, 0 failures, 99.8% uptime, p95 latency 320ms.

If issues found: 2-3 bullets with numbers, then a short "Suggested action" line. Example:
*IncidentFox Automatic Status Report*
- 20/142 agent runs failed (14%) — top error: tool_error (12), timeout (8)
- p95 latency spiked to 1.2s (normally 300ms)
- Grafana: 3 alerts fired in us-west-2

Suggested action: Investigate tool_error spike — likely downstream API degradation. Check recent deploys.

Rules: Always include total runs, failure count with %, top error types. \
Never repeat the same number twice. Keep suggested action to one sentence."""

EVENING_REPORT_PROMPT = """\
Check Grafana and Amplitude for the last 12 hours (8AM-8PM daytime). \
Output ONLY the final result — no narration, no "I will check", no process description.

Always start with: "*IncidentFox Automatic Status Report*"

If healthy: one sentence. Example:
*IncidentFox Automatic Status Report*
Healthy day — 1,203 agent runs, 2 failures (0.2%), p95 latency 280ms.

If issues found: 2-3 bullets with numbers, then a short "Suggested action" line. Example:
*IncidentFox Automatic Status Report*
- 45/1,203 agent runs failed (3.7%) — top error: timeout (30), tool_error (15)
- Error spike at 2:15 PM, resolved by 2:40 PM
- Grafana: elevated 5xx rate on /api/chat endpoint

Suggested action: Monitor timeout trend — may need to increase agent execution limits or check downstream latency.

Rules: Always include total runs, failure count with %, top error types. \
Never repeat the same number twice. Keep suggested action to one sentence."""


def main() -> None:
    load_dotenv()

    org_id = os.getenv("MOCHACARE_ORG_ID")
    slack_channel_id = os.getenv("MOCHACARE_SLACK_CHANNEL_ID")
    github_repo = os.getenv("MOCHACARE_GITHUB_REPO", "")
    team_node_id = os.getenv("MOCHACARE_TEAM_ID", "mochacare-sre")
    team_name = "MochaCare SRE"
    slack_channel_name = os.getenv("MOCHACARE_SLACK_CHANNEL_NAME", "#mochacare-ops")
    tz = os.getenv("MOCHACARE_TIMEZONE", "America/Los_Angeles")
    grafana_url = os.getenv("MOCHACARE_GRAFANA_URL", "")

    if not org_id:
        print("ERROR: MOCHACARE_ORG_ID is required")
        print("  export MOCHACARE_ORG_ID=mochacare")
        sys.exit(1)

    if not slack_channel_id:
        print("ERROR: MOCHACARE_SLACK_CHANNEL_ID is required")
        print("  export MOCHACARE_SLACK_CHANNEL_ID=C0...")
        sys.exit(1)

    print("Seeding MochaCare configuration...")
    print(f"  Organization: {org_id}")
    print(f"  Team: {team_node_id}")
    print(f"  Slack: {slack_channel_id} ({slack_channel_name})")
    if github_repo:
        print(f"  GitHub repo: {github_repo}")
    if grafana_url:
        print(f"  Grafana: {grafana_url}")
    print(f"  Timezone: {tz}")

    with db_session() as s:
        # 1. Check that org exists
        org = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == org_id,
                OrgNode.node_id == org_id,
            )
        ).scalar_one_or_none()

        if org is None:
            print(f"  Creating organization '{org_id}'...")
            s.add(
                OrgNode(
                    org_id=org_id,
                    node_id=org_id,
                    parent_id=None,
                    node_type=NodeType.org,
                    name="MochaCare",
                )
            )
        else:
            print(f"  Found organization: {org.name}")

        # 2. Create team node
        team = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == org_id,
                OrgNode.node_id == team_node_id,
            )
        ).scalar_one_or_none()

        if team is None:
            print("  Creating team...")
            s.add(
                OrgNode(
                    org_id=org_id,
                    node_id=team_node_id,
                    parent_id=org_id,
                    node_type=NodeType.team,
                    name=team_name,
                )
            )
        else:
            print("  Team already exists, updating config...")

        s.flush()

        # 3. Create/update team configuration
        config_json = {
            "team_name": team_name,
            "description": "SRE monitoring for MochaCare — AI agent infrastructure on Vercel",
            "subscription_status": "active",
            "is_trial": True,
            "trial_expires_at": "2026-04-01T00:00:00Z",
            "routing": {
                "slack_channel_ids": [slack_channel_id],
                "github_repos": [github_repo] if github_repo else [],
                "pagerduty_service_ids": [],
                "services": [],
            },
            "agents": {
                "planner": {
                    "enabled": True,
                    "model": {
                        "name": "anthropic/claude-sonnet-4-20250514",
                        "temperature": 0.3,
                    },
                    "prompt": {
                        "system": MOCHACARE_SRE_PROMPT,
                        "prefix": "",
                        "suffix": "",
                    },
                    "max_turns": 50,
                },
                "investigation": {"enabled": True},
                "coding": {"enabled": False},
                "writeup": {"enabled": False},
            },
        }

        if grafana_url:
            config_json["observability"] = {
                "grafana": {"url": grafana_url},
            }

        team_cfg = s.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == org_id,
                NodeConfiguration.node_id == team_node_id,
            )
        ).scalar_one_or_none()

        if team_cfg is None:
            print("  Creating team configuration...")
            s.add(
                NodeConfiguration(
                    id=f"cfg-{uuid.uuid4().hex[:12]}",
                    org_id=org_id,
                    node_id=team_node_id,
                    node_type="team",
                    config_json=config_json,
                    updated_by="seed_mochacare",
                )
            )
        else:
            print("  Updating existing team configuration...")
            team_cfg.config_json = config_json
            team_cfg.updated_by = "seed_mochacare"

        # 4. Create/update output configuration
        output_cfg = s.execute(
            select(TeamOutputConfig).where(
                TeamOutputConfig.org_id == org_id,
                TeamOutputConfig.team_node_id == team_node_id,
            )
        ).scalar_one_or_none()

        default_destinations = [
            {
                "type": "slack",
                "channel_id": slack_channel_id,
                "channel_name": slack_channel_name,
            }
        ]

        if output_cfg is None:
            print("  Creating output configuration...")
            s.add(
                TeamOutputConfig(
                    org_id=org_id,
                    team_node_id=team_node_id,
                    default_destinations=default_destinations,
                    trigger_overrides={
                        "slack": "reply_in_thread",
                        "api": "use_default",
                        "scheduled": "use_default",
                    },
                )
            )
        else:
            print("  Updating existing output configuration...")
            output_cfg.default_destinations = default_destinations

        # 5. Create scheduled jobs (morning + evening reports)
        import zoneinfo

        job_tz = zoneinfo.ZoneInfo(tz)
        now = datetime.now(job_tz)

        job_defs = [
            {
                "name": "Morning Status Report",
                "schedule": "0 8 * * *",
                "prompt": MORNING_REPORT_PROMPT,
            },
            {
                "name": "Evening Status Report",
                "schedule": "0 20 * * *",
                "prompt": EVENING_REPORT_PROMPT,
            },
        ]

        for job_def in job_defs:
            existing = s.execute(
                select(ScheduledJob).where(
                    ScheduledJob.org_id == org_id,
                    ScheduledJob.team_node_id == team_node_id,
                    ScheduledJob.name == job_def["name"],
                )
            ).scalar_one_or_none()

            cron = croniter(job_def["schedule"], now)
            next_run = cron.get_next(datetime)
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=job_tz)
            next_run = next_run.astimezone(timezone.utc)

            job_config = {
                "prompt": job_def["prompt"],
                "agent_name": "planner",
                "max_turns": 8,
                "output_destinations": [
                    {
                        "type": "slack",
                        "channel_id": slack_channel_id,
                        "channel_name": slack_channel_name,
                        "slack_team_id": os.getenv("MOCHACARE_SLACK_TEAM_ID", ""),
                    }
                ],
            }

            if existing is None:
                print(f"  Creating scheduled job: {job_def['name']}...")
                s.add(
                    ScheduledJob(
                        org_id=org_id,
                        team_node_id=team_node_id,
                        name=job_def["name"],
                        job_type="agent_run",
                        schedule=job_def["schedule"],
                        timezone=tz,
                        enabled=True,
                        config=job_config,
                        next_run_at=next_run,
                        created_by="seed_mochacare",
                    )
                )
            else:
                print(f"  Updating scheduled job: {job_def['name']}...")
                existing.schedule = job_def["schedule"]
                existing.timezone = tz
                existing.config = job_config
                existing.next_run_at = next_run

        s.commit()

    print("\nMochaCare seeding complete!")
    print("\n" + "=" * 60)
    print("SETUP SUMMARY")
    print("=" * 60)
    print(f"\nOrg: {org_id}")
    print(f"Team: {team_node_id}")
    print(f"Slack: {slack_channel_id} ({slack_channel_name})")
    if github_repo:
        print(f"GitHub: {github_repo}")
    if grafana_url:
        print(f"Grafana: {grafana_url}")
    print(f"\nScheduled Reports (timezone: {tz}):")
    print("  Morning: 8:00 AM — covers overnight (8PM-8AM)")
    print("  Evening: 8:00 PM — covers daytime (8AM-8PM)")
    print("\nAgent Config:")
    print("  Model: claude-sonnet-4 (temperature=0.3)")
    print("  Max turns: 20 (reports: 8)")
    print("  Mode: planner + investigation")
    print("\n" + "=" * 60)
    print("\nNext steps:")
    print("  1. Set up Grafana Cloud and configure log drain from Vercel")
    print("  2. Deploy updated config-service and orchestrator")
    print("  3. Verify scheduled jobs appear: GET /api/v1/config/me/scheduled-jobs")
    print(
        "  4. Wait for first report or test with: POST /api/v1/internal/scheduled-jobs/due"
    )


if __name__ == "__main__":
    main()
