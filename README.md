# IncidentFox

> **Build the world's best AI SRE.**

AI-powered incident investigation and infrastructure automation. IncidentFox integrates with your observability stack, infrastructure, and collaboration tools to automatically investigate incidents, find root causes, and suggest fixes.

**[Try it for free right now](https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ), or [spin up the docker locally](#quick-start) in 5 minutes.**

<p align="center">
  <img src="https://github.com/user-attachments/assets/b6892fe8-0a19-40f9-9d86-465aa3387108" width="600" alt="Slack Investigation">
  <br>
  <em>Investigate incidents directly from Slack</em>
</p>

---

## Why IncidentFox?

| Challenge | How IncidentFox Helps |
|-----------|----------------------|
| **Alert fatigue** | Correlation engine reduces noise 85-95% using temporal, topology, and semantic analysis |
| **Context switching** | Stay in Slack — investigations stream updates directly to your channel |
| **Tribal knowledge silos** | RAPTOR knowledge base learns your runbooks and past incidents |
| **Tool sprawl** | 178+ built-in integrations, plus MCP protocol for anything else |

---

## Table of Contents

- [Get Started](#get-started)
- [Quick Start: Local Docker + Slack](#quick-start)
- [Features](#features)
- [Integrations](#integrations)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Get Started

|  | **Try Free** | **Local Docker** | **Self-Host** | **Managed** |
|---|--------------|------------------|---------------|-------------|
| **Best for** | Quick exploration | Evaluating with your team | Production, full control | Production, premium features |
| **How** | Join our Slack | Docker Compose | Kubernetes (Helm) | On-prem or SaaS |
| **Setup time** | Instant | 5 minutes | 30 minutes | [Contact us](mailto:founders@incidentfox.ai) |
| **Cost** | Free | Free | Free (open source) | Custom pricing |
|  | [Join Slack →](https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ) | [Quick Start ↓](#quick-start) | [Deployment Guide →](docs/DEPLOYMENT.md) | [Get in Touch →](mailto:founders@incidentfox.ai) |

---

## Quick Start

Get IncidentFox running locally with Docker and Slack in 5 minutes.

**Prerequisites:** Docker, Slack workspace admin access, Anthropic API key

<p align="center">
  <video src="https://github.com/user-attachments/assets/c51c51f2-3e1f-459e-8ce4-1e2a56c92971" width="700" controls autoplay loop muted></video>
</p>

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps?new_app=1) → **Create New App** → **From an app manifest**
2. Select your workspace
3. Paste this manifest:

```yaml
display_information:
  name: IncidentFox
  description: AI-powered SRE agent for incident investigation
  background_color: "#4A154B"
features:
  bot_user:
    display_name: IncidentFox
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - channels:history
      - channels:read
      - chat:write
      - files:read
      - files:write
      - users:read
      - reactions:write
      - im:history
      - groups:history
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.channels
      - message.groups
      - message.im
  interactivity:
    is_enabled: true
  socket_mode_enabled: true
```

4. Click **Create** → **Install to Workspace** → **Allow**

### 2. Get Your Tokens

| Token | Where to Find It |
|-------|------------------|
| **Bot Token** (`xoxb-...`) | OAuth & Permissions → Bot User OAuth Token |
| **App Token** (`xapp-...`) | Basic Information → App-Level Tokens → Generate with `connections:write` scope |
| **Anthropic API Key** | [console.anthropic.com](https://console.anthropic.com) |

### 3. Run IncidentFox

```bash
git clone https://github.com/incidentfox/incidentfox.git
cd incidentfox

cp .env.example .env
# Edit .env with your tokens:
#   SLACK_BOT_TOKEN=xoxb-...
#   SLACK_APP_TOKEN=xapp-...
#   ANTHROPIC_API_KEY=sk-ant-...

docker-compose up -d
```

### 4. Test It

In Slack:
```
/invite @IncidentFox
@IncidentFox what pods are running in my cluster?
```

**Need help?** See the [detailed setup guide](docs/SLACK_SETUP.md) with screenshots.

---

## Features

### Core Platform

- **Slack-Native Interface** — Investigations stream directly to your channels with rich formatting
- **178+ Built-in Tools** — Kubernetes, AWS, Grafana, Datadog, Prometheus, GitHub, and more
- **MCP Protocol Support** — Connect to any MCP server for unlimited integrations

### AI Capabilities

- **RAPTOR Knowledge Base** — Hierarchical retrieval that learns from your runbooks and past incidents
- **Alert Correlation Engine** — Temporal + topology + semantic analysis reduces alert noise by 85-95%
- **Smart Log Sampling** — Prevents context overflow with intelligent sampling strategies

### Enterprise

- **Deployment Options** — SaaS, Kubernetes (Helm), or fully on-premise
- **SSO/OIDC** — Google, Azure AD, Okta
- **Hierarchical Config** — Org → Team inheritance with overrides
- **Audit Logging** — Full trail of all agent actions

[Full feature details →](docs/FEATURES.md)

---

## Integrations

**Triggers:** Slack · GitHub Bot · PagerDuty · REST API · A2A Protocol

**Observability:** Grafana · Datadog · New Relic · Prometheus · Elasticsearch · Coralogix

**Infrastructure:** Kubernetes · AWS · Docker

**Code:** GitHub · GitLab

[Integration setup guides →](docs/INTEGRATIONS.md)

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
