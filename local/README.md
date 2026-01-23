# IncidentFox Local

AI-powered SRE tools for your terminal.

## Claude Code Plugin

**85+ DevOps & SRE tools for Claude Code.** Query your infrastructure, investigate incidents, analyze costs, and debug CI/CD — all from your terminal.

### Quick Start

```bash
cd claude_code_pack
./install.sh
claude
```

Then try:
```
> Check my Kubernetes cluster health
> What integrations are configured?
> Analyze my AWS costs for the past 30 days
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
