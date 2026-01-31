# IncidentFox

AI-powered incident investigation and infrastructure automation. IncidentFox integrates with your observability stack, infrastructure, and collaboration tools to automatically investigate incidents, find root causes, and suggest fixes.

**[Try it for free right now](https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ), or [spin up the docker locally](#quick-start) in 5 minutes.**

<p align="center">
  <img src="https://github.com/user-attachments/assets/b6892fe8-0a19-40f9-9d86-465aa3387108" width="600" alt="Slack Investigation">
  <br>
  <em>Investigate incidents directly from Slack</em>
</p>

---

## Table of Contents

- [What is IncidentFox?](#what-is-incidentfox)
- [Get Started](#get-started)
- [Quick Start: Local Docker + Slack](#quick-start)
- [Deploy for Your Team](#deploy-for-your-team)
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

IncidentFox is **open source** (Apache 2.0). All core features are free — deploy anywhere, no restrictions.

For teams that need more, we offer **managed deployments**, **premium features** (advanced analytics, priority support), and **professional services**. [Contact us →](mailto:founders@incidentfox.ai)

|  | **Try Free** | **Local Docker** | **Self-Host** | **Managed** |
|---|--------------|------------------|---------------|-------------|
| **Best for** | Quick exploration | Evaluating with your team | Production, full control | Production, premium features |
| **How** | Join our Slack | Docker Compose | Kubernetes (Helm) | On-prem or SaaS |
| **Setup time** | Instant | 5 minutes | 30 minutes | 30 minutes |
| **Cost** | Free | Free | Free (open source) | Custom pricing |
|  | [Join Slack →](https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ) | [Quick Start ↓](#quick-start) | [Deployment Guide →](docs/DEPLOYMENT.md) | [Get in Touch →](mailto:founders@incidentfox.ai) |

---

## Quick Start

Run IncidentFox on your local machine with Docker. Perfect for individual evaluation or small team trials.

<p align="center">
  <video src="https://github.com/user-attachments/assets/c51c51f2-3e1f-459e-8ce4-1e2a56c92971" width="700" controls autoplay loop muted></video>
</p>

**1.** [Create a Slack app](https://api.slack.com/apps?new_app=1) using [this manifest](docs/slack-manifest.yaml)

**2.** Clone and configure:

```bash
git clone https://github.com/incidentfox/incidentfox.git && cd incidentfox
cp .env.example .env
# Add your tokens to .env (see below)
docker-compose up -d
```

<details>
<summary>Where to get your tokens</summary>

| Token | Where to Find It |
|-------|------------------|
| `SLACK_BOT_TOKEN` | Slack app → **OAuth & Permissions** → Bot User OAuth Token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Slack app → **Basic Information** → App-Level Tokens → Generate with `connections:write` (`xapp-...`) |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |

</details>

**3.** Test it in Slack:

```
/invite @IncidentFox
@IncidentFox what pods are running in my cluster?
```

**Need help?** See the [detailed setup guide](docs/SLACK_SETUP.md) with screenshots.

---

## Deploy for Your Team

For production deployments, use our Helm charts to deploy IncidentFox on Kubernetes.

### Quick Deploy

```bash
helm repo add incidentfox https://charts.incidentfox.ai
helm install incidentfox incidentfox/incidentfox -n incidentfox --create-namespace
```

**Full deployment guide:** [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | **Helm chart docs:** [charts/incidentfox/README.md](charts/incidentfox/README.md)

### Architecture Overview

```
                    ┌─────────────────────────────────────┐
                    │   Slack · GitHub · PagerDuty · API   │
                    └──────────────────┬──────────────────┘
                                       │ webhooks
                    ┌──────────────────▼──────────────────┐
                    │            Orchestrator              │
                    │   (routes webhooks, team lookup,     │
                    │    token auth, audit logging)        │
                    └───────┬─────────────────┬───────────┘
                            │                 │
          ┌─────────────────▼───┐    ┌────────▼────────────┐
          │       Agent         │◄──►│   Config Service    │◄──┐
          │  (OpenAI/Claude SDK,│    │  (multi-tenant cfg, │   │
          │   178+ tools,       │    │   RBAC, routing,    │   │
          │   multi-agent)      │    │   team hierarchy)   │   │
          └─────────┬───────────┘    └──────────┬─────────┘   │
                    │                           │             │
                    ▼                           ▼             │
          ┌────────────────────┐    ┌─────────────────────┐   │
          │  Knowledge Base    │    │     PostgreSQL      │   │
          │  (RAPTOR trees,    │    │  (config, audit,    │   │
          │   runbooks, docs)  │    │   investigations)   │   │
          └────────────────────┘    └─────────────────────┘   │
                    │                                         │
                    ▼                                         │
          ┌────────────────────┐    ┌─────────────────────┐   │
          │   External APIs    │    │       Web UI        │───┘
          │  (K8s, AWS, Datadog│    │  (dashboard, team   │
          │   Grafana, etc.)   │    │   management)       │
          └────────────────────┘    └─────────────────────┘
```

<p align="center">
  <img src="https://github.com/user-attachments/assets/8c785a32-c46a-4d5b-8297-fe13f23a2392" alt="Web Console">
  <br>
  <em>Web Console — Easiest way to view and customize agents</em>
</p>

---

## Under the Hood

The engineering that makes IncidentFox actually work in production:

<p align="center">
  <img src="https://github.com/user-attachments/assets/60934195-83bf-4d5d-ab7e-0c32e60dbe86" alt="Knowledge Base">
  <br>
  <em>Hierarchical RAG for your proprietary knowledge</em>
</p>

| Capability | What It Does | Why It Matters |
|------------|--------------|----------------|
| **RAPTOR Knowledge Base** | Hierarchical tree structure (ICLR 2024) — clusters → summarizes → abstracts | Standard RAG fails on 100-page runbooks. RAPTOR maintains context across long documents. |
| **Smart Log Sampling** | Statistics first → sample errors → drill down on anomalies | Other tools load 100K lines and hit context limits. We sample intelligently to stay useful. |
| **Alert Correlation Engine** | 3-layer analysis: temporal + topology + semantic | Groups alerts AND finds root cause. Reduces noise by 85-95%. |
| **178+ Built-in Tools** | Kubernetes, AWS, Grafana, Datadog, Prometheus, GitHub, and more | No "bring your own tools" setup. Works out of the box with your stack. |
| **MCP Protocol Support** | Connect to any MCP server for unlimited integrations | Add new tools in minutes via config, not code. |
| **Multi-Agent Orchestration** | Planner routes to specialist agents (K8s, AWS, Metrics, Code, etc.) | Complex investigations get handled by the right expert, not a generic agent. |

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
