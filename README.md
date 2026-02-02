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

<p align="center">
  <img src="https://github.com/user-attachments/assets/b6892fe8-0a19-40f9-9d86-465aa3387108" width="600" alt="Slack Investigation">
  <br>
  <em>Investigate incidents directly from Slack</em>
</p>

---

## Table of Contents

- [What is IncidentFox?](#what-is-incidentfox)
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

## Get Started

IncidentFox is **open source** (Apache 2.0). You can try it instantly in Slack, or deploy it yourself for full control. Pick the option that fits your needs:

| Option | Best For | Setup Time | Cost | Privacy | |
|--------|----------|------------|------|---------|---|
| **Try Free** | See it in action | Instant | Free | Our playground environment | [![Join Slack](https://img.shields.io/badge/Join_Slack-4A154B?logo=slack&logoColor=white)](https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ) |
| **Local Docker** | Evaluate with your infra | 5 minutes | Free | Everything local | [Setup Guide →](docs/SLACK_SETUP.md) |
| **Managed (premium features)** | Production, we handle ops | 30 minutes | [Contact us (7-day free trial)](mailto:founders@incidentfox.ai) | SaaS or on-prem, SOC2 | [![Add to Slack](https://img.shields.io/badge/Add_to_Slack-4A154B?logo=slack&logoColor=white)](https://slack.com/oauth/v2/authorize?client_id=9967324357443.10323403264580&scope=app_mentions:read,channels:history,channels:join,channels:read,chat:write,chat:write.customize,commands,files:read,files:write,groups:history,groups:read,im:history,im:read,im:write,links:read,links:write,metadata.message:read,mpim:history,mpim:read,reactions:read,reactions:write,usergroups:read,users:read&user_scope=) |
| **Self-Host (Open Core)** | Production, full control | 30 minutes | Free | Everything local | [Deployment Guide →](docs/DEPLOYMENT.md) |

**New to IncidentFox?** We recommend trying it in our Slack first — no setup required, see how it works instantly. [![Join Slack](https://img.shields.io/badge/Join_Slack-4A154B?logo=slack&logoColor=white)](https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ)

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
┌────────▼────────┐   ┌────▼─────────────────────────▼────┐
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

Security and compliance for production deployments:

| Feature | Description |
|---------|-------------|
| **SOC 2 Compliant** | Audited security controls, data handling, and access management |
| **Claude Sandbox** | Isolated Kubernetes sandboxes for agent execution — no shared state between runs |
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
| [Quick Start](#quick-start) | [Features](docs/FEATURES.md) | [Dev Guide](DEVELOPMENT_KNOWLEDGE.md) |
| [Deployment Guide](docs/DEPLOYMENT.md) | [Integrations](docs/INTEGRATIONS.md) | [Agent Architecture](agent/README.md) |
| [Slack Setup (detailed)](docs/SLACK_SETUP.md) | [Architecture](docs/ARCHITECTURE.md) | [Tools Catalog](agent/docs/TOOLS_CATALOG.md) |

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
