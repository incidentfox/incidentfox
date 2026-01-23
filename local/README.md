# IncidentFox Local

Run IncidentFox AI SRE locally. Choose your preferred setup:

| Option | Best For | Setup Time | Infrastructure |
|--------|----------|------------|----------------|
| **[Claude Code Plugin](#claude-code-plugin)** | Most users | 2 minutes | None |
| **[Local CLI](#local-cli)** | Advanced customization | 10+ minutes | Docker required |

---

## Claude Code Plugin

**Recommended for most users.** Zero infrastructure, works directly in Claude Code with 85+ SRE tools.

### Quick Start

```bash
cd claude_code_pack
./install.sh
```

### What You Get

- 85+ investigation tools (Kubernetes, AWS, Datadog, Prometheus, GitHub, Slack, etc.)
- Unified log search across multiple backends
- Investigation history with pattern learning
- Postmortem generation
- No Docker, no services to manage

### Learn More

See **[claude_code_pack/README.md](./claude_code_pack/README.md)** for full documentation.

---

## Local CLI

**For advanced users** who want maximum customization, custom agents, or self-hosted infrastructure.

> **Note:** The local CLI is still in early development. For a more stable experience, use the Claude Code plugin above.

### Quick Start

```bash
make quickstart
```

### What You Get

- Multi-agent architecture (Planner + specialized sub-agents)
- Self-hosted services (PostgreSQL, Config Service, Agent)
- Full control over prompts and agent behavior
- Web UI for configuration

### Requirements

- Docker & Docker Compose
- OpenAI API key

### Learn More

See **[incidentfox_cli/README.md](./incidentfox_cli/README.md)** for full documentation.

---

## Comparison

| Feature | Claude Code Plugin | Local CLI |
|---------|-------------------|-----------|
| Setup complexity | Simple (2 min) | Complex (requires Docker) |
| Infrastructure | None | PostgreSQL + Services |
| Tools | 85+ MCP tools | 50+ function tools |
| LLM | Claude (via Claude Code) | OpenAI (configurable) |
| Customization | Limited | Full control |
| Stability | Stable | Early development |
| Cost | Claude Code subscription | OpenAI API costs |

## Which Should I Use?

**Use Claude Code Plugin if you:**
- Want the fastest setup
- Already use Claude Code
- Don't need custom agents
- Want a stable, tested experience

**Use Local CLI if you:**
- Need custom agent behavior
- Want to self-host everything
- Need to use a specific LLM provider
- Are comfortable with Docker and early-stage software
