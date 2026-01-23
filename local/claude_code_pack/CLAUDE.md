# IncidentFox - SRE Tools for Claude Code

You have access to **~100 DevOps & SRE tools** via the IncidentFox MCP server. These tools help with:

- **Kubernetes** - Pods, deployments, logs, events, resources
- **AWS** - EC2, CloudWatch, ECS, cost analysis
- **Observability** - Datadog, Prometheus, Grafana, Elasticsearch, Loki
- **Collaboration** - Slack, PagerDuty, GitHub
- **Analysis** - Anomaly detection, log analysis, blast radius

## Quick Start

Explore your infrastructure (try whichever applies):

```
Check my Kubernetes cluster health
Show my Grafana dashboards
```

## Real Work

Use these tools for actual tasks:

| Use Case | Example |
|----------|---------|
| **Alert Triage** | "Help me triage this alert: [paste]" |
| **Cost Optimization** | "Find AWS costs over the last month and explore reduction opportunities" |
| **CI/CD Debugging** | "Why did my GitHub Actions workflow fail? [paste url]" |
| **Log Analysis** | "Search logs for connection errors" |

## Configuration

Run `get_config_status` to see which integrations are configured. Missing credentials? Use `save_credential` to add them:

```
Save my Datadog API key: [key]
```

## Learn More

- Full docs: `local/claude_code_pack/README.md`
- 85+ tools reference in README
