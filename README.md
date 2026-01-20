# IncidentFox

> **Our mission: Build the world's best AI SRE.**

**AI-powered incident investigation and infrastructure automation.**

IncidentFox is an AI SRE / AI On-Call engineer that integrates with your observability stack, infrastructure, and collaboration tools to automatically investigate incidents, find root causes, and suggest fixes.
![image](https://github.com/user-attachments/assets/b6892fe8-0a19-40f9-9d86-465aa3387108)

🌐 **Try it live:** [ui.incidentfox.ai](https://ui.incidentfox.ai) | 📧 **Enterprise & On-Premise:** [founders@incidentfox.ai](mailto:founders@incidentfox.ai)

![image](https://github.com/user-attachments/assets/8c785a32-c46a-4d5b-8297-fe13f23a2392)
![image](https://github.com/user-attachments/assets/60934195-83bf-4d5d-ab7e-0c32e60dbe86)



---

## Why IncidentFox?

| Challenge | How IncidentFox Solves It |
|-----------|---------------------------|
| Alert fatigue | **Smart correlation** reduces noise by 85-95% using temporal, topology, and semantic analysis |
| Context switching | **Rich Slack UI** with progressive investigation updates—stay in your workflow |
| Tribal knowledge | **RAPTOR knowledge base** learns your runbooks and past incidents |
| Tool sprawl | **MCP protocol** connects to any tool in minutes, not weeks |
| Team differences | **Config inheritance** lets orgs set defaults while teams customize |

---

## ✨ Key Features

### Core Capabilities
- **Dual Agent Runtime** - OpenAI Agents SDK (production) + Claude SDK with K8s sandboxing (exploratory)
- **178+ Tools** - Kubernetes, AWS, Grafana, Datadog, New Relic, GitHub, Elasticsearch, and more
- **Multiple Triggers** - Slack, GitHub Bot, PagerDuty, A2A Protocol, REST API
- **MCP Protocol** - Connect to 100+ MCP servers for unlimited integrations without code changes

### Advanced AI Features
- **RAPTOR Knowledge Base** - Hierarchical retrieval that learns your proprietary knowledge (ICLR 2024 paper)
- **Alert Correlation Engine** - 3-layer analysis (temporal + topology + semantic) with LLM-generated summaries
- **Dependency Discovery** - Auto-maps service dependencies from distributed traces
- **Continuous Learning Pipeline** - Analyzes team patterns and proposes prompt/tool improvements
- **Smart Log Sampling** - Prevents context overflow with intelligent sampling strategies

### Enterprise Ready
- **Hierarchical Config** - Org → Business Unit → Team inheritance with override capabilities
- **SSO/OIDC** - Google, Azure AD, Okta per-organization
- **Approval Workflows** - Require review for prompt/tool changes
- **Audit Logging** - Full trail of all changes and agent runs
- **Privacy First** - Optional telemetry with org-level opt-out, no PII collected

### Extensible & Customizable
- **Beyond SRE** - Configure for CI/CD fix, cloud cost optimization, security scanning, or any automation
- **A2A Protocol** - Agent-to-agent communication for multi-agent orchestration
- **Custom Prompts** - Per-team agent behavior customization
- **MCP Servers** - Add any integration via Model Context Protocol

## 🚀 Quick Start

### Option 1: Local CLI (Fastest)

Try IncidentFox locally with an interactive terminal:

```bash
cd local

# 1. Setup (creates .env, starts PostgreSQL, Config Service, Agent)
make setup
make start

# 2. Add your OpenAI API key to .env
echo "OPENAI_API_KEY=sk-xxx" >> .env

# 3. Generate team token and run CLI
make seed
make cli
```

```
incidentfox> Check if there are any pods crashing in default namespace

🔍 Investigating...

Found 2 pods in CrashLoopBackOff:
- payment-service-abc123: OOMKilled (memory limit 512Mi)
- cart-service-xyz789: Error in startup probe

Recommendations:
1. Increase memory limit for payment-service to 1Gi
2. Check cart-service logs for startup errors
```

**Full local setup guide:** [local/README.md](local/README.md)

### Option 2: Manual Setup

#### Prerequisites

- Python 3.11+
- Node.js 18+ (for web UI)
- Docker
- Kubernetes cluster access (for K8s tools)
- AWS credentials (for AWS tools)

#### Start Services

```bash
# 1. Start the agent service
cd agent
poetry install --extras all
poetry run python -m ai_agent --mode api

# 2. Start the config service
cd config_service
pip install -r requirements.txt
python -m src.api.main

# 3. Start the web UI
cd web_ui
pnpm install
pnpm dev
```

### Environment Variables

```bash
# Core
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o  # or gpt-4-turbo

# Integrations (optional, enable as needed)
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
GITHUB_TOKEN=ghp_...
GITHUB_WEBHOOK_SECRET=...
PAGERDUTY_WEBHOOK_SECRET=...
AWS_REGION=us-west-2
GRAFANA_URL=https://grafana.example.com
GRAFANA_API_KEY=...
DATADOG_API_KEY=...
DATADOG_APP_KEY=...
```

## 🔌 Integrations

### Slack Bot (Primary Interface)

Mention the bot in any channel to start an investigation:

```
@incidentfox why is the payments service slow?
@incidentfox investigate pod nginx-abc123 crashing
```

**Setup:**
1. Create a Slack App at https://api.slack.com/apps
2. Add Bot Token Scopes: `chat:write`, `app_mentions:read`, `channels:history`
3. Install to workspace and copy Bot Token
4. Set `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET`
5. Configure Event Subscriptions URL: `https://your-domain/api/slack/events`

### GitHub Bot

Comment on issues or PRs to trigger investigation:

```
@incidentfox investigate why this test is failing
/investigate the authentication changes in this PR
/analyze potential security issues
```

**Setup:**
1. Create a GitHub Personal Access Token at https://github.com/settings/tokens
   - Scopes: `repo`, `write:discussion`
2. Set environment variables:
   ```bash
   GITHUB_WEBHOOK_SECRET=your-random-secret
   GITHUB_TOKEN=ghp_xxxxxxxxxxxx
   ```
3. Configure webhook in your repo:
   - Go to **Settings → Webhooks → Add webhook**
   - Payload URL: `https://your-domain/api/github/webhook`
   - Content type: `application/json`
   - Secret: Same as `GITHUB_WEBHOOK_SECRET`
   - Events: ✅ Issue comments, ✅ Pull request review comments

**What happens:**
1. User comments `@incidentfox investigate X`
2. Bot reacts with 👀 (working)
3. Investigation runs (30-60 seconds)
4. Bot posts formatted results as a comment
5. Bot reacts with 🚀 (done)

### PagerDuty (Auto-Investigation)

Automatically investigate when alerts fire:

**Setup:**
1. Go to PagerDuty → Services → Your Service → Integrations
2. Add "Generic Webhooks (v3)"
3. Set URL: `https://your-domain/api/pagerduty/webhook`
4. Copy signing secret to `PAGERDUTY_WEBHOOK_SECRET`

When an incident triggers, IncidentFox automatically:
- Starts investigation with alert context
- Posts findings to configured Slack channel
- Includes service name, urgency, and priority

### A2A Protocol (Agent-to-Agent)

Allow other AI agents to call IncidentFox using Google's A2A protocol:

```json
POST /api/a2a
{
  "method": "tasks/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"text": "Investigate high latency in payments service"}]
    }
  }
}
```

**Supported methods:** `tasks/send`, `tasks/get`, `tasks/cancel`, `agent/authenticatedExtendedCard`

### REST API

Direct programmatic access:

```bash
curl -X POST https://your-domain/api/orchestrator/agents/run \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "org_id": "org-1",
    "team_node_id": "team-platform",
    "agent_name": "planner",
    "message": "Investigate pod crash in production"
  }'
```

## 🤖 Agent Architecture

```
                    ┌─────────────────────────────────────────┐
                    │            Orchestrator                  │
                    │  (Slack/API → Team Router)               │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │           Agent Registry                 │
                    │  • Dynamic agent creation                │
                    │  • Team-specific config + prompts        │
                    │  • Hot-reload on config changes          │
                    └────────────────┬────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
        ▼                            ▼                            ▼
┌───────────────┐          ┌─────────────────┐          ┌─────────────────┐
│   Planner     │          │  Investigation  │          │  Specialized    │
│   Agent       │◀────────▶│     Agent       │◀────────▶│    Agents       │
│               │          │                 │          │                 │
│  Orchestrates │          │  General SRE    │          │ K8s, AWS, Code  │
│  complex tasks│          │  Troubleshooting│          │ Metrics, CI, etc│
└───────────────┘          └─────────────────┘          └─────────────────┘
```
![image](https://github.com/user-attachments/assets/5e0a4afa-d807-4931-b2d6-186984e329de)


### Agent Capabilities

| Agent | Purpose | Key Tools |
|-------|---------|-----------|
| **Planner** | Orchestrates complex multi-step tasks | Routes to specialized agents |
| **Investigation** | General SRE troubleshooting (primary) | 30+ tools (K8s, AWS, logs, metrics) |
| **K8s** | Kubernetes debugging | `list_pods`, `get_pod_logs`, `describe_deployment` |
| **AWS** | AWS resource investigation | `describe_ec2`, `get_cloudwatch_logs`, `list_ecs_tasks` |
| **Metrics** | Anomaly detection | `prophet_detect_anomalies`, `correlate_metrics` |
| **Coding** | Code analysis & fixes | `read_file`, `git_diff`, `python_run_tests` |
| **GitHub** | PR/Issue investigation | `search_code`, `list_pull_requests`, `get_workflow_runs` |
| **Log Analysis** | Deep log investigation | Log search, pattern analysis, correlation |
| **CI** | CI/CD debugging | Build logs, deployment history, rollbacks |
| **Writeup** | Incident documentation | Generates postmortems and summaries |

### Tool Categories

| Category | Tools | Description |
|----------|-------|-------------|
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

## 📁 Repository Structure

```
mono-repo/
├── agent/                 # Multi-agent runtime + REST API (Python)
│   ├── src/ai_agent/
│   │   ├── agents/        # Agent definitions (planner, k8s, aws, etc.)
│   │   ├── tools/         # 50+ tool implementations
│   │   └── integrations/  # MCP servers, external integrations
│   └── pyproject.toml
│
├── config_service/        # Control plane API (FastAPI)
│   ├── src/
│   │   ├── api/           # REST endpoints
│   │   └── db/            # SQLAlchemy models, migrations
│   └── alembic/           # Database migrations
│
├── web_ui/                # Admin & Team Console (Next.js)
│   ├── src/app/
│   │   ├── admin/         # Org tree, integrations, policies, audit
│   │   ├── team/          # MCPs, prompts, knowledge, agent runs
│   │   └── api/           # API routes (Slack, GitHub, PagerDuty, A2A)
│   └── package.json
│
├── orchestrator/          # Provisioning + Slack trigger routing
├── ai_pipeline/           # Learning pipeline (ingestion, proposals, evals)
├── knowledge_base/        # RAPTOR-based retrieval
├── database/              # RDS Terraform + scripts
└── charts/                # Helm charts for Kubernetes deployment
```

## 🏗️ Deployment

IncidentFox can be deployed to any Kubernetes cluster. We provide Helm charts for Kubernetes deployment and Terraform modules for cloud infrastructure.

### Prerequisites

- Kubernetes cluster (EKS, GKE, AKS, or any K8s 1.24+)
- PostgreSQL database (RDS, Cloud SQL, or self-managed)
- OpenAI API key (or compatible LLM endpoint)
- (Optional) AWS Load Balancer Controller for ALB ingress
- (Optional) External Secrets Operator for secrets management

### Helm Chart Deployment

```bash
# 1. Create namespace
kubectl create namespace incidentfox

# 2. Create required secrets
kubectl create secret generic incidentfox-database-url \
  --from-literal=DATABASE_URL="postgresql://user:pass@host:5432/incidentfox" \
  -n incidentfox

kubectl create secret generic incidentfox-openai \
  --from-literal=api_key="sk-your-openai-key" \
  -n incidentfox

kubectl create secret generic incidentfox-config-service \
  --from-literal=ADMIN_TOKEN="your-admin-token" \
  --from-literal=TOKEN_PEPPER="random-32-char-string" \
  -n incidentfox

# 3. Deploy with Helm
helm upgrade --install incidentfox ./charts/incidentfox \
  -n incidentfox \
  -f charts/incidentfox/values.yaml

# 4. Check deployment status
kubectl get pods -n incidentfox
```

**Helm Values Files:**
- `values.yaml` - Default configuration
- `values.pilot.yaml` - Minimal first-deploy profile (token auth, HTTP)
- `values.prod.yaml` - Production profile (OIDC, HTTPS, HPA)

See [charts/incidentfox/README.md](charts/incidentfox/README.md) for full configuration options including OIDC, RBAC, and production hardening.

### Terraform Infrastructure (Optional)

If you need to provision cloud infrastructure, Terraform modules are provided for each service:

```bash
# Database (RDS PostgreSQL)
cd database/infra/terraform
terraform init
terraform apply -var="environment=prod"

# Agent infrastructure (ECS/Fargate example)
cd agent/infra/terraform
terraform init
terraform apply

# Web UI (with ALB)
cd web_ui/infra/terraform
terraform init
terraform apply
```

**Available Terraform modules:**
- `database/infra/terraform/` - RDS PostgreSQL with security groups
- `agent/infra/terraform/` - ECS task definitions, IAM roles, CloudWatch
- `web_ui/infra/terraform/` - ALB, ECS, SSM parameters
- `knowledge_base/infra/terraform/` - S3 buckets, ECS, IAM

### Docker Compose (Development)

For local development without Kubernetes:

```bash
docker-compose up -d
```

### Architecture Overview

```
Platform: Kubernetes (EKS, GKE, AKS, or any K8s cluster)
Namespace: incidentfox (configurable)
Services: 4 core services
  - agent (Python/Poetry) - Multi-agent AI runtime
  - config-service (Python/FastAPI) - Configuration & auth
  - orchestrator (Python/FastAPI) - Webhook routing & provisioning
  - web-ui (Next.js/pnpm) - Admin & team console
```

**Service Endpoints (configure for your environment):**
- Web UI: `https://ui.<your-domain>` (public)
- Orchestrator: `https://orchestrator.<your-domain>` (webhooks)
- Config Service: Internal only (cluster DNS)
- Agent: Internal only (cluster DNS)

## 🔐 Security & Governance

- **SSO/OIDC** - Per-organization SSO configuration (Google, Azure AD, Okta)
- **RBAC** - Admin vs Team roles with scoped permissions
- **Approval Workflows** - Require approval for prompt/tool changes
- **Audit Logging** - Full audit trail of all changes and agent runs
- **Token Management** - Expiry warnings, auto-revocation of inactive tokens
- **Config Inheritance** - Org → Group → Team with override capabilities

## 📊 Web UI Features

### Admin Console
- **Org Tree** - Hierarchical organization management
- **Integrations** - Configure Slack, GitHub, Datadog, etc.
- **Security Policies** - Token expiry, approval requirements
- **Audit Logs** - Unified view of all system events
- **Pending Changes** - Review and approve configuration changes
- **Org Defaults** - Default prompts and MCPs for all teams

### Team Console
- **Agent Prompts** - Customize agent behavior
- **MCP Servers** - Configure Model Context Protocol servers
- **Knowledge Base** - Upload documents, review AI proposals
- **Agent Runs** - View investigation history
- **Pending Changes** - Team-scoped approval queue

## 🧪 Testing

```bash
# Agent tests
cd agent && poetry run pytest

# Config service tests
cd config_service && pytest

# Web UI tests
cd web_ui && pnpm test
```

## 📈 Evaluation Framework

IncidentFox includes a comprehensive evaluation framework to measure agent performance on real incident scenarios. This enables continuous improvement and provides confidence in agent capabilities.

### How It Works

1. **Fault Injection** - We inject real failures into a test environment (otel-demo on Kubernetes)
2. **Agent Investigation** - The agent investigates and produces a diagnosis
3. **Scoring** - Responses are scored across 5 dimensions
4. **Iteration** - Results guide prompt/tool improvements

### Evaluation Scenarios

| Tier | Scenario | Description | Target |
|------|----------|-------------|--------|
| 0 | Health Check | Verify agent recognizes healthy systems | Baseline |
| 1 | Pod Crashes | Cart, Payment, Ad service crashes (CrashLoopBackOff) | ≥85 score |
| 1 | Container Failures | OOMKilled, exit code errors | ≥85 score |
| 2 | Feature Flag Failures | Application-level failures via flagd | ≥80 score |
| 2 | Dependency Issues | Service connectivity, collector failures | ≥80 score |
| 3 | Complex Cascading | Multi-service failures, resource exhaustion | ≥75 score |

### Scoring Dimensions

| Dimension | Weight | What We Measure |
|-----------|--------|-----------------|
| **Root Cause** | 30 pts | Did the agent identify the correct root cause? |
| **Evidence** | 20 pts | Did the agent cite specific logs, events, or metrics? |
| **Timeline** | 15 pts | Did the agent reconstruct what happened when? |
| **Impact** | 15 pts | Did the agent identify affected systems? |
| **Recommendations** | 20 pts | Did the agent suggest actionable fixes? |

**Total: 100 points per scenario**

### Latest Results

```
┌─────────────────────────┬───────┬────────┬───────────┐
│ Scenario                │ Score │ Time   │ Status    │
├─────────────────────────┼───────┼────────┼───────────┤
│ healthCheck             │ 60    │ 14.3s  │ ✅ Pass   │
│ cartCrash               │ 90    │ 17.2s  │ ✅ Pass   │
│ adCrash                 │ 90    │ 16.7s  │ ✅ Pass   │
│ cartFailure             │ 85    │ 27.6s  │ ✅ Pass   │
│ adFailure               │ 90    │ 15.4s  │ ✅ Pass   │
│ productCatalogFailure   │ 85    │ 16.1s  │ ✅ Pass   │
├─────────────────────────┼───────┼────────┼───────────┤
│ Average                 │ 83.3  │ 17.9s  │           │
│ Pass Rate               │ 75%   │        │ 6/8       │
└─────────────────────────┴───────┴────────┴───────────┘
```

### Example: Cart Crash Investigation

**Scenario:** Cart service pod is in CrashLoopBackOff

**Agent Output:**
```json
{
  "summary": "The cart service pod is experiencing a crash issue.",
  "root_cause": {
    "description": "Container crashing due to a simulated crash error in the logs.",
    "confidence": 95,
    "evidence": [
      "Back-off restarting failed container cart",
      "Logs indicate 'SIMULATED CRASH'"
    ]
  },
  "timeline": [
    "Pod 'cart-f6b44c77c-lg7jn' started and pulled images successfully.",
    "Container 'cart' started but failed, leading to a back-off restart."
  ],
  "affected_systems": ["cart service"],
  "recommendations": [
    "Investigate the application code for the cart service.",
    "Consider rolling back to a previous stable version."
  ]
}
```

**Score: 90/100** ✅

### Running Evals

```bash
# Run full evaluation suite
python3 scripts/eval_agent_performance.py

# Quick validation (3 scenarios)
python3 scripts/run_agent_eval.py --agent-url http://localhost:8080

# Against deployed agent
python3 scripts/eval_agent_performance.py --agent-url http://agent.internal:8080
```

### Eval-Driven Development

We use evals to:
- **Benchmark** new model versions (GPT-4o vs GPT-4-turbo)
- **Validate** prompt changes before deployment
- **Regression test** tool modifications
- **Compare** agent architectures (handoff vs agent-as-tool)

Target: **≥85 average score, <60s per scenario**

## 🔒 Privacy & Telemetry

IncidentFox includes an **optional telemetry system** to help improve the product. Organizations have full control:

### User Control
- **Opt-out anytime** via Settings → Telemetry in the web UI
- **Immediate effect** - changes take effect within 5 minutes
- **Org-level preference** - applies to all teams in the organization

### What We Collect (When Enabled)
- Aggregate metrics: run counts, success/failure rates, duration statistics
- Usage patterns: tool usage, agent types, trigger sources
- Performance data: latency percentiles (p50/p95/p99), error types
- Team activity: number of active teams (not team names or IDs)

### What We DON'T Collect
- Personal information, credentials, or tokens
- Agent prompts, messages, or conversation content
- Knowledge base documents or team-specific data
- API keys, secrets, or integration credentials
- IP addresses, hostnames, or network identifiers

### Technical Implementation
- All data is **aggregated and anonymized** before sending
- Sent securely to vendor service via TLS
- **Never shared with third parties**
- Heartbeat reports every 5 minutes + daily analytics at 2AM UTC

**See [Telemetry System Documentation](docs/TELEMETRY_SYSTEM.md) for complete details.**

## 📚 Documentation

### Architecture
- [Architecture Decisions](docs/ARCHITECTURE_DECISIONS.md) - Key ADRs and rationale
- [Multi-Tenant Design](orchestrator/docs/MULTI_TENANT_DESIGN.md) - Shared vs per-team runtime
- [Routing Design](docs/ROUTING_DESIGN.md) - Webhook routing to teams
- [Telemetry System](docs/TELEMETRY_SYSTEM.md) - Privacy-first telemetry with opt-out

### Getting Started
- [Local CLI Setup](local/README.md) - Run IncidentFox locally in your terminal
- [Development Knowledge](DEVELOPMENT_KNOWLEDGE.md) - Comprehensive dev reference

### Services
- [Agent README](agent/README.md) - Agent architecture and tools
- [Orchestrator Docs](orchestrator/docs/ARCHITECTURE.md) - Control plane design
- [Config Service README](config_service/README.md) - API and configuration
- [Telemetry Collector README](telemetry_collector/README.md) - Telemetry sidecar service
- [Web UI README](web_ui/README.md) - Frontend development
- [Tools Catalog](agent/docs/TOOLS_CATALOG.md) - Complete list of 178 built-in tools

### Advanced Features
- [A2A Protocol](agent/docs/A2A_PROTOCOL.md) - Agent-to-agent communication
- [MCP Client](agent/docs/MCP_CLIENT_IMPLEMENTATION.md) - Dynamic tool loading via MCP
- [Log Sampling Design](agent/docs/LOG_SAMPLING_DESIGN.md) - Intelligent log sampling
- [Slack Investigation Flow](agent/docs/SLACK_INVESTIGATION_FLOW.md) - Progressive Slack UI
- [Config Inheritance](docs/CONFIG_INHERITANCE.md) - Hierarchical configuration

## 🔗 Testing & Evaluation

For testing agent capabilities, we recommend:

- **[OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo)** - Microservices demo app ideal for fault injection testing
  - Used by the evaluation framework to test agent investigation capabilities
  - Supports various failure scenarios (pod crashes, feature flags, dependency issues)

- **Your own staging environment** - Deploy IncidentFox alongside your existing staging Kubernetes cluster for realistic testing

---

## 🗺️ Roadmap

### Completed
- [x] Multi-agent architecture with Agent-as-Tool pattern
- [x] 178+ tools across K8s, AWS, Grafana, GitHub, etc.
- [x] Prophet-based anomaly detection
- [x] Slack, GitHub, PagerDuty, A2A integrations
- [x] Enterprise governance (SSO, RBAC, audit)
- [x] Team-specific configuration and prompts
- [x] Evaluation framework with fault injection scoring
- [x] RAPTOR knowledge base (hierarchical retrieval)
- [x] Auto-remediation actions (with approval workflow)
- [x] MCP protocol client (dynamic tool loading)
- [x] Alert correlation engine (temporal + topology + semantic)
- [x] Dependency service (auto-discovery from traces)
- [x] Dual agent support (OpenAI + Claude with sandboxing)
- [x] Continuous learning pipeline (gap analysis + proposals)
- [x] Smart log sampling (context overflow prevention)

### In Progress
- [ ] Custom tool generation from descriptions
- [ ] Enhanced A2A protocol documentation
- [ ] More MCP server integrations

---

## 💼 Commercial Options

IncidentFox is open source and free to use. For teams that need more, we offer:

| Option | What You Get |
|--------|--------------|
| **SaaS** | Fully managed at [ui.incidentfox.ai](https://ui.incidentfox.ai) - no infrastructure to manage |
| **On-Premise Enterprise** | Maximum security - everything runs in YOUR environment |
| **Premium Features** | State-of-the-art AI capabilities: correlation, learning pipeline, and more |
| **Professional Services** | Custom integrations, training, and dedicated support |

### Why On-Premise?

For organizations with strict security requirements:

- **Your infrastructure, your control** - All data stays within your environment
- **Air-gapped support** - Works without internet (with local LLM option)
- **SOC 2 compliant** - Enterprise-grade security and audit trails
- **State-of-the-art features** - Same SOTA capabilities as SaaS (RAPTOR, correlation, learning pipeline)
- **No vendor lock-in** - Open source core means you own your deployment

**Contact:** [founders@incidentfox.ai](mailto:founders@incidentfox.ai)

### Premium Services

These services are available separately for enhanced capabilities:

| Service | Description |
|---------|-------------|
| **Correlation Service** | 3-layer alert correlation (temporal, topology, semantic) - reduces noise by 85-95% |
| **Dependency Service** | Auto-discovers service dependencies from distributed traces |
| **AI Pipeline** | Continuous learning that improves prompts and tools based on team patterns |
| **SRE Agent** | Claude-based agent with K8s sandboxing for exploratory investigations |

---

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE) - see the LICENSE file for details.
