---
name: kubernetes-debug
description: Kubernetes debugging methodology and scripts. Use for pod crashes, CrashLoopBackOff, OOMKilled, deployment issues, resource problems, or container failures.
---

# Kubernetes Debugging

## Core Principle: Gateway First, Events Before Logs

**ALWAYS start by discovering clusters via the gateway.** Do NOT use kubectl directly — this sandbox has no direct k8s API access. All k8s queries go through the k8s-gateway.

### Step 1: Discover clusters (MANDATORY first step)
```bash
python .claude/skills/infrastructure-kubernetes/scripts/list_clusters.py
```

### Step 2: Use --cluster-id on all scripts
```bash
python .claude/skills/infrastructure-kubernetes/scripts/list_namespaces.py --cluster-id <CLUSTER_ID>
python .claude/skills/infrastructure-kubernetes/scripts/list_pods.py -n production --cluster-id <CLUSTER_ID>
```

**NEVER run kubectl directly.** NEVER run scripts without `--cluster-id`. If `list_clusters.py` returns no clusters, tell the user they need to install the k8s-agent on their cluster first.

**Gateway-capable scripts:** list_pods, get_events, get_logs, describe_pod, describe_deployment, list_namespaces.
**Direct-only scripts (not available in SaaS):** describe_node, get_resources.

**ALWAYS check pod events BEFORE logs.** Events explain 80% of issues faster:
- OOMKilled → Memory limit exceeded
- ImagePullBackOff → Image not found or auth issue
- FailedScheduling → No nodes with enough resources
- CrashLoopBackOff → Container crashing repeatedly

## Available Scripts

All scripts are in `.claude/skills/infrastructure-kubernetes/scripts/`

### list_clusters.py - Discover available remote clusters
```bash
python .claude/skills/infrastructure-kubernetes/scripts/list_clusters.py
python .claude/skills/infrastructure-kubernetes/scripts/list_clusters.py --json
```

### list_pods.py - List pods with status
```bash
python .claude/skills/infrastructure-kubernetes/scripts/list_pods.py -n <namespace> [--label <selector>] [--cluster-id <id>]

# Examples:
python .claude/skills/infrastructure-kubernetes/scripts/list_pods.py -n otel-demo
python .claude/skills/infrastructure-kubernetes/scripts/list_pods.py -n otel-demo --label app.kubernetes.io/name=payment
python .claude/skills/infrastructure-kubernetes/scripts/list_pods.py -n production --cluster-id abc123
```

### get_events.py - Get pod events (USE FIRST!)
```bash
python .claude/skills/infrastructure-kubernetes/scripts/get_events.py <pod-name> -n <namespace> [--cluster-id <id>]

# Examples:
python .claude/skills/infrastructure-kubernetes/scripts/get_events.py payment-7f8b9c6d5-x2k4m -n otel-demo
python .claude/skills/infrastructure-kubernetes/scripts/get_events.py payment-7f8b9c6d5-x2k4m -n production --cluster-id abc123
```

### get_logs.py - Get pod logs
```bash
python .claude/skills/infrastructure-kubernetes/scripts/get_logs.py <pod-name> -n <namespace> [--tail N] [--container NAME] [--cluster-id <id>]

# Examples:
python .claude/skills/infrastructure-kubernetes/scripts/get_logs.py payment-7f8b9c6d5-x2k4m -n otel-demo --tail 100
python .claude/skills/infrastructure-kubernetes/scripts/get_logs.py payment-7f8b9c6d5-x2k4m -n otel-demo --container payment
```

### describe_pod.py - Detailed pod info
```bash
python .claude/skills/infrastructure-kubernetes/scripts/describe_pod.py <pod-name> -n <namespace> [--cluster-id <id>]
```

### describe_deployment.py - Deployment status and rollout history
```bash
python .claude/skills/infrastructure-kubernetes/scripts/describe_deployment.py <deployment-name> -n <namespace> [--cluster-id <id>]

# Example:
python .claude/skills/infrastructure-kubernetes/scripts/describe_deployment.py payment -n otel-demo
```

### list_namespaces.py - List all namespaces
```bash
python .claude/skills/infrastructure-kubernetes/scripts/list_namespaces.py [--cluster-id <id>]
```

### get_resources.py - Resource usage vs limits (direct-only)
```bash
python .claude/skills/infrastructure-kubernetes/scripts/get_resources.py <pod-name> -n <namespace>
```

### describe_node.py - Node status, conditions, and resource usage (direct-only)
```bash
python .claude/skills/infrastructure-kubernetes/scripts/describe_node.py <node-name>
python .claude/skills/infrastructure-kubernetes/scripts/describe_node.py --all

# Examples:
python .claude/skills/infrastructure-kubernetes/scripts/describe_node.py ip-10-0-1-42.ec2.internal
python .claude/skills/infrastructure-kubernetes/scripts/describe_node.py --all --json
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
1. `describe_deployment.py` - Check replica counts and rollout history
2. `list_pods.py` - Find stuck pods
3. `get_events.py` - Check events on stuck pods

### Node Resource Issues (High CPU/Memory, FailedScheduling)
1. `describe_node.py --all` - Check all nodes for conditions and resource usage
2. `describe_node.py <node>` - Deep dive into specific node
3. `list_pods.py` - Check if pods are Pending/FailedScheduling
4. `get_events.py` - Look for FailedScheduling with resource reasons

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
