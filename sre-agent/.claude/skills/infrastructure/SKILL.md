---
name: infrastructure
description: Infrastructure debugging for Kubernetes and AWS. Use when investigating pod crashes, deployment issues, resource problems, container failures, or cloud infrastructure issues.
---

# Infrastructure Debugging

## Available Domains

### Kubernetes
For pod crashes, deployment issues, resource problems, container failures.
Use: `/infrastructure-kubernetes`

### AWS (future)
For EC2, ECS, Lambda, and CloudWatch issues.
Coming soon.

## Quick Reference

### Kubernetes Issues
```bash
# List pods in namespace
python .claude/skills/infrastructure-kubernetes/scripts/list_pods.py -n otel-demo

# Get pod events (ALWAYS check first!)
python .claude/skills/infrastructure-kubernetes/scripts/get_events.py <pod-name> -n otel-demo

# Get pod logs
python .claude/skills/infrastructure-kubernetes/scripts/get_logs.py <pod-name> -n otel-demo --tail 100
```

### Common Patterns

| Symptom | First Action | Script |
|---------|--------------|--------|
| Pod CrashLoopBackOff | Check events | `get_events.py` |
| Pod OOMKilled | Check resources | `get_resources.py` |
| Pod Pending | Check events + nodes | `get_events.py` |
| Deployment stuck | Check rollout history | `get_history.py` |
