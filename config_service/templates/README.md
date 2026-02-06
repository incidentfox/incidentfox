# IncidentFox Template Library

This directory contains all production-ready templates for the IncidentFox AI SRE platform.

## Overview

Templates are pre-configured multi-agent systems optimized for specific use cases. Each template includes:
- Agent topology (which agents, how they delegate)
- Specialized prompts for the use case
- Curated tool selection
- MCP/integration requirements
- Runtime configurations

## Available Templates

### 1. 🚨 Slack Incident Triage
**File**: `01_slack_incident_triage.json`
**Category**: incident-response
**Agents**: Planner, Investigation, K8s, AWS, Metrics

Fast root cause analysis for production incidents triggered via Slack. Correlates logs, metrics, and events across Kubernetes and AWS infrastructure.

**Required MCPs**: kubernetes, slack
**Optional MCPs**: grafana, datadog, aws_eks

**Use Cases**:
- Pod crash loops and OOMKilled errors
- API latency spikes after deployments
- Database connection exhaustion
- Service degradation

---

### 2. 🔧 Git CI Auto-Fix
**File**: `02_git_ci_auto_fix.json`
**Category**: ci-cd
**Agents**: Planner, CI, Coding

Analyzes GitHub Actions and CodePipeline failures, identifies root causes, and can automatically commit fixes for common issues (formatting, imports, simple errors).

**Required MCPs**: github_app, git
**Optional MCPs**: codepipeline, docker

**Use Cases**:
- Jest/Cypress test failures
- Docker build errors
- ESLint/formatting issues
- Dependency conflicts
- Flaky test detection

---

### 3. 💰 AWS Cost Reduction
**File**: `03_aws_cost_reduction.json`
**Category**: finops
**Agents**: Planner, Cost Analyzer, AWS

FinOps agent that analyzes AWS spend, identifies waste (idle resources, oversized instances), and recommends optimization opportunities with $ impact calculations.

**Required MCPs**: aws_eks, slack

**Use Cases**:
- Identify idle EC2 instances (<5% CPU)
- Find oversized RDS databases
- Recommend Reserved Instances
- Clean up old EBS snapshots
- Optimize S3 storage classes

---

### 4. 💻 Coding Assistant
**File**: `04_coding_assistant.json`
**Category**: coding
**Agents**: Coding (single agent)

AI senior software engineer for code reviews, refactoring suggestions, test generation, and documentation. Posts findings as PR comments.

**Required MCPs**: github_app, git

**Use Cases**:
- Code review for bugs and security issues
- Refactor complex functions
- Generate unit tests with edge cases
- Document complex algorithms
- Fix linting issues

---

### 5. 🗄️ Data Migration Assistant
**File**: `05_data_migration.json`
**Category**: data
**Agents**: Planner, Migration Planner, Coding

Plans and executes database migrations with schema analysis, data transformation scripts, validation queries, and rollback procedures.

**Required MCPs**: snowflake, slack
**Optional MCPs**: elasticsearch, postgres

**Use Cases**:
- Postgres → Snowflake migration
- Elasticsearch re-indexing
- Schema version upgrades
- Data backfilling
- Cross-region data sync

---

### 6. 🎉 News Comedian (Demo)
**File**: `06_news_comedian.json`
**Category**: demo
**Agents**: News Comedian (single agent)

Fun demo agent that searches for latest tech news and writes witty jokes about them. Great for team morale and showcasing platform capabilities.

**Required MCPs**: slack

**Use Cases**:
- Daily tech news digest with humor
- Product demos
- Team morale booster
- Showcase multi-tool coordination

---

### 7. 🔔 Alert Fatigue Reduction
**File**: `07_alert_fatigue.json`
**Category**: incident-response
**Agents**: Planner, Alert Analyzer, Metrics

Analyzes alerting patterns to identify noisy, redundant, or low-value alerts. Recommends threshold tuning to reduce alert volume by 30-50%.

**Required MCPs**: slack
**Optional MCPs**: grafana, datadog, coralogix, pagerduty

**Use Cases**:
- Identify high-frequency low-value alerts
- Find flapping alerts
- Detect redundant alert clusters
- Recommend threshold tuning
- Calculate potential time savings

---

### 8. 🛡️ Disaster Recovery Validator
**File**: `08_dr_validator.json`
**Category**: reliability
**Agents**: Planner, DR Validator, AWS, K8s

Validates disaster recovery procedures by actually testing backups (not just checking they exist), measuring RTO/RPO, and validating failover procedures.

**Required MCPs**: aws_eks, slack
**Optional MCPs**: kubernetes

**Use Cases**:
- Test RDS backup restore
- Validate multi-region failover
- Measure actual RTO vs target
- Verify DR runbook accuracy
- Quarterly compliance testing

---

### 9. 📝 Incident Postmortem Generator
**File**: `09_incident_postmortem.json`
**Category**: incident-response
**Agents**: Planner, Postmortem Writer, Investigation

Automatically generates blameless postmortem reports by analyzing Slack conversations, PagerDuty alerts, logs, and metrics. Creates timeline with evidence and actionable follow-ups.

**Required MCPs**: slack
**Optional MCPs**: pagerduty, coralogix, grafana, kubernetes

**Use Cases**:
- Generate postmortem from Slack thread
- Create timeline from PagerDuty incident
- Auto-create GitHub issues for action items
- Blameless RCA with evidence

---

### 10. 📊 Universal Telemetry Agent
**File**: `10_universal_telemetry.json`
**Category**: observability
**Agents**: Planner, Telemetry

**🌟 Innovation**: Works with ANY observability platform! Auto-detects Coralogix, Grafana, Datadog, New Relic and uses a unified 3-layer approach (Metrics → Logs → Traces).

**Required MCPs**: slack + at least one observability platform
**Optional MCPs**: coralogix, grafana, datadog, newrelic

**Use Cases**:
- Platform-agnostic incident investigation
- Cross-validate findings across multiple platforms
- Works during platform migrations
- Compare metrics between Grafana and Datadog

---

## Template Statistics

- **Total Templates**: 10
- **Categories**:
  - Incident Response (4)
  - CI/CD (1)
  - FinOps (1)
  - Coding (1)
  - Data (1)
  - Observability (1)
  - Reliability (1)
  - Demo (1)
- **Total Agents**: 25+ unique agent configurations
- **Lines of JSON**: ~2,500

## Usage

### Seeding Templates into Database

```bash
cd config_service
python scripts/seed_templates.py
```

### Applying a Template (Web UI)

1. Navigate to `/team/templates`
2. Browse available templates
3. Click template card to preview
4. Click "Apply to My Team"
5. Confirm application
6. Agents are immediately available (hot-reload)

### Applying a Template (API)

```bash
# Get team token
export TOKEN="your-team-token"

# List templates
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/v1/templates

# Apply template
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customize": {}}' \
  http://localhost:8080/api/v1/team/templates/{template_id}/apply
```

## Template Structure

Each template JSON follows this structure:

```json
{
  "$schema": "incidentfox-template-v1",
  "$template_name": "Template Name",
  "$template_slug": "template-slug",
  "$description": "Brief description",
  "$category": "category-name",
  "$version": "1.0.0",

  "agents": {
    "agent_name": {
      "enabled": true,
      "name": "Display Name",
      "description": "What this agent does",
      "model": { "name": "gpt-5.2", "temperature": 0.3 },
      "prompt": { "system": "Agent system prompt" },
      "max_turns": 50,
      "tools": { "enabled": [...], "disabled": [] },
      "sub_agents": [...]
    }
  },

  "mcps": {
    "mcp_name": { "enabled": true, "required": true }
  },

  "runtime_config": {
    "max_concurrent_agents": 3,
    "default_timeout_seconds": 300
  },

  "output_config": {
    "default_destinations": ["slack"],
    "formatting": { ... }
  }
}
```

## Creating New Templates

1. Create JSON file following the structure above
2. Add metadata to `scripts/seed_templates.py` in `TEMPLATE_METADATA` dict
3. Run seed script to load into database
4. Template will appear in Web UI marketplace

## Documentation

- **Design Doc**: `docs/TEMPLATE_SYSTEM_DESIGN.md`
- **Implementation**: `docs/TEMPLATE_SYSTEM_IMPLEMENTATION.md`
- **Seed Script**: `scripts/seed_templates.py`

---

**Last Updated**: 2026-01-10
**Version**: 1.0.0
**Templates**: 10/10 Complete ✅
