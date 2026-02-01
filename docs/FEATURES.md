# IncidentFox Features

This document provides a comprehensive overview of IncidentFox's capabilities, from core functionality to advanced AI features and enterprise-grade governance.

---

## Table of Contents

- [Core Capabilities](#core-capabilities)
- [Advanced AI Features](#advanced-ai-features)
- [Enterprise Ready](#enterprise-ready)
- [Extensible & Customizable](#extensible--customizable)

---

## Core Capabilities

### Dual Agent Runtime

IncidentFox supports two agent frameworks to meet different operational needs:

- **OpenAI Agents SDK** (Production) - Stable, reliable runtime for production workloads
- **Claude SDK with K8s Sandboxing** (Exploratory) - Advanced sandboxing for experimental investigations

This dual-runtime approach provides flexibility for different investigation scenarios while maintaining production stability.

### 300+ Built-in Tools

IncidentFox comes with an extensive toolset covering your entire infrastructure and development stack:

| Category | Count | Tools |
|----------|-------|-------|
| **Kubernetes** | 9 | Pod logs, events, deployments, services, resource usage |
| **AWS** | 8 | EC2, Lambda, RDS, ECS, CloudWatch logs/metrics |
| **Anomaly Detection** | 8 | Prophet forecasting, Z-score detection, correlation, change points |
| **Grafana** | 6 | Dashboards, Prometheus queries, alerts, annotations |
| **Datadog** | 3 | Metrics, logs, APM |
| **New Relic** | 2 | NRQL queries, APM summary |
| **GitHub** | 16 | Code search, PRs, issues, workflows, file operations |
| **Git** | 12 | Status, diff, log, blame, branches |
| **Docker** | 15 | Build, run, logs, exec, compose |
| **Coding** | 7 | File I/O, tests, linting, search |
| **Browser** | 4 | Screenshots, scraping, PDF generation |
| **Slack** | 5 | Messages, channels, threads |
| **Elasticsearch** | 3 | Log search, aggregations |
| **Meta** | 2 | `llm_call`, `web_search` (available to all agents) |

**See [agent/docs/TOOLS_CATALOG.md](../agent/docs/TOOLS_CATALOG.md) for the complete tool reference.**

### Multiple Triggers

Start investigations from wherever incidents are detected:

- **Slack Bot** - Mention @incidentfox in any channel
- **GitHub Bot** - Comment on PRs and issues
- **PagerDuty Webhooks** - Auto-investigate when alerts fire
- **A2A Protocol** - Agent-to-agent communication for orchestration
- **REST API** - Direct programmatic access

**Setup guides:** [INTEGRATIONS.md](INTEGRATIONS.md)

### MCP Protocol Support

Connect to 100+ Model Context Protocol (MCP) servers for unlimited integrations without code changes:

- Add any MCP server to your configuration
- Tools become available to agents immediately
- No deployment or code changes required
- Community-maintained server ecosystem

**Documentation:** [../agent/docs/MCP_CLIENT_IMPLEMENTATION.md](../agent/docs/MCP_CLIENT_IMPLEMENTATION.md)

---

## Advanced AI Features

### RAPTOR Knowledge Base

Hierarchical retrieval system based on the ICLR 2024 paper "RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval":

- **Multi-level indexing** - Stores information at different abstraction levels
- **Learns your runbooks** - Automatically indexes team documentation
- **Past incident memory** - Retrieves similar historical investigations
- **Proprietary knowledge** - Handles your organization-specific context

The hierarchical structure enables more accurate retrieval than flat vector databases, especially for complex technical documentation.

**Implementation:** [../knowledge_base/](../knowledge_base/)

### Alert Correlation Engine

3-layer analysis system that reduces alert noise by 85-95%:

1. **Temporal Correlation** - Groups alerts that fire within time windows
2. **Topology Correlation** - Links alerts across service dependencies
3. **Semantic Correlation** - Uses LLM to understand alert relationships

**Output:** Single correlated incident with AI-generated summary instead of dozens of individual alerts.

**Premium Feature:** Available in SaaS and On-Premise Enterprise editions.

### Dependency Discovery

Auto-maps service dependencies from distributed traces:

- Analyzes OpenTelemetry traces to build service graph
- Identifies upstream/downstream relationships
- Updates topology database automatically
- Powers blast radius analysis and root cause investigation

**Premium Feature:** Available in SaaS and On-Premise Enterprise editions.

### Continuous Learning Pipeline

Analyzes agent performance to suggest improvements:

1. **Gap Analysis** - Identifies missing tools or knowledge
2. **Pattern Recognition** - Learns team-specific investigation patterns
3. **Proposal Generation** - Suggests prompt and tool improvements
4. **Evaluation** - Tests proposals against historical incidents

**Implementation:** [../ai_pipeline/](../ai_pipeline/)

**Premium Feature:** Available in SaaS and On-Premise Enterprise editions.

### Smart Log Sampling

Prevents context overflow when dealing with high-volume logs:

- **Intelligent sampling** - Preserves key events while reducing volume
- **Pattern detection** - Keeps representative samples of repeated errors
- **Time-based distribution** - Maintains temporal context
- **Configurable strategies** - Adjust sampling based on investigation needs

Ensures agents stay within token limits without losing critical information.

---

## Enterprise Ready

### Hierarchical Configuration

**Org → Business Unit → Team** inheritance model with override capabilities:

- **Organization defaults** - Set baseline configuration for all teams
- **Business unit overrides** - Customize for different departments
- **Team-specific settings** - Fine-tune agent behavior per team
- **Cascading changes** - Update upstream and propagate automatically

Example:
```
Org: "Use GPT-4o for all agents"
  ↓
BU (Platform): "Add K8s cluster connection"
  ↓
Team (Payments): "Override to use Claude for sensitive data"
```

**Documentation:** [CONFIG_INHERITANCE.md](CONFIG_INHERITANCE.md)

### SSO & OIDC

Per-organization single sign-on support:

- **Google Workspace** - oauth2
- **Azure AD / Entra ID** - OIDC
- **Okta** - OIDC
- **Generic OIDC** - Any OIDC-compliant provider

Each organization configures their own identity provider independently.

### Approval Workflows

Require review before changes are deployed:

- **Prompt changes** - Review agent behavior modifications
- **Tool additions** - Approve new capabilities before enabling
- **Configuration updates** - Control propagation of config changes
- **Audit trail** - Track who approved what and when

Ensures governance without blocking team autonomy.

### Audit Logging

Complete trail of all system activity:

- **Agent runs** - Full transcript of every investigation
- **Configuration changes** - Who changed what, when
- **API calls** - All programmatic access logged
- **User actions** - Web UI and Slack interactions tracked
- **Approval decisions** - Review outcomes and justifications

**Retention:** Configurable per organization (default: 90 days)

### Privacy & Telemetry

**Opt-out anytime** - Organization-level control:

- Disabled by default for self-hosted deployments
- Can be enabled in Settings → Telemetry
- **No PII collected** - Only aggregate metrics and usage patterns
- **Transparent** - View exactly what's sent before enabling

**Documentation:** [TELEMETRY_SYSTEM.md](TELEMETRY_SYSTEM.md)

---

## Extensible & Customizable

### Beyond SRE

While optimized for incident investigation, IncidentFox can be configured for any automation workflow:

- **CI/CD Fix** - Auto-debug failed pipelines
- **Cloud Cost Optimization** - Identify and suggest savings opportunities
- **Security Scanning** - Analyze vulnerabilities and suggest fixes
- **Code Review** - Automated PR analysis
- **Documentation Generation** - Create runbooks from investigations

Simply customize agent prompts and available tools for your use case.

### A2A Protocol

Google's Agent-to-Agent communication protocol for multi-agent orchestration:

- **Task delegation** - Primary agent calls specialist agents
- **Streaming responses** - Real-time progress updates
- **Standard interface** - Any A2A-compliant agent can participate
- **Composable workflows** - Build complex automations from simple agents

**Documentation:** [../agent/docs/A2A_PROTOCOL.md](../agent/docs/A2A_PROTOCOL.md)

### Custom Prompts

Per-team agent behavior customization:

- **System prompt** - Define agent personality and approach
- **Investigation template** - Structure how investigations proceed
- **Output format** - Control markdown, JSON, or custom formats
- **Tool guidance** - Suggest when to use specific tools

Changes apply only to your team without affecting others.

### MCP Servers

Add any integration via Model Context Protocol:

1. Find an MCP server (100+ available) or build your own
2. Add to your team configuration
3. Tools immediately available to agents
4. No deployment required

**Popular MCP servers:**
- Sentry, Jira, Linear, Notion
- PostgreSQL, MySQL, MongoDB
- Terraform, Ansible, Puppet
- Custom internal tools

**MCP Server Directory:** https://github.com/modelcontextprotocol/servers

---

## What's Next?

- **[INTEGRATIONS.md](INTEGRATIONS.md)** - Set up Slack, GitHub, PagerDuty, and more
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Understand the agent system design
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Deploy for your organization (Docker Compose, Kubernetes, Production)
