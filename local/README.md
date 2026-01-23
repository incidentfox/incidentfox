# IncidentFox Local

AI-powered SRE tools for your terminal.

## Claude Code Plugin

**Claude Code plugin with ~100 DevOps & SRE tools, skills, and commands** to investigate incidents, analyze costs, and debug CI/CD — all from your terminal.

### Quick Start

```bash
cd claude_code_pack
./install.sh
claude
```

**Quick start** — explore your infrastructure (try whichever applies):
```
> Check my Kubernetes cluster health
> Show my Grafana dashboards
```

**Real work** — use these tools for actual tasks:
```
> Help me triage this alert: [paste alert]
> Find AWS costs over the last month and explore reduction opportunities
> Why did my GitHub Actions workflow fail? [paste url]
```

### What You Get

- 85+ investigation tools (Kubernetes, AWS, Datadog, Prometheus, GitHub, Slack, etc.)
- Unified log search across multiple backends
- Investigation history with pattern learning
- Postmortem generation
- No Docker, no services to manage

**Full documentation:** [claude_code_pack/README.md](./claude_code_pack/README.md)

---

<details>
<summary><strong>Local CLI (Experimental)</strong></summary>

> **Warning:** The local CLI is in early development and not recommended for production use. For a stable experience, use the Claude Code plugin above.

The local CLI is a self-hosted multi-agent system for advanced users who need:
- Custom agent behavior and prompts
- Self-hosted infrastructure
- Non-Claude LLM providers

**Requirements:** Docker, Docker Compose, OpenAI API key

**Documentation:** [incidentfox_cli/README.md](./incidentfox_cli/README.md)

</details>
