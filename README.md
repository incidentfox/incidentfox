# IncidentFox 🦊

<p align="center">
  <strong>Your AI Copilot for Incident Response</strong>
  <br><br>
  <em>Investigate incidents, find root causes, and suggest fixes — automatically</em>
  <br><br>
  <a href="https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ">Try Free in Slack</a> · <a href="#quick-start">5-Min Docker Setup</a> · <a href="docs/DEPLOYMENT.md">Deploy for Your Team</a>
</p>

---

IncidentFox is an **open-source AI SRE** that integrates with your observability stack, infrastructure, and collaboration tools. It automatically forms hypotheses, collects data from your systems, and reasons through to find root causes — all while you focus on the fix.

**Built for production on-call** — handles log sampling, alert correlation, anomaly detection, and dependency mapping so you don't have to.

<img width="1600" height="1000" alt="Frame 1" src="https://github.com/user-attachments/assets/b85a183c-fda4-4b5c-9089-501f58f966b8" />
<img width="1600" height="1000" alt="Frame 2" src="https://github.com/user-attachments/assets/0f78795b-25c6-419d-bd1f-3b4b7d74d526" />
<img width="1600" height="1000" alt="Frame 3" src="https://github.com/user-attachments/assets/a0c58bee-e3ca-47a9-82a5-0bfc788d3488" />
<img width="1600" height="1000" alt="Frame 4" src="https://github.com/user-attachments/assets/b9ef9263-fbd4-4229-918d-e728385761f2" />
<img width="1600" height="1000" alt="Frame 5" src="https://github.com/user-attachments/assets/f09be022-bc19-457e-acd4-a4e9b4af12a6" />
<img width="1600" height="1000" alt="Frame 6" src="https://github.com/user-attachments/assets/00f3c017-b608-459c-8f1f-37f8cf66d1e2" />

---

## Table of Contents

- [What is IncidentFox?](#what-is-incidentfox)
- [How We're Different](#how-were-different)
- [Get Started](#get-started)
- [Why IncidentFox](#why-incidentfox)
- [Architecture Overview](#architecture-overview)
- [Under the Hood](#under-the-hood)
- [Enterprise Ready](#enterprise-ready)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## What is IncidentFox?

An **AI SRE** that helps root cause and propose mitigations for production on-call issues. It automatically forms hypotheses, collects info from your infrastructure, observability tools, and code, and reasons through to an answer.

**Slack-first** ([see screenshot above](#incidentfox)), but also works on web UI, GitHub, PagerDuty, and API.

**Highly customizable** — set up in minutes, and it self-improves by automatically learning and persisting your team's context.

---

## How We're Different

**AI SRE is not a new idea.** The problem? Most AI SREs don't actually work — they lack the context to debug *your* specific systems.

### Context Is Everything

Other tools ask you to manually configure integrations, write runbooks, and hope the AI figures it out. **IncidentFox does the opposite.**

On setup, we analyze your codebase, Slack history, and past incidents to understand how your org actually works. Internal CI/CD system with weird quirks? Custom deployment tooling? We learn it automatically and build integrations that work out of the box.

**No weeks of integration work. No building your own MCP servers.** We connect to the tools that actually matter for root cause — so you can skip straight to debugging.

### Slack-Native UX

We're opinionated: **you shouldn't leave Slack during an incident.**

- Upload a Grafana screenshot → we analyze it
- Attach a log file → we parse and correlate
- All tool outputs, evidence, and reasoning → visible as Slack attachments
- No new tabs. No context switching. Debug where you already work.

### Powerful Agents, Secure by Default

Our agents run in sandboxed environments with filesystem access — enabling code generation, script execution, and deep analysis. Security guardrails keep them focused on the task.

**The result:** Higher accuracy, faster resolution, less time wasted on integration work.

---

## Get Started

IncidentFox is **open source** (Apache 2.0). Choose the option that fits your needs:

| | Try Free in Slack | Run Locally | Self-Host for Production |
|---|---|---|---|
| **Best for** | See it in action | Evaluate with your infrastructure | Production deployment, full control |
| **Setup time** | Instant | 3 commands | 30 minutes |
| **Cost** | Free | Free | Free (open source) |
| **Privacy** | Our playground environment | Everything local | Everything on your infrastructure |
| | [![Join Slack](https://img.shields.io/badge/Join_Slack-4A154B?logo=slack&logoColor=white)](https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ) | [See below ↓](#quick-start-run-locally) | [Deployment Guide →](docs/DEPLOYMENT.md) |

**New to IncidentFox?** We recommend trying it in our Slack first — no setup required, see how it works instantly.

---

### Quick Start: Run Locally

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Add your API key — edit .env and set ANTHROPIC_API_KEY
#    (or any other provider — see .env.example for options)

# 3. Start all services
make dev
```

**That's it.** IncidentFox starts Postgres, config-service, sre-agent, and slack-bot. Migrations run automatically. Configuration loads from `config_service/config/local.yaml` — edit that file to change models, integrations, or prompts (changes hot-reload, no restart needed).

**Add Slack to test agent responses:**
1. [Create a Slack app](https://api.slack.com/apps?new_app=1) using [the manifest](slack-bot/slack-manifest.json)
2. Add tokens to `.env`:
   ```
   SLACK_BOT_TOKEN=xoxb-your-bot-token
   SLACK_APP_TOKEN=xapp-your-app-token
   ```
3. `make restart`

The bot auto-connects and registers your workspace — no workspace ID setup needed.

**→ [Slack setup guide with screenshots](docs/SLACK_SETUP.md)**
**→ [Full local development guide](docs/LOCAL_DEVELOPMENT.md)**

---

### Managed Version (Premium Features)

For teams that want production-ready IncidentFox with:
- **Auto-learning**: We analyze your codebase, Slack history, and past incidents to build custom integrations automatically
- **Team-specific agents**: Each team gets agents tuned to their stack
- **SOC 2 compliance**, SSO/OIDC, on-premise options, and dedicated support

[Contact us for a demo (7-day free trial)](mailto:founders@incidentfox.ai) or [![Add to Slack](https://img.shields.io/badge/Add_to_Slack-4A154B?logo=slack&logoColor=white)](https://slack.com/oauth/v2/authorize?client_id=9967324357443.10323403264580&scope=app_mentions:read,channels:history,channels:join,channels:read,chat:write,chat:write.customize,commands,files:read,files:write,groups:history,groups:read,im:history,im:read,im:write,links:read,links:write,metadata.message:read,mpim:history,mpim:read,reactions:read,reactions:write,usergroups:read,users:read&user_scope=)

---

## Why IncidentFox

**For Engineering Leaders:** What this means for your team.

| Outcome | Impact |
|---------|--------|
| **Faster Incident Resolution** | Hours → minutes. Auto-correlates alerts, analyzes logs, traces dependencies. |
| **85-95% Less Alert Noise** | Smart correlation finds root cause. Engineers focus on real problems. |
| **Knowledge Retention** | Learns your systems and runbooks. Knowledge stays when people leave. |
| **Works on Day One** | 300+ integrations. No months of setup — connect and go. |
| **No Vendor Lock-In** | Open source, bring your own LLM keys, deploy anywhere. |
| **Gets Smarter Over Time** | Learns from every investigation. Your expertise compounds. |

**The bottom line:** Less time firefighting, more time building.

---

## Integrations

IncidentFox connects to your existing tools and infrastructure. No manual setup required — configure once and it works everywhere.

### Available Now ✅

| Category | Integrations |
|----------|--------------|
| **Logs & Metrics** | Coralogix · Grafana · Elasticsearch · Datadog · Prometheus · Jaeger |
| **Incidents** | incident.io |
| **Cloud & Infra** | Kubernetes |
| **Dev Tools** | GitHub · Confluence |

### Coming Soon 🚀

| Category | Integrations |
|----------|--------------|
| **Logs & Metrics** | CloudWatch · Splunk · OpenSearch · New Relic · Honeycomb · Dynatrace · Chronosphere · VictoriaMetrics · Kloudfuse · Sentry · Snowflake |
| **Incidents** | PagerDuty · Opsgenie · ServiceNow |
| **Cloud & Infra** | AWS · GCP · Azure · Temporal |
| **Dev Tools** | Jira · Linear · Notion · Glean |

**Need an integration?** [Contact us](mailto:founders@incidentfox.ai) or contribute via [MCP protocol](#under-the-hood) — add new integrations in minutes.

[Full integration docs →](docs/INTEGRATIONS.md)

---

## Architecture Overview

```
┌───────────────────────────────────┐     ┌──────────────────────┐
│ Slack / GitHub / PagerDuty / API  │     │       Web UI         │
└─────────────────┬─────────────────┘     │   (dashboard, team   │
                  │ webhooks              │    management)       │
┌─────────────────▼─────────────────┐     └──────────┬───────────┘
│           Orchestrator            │                │
│  (routes webhooks, team lookup,   │                │
│    token auth, audit logging)     │                │
└────────┬─────────────────┬────────┘                │
         │                 │                         │
┌────────▼────────┐   ┌────▼─────────────────────────▼───┐
│      Agent      │<->│          Config Service          │
│ (Claude/OpenAI, │   │    (multi-tenant cfg, RBAC,      │
│   300+ tools,   │   │     routing, team hierarchy)     │
│   multi-agent)  │   └─────────────────┬────────────────┘
└────┬───────┬────┘                     │
     │       │                          ▼
     │       │              ┌───────────────────────┐
     │       │              │      PostgreSQL       │
     │       │              │    (config, audit,    │
     │       │              │    investigations)    │
     │       │              └───────────────────────┘
     │       │
     ▼       ▼
┌──────────┐ ┌─────────────────────────┐
│ Knowledge│ │      External APIs      │
│   Base   │ │   (K8s, AWS, Datadog,   │
│ (RAPTOR) │ │     Grafana, etc.)      │
└──────────┘ └─────────────────────────┘
```

<p align="center">
  <img src="https://github.com/user-attachments/assets/8c785a32-c46a-4d5b-8297-fe13f23a2392" alt="Web Console">
  <br>
  <em>Web Console — Easiest way to view and customize agents</em>
</p>

---

## Under the Hood

The engineering that makes IncidentFox actually work in production:

| Capability | What It Does | Why It Matters |
|------------|--------------|----------------|
| **RAPTOR Knowledge Base** | Hierarchical tree structure (ICLR 2024) — clusters → summarizes → abstracts | Standard RAG fails on 100-page runbooks. RAPTOR maintains context across long documents. |
| **Smart Log Sampling** | Statistics first → sample errors → drill down on anomalies | Other tools load 100K lines and hit context limits. We sample intelligently to stay useful. |
| **Alert Correlation Engine** | 3-layer analysis: temporal + topology + semantic | Groups alerts AND finds root cause. Reduces noise by 85-95%. |
| **Prophet Anomaly Detection** | Meta's Prophet algorithm with seasonality-aware forecasting | Detects anomalies that account for daily/weekly patterns, not just static thresholds. |
| **Dependency Discovery** | Automatic service topology mapping with blast radius analysis | Know what's affected before you start investigating. No manual service maps needed. |
| **300+ Built-in Tools** | Kubernetes, AWS, Azure, GCP, Grafana, Datadog, Prometheus, GitHub, and more | No "bring your own tools" setup. Works out of the box with your stack. |
| **MCP Protocol Support** | Connect to any MCP server for unlimited integrations | Add new tools in minutes via config, not code. |
| **Multi-Agent Orchestration** | Planner routes to specialist agents (K8s, AWS, Metrics, Code, etc.) | Complex investigations get handled by the right expert, not a generic agent. |
| **Model Flexibility** | Supports OpenAI and Claude SDKs — use the model that fits your needs | No vendor lock-in. Switch models or use different models for different tasks. |
| **Continuous Self-Improvement** | Learns from investigations, persists patterns, builds team context | Gets smarter over time. Your past incidents inform future investigations. |

<p align="center">
  <img src="https://github.com/user-attachments/assets/60934195-83bf-4d5d-ab7e-0c32e60dbe86" alt="Knowledge Base">
  <br>
  <em>RAPTOR knowledge base storing 50K+ docs as your proprietary knowledge</em>
</p>

[Full technical details →](docs/FEATURES.md)

---

## Enterprise Ready

Security, compliance, and deep customization for production deployments.

### Context at Scale

Every team is different — different tech stacks, observability tools, incident patterns, and services. Enterprise unlocks **deep specialization**:

| Feature | Description |
|---------|-------------|
| **Auto-Learn Your Org** | We analyze your codebase, Slack history, and past incidents to identify which internal tools matter most for debugging. Then we auto-build integrations. |
| **Team-Specific Agents** | Each team gets agents tuned to their stack. Your payments team and your infra team have different needs — their agents reflect that. |
| **Custom Prompts & Tools** | Auto-learned defaults, with full control to tune. Engineers can adjust prompts, add tools, and configure agents per team. |
| **Context Compounds** | Every investigation makes IncidentFox smarter about your systems. Tribal knowledge gets captured, not lost. |

### Security & Compliance

| Feature | Description |
|---------|-------------|
| **SOC 2 Compliant** | Audited security controls, data handling, and access management |
| **Sandboxed Execution** | Isolated Kubernetes sandboxes for agent execution — no shared state between runs |
| **Secrets Proxy** | Credentials never touch the agent. Envoy proxy injects secrets at request time. |
| **Approval Workflows** | Critical changes (prompts, tools, configs) require review before deployment |
| **SSO/OIDC** | Google, Azure AD, Okta — per-organization configuration |
| **Hierarchical Config** | Org → Business Unit → Team inheritance with override capabilities |
| **Audit Logging** | Full trail of all agent actions, config changes, and investigations |
| **On-Premise** | Deploy entirely in your environment — air-gapped support available |

[Enterprise deployment guide →](docs/DEPLOYMENT.md)

---

## Documentation

| Getting Started | Reference | Development |
|----------------|-----------|-------------|
| [Quick Start](#quick-start-run-locally) | [Features](docs/FEATURES.md) | [Local Development](docs/LOCAL_DEVELOPMENT.md) |
| [Deployment Guide](docs/DEPLOYMENT.md) | [Integrations](docs/INTEGRATIONS.md) | [Contributing Guide](DEVELOPMENT_KNOWLEDGE.md) |
| [Slack Setup](docs/SLACK_SETUP.md) | [Architecture](docs/ARCHITECTURE.md) | [Tools Catalog](agent/docs/TOOLS_CATALOG.md) |

---

## Contributing

We welcome contributions! See issues labeled **good first issue** to get started.

For bugs or feature requests, open an issue on [GitHub](https://github.com/incidentfox/incidentfox/issues).

---

## License

[Apache License 2.0](LICENSE)

---

## See Also

**[Claude Code Plugin](local/claude_code_pack/)** — Standalone SRE tools for individual developers using Claude Code CLI. Not connected to the IncidentFox platform above.

---

## Connect with Us

<p align="center">
  <a href="https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ"><img src="https://img.shields.io/badge/Slack-Community-611f69?style=for-the-badge&logo=slack" alt="Slack"></a>
  &nbsp;
  <a href="https://www.linkedin.com/company/incidentfox/"><img src="https://img.shields.io/badge/LinkedIn-Company-0077B5?style=for-the-badge&logo=linkedin" alt="LinkedIn"></a>
  &nbsp;
  <a href="https://x.com/jimmyweiiiii"><img src="https://img.shields.io/badge/X-@jimmyweiiiii-000000?style=for-the-badge&logo=x" alt="X - Jimmy"></a>
  &nbsp;
  <a href="https://x.com/LongYi1207"><img src="https://img.shields.io/badge/X-@LongYi1207-000000?style=for-the-badge&logo=x" alt="X - LongYi"></a>
</p>

<p align="center">
  <em>Built with ❤️ by the IncidentFox team</em>
</p>
