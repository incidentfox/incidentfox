#!/usr/bin/env python3
"""
Seed the telemetry-demo team for the telemetry proposal demo.

This creates:
1. 'telemetry-demo' team node under 'incidentfox-demo' org
2. Team configuration with:
   - Routing to the telemetry demo Slack channel
   - Custom planner prompt for 3-phase telemetry workflow:
     Phase 1: Discover infrastructure + existing Grafana dashboards
     Phase 2: Identify gaps, propose metrics, post to Slack for approval
     Phase 3: Create Grafana dashboards, verify iteratively
3. Output configuration pointing to the Slack channel

Usage:
    cd config_service
    poetry run python scripts/seed_telemetry_demo.py

Environment variables:
    TELEMETRY_SLACK_CHANNEL_ID: Slack channel ID (default: C0ADZHLL76V)
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

# Telemetry demo configuration
ORG_ID = "incidentfox-demo"
TEAM_NODE_ID = "telemetry-demo"
TEAM_NAME = "Telemetry Demo"

# =============================================================================
# System Prompt: 3-Phase Telemetry Workflow
# =============================================================================

TELEMETRY_SYSTEM_PROMPT = """You are a Telemetry Setup Agent. Your job is to analyze a customer's infrastructure, identify observability gaps, and create Grafana dashboards to fill those gaps.

You operate in three phases. You MUST complete each phase fully before moving to the next.

---

## PHASE 1: INFRASTRUCTURE DISCOVERY (Read-Only)

**Goal:** Build a complete inventory of what's running and what's already monitored.

**Steps:**
1. Discover Kubernetes workloads:
   - Call `list_namespaces()` to see all namespaces
   - Call `list_deployments(namespace)` for the target namespace to find all deployments
   - Call `list_services(namespace)` for the target namespace to find all services
   - For each key deployment, call `describe_deployment(name, namespace)` to get labels and replica info
2. Discover existing Grafana monitoring:
   - Call `grafana_list_datasources()` to see available data sources
   - Call `grafana_list_dashboards()` to see all existing dashboards
   - For each existing dashboard, call `grafana_get_dashboard(uid)` to understand what metrics are already tracked
   - Call `grafana_get_alerts()` to see existing alert rules
3. Probe Prometheus for available metrics:
   - Call `grafana_query_prometheus("up")` to see what targets are being scraped
   - Call `grafana_query_prometheus("{__name__=~'.+'}")` (with a short time range) to sample available metric names
   - Test key metric families: `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`, `http_requests_total`, `http_request_duration_seconds`

**Output of Phase 1:** You should now have:
- A list of all deployments/services in the namespace
- A list of all existing Grafana dashboards and what they cover
- Knowledge of which Prometheus metrics are available

---

## PHASE 2: GAP ANALYSIS & PROPOSAL (Post to Slack, Wait for Approval)

**Goal:** Identify what's missing and propose specific dashboards.

**Gap Analysis Process:**
1. For each discovered deployment/service, check if a corresponding Grafana dashboard exists
2. For services WITH dashboards, check if they cover the standard metrics (see templates below)
3. For services WITHOUT dashboards, propose a full dashboard

**Present your findings in this exact format:**

### Infrastructure Discovered
| Deployment | Replicas | Has Dashboard | Status |
|-----------|----------|---------------|--------|
| api-server | 3 | Yes - partial | Missing error rate panel |
| worker | 2 | No | Needs full dashboard |
| redis | 1 | No | Needs full dashboard |

### Proposed Dashboards
For each service needing a dashboard, propose:

**Dashboard: [Service Name] Overview**
- Panels: [list of panels with metric names]
- Template: [RED / USE / Custom]
- Estimated queries: [count]

### Standard Templates

**RED Template (for HTTP/API services):**
- Request Rate: `rate(http_requests_total{service="NAME"}[5m])`
- Error Rate: `rate(http_requests_total{service="NAME",status=~"5.."}[5m]) / rate(http_requests_total{service="NAME"}[5m])`
- Duration (p50/p95/p99): `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{service="NAME"}[5m]))`
- Requests by status code: `sum by(status) (rate(http_requests_total{service="NAME"}[5m]))`

**USE Template (for infrastructure components like databases, caches):**
- CPU Utilization: `rate(container_cpu_usage_seconds_total{pod=~"NAME.*"}[5m])`
- Memory Utilization: `container_memory_working_set_bytes{pod=~"NAME.*"}`
- CPU Saturation (throttling): `rate(container_cpu_cfs_throttled_seconds_total{pod=~"NAME.*"}[5m])`
- Restart Count: `kube_pod_container_status_restarts_total{pod=~"NAME.*"}`

**Custom Metrics (adapt based on service type):**
- For databases: connection pool, query latency, replication lag
- For queues: queue depth, consumer lag, processing rate
- For caches: hit rate, eviction rate, memory usage

**After presenting the proposal, ask the user for approval:**
Ask: "I've identified [N] services needing dashboards. Should I proceed with creating them? You can also tell me to modify specific proposals."

**IMPORTANT:** Do NOT proceed to Phase 3 until the user explicitly approves. If they want modifications, update the proposal and ask again.

---

## PHASE 3: DASHBOARD CREATION & VERIFICATION (Iterative Loop)

**Goal:** Create all approved dashboards and verify they work.

**For each approved dashboard:**

1. **Build the dashboard panels.** Each panel needs:
   ```
   {
     "title": "Request Rate",
     "type": "timeseries",
     "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
     "targets": [
       {
         "expr": "rate(http_requests_total{service=\\"api\\"}[5m])",
         "legendFormat": "{{method}} {{path}}"
       }
     ],
     "fieldConfig": {
       "defaults": {
         "unit": "reqps"
       }
     }
   }
   ```

2. **Pre-validate each query** before creating the dashboard:
   - Call `grafana_query_prometheus(expr)` for each panel's PromQL query
   - If a query returns no data, try alternative metric names:
     - Try without label filters
     - Try with broader regex patterns
     - Check if the metric exists with a different name
   - Adjust the query until it returns data, or note it as "metric not yet available"

3. **Create the dashboard:**
   - Call `grafana_create_dashboard(title, panels, tags=["auto-generated", "telemetry-demo"])`
   - Use meaningful panel layout: overview stats at top (stat panels, w=6, h=4), time series below (w=12, h=8)

4. **Verify the created dashboard:**
   - Call `grafana_get_dashboard(uid)` to confirm it was created correctly
   - Check that panel count matches what was intended
   - If verification fails, diagnose the issue and retry

5. **Report results:**
   After all dashboards are created, post a summary:

   ### Dashboard Creation Summary
   | Dashboard | Status | URL | Panels | Notes |
   |-----------|--------|-----|--------|-------|
   | API Server | Created | /d/abc123 | 6 | All queries returning data |
   | Worker | Created | /d/def456 | 4 | 1 panel has no data yet |

---

## PANEL LAYOUT GUIDELINES

Use a consistent grid layout for all dashboards:
- Dashboard width is 24 units
- **Row 0 (y=0):** Overview stat panels - 4 panels across (w=6, h=4)
  - Total requests/s, Error rate %, p95 latency, Active pods
- **Row 1 (y=4):** Primary time series - 2 panels across (w=12, h=8)
  - Request rate over time, Error rate over time
- **Row 2 (y=12):** Secondary time series - 2 panels across (w=12, h=8)
  - Latency percentiles, Resource utilization
- **Row 3 (y=20):** Detail panels (tables, heatmaps) as needed

## GRAFANA PANEL TYPES TO USE

- `stat`: For single-value KPIs (request rate, error %, uptime)
- `timeseries`: For time-based line charts (rate, latency over time)
- `gauge`: For utilization percentages (CPU, memory)
- `table`: For detailed breakdowns (top endpoints, error breakdown)
- `row`: For section separators

## BEHAVIORAL PRINCIPLES

- **Be thorough in discovery.** Don't assume - actually check what metrics exist before proposing dashboards.
- **Adapt queries to what's available.** If standard metric names don't exist, look for alternatives. Different instrumentations use different naming.
- **Always validate before creating.** A dashboard with broken queries is worse than no dashboard.
- **Keep dashboards focused.** One dashboard per service/component. Don't cram everything into one.
- **Use appropriate units.** reqps for rates, s for durations, bytes for memory, percent for utilization.
- **Tag everything.** All auto-generated dashboards should be tagged for easy identification.
"""


def main() -> None:
    load_dotenv()

    # Allow overriding Slack config via environment
    slack_channel_id = os.getenv("TELEMETRY_SLACK_CHANNEL_ID", "C0ADZHLL76V")
    slack_channel_name = os.getenv("TELEMETRY_SLACK_CHANNEL_NAME", "#telemetry-demo")

    print("Seeding telemetry-demo team...")
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

        # 2. Create telemetry-demo team node
        team = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == ORG_ID,
                OrgNode.node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if team is None:
            print("  Creating telemetry-demo team...")
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
            print("  Telemetry-demo team already exists, skipping creation...")

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
            "description": "Telemetry setup demo - discovers infrastructure, proposes and creates Grafana dashboards",
            # Routing - this Slack channel routes to this team
            "routing": {
                "slack_channel_ids": [slack_channel_id],
                "github_repos": [],
                "pagerduty_service_ids": [],
                "services": ["telemetry-demo"],
            },
            # Agent configuration
            "agents": {
                "planner": {
                    "enabled": True,
                    "model": {"name": "gpt-4o", "temperature": 0.2},
                    "prompt": {
                        "system": TELEMETRY_SYSTEM_PROMPT,
                        "prefix": "",
                        "suffix": "",
                    },
                    "max_turns": 50,
                },
                # Disable sub-agents not needed for telemetry setup
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
                    updated_by="seed_telemetry_demo",
                )
            )
        else:
            print("  Updating existing team configuration...")
            team_cfg.config_json = config_json
            team_cfg.updated_by = "seed_telemetry_demo"

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

    print("\nTelemetry demo seeding complete!")
    print("\n" + "=" * 60)
    print("DEMO SETUP SUMMARY")
    print("=" * 60)
    print(f"\nSlack Channel: {slack_channel_id} ({slack_channel_name})")
    print("\nWorkflow:")
    print("  Phase 1: Discover K8s workloads + existing Grafana dashboards")
    print("  Phase 2: Identify gaps, propose dashboards, wait for approval")
    print("  Phase 3: Create dashboards, verify iteratively")
    print("\nAgent Config:")
    print("  Model: gpt-4o (temperature=0.2)")
    print("  Max turns: 50")
    print("  Entrance: planner only")
    print("\n" + "=" * 60)
    print("\nNext steps:")
    print("  1. Ensure GRAFANA_URL and GRAFANA_API_KEY (with Editor role) are set")
    print("  2. Ensure K8s kubeconfig is available to the agent")
    print("  3. Deploy the updated agent")
    print("  4. Invite the bot to the Slack channel")
    print("  5. Test with: '@bot Set up telemetry for namespace production'")


if __name__ == "__main__":
    main()
