# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2025-01-23

### Added

#### New Tool Modules (57 new tools)

- **GitHub (25+ tools)**: Complete GitHub integration for deployment correlation
  - Repository info, commits, compare, time-range search
  - Pull requests: list, get, commits, search
  - Issues: list, get, search
  - Workflows: runs, jobs, logs
  - Deployments: list, status
  - Releases: list, get
  - Code: file contents, search, branches

- **Slack (4 tools)**: Incident communication context
  - `slack_search_messages` - Search messages with Slack operators
  - `slack_get_channel_history` - Channel message history
  - `slack_get_thread_replies` - Thread replies
  - `slack_post_message` - Post incident updates

- **PagerDuty (5 tools)**: Incident lifecycle management
  - `pagerduty_get_incident` - Incident details
  - `pagerduty_get_incident_log_entries` - Incident timeline
  - `pagerduty_list_incidents` - List with filters
  - `pagerduty_get_escalation_policy` - Escalation details
  - `pagerduty_calculate_mttr` - Mean Time To Resolve metrics

- **Grafana (6 tools)**: Dashboard-driven investigation
  - `grafana_list_dashboards` - Find dashboards
  - `grafana_get_dashboard` - Dashboard with panel queries
  - `grafana_query_prometheus` - Query via Grafana datasource
  - `grafana_list_datasources` - Available datasources
  - `grafana_get_annotations` - Deployment/incident markers
  - `grafana_get_alerts` - Alert rules and states

- **Sentry (5 tools)**: Application error correlation
  - `sentry_list_issues` - Error list with counts
  - `sentry_get_issue_details` - Full error context
  - `sentry_list_projects` - Organization projects
  - `sentry_get_project_stats` - Error volume trends
  - `sentry_list_releases` - Release correlation

- **Log Analysis (7 tools)**: Sophisticated multi-backend analysis
  - `log_get_statistics` - Aggregated stats (MANDATORY first step)
  - `log_sample` - Intelligent sampling strategies
  - `log_search_pattern` - Pattern search with context
  - `log_around_timestamp` - Temporal correlation
  - `log_correlate_events` - Error/deployment correlation
  - `log_extract_signatures` - Cluster similar messages
  - `log_detect_anomalies` - Volume anomaly detection
  - Supports: Elasticsearch, Coralogix, Datadog, Splunk, CloudWatch

- **Enhanced Anomaly Detection (5 tools)**: Advanced metric analysis with Prophet
  - `forecast_metric` - Linear regression forecasting with confidence bounds
  - `analyze_metric_distribution` - Percentile analysis, SLO insights, distribution shape
  - `prophet_detect_anomalies` - Seasonality-aware anomaly detection
  - `prophet_forecast` - Forecasting with uncertainty bounds
  - `prophet_decompose` - Trend/seasonality/residual decomposition

#### Configuration Enhancements

- Added config status for all new integrations
- Updated `save_credential` with all new credential keys
- Auto-detection for log backends in log_analysis tools

### Changed

- Total tool count increased from 50+ to 85+
- Updated README with comprehensive tool documentation
- Updated Architecture section with new tool modules

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
