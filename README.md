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

### 🚀 Try IncidentFox Now

<p align="center">
  <a href="https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ"><img src="https://img.shields.io/badge/Try%20Free-Join%20Our%20Slack-611f69?style=for-the-badge&logo=slack" alt="Join our Slack"></a>
  &nbsp;&nbsp;
  <a href="https://slack.com/oauth/v2/authorize?client_id=9967324357443.10323403264580&scope=app_mentions:read,channels:history,channels:join,channels:read,chat:write,chat:write.customize,commands,files:read,files:write,groups:history,groups:read,im:history,im:read,im:write,links:read,links:write,metadata.message:read,mpim:history,mpim:read,reactions:read,reactions:write,usergroups:read,users:read&user_scope="><img alt="Add to Slack" height="40" width="139" src="https://platform.slack-edge.com/img/add_to_slack.png" srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x" /></a>
</p>

**1️⃣ Try Free in Our Workspace** (Easiest)
No setup required. Join our public Slack and start investigating right away. IncidentFox is already installed and connected to our playground telemetry.

**2️⃣ Add to Your Workspace** (Recommended)
Install IncidentFox in your own Slack with 1-click. **7-day free trial** included. Connect to your own infrastructure and telemetry. Don't have permission to install in your company Slack? Create a new workspace and try it there!

---

### 📦 All Deployment Options

|  | **Try Free** | **Local Docker** | **Self-Host** | **Managed** |
|---|--------------|------------------|---------------|-------------|
| **Best for** | Quick exploration | Evaluating with your team | Production, full control | Production, premium features |
| **How** | Join our Slack | Docker Compose | Kubernetes (Helm) | On-prem or SaaS |
| **Setup time** | Instant | 5 minutes | 30 minutes | 30 minutes |
| **Cost** | Free | Free | Free (open source) | Custom pricing |
| **Privacy** | Playground telemetry | Everything local | Everything local | Your choice |
|  | [Join Slack →](https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ) | [Quick Start ↓](#quick-start) | [Deployment Guide →](docs/DEPLOYMENT.md) | [Get in Touch →](mailto:founders@incidentfox.ai) |

**Security-conscious?** Use **Local Docker** or **Self-Host** for complete data control. Everything runs locally — your telemetry, logs, and infrastructure never leave your environment. You can also bring your own API key or internal router URL, so no data leaves your company. [Watch setup video →](#quick-start)

---

## Quick Start: Local Docker + Slack Bot

Run IncidentFox **100% locally** with Docker. Everything stays on your machine — no data leaves your environment. Perfect for security-conscious teams or individual evaluation.

<p align="center">
  <video src="https://github.com/user-attachments/assets/c51c51f2-3e1f-459e-8ce4-1e2a56c92971" width="700" controls autoplay loop muted></video>
  <br>
  <em>Watch: Setting up IncidentFox locally with Slack in 5 minutes</em>
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

### 🔒 Maximum Privacy: Bring Your Own Key

For organizations with strict data governance:
- **Use your own API key** — Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` to use your own LLM account
- **Use your internal router** — Point to your company's internal LLM router URL
- **No data leaves your company** — All requests stay within your environment

See [deployment guide](docs/DEPLOYMENT.md) for details.

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
  ┌───────────────────────────────────┐    ┌─────────────────────┐
  │   Slack · GitHub · PagerDuty · API │    │       Web UI        │
  └─────────────────┬─────────────────┘    │  (dashboard, team   │
                    │ webhooks             │   management)       │
  ┌─────────────────▼─────────────────┐    └──────────┬──────────┘
  │            Orchestrator            │               │
  │   (routes webhooks, team lookup,   │               │
  │    token auth, audit logging)      │               │
  └───────┬───────────────────┬───────┘               │
          │                   │                       │
  ┌───────▼───────┐    ┌──────▼───────────────────────▼──┐
  │     Agent     │◄──►│        Config Service           │
  │ (Claude/OpenAI│    │  (multi-tenant cfg, RBAC,       │
  │  300+ tools,  │    │   routing, team hierarchy)      │
  │  multi-agent) │    └──────────────┬─────────────────┘
  └───┬───────┬───┘                   │
      │       │                       ▼
      │       │           ┌─────────────────────┐
      │       │           │     PostgreSQL      │
      │       │           │  (config, audit,    │
      │       │           │   investigations)   │
      │       │           └─────────────────────┘
      │       │
      ▼       ▼
  ┌────────┐ ┌────────────────────┐
  │Knowledge│ │   External APIs    │
  │  Base   │ │  (K8s, AWS, Datadog│
  │ (RAPTOR)│ │   Grafana, etc.)   │
  └─────────┘ └────────────────────┘
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
