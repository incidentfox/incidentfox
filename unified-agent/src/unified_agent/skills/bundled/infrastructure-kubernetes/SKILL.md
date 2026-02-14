---
name: kubernetes-debug
description: Kubernetes debugging methodology and scripts. Use for pod crashes, CrashLoopBackOff, OOMKilled, deployment issues, resource problems, or container failures.
category: infrastructure
required_integrations:
  - kubernetes
---

# Kubernetes Debugging

## Core Principle: Events Before Logs

**ALWAYS check pod events BEFORE logs.** Events explain 80% of issues faster:
- OOMKilled → Memory limit exceeded
- ImagePullBackOff → Image not found or auth issue
- FailedScheduling → No nodes with enough resources
- CrashLoopBackOff → Container crashing repeatedly

## Available Scripts

All scripts are in `.claude/skills/infrastructure-kubernetes/scripts/`

### list_pods.py - List pods with status
```bash
python .claude/skills/infrastructure-kubernetes/scripts/list_pods.py -n <namespace> [--label <selector>]

# Examples:
python .claude/skills/infrastructure-kubernetes/scripts/list_pods.py -n otel-demo
python .claude/skills/infrastructure-kubernetes/scripts/list_pods.py -n otel-demo --label app.kubernetes.io/name=payment
```

### get_events.py - Get pod events (USE FIRST!)
```bash
python .claude/skills/infrastructure-kubernetes/scripts/get_events.py <pod-name> -n <namespace>

# Example:
python .claude/skills/infrastructure-kubernetes/scripts/get_events.py payment-7f8b9c6d5-x2k4m -n otel-demo
```

### get_logs.py - Get pod logs
```bash
python .claude/skills/infrastructure-kubernetes/scripts/get_logs.py <pod-name> -n <namespace> [--tail N] [--container NAME]

# Examples:
python .claude/skills/infrastructure-kubernetes/scripts/get_logs.py payment-7f8b9c6d5-x2k4m -n otel-demo --tail 100
python .claude/skills/infrastructure-kubernetes/scripts/get_logs.py payment-7f8b9c6d5-x2k4m -n otel-demo --container payment
```

### describe_pod.py - Detailed pod info
```bash
python .claude/skills/infrastructure-kubernetes/scripts/describe_pod.py <pod-name> -n <namespace>
```

### get_resources.py - Resource usage vs limits
```bash
python .claude/skills/infrastructure-kubernetes/scripts/get_resources.py <pod-name> -n <namespace>
```

### describe_deployment.py - Deployment status
```bash
python .claude/skills/infrastructure-kubernetes/scripts/describe_deployment.py <deployment-name> -n <namespace>
```

### get_history.py - Rollout history
```bash
python .claude/skills/infrastructure-kubernetes/scripts/get_history.py <deployment-name> -n <namespace>
```

## Debugging Workflows

### Pod Not Starting (Pending/CrashLoopBackOff)
1. `list_pods.py` - Check pod status
2. `get_events.py` - Look for scheduling/pull/crash events
3. `describe_pod.py` - Check conditions and container states
4. `get_logs.py` - Only if events don't explain

### Pod Restarting (OOMKilled/Crashes)
1. `get_events.py` - Check for OOMKilled or error events
2. `get_resources.py` - Compare usage vs limits
3. `get_logs.py` - Check for errors before crash
4. `describe_pod.py` - Check restart count and state

### Deployment Not Progressing
1. `describe_deployment.py` - Check replica counts
2. `list_pods.py` - Find stuck pods
3. `get_events.py` - Check events on stuck pods
4. `get_history.py` - Check rollout history for rollback

## Common Issues & Solutions

| Event Reason | Meaning | Action |
|--------------|---------|--------|
| OOMKilled | Container exceeded memory limit | Increase limits or fix memory leak |
| ImagePullBackOff | Can't pull image | Check image name, registry auth |
| CrashLoopBackOff | Container keeps crashing | Check logs for startup errors |
| FailedScheduling | No node can run pod | Check node resources, taints |
| Unhealthy | Liveness probe failed | Check probe config, app health |

## Output Format

When reporting findings, use this structure:

```
## Kubernetes Analysis

**Pod**: <name>
**Namespace**: <namespace>
**Status**: <phase> (Restarts: N)

### Events
- [timestamp] <reason>: <message>

### Issues Found
1. [Issue description with evidence]

### Root Cause Hypothesis
[Based on events and logs]

### Recommended Action
[Specific remediation step]
```
