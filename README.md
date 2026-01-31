# IncidentFox

> **Open-source AI SRE that actually investigates.**

IncidentFox connects to your existing tools — Kubernetes, AWS, Grafana, Datadog, GitHub, Slack — and automatically investigates incidents. It reads logs, queries metrics, traces through service dependencies, and finds root causes. Not just alert correlation. Actual debugging.

**Self-host in 5 minutes. Keep your data in your environment.**

<p align="center">
  <img src="https://github.com/user-attachments/assets/b6892fe8-0a19-40f9-9d86-465aa3387108" width="600" alt="Slack Investigation">
  <br>
  <em>Investigate incidents directly from Slack</em>
</p>

---

## Quick Start

### Option 1: Individual Developers - Claude Code Pack

**Claude Code plugin with ~100 DevOps & SRE tools** to investigate incidents, analyze costs, and debug CI/CD from your terminal.

<p align="center">
  <video src="https://github.com/user-attachments/assets/0965d78d-3d6a-4fd4-809e-d9ada9d9ce2c" width="700" controls autoplay loop muted></video>
</p>


```bash
cd local/claude_code_pack
./install.sh
claude
```

**Try it out:**
```
> Check my Kubernetes cluster health
> Show my Grafana dashboards
> Help me triage this alert: [paste alert]
> Find AWS costs and explore reduction opportunities
```

**Full docs:** [local/claude_code_pack/README.md](local/claude_code_pack/README.md)

---

### Option 2: Teams - Self-Hosted Slack Bot

<p align="center">
  <video src="https://github.com/user-attachments/assets/c51c51f2-3e1f-459e-8ce4-1e2a56c92971" width="700" controls autoplay loop muted></video>
</p>

Get IncidentFox running in your Slack workspace in under 5 minutes.

**Prerequisites:** Docker, Slack workspace, Anthropic API key

#### 1. Create Slack App (2 min)

1. **<a href="https://api.slack.com/apps?new_app=1" target="_blank" rel="noopener noreferrer">
   Click here to create your app
   </a>** → Choose "From an app manifest"

   <img width="1355" height="923" alt="image" src="https://github.com/user-attachments/assets/dfeadd58-a6c2-4b13-8df3-e7b8ac69c886" />


2. Select your workspace
   
   <img width="550" height="380" alt="image" src="https://github.com/user-attachments/assets/0eb2ee77-deb8-4959-841b-8e7d0ede91b2" />

3. Copy
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
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false

```
4. Paste into the YAML field
   
   <img width="532" height="1007" alt="image" src="https://github.com/user-attachments/assets/2b926f88-9f2d-4f66-bb50-cc539b888353" />

5. Click "Create" → "Install App" → "Install to Workspace" → "Allow"
   
<img width="989" height="343" alt="image" src="https://github.com/user-attachments/assets/54cdb087-497c-498a-86f9-31d133ec18c4" />


#### 2. Get Your Tokens (1 min)

**Bot Token:**
- Click **OAuth & Permissions** → Copy "Bot User OAuth Token" (starts with `xoxb-`)
<img width="744" height="559" alt="image" src="https://github.com/user-attachments/assets/0d7ea70c-394d-4787-a3b4-e32f395d44e1" />


**App Token:**
- Click **Basic Information** → **App-Level Tokens**
- Generate token with `connections:write` scope
- Copy token (starts with `xapp-`)
<img width="697" height="747" alt="image" src="https://github.com/user-attachments/assets/620bb92b-db49-4d50-8c22-70682ba008d2" />

**Anthropic API Key**
- [Go to Anthropic console to generate an API Key](https://platform.claude.com/settings/keys)

#### 3. Configure & Run (2 min)

```bash
git clone https://github.com/incidentfox/incidentfox.git
cd incidentfox

# Create config
cp .env.example .env

# Edit .env and add:
# - SLACK_BOT_TOKEN=xoxb-...
# - SLACK_APP_TOKEN=xapp-...
# - ANTHROPIC_API_KEY=sk-ant-...

# Start everything
docker-compose up -d
```

#### 4. Test It

```
# In Slack:
/invite @IncidentFox
@IncidentFox what's 2+2?
```

You should see a streaming response! 🎉

**Detailed setup:** [Slack Integration Guide](docs/INTEGRATIONS.md#slack-bot-primary-interface) | [Deployment Options](docs/DEPLOYMENT.md)

---

## Why IncidentFox?

Most AI SRE tools are either **locked to one vendor** (Datadog Bits AI only works with Datadog) or **stop at alert correlation** (BigPanda groups alerts, humans still debug). IncidentFox is different: it's open-source, works with your existing stack, and actually investigates.

### What Makes Us Different

**Customize agents without code.** Agents are JSON configs — model, prompts, tools, sub-agents. Want your investigation agent to always check your escalation policy first? Edit the prompt in the UI. 30 seconds, no deploy.

**Add integrations in 5 minutes.** MCP protocol means one JSON block to connect any tool ecosystem — AWS EKS, GitHub, Slack, Postgres, 100+ others. No custom integration code. No deployment.

**Config inheritance for multi-team scale.** Org sets defaults (which agents, which integrations). Teams override only what they need. Deep merge at every key — teams add tools without losing org baseline. 50 teams, 5 lines of config each.

**Agents that learn from incidents.** After 100 investigations, the system detects patterns: "You query Kafka 40 times but don't have Kafka tools — add them?" Proposes improvements. Approval-gated, no auto-deploy.

**RAPTOR knowledge base (ICLR 2024).** Not flat vector search. Hierarchical tree that clusters docs → summarizes clusters → builds abstraction layers. 100-page runbook? High-level queries find summaries, detail queries find specifics. Standard RAG fails on dense technical docs.

**Validation before you break production.** Disable an integration? System checks: "Can't disable Grafana — `grafana_query_prometheus` depends on it, and planner agent uses that tool." Catches misconfigs before deploy.

### vs. Competitors

| Capability | IncidentFox | Datadog/Dynatrace | BigPanda/Moogsoft | incident.io/Rootly |
|------------|-------------|-------------------|-------------------|-------------------|
| Works with any stack | ✅ Grafana + Datadog + custom | ❌ Their ecosystem only | ⚠️ Alert ingestion only | ⚠️ Workflow focus |
| Customize agents | ✅ JSON config, no code | ❌ Fixed agents | ❌ N/A | ❌ N/A |
| Add integrations | ✅ 5 min (MCP) | ❌ Wait for vendor | ❌ Custom code | ❌ Custom code |
| Multi-team config | ✅ Inheritance + merge | ❌ Flat | ❌ Flat | ❌ Flat |
| Self-learning | ✅ Gap detection + proposals | ❌ Static | ❌ Static | ❌ Static |
| Knowledge base | ✅ RAPTOR (hierarchical) | ⚠️ Basic RAG | ❌ None | ❌ None |
| Self-hosted | ✅ Docker/Helm/air-gapped | ❌ SaaS only | ⚠️ On-prem available | ❌ SaaS only |
| Open source | ✅ Apache 2.0 | ❌ Proprietary | ❌ Proprietary | ❌ Proprietary |

---

## Features

<p align="center">
  <img src="https://github.com/user-attachments/assets/60934195-83bf-4d5d-ab7e-0c32e60dbe86" alt="Knowledge Base">
  <br>
  <em>Hierarchical RAG for your proprietary knowledge</em>
</p>

### Core Capabilities

- **Dual Agent Runtime** - OpenAI Agents SDK (production) + Claude SDK with K8s sandboxing (exploratory)
- **178+ Built-in Tools** - Kubernetes, AWS, Grafana, Datadog, New Relic, GitHub, Elasticsearch, and more
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

### Extensible

- **Beyond SRE** - Configure for CI/CD fix, cloud cost optimization, security scanning, or any automation
- **A2A Protocol** - Agent-to-agent communication for multi-agent orchestration
- **Custom Prompts** - Per-team agent behavior customization
- **MCP Servers** - Add any integration via Model Context Protocol

**Full feature details:** [docs/FEATURES.md](docs/FEATURES.md)

---

## Integrations

### Primary Interface: Slack Bot

Mention the bot in any channel to start an investigation:

```
@incidentfox why is the payments service slow?
@incidentfox investigate pod nginx-abc123 crashing
```

### Additional Integrations

| Integration | Trigger | Use Case |
|-------------|---------|----------|
| **GitHub Bot** | Comment on PRs/issues | CI/CD debugging, code analysis |
| **PagerDuty** | Webhook on alert | Auto-investigation when incidents fire |
| **A2A Protocol** | API call from another agent | Multi-agent orchestration |
| **REST API** | Direct HTTP | Custom integrations, automation |

### Observability & Infrastructure

Kubernetes • AWS • Grafana • Datadog • New Relic • Prometheus • Elasticsearch • Coralogix

**Setup guides:** [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)

---

## Deployment

<p align="center">
  <img src="https://github.com/user-attachments/assets/8c785a32-c46a-4d5b-8297-fe13f23a2392" alt="Web Console">
  <br>
  <em>Web Console — View and manage multi-agent workflows</em>
</p>

### Deployment Options

| Option | Best For | Get Started |
|--------|----------|-------------|
| **SaaS** | Teams that want to get started immediately — no infrastructure to manage | [ui.incidentfox.ai](https://ui.incidentfox.ai) |
| **Kubernetes (Helm)** | Teams with existing K8s clusters who want full control | [Helm Chart Docs](charts/incidentfox/README.md) |
| **On-Premise** | Organizations with strict security requirements — everything in your environment | [Contact us](mailto:founders@incidentfox.ai) |

### Quick Deploy with Helm

```bash
# Create namespace
kubectl create namespace incidentfox

# Create secrets
kubectl create secret generic incidentfox-database-url \
  --from-literal=DATABASE_URL="postgresql://user:pass@host:5432/incidentfox" \
  -n incidentfox

kubectl create secret generic incidentfox-openai \
  --from-literal=api_key="sk-your-openai-key" \
  -n incidentfox

# Deploy
helm upgrade --install incidentfox ./charts/incidentfox \
  -n incidentfox \
  -f charts/incidentfox/values.yaml

# Check status
kubectl get pods -n incidentfox
```

**Deployment guide:** [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

---

## Documentation

### Getting Started
- **[Quick Start](#quick-start)** - Try locally or self-host in 5 minutes
- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** - Complete deployment guide
- **[local/claude_code_pack/README.md](local/claude_code_pack/README.md)** - Local CLI for developers

### Core Documentation
- **[docs/FEATURES.md](docs/FEATURES.md)** - Detailed feature overview
- **[docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)** - Integration setup guides
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** - System architecture and design
- **[docs/EVALUATION.md](docs/EVALUATION.md)** - Evaluation framework

### Development
- **[DEVELOPMENT_KNOWLEDGE.md](DEVELOPMENT_KNOWLEDGE.md)** - Comprehensive dev reference
- **[agent/README.md](agent/README.md)** - Agent architecture and tools
- **[config_service/README.md](config_service/README.md)** - API and configuration
- **[web_ui/README.md](web_ui/README.md)** - Frontend development

### Advanced Topics
- **[docs/ARCHITECTURE_DECISIONS.md](docs/ARCHITECTURE_DECISIONS.md)** - Key ADRs and rationale
- **[agent/docs/TOOLS_CATALOG.md](agent/docs/TOOLS_CATALOG.md)** - Complete list of 178 built-in tools
- **[agent/docs/A2A_PROTOCOL.md](agent/docs/A2A_PROTOCOL.md)** - Agent-to-agent communication
- **[agent/docs/MCP_CLIENT_IMPLEMENTATION.md](agent/docs/MCP_CLIENT_IMPLEMENTATION.md)** - Dynamic tool loading via MCP

---

## Commercial Options

IncidentFox is open source and free to use. For teams that need more:

| Option | What You Get |
|--------|--------------|
| **SaaS** | Fully managed at [ui.incidentfox.ai](https://ui.incidentfox.ai) |
| **On-Premise Enterprise** | Maximum security — all data stays in your environment |
| **Premium Features** | Correlation engine, learning pipeline, dependency discovery |
| **Professional Services** | Custom integrations, training, dedicated support |

**Contact:** [founders@incidentfox.ai](mailto:founders@incidentfox.ai)

---

## Roadmap

### Completed
- [x] Multi-agent architecture with Agent-as-Tool pattern
- [x] 178+ tools across K8s, AWS, Grafana, GitHub, etc.
- [x] Slack, GitHub, PagerDuty, A2A integrations
- [x] Enterprise governance (SSO, RBAC, audit)
- [x] RAPTOR knowledge base (hierarchical retrieval)
- [x] Alert correlation engine (temporal + topology + semantic)
- [x] Dual agent support (OpenAI + Claude with sandboxing)
- [x] Continuous learning pipeline
- [x] Evaluation framework with fault injection scoring

### In Progress
- [ ] Custom tool generation from descriptions
- [ ] Enhanced A2A protocol documentation
- [ ] More MCP server integrations

---

## Contributing

We welcome contributions! See issues labeled **good first issue** to get started.

For bugs or feature requests, please open an issue at [GitHub Issues](https://github.com/incidentfox/incidentfox/issues).

---

## License

This project is licensed under the [Apache License 2.0](LICENSE).

---

**Enjoy investigating! 🦊**
