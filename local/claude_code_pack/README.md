# IncidentFox for Claude Code

**Claude Code plugin with ~100 DevOps & SRE tools, skills, and commands** to investigate incidents, analyze costs, and debug CI/CD — all from your terminal.

<p align="center">
  <video src="https://github.com/user-attachments/assets/52d86ad1-6dc9-45e5-b80c-5f8a96b3dccd" width="700" controls autoplay loop muted></video>
</p>

## What You Can Do

| Use Case | Example Prompt |
|----------|----------------|
| **Check Infrastructure** | "Check my Kubernetes cluster health" |
| **Alert Triage** | "Help me investigate this alert: [paste]" |
| **AWS Cost Optimization** | "Analyze my AWS costs and find savings" |
| **CI/CD Debugging** | "Why did my GitHub workflow fail?" |
| **Incident Investigation** | "What's causing high latency in payments?" |
| **Log Analysis** | "Search Datadog logs for errors in the last hour" |

## Quick Start

### 1. Install (2 minutes)

```bash
git clone https://github.com/incidentfox/incidentfox.git
cd incidentfox/local/claude_code_pack
./install.sh
```

### 2. Try It

**Option A: MCP Tools Only**
```bash
claude
```
Gives you ~100 MCP tools for querying infrastructure, logs, metrics, etc.

**Option B: Full Plugin (Recommended)**
```bash
claude --plugin-dir /path/to/incidentfox/local/claude_code_pack
```
Gives you everything in Option A, plus:
- `/incident` — Start a structured investigation
- `/metrics` — Query metrics from configured sources
- `/remediate` — Propose and execute remediation actions
- 5 expert skills (investigation methodology, K8s debugging, AWS troubleshooting, log analysis, SRE principles)

---

**Quick start** — explore your infrastructure (try whichever applies):
```
> Check my Kubernetes cluster health
> Show my Grafana dashboards
```

**Real work** — use these tools for actual tasks:
```
> Help me triage this alert: [paste alert]
> Find AWS costs over the last month and explore reduction opportunities
> Why did my GitHub Actions workflow fail? [paste url]
```

### 3. Configure Integrations

Tools auto-detect what's available. Missing credentials? Add them on-the-fly:

```
> Search Datadog logs for errors

Claude: I need your Datadog API key to search logs.

> Here's my API key: dd-api-xxxxx

Claude: Saved. Now searching...
```

Or check what's configured:
```
> What integrations are configured?
```

## Installation Details

The install script will:
1. Check prerequisites ([uv](https://github.com/astral-sh/uv) and Claude Code CLI)
2. Install Python dependencies
3. Add the MCP server to Claude Code globally
4. Verify the installation works

### Verify Installation

```bash
claude mcp list
# Should show: incidentfox: ... ✓ Connected
```

### (Optional) Create a service catalog

```bash
cat > .incidentfox.yaml << 'EOF'
services:
  api-gateway:
    namespace: production
    deployments: [api-gateway]
    dependencies: [auth-service, user-service, postgres]
    logs:
      datadog: "service:api-gateway"

known_issues:
  - pattern: "connection refused.*postgres"
    cause: "Database connection pool exhausted"
    solution: "Scale postgres replicas or increase pool size"
EOF
```

### Manual Installation

<details>
<summary>Click to expand manual installation steps</summary>

If you prefer to install manually instead of using `./install.sh`:

```bash
# 1. Clone and enter the directory
git clone https://github.com/incidentfox/incidentfox.git
cd incidentfox/local/claude_code_pack

# 2. Install Python dependencies
cd mcp-servers/incidentfox
uv sync
cd ../..

# 3. Add MCP server to Claude Code
claude mcp add-json incidentfox "$(cat <<EOF
{
  "command": "uv",
  "args": ["--directory", "$(pwd)/mcp-servers/incidentfox", "run", "incidentfox-mcp"],
  "env": {
    "KUBECONFIG": "\${KUBECONFIG:-~/.kube/config}",
    "AWS_REGION": "\${AWS_REGION:-us-east-1}",
    "DATADOG_API_KEY": "\${DATADOG_API_KEY}",
    "DATADOG_APP_KEY": "\${DATADOG_APP_KEY}"
  }
}
EOF
)" -s user

# 4. Verify
claude mcp list
```

</details>

## Configuration

IncidentFox supports two ways to configure credentials:

### Option 1: Environment Variables (Traditional)

Set environment variables before starting Claude:

```bash
# Kubernetes (usually auto-detected)
export KUBECONFIG=~/.kube/config

# AWS
export AWS_REGION=us-east-1

# Datadog
export DATADOG_API_KEY=your-api-key
export DATADOG_APP_KEY=your-app-key

# Prometheus/Alertmanager
export PROMETHEUS_URL=http://prometheus:9090
export ALERTMANAGER_URL=http://alertmanager:9093

# Elasticsearch (optional)
export ELASTICSEARCH_URL=http://elasticsearch:9200

# Loki (optional)
export LOKI_URL=http://loki:3100

# GitHub
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
export GITHUB_REPOSITORY=owner/repo  # optional default

# Slack
export SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxx
export SLACK_DEFAULT_CHANNEL=C01234ABCDE  # optional

# PagerDuty
export PAGERDUTY_API_KEY=your-pagerduty-api-key

# Grafana
export GRAFANA_URL=http://grafana:3000
export GRAFANA_API_KEY=your-grafana-api-key

# Sentry
export SENTRY_AUTH_TOKEN=your-sentry-auth-token
export SENTRY_ORGANIZATION=your-org-slug
export SENTRY_PROJECT=your-project-slug  # optional

# Coralogix
export CORALOGIX_API_KEY=your-coralogix-api-key
export CORALOGIX_REGION=cx498  # optional, default: cx498

# Splunk
export SPLUNK_HOST=splunk.example.com
export SPLUNK_TOKEN=your-splunk-token
export SPLUNK_PORT=8089  # optional, default: 8089
```

### Option 2: On-the-fly Configuration (Recommended)

Configure credentials interactively during your session. When a tool needs credentials, Claude will ask for them and save them automatically.

```
You: Search Datadog logs for errors

Claude: I need your Datadog API key. What is it?

You: dd-api-abc123xyz

Claude: Got it. And the app key?

You: dd-app-xyz789abc

Claude: Credentials saved. Searching logs...
        Found 47 error events in the last hour.
```

Credentials are saved to `~/.incidentfox/.env` and persist across sessions.

**Configuration Tools:**

| Tool | Description |
|------|-------------|
| `get_config_status` | Check which integrations are configured |
| `save_credential` | Save a credential for future use |
| `delete_credential` | Remove a saved credential |

**Check your configuration:**
```
> What integrations are configured?

Kubernetes: ✓ configured (using ~/.kube/config)
AWS: ✓ configured (region: us-west-2)
Datadog: ✗ not configured (missing DATADOG_API_KEY, DATADOG_APP_KEY)
Prometheus: ✗ not configured (missing PROMETHEUS_URL)
```

## Service Catalog (.incidentfox.yaml)

Create a `.incidentfox.yaml` in your project root to personalize investigations:

```yaml
services:
  payment-api:
    namespace: production
    deployments: [payment-api, payment-worker]
    dependencies: [postgres, redis, stripe-api]
    logs:
      datadog: "service:payment-api"
      cloudwatch: "/aws/eks/payment-api"
    dashboards:
      grafana: "https://grafana.example.com/d/abc123"
    runbooks:
      high-latency: "./runbooks/payment-latency.md"
      oom-killed: "./runbooks/oom-debug.md"
    oncall:
      slack: "#payment-oncall"
      pagerduty: "PABC123"

alerts:
  payment-high-latency:
    service: payment-api
    severity: P2
    runbook: high-latency

known_issues:
  - pattern: "ConnectionResetError.*redis"
    cause: "Redis connection pool exhaustion"
    solution: "Scale redis replicas or increase pool size"
    services: [payment-api, cart-service]
```

## Tools Reference

### Configuration (3 tools)
| Tool | Description |
|------|-------------|
| `get_config_status` | Check which integrations are configured |
| `save_credential` | Save a credential to persistent storage |
| `delete_credential` | Remove a saved credential |

### Kubernetes (7 tools)
| Tool | Description |
|------|-------------|
| `list_pods` | List pods with status in a namespace |
| `get_pod_logs` | Get logs from a pod |
| `get_pod_events` | Get events for a pod (check before logs!) |
| `describe_pod` | Detailed pod information |
| `describe_deployment` | Deployment status and conditions |
| `get_deployment_history` | Rollout history for rollback decisions |
| `get_pod_resources` | Resource allocation vs actual usage |

### AWS (5 tools)
| Tool | Description |
|------|-------------|
| `describe_ec2_instance` | EC2 instance status and details |
| `get_cloudwatch_logs` | CloudWatch log retrieval |
| `query_cloudwatch_insights` | Advanced log queries with aggregation |
| `get_cloudwatch_metrics` | CloudWatch metrics (CPU, memory, etc.) |
| `list_ecs_tasks` | ECS/Fargate task status |

### Datadog (3 tools)
| Tool | Description |
|------|-------------|
| `query_datadog_metrics` | Query Datadog metrics |
| `search_datadog_logs` | Search Datadog logs |
| `get_service_apm_metrics` | APM metrics (request rate, latency, errors) |

### Prometheus (4 tools)
| Tool | Description |
|------|-------------|
| `query_prometheus` | Execute PromQL range queries |
| `prometheus_instant_query` | Execute instant PromQL queries |
| `get_prometheus_alerts` | Get firing alerts from Prometheus |
| `get_alertmanager_alerts` | Get alerts from Alertmanager |

### Unified Logs (2 tools)
| Tool | Description |
|------|-------------|
| `search_logs` | Search across all configured log backends |
| `get_log_backends` | List configured log backends |

### Active Alerts (1 tool)
| Tool | Description |
|------|-------------|
| `get_active_alerts` | Aggregate alerts from Prometheus, Alertmanager, Datadog |

### Anomaly Detection (8 tools)
| Tool | Description |
|------|-------------|
| `detect_anomalies` | Z-score based anomaly detection |
| `correlate_metrics` | Find correlation between two metrics |
| `find_change_point` | Detect when behavior changed |
| `forecast_metric` | Linear regression forecasting with confidence bounds |
| `analyze_metric_distribution` | Percentile analysis (p50/p90/p95/p99), SLO insights |
| `prophet_detect_anomalies` | Seasonality-aware anomaly detection (requires Prophet) |
| `prophet_forecast` | Forecasting with uncertainty bounds (requires Prophet) |
| `prophet_decompose` | Trend/seasonality/residual decomposition (requires Prophet) |

### Git (6 tools)
| Tool | Description |
|------|-------------|
| `git_log` | Recent commit history |
| `git_diff` | Show changes between commits |
| `git_show` | Show specific commit details |
| `git_blame` | Show who changed each line |
| `correlate_with_deployment` | Find commits around incident time |
| `git_recent_changes` | Files changed in recent period |

### GitHub (25+ tools)
| Tool | Description |
|------|-------------|
| `github_get_repo` | Repository info and statistics |
| `github_list_commits` | List recent commits |
| `github_get_commit` | Get commit details with diff |
| `github_compare_commits` | Compare branches/commits |
| `github_search_commits_by_timerange` | Find commits in time window |
| `github_list_prs` | List pull requests |
| `github_get_pr` | Get PR details with comments |
| `github_list_pr_commits` | Commits in a PR |
| `github_search_prs` | Search PRs by query |
| `github_list_issues` | List repository issues |
| `github_get_issue` | Get issue details |
| `github_search_issues` | Search issues by query |
| `github_list_workflow_runs` | List GitHub Actions runs |
| `github_get_workflow_run` | Get workflow run details |
| `github_list_workflow_jobs` | Jobs in a workflow run |
| `github_get_workflow_logs` | Download workflow logs |
| `github_list_deployments` | List deployments |
| `github_get_deployment_status` | Get deployment status |
| `github_list_releases` | List releases |
| `github_get_release` | Get release details |
| `github_get_file_contents` | Read file from repo |
| `github_search_code` | Search code in repository |
| `github_list_branches` | List branches |
| `github_get_branch` | Get branch protection info |
| `github_correlate_deployment_with_incident` | Find deployments around incident time |

### Slack (4 tools)
| Tool | Description |
|------|-------------|
| `slack_search_messages` | Search messages for incident context |
| `slack_get_channel_history` | Get channel message history |
| `slack_get_thread_replies` | Get thread replies |
| `slack_post_message` | Post updates during incidents |

### PagerDuty (5 tools)
| Tool | Description |
|------|-------------|
| `pagerduty_get_incident` | Get incident details |
| `pagerduty_get_incident_log_entries` | Incident timeline/log entries |
| `pagerduty_list_incidents` | List incidents with filters |
| `pagerduty_get_escalation_policy` | Escalation policy details |
| `pagerduty_calculate_mttr` | Calculate Mean Time To Resolve |

### Grafana (6 tools)
| Tool | Description |
|------|-------------|
| `grafana_list_dashboards` | List available dashboards |
| `grafana_get_dashboard` | Get dashboard with panel queries |
| `grafana_query_prometheus` | Query Prometheus via Grafana |
| `grafana_list_datasources` | List configured datasources |
| `grafana_get_annotations` | Get deployment/incident annotations |
| `grafana_get_alerts` | Get Grafana alert rules and states |

### Sentry (5 tools)
| Tool | Description |
|------|-------------|
| `sentry_list_issues` | List issues/errors in a project |
| `sentry_get_issue_details` | Detailed issue info and tags |
| `sentry_list_projects` | List organization projects |
| `sentry_get_project_stats` | Error volume statistics |
| `sentry_list_releases` | List releases for correlation |

### Log Analysis (7 tools - Multi-backend)
| Tool | Description |
|------|-------------|
| `log_get_statistics` | Get aggregated stats (CALL FIRST!) |
| `log_sample` | Intelligent log sampling |
| `log_search_pattern` | Search for specific patterns |
| `log_around_timestamp` | Get logs around an event |
| `log_correlate_events` | Correlate errors with deployments/restarts |
| `log_extract_signatures` | Cluster similar log messages |
| `log_detect_anomalies` | Detect volume anomalies |

Supported backends: Elasticsearch, Coralogix, Datadog, Splunk, CloudWatch (auto-detected)

### Docker (7 tools)
| Tool | Description |
|------|-------------|
| `docker_ps` | List containers |
| `docker_logs` | Get container logs |
| `docker_inspect` | Container details (state, config, network) |
| `docker_stats` | Resource usage statistics |
| `docker_top` | List processes in container |
| `docker_events` | Recent Docker events |
| `docker_diff` | Filesystem changes in container |

### Investigation History (8 tools)
| Tool | Description |
|------|-------------|
| `start_investigation` | Start tracking an investigation |
| `add_finding` | Add a finding to investigation |
| `complete_investigation` | Complete with root cause/resolution |
| `get_investigation` | Get investigation details |
| `search_investigations` | Search past investigations |
| `find_similar_investigations` | Find similar past incidents |
| `record_pattern` | Record a known issue pattern |
| `get_statistics` | Get investigation statistics |

### Postmortem (3 tools)
| Tool | Description |
|------|-------------|
| `generate_postmortem` | Generate structured postmortem |
| `create_timeline_event` | Create timeline event |
| `export_postmortem` | Export to file |

### Blast Radius (3 tools)
| Tool | Description |
|------|-------------|
| `get_blast_radius` | Estimate impact of service failure |
| `get_service_dependencies` | Get upstream dependencies |
| `get_dependency_graph` | Full service dependency graph |

### Cost Analysis (4 tools)
| Tool | Description |
|------|-------------|
| `get_cost_summary` | AWS cost breakdown by service |
| `get_cost_anomalies` | Detect spending anomalies |
| `get_ec2_rightsizing` | Instance rightsizing recommendations |
| `get_daily_cost_trend` | Daily cost trend |

### Remediation (3 tools with dry-run)
| Tool | Description |
|------|-------------|
| `propose_pod_restart` | Restart a specific pod |
| `propose_deployment_restart` | Rolling restart of a deployment |
| `propose_scale_deployment` | Scale deployment replicas |

All remediation tools support `dry_run=True` to preview without executing.

### Service Catalog (3 tools)
| Tool | Description |
|------|-------------|
| `get_service_info` | Get service details from catalog |
| `check_known_issues` | Match error against known issues |
| `get_runbook` | Get runbook contents |
| `search_runbooks` | Search runbooks by keyword |

## Skills

| Skill | Description | Triggers |
|-------|-------------|----------|
| `investigate` | 5-phase systematic investigation methodology | "investigate", "debug", "incident" |
| `k8s-debug` | Kubernetes debugging patterns (events before logs) | "pod", "deployment", "CrashLoopBackOff" |
| `aws-troubleshoot` | AWS service troubleshooting patterns | "EC2", "Lambda", "CloudWatch" |
| `log-analysis` | Partition-first log analysis methodology | "logs", "errors", "search" |
| `sre-principles` | Evidence-based reasoning and communication | Always active during investigations |

## Example Usage

### Start an Investigation
```
> /incident Payment API returning 500 errors

I'll start by tracking this investigation and gathering evidence...

[start_investigation called]
[get_active_alerts called - found 2 firing alerts]
[search_logs called - found error spike at 14:32]
[get_pod_events called - found OOMKilled events]
```

### Check Service Dependencies
```
> What's the blast radius if postgres goes down?

[get_blast_radius called]

The postgres service has HIGH blast radius:
- Direct dependents: payment-api, user-service, order-service
- Transitive impact: checkout-flow, mobile-app, admin-dashboard
- Total affected: 6 services

Recommendation: Ensure postgres has proper failover configured.
```

### Generate a Postmortem
```
> /postmortem

[generate_postmortem called with investigation data]

# Incident Postmortem: Payment API 500 Errors

**Date:** 2024-01-22
**Severity:** P2
**Service:** payment-api

## Summary
Memory leak in cart serialization caused OOMKilled restarts.

## Timeline
| Time | Event |
|------|-------|
| 14:30 | Deployment v1.2.3 completed |
| 14:32 | Error rate increased |
| 14:35 | OOMKilled events began |
...
```

### Dry-Run Remediation
```
> Restart the payment-api deployment (dry run first)

[propose_deployment_restart called with dry_run=True]

DRY RUN - Would execute:
  kubectl rollout restart deployment/payment-api -n production

Effect: All 5 pods will be restarted in a rolling fashion
Current ready replicas: 5/5

Proceed with actual restart? (call without dry_run=True)
```

## Local Development

```bash
# Install dependencies
cd mcp-servers/incidentfox
uv sync

# Run the server
uv run incidentfox-mcp

# Test imports
uv run python -c "from incidentfox_mcp.server import mcp; print(mcp.name)"
```

## Architecture

```
claude_code_pack/
├── .claude-plugin/plugin.json   # Plugin manifest
├── skills/                       # On-demand expertise injection
│   ├── investigate/             # 5-phase methodology
│   ├── k8s-debug/               # K8s patterns
│   ├── aws-troubleshoot/        # AWS patterns
│   ├── log-analysis/            # Partition-first logs
│   └── sre-principles/          # Evidence-based reasoning
├── commands/                     # Slash commands
├── hooks/                        # Remediation safety
└── mcp-servers/incidentfox/     # Python MCP server (85+ tools)
    └── src/incidentfox_mcp/
        ├── server.py            # FastMCP entry point
        ├── tools/               # Tool implementations
        │   ├── kubernetes.py    # K8s pod/deployment tools
        │   ├── aws.py           # EC2, CloudWatch, ECS
        │   ├── datadog.py       # Metrics, logs, APM
        │   ├── prometheus.py    # PromQL queries, alerts
        │   ├── github.py        # Repos, PRs, workflows, deployments
        │   ├── slack.py         # Message search, channel history
        │   ├── pagerduty.py     # Incidents, escalation, MTTR
        │   ├── grafana.py       # Dashboards, annotations, alerts
        │   ├── sentry.py        # Error tracking, releases
        │   ├── log_analysis.py  # Multi-backend log analysis
        │   └── ...              # And more
        └── resources/           # Service catalog, runbooks
```

## Data Storage

Investigation history is stored locally:
```
~/.incidentfox/
├── history.db          # SQLite: investigations, findings, patterns
├── config.yaml         # User preferences (optional)
└── logs/
    └── remediation.log # Audit log for remediation actions
```

## Auto-Approve MCP Tools (Skip Permission Prompts)

By default, Claude Code asks for permission each time an MCP tool is used. You can pre-approve IncidentFox tools to skip these prompts.

### Option 1: Command Line Flag

```bash
claude --allowedTools "mcp__incidentfox__*"
```

This allows all IncidentFox tools for the session. You can be more specific:

```bash
# Allow only read-only tools
claude --allowedTools "mcp__incidentfox__list_pods,mcp__incidentfox__get_pod_logs,mcp__incidentfox__search_logs"
```

### Option 2: Settings File (Persistent)

Add to your Claude Code settings (`~/.claude/settings.json` or project `.claude/settings.json`):

```json
{
  "permissions": {
    "allow": [
      "mcp__incidentfox__*"
    ]
  }
}
```

Or allow specific tool categories:

```json
{
  "permissions": {
    "allow": [
      "mcp__incidentfox__list_*",
      "mcp__incidentfox__get_*",
      "mcp__incidentfox__search_*",
      "mcp__incidentfox__describe_*",
      "mcp__incidentfox__query_*"
    ],
    "deny": [
      "mcp__incidentfox__propose_*"
    ]
  }
}
```

### Option 3: Trust for Current Project

When Claude asks for permission, select "Always allow for this project" to auto-approve that specific tool going forward.

> **Note:** Remediation tools (`propose_pod_restart`, `propose_deployment_restart`, `propose_scale_deployment`) have additional confirmation hooks that run even with auto-approval enabled. This ensures you always confirm before making changes to your infrastructure.

## Security

- All remediation actions require confirmation via hooks
- Dry-run mode available for all remediation tools
- Read-only git access (no commits)
- Credentials via environment variables (not stored in plugin)
- Audit logs for all remediation actions
- No data sent to external services (except configured integrations)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new tools
4. Submit a pull request

## License

MIT

## Support

- Issues: https://github.com/incidentfox/claude-code-pack/issues
- Documentation: https://docs.incidentfox.ai
- Full product: https://incidentfox.ai
