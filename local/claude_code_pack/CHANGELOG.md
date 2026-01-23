# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2024-01-22

### Added

#### MCP Server with 50+ Tools
- **Kubernetes (7 tools)**: `list_pods`, `get_pod_logs`, `get_pod_events`, `describe_pod`, `describe_deployment`, `get_deployment_history`, `get_pod_resources`
- **AWS (5 tools)**: `describe_ec2_instance`, `get_cloudwatch_logs`, `query_cloudwatch_insights`, `get_cloudwatch_metrics`, `list_ecs_tasks`
- **Datadog (3 tools)**: `query_datadog_metrics`, `search_datadog_logs`, `get_service_apm_metrics`
- **Prometheus (4 tools)**: `query_prometheus`, `prometheus_instant_query`, `get_prometheus_alerts`, `get_alertmanager_alerts`
- **Unified Logs (2 tools)**: `search_logs`, `get_log_backends` - search across Datadog, CloudWatch, Elasticsearch, Loki
- **Active Alerts (1 tool)**: `get_active_alerts` - aggregate from all alert sources
- **Anomaly Detection (3 tools)**: `detect_anomalies`, `correlate_metrics`, `find_change_point`
- **Git (6 tools)**: `git_log`, `git_diff`, `git_show`, `git_blame`, `correlate_with_deployment`, `git_recent_changes`
- **Docker (7 tools)**: `docker_ps`, `docker_logs`, `docker_inspect`, `docker_stats`, `docker_top`, `docker_events`, `docker_diff`
- **Investigation History (8 tools)**: `start_investigation`, `add_finding`, `complete_investigation`, `get_investigation`, `search_investigations`, `find_similar_investigations`, `record_pattern`, `get_statistics`
- **Postmortem (3 tools)**: `generate_postmortem`, `create_timeline_event`, `export_postmortem`
- **Blast Radius (3 tools)**: `get_blast_radius`, `get_service_dependencies`, `get_dependency_graph`
- **Cost Analysis (4 tools)**: `get_cost_summary`, `get_cost_anomalies`, `get_ec2_rightsizing`, `get_daily_cost_trend`
- **Remediation (3 tools)**: `propose_pod_restart`, `propose_deployment_restart`, `propose_scale_deployment` - all with dry-run support

#### Skills (5)
- `investigate` - 5-phase systematic investigation methodology
- `k8s-debug` - Kubernetes debugging patterns (events before logs)
- `aws-troubleshoot` - AWS service troubleshooting patterns
- `log-analysis` - Partition-first log analysis methodology
- `sre-principles` - Evidence-based reasoning and communication

#### Commands (3)
- `/incident` - Start a structured investigation
- `/metrics` - Query metrics from configured sources
- `/remediate` - Propose and execute remediation actions

#### Resources
- Service catalog via `.incidentfox.yaml`
- Runbook loading from `runbooks/` directory

#### Safety Features
- Dry-run mode for all remediation tools
- PreToolUse hooks for remediation confirmation
- PostToolUse hooks for audit logging
- Investigation history stored in SQLite (`~/.incidentfox/history.db`)

### Security
- All credentials via environment variables
- Read-only git access
- No automatic commits or pushes
- Remediation requires explicit confirmation
