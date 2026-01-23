# IncidentFox - SRE Tools for Claude Code

You have access to **85+ SRE investigation tools** via the IncidentFox MCP server. These tools help with:

- **Kubernetes** - Pods, deployments, logs, events, resources
- **AWS** - EC2, CloudWatch, ECS, cost analysis
- **Observability** - Datadog, Prometheus, Grafana, Elasticsearch, Loki
- **Collaboration** - Slack, PagerDuty, GitHub
- **Analysis** - Anomaly detection, log analysis, blast radius

## Quick Start Commands

Try these read-only commands to explore your infrastructure:

```
Check my Kubernetes cluster health
List pods in the default namespace
Show recent errors from Datadog logs
What AWS resources am I running?
```

## Common Use Cases

### Alert Triage
```
Help me investigate this alert: [paste alert]
What's causing high latency in the payment service?
```

### AWS Cost Optimization
```
Analyze my AWS costs for the past 30 days
Find EC2 instances that could be rightsized
```

### CI/CD Debugging
```
Why did my GitHub workflow fail?
Show me the last 5 failed deployments
```

### Incident Investigation
```
/incident [description] - Start structured investigation
```

## Configuration

Run `get_config_status` to see which integrations are configured. Missing credentials? Use `save_credential` to add them:

```
Save my Datadog API key: [key]
```

## Learn More

- Full docs: `local/claude_code_pack/README.md`
- 85+ tools reference in README
