---
name: k8s-debug
description: Kubernetes debugging patterns. Use for pod crashes, CrashLoopBackOff, OOMKilled, ImagePullBackOff, scheduling failures, deployment issues.
---

# Kubernetes Debugging Expertise

## Golden Rule: Events Before Logs

When debugging Kubernetes issues, **ALWAYS check events first**:

1. `get_pod_events` - Shows scheduling, pulling, starting, probes, OOM
2. THEN `get_pod_logs` - Application-level errors

Events explain most crash/scheduling issues faster than logs.

## Typical Investigation Flow

```
1. list_pods        → Get overview of pod health in namespace
2. get_pod_events   → Understand WHY pods are in their state
3. get_pod_logs     → Only if events don't explain the issue
4. get_pod_resources → For performance/resource issues
5. describe_deployment → Check deployment status and conditions
```

## Common Issue Patterns

### CrashLoopBackOff

**First check**: `get_pod_events`

| Event Reason | Likely Cause | Next Step |
|--------------|--------------|-----------|
| OOMKilled | Memory limit too low or memory leak | Check `get_pod_resources`, increase limits |
| Error | Application crash | Check `get_pod_logs` for stack trace |
| BackOff | Repeated failures | Check logs for startup errors |

**Checklist**:
- [ ] Memory limits vs actual usage
- [ ] Recent deployment changes (`get_deployment_history`)
- [ ] Missing config/secrets
- [ ] Dependency failures (database, external services)

### OOMKilled

**First check**: `get_pod_events` (confirms OOMKilled)
**Then**: `get_pod_resources` (compare usage to limits)

**Common causes**:
- Memory limit set too low for workload
- Memory leak (usage increases over time)
- Sudden traffic spike causing memory pressure
- Large request payloads cached in memory

### ImagePullBackOff

**First check**: `get_pod_events`

**Common causes**:
- Wrong image name or tag
- Private registry without imagePullSecrets
- Rate limiting from registry
- Network issues reaching registry

### Pending Pods

**First check**: `get_pod_events`

**Look for**:
- `FailedScheduling` - Insufficient resources
- `Unschedulable` - Node affinity/taints
- No matching nodes for nodeSelector

### Readiness/Liveness Probe Failures

**First check**: `describe_pod` (shows probe config)
**Then**: `get_pod_events` (probe failure events)
**Then**: `get_pod_logs` (why endpoint isn't responding)

### Evicted Pods

**First check**: `get_pod_events`

**Causes**:
- Node resource pressure (disk, memory)
- Priority preemption
- Taint-based eviction

## Deployment Issues

### Stuck Rollout

```
describe_deployment  → Check replicas (desired vs ready vs available)
get_deployment_history → Compare current vs previous revision
get_pod_events → For pods in new ReplicaSet
```

**Common causes**:
- New pods failing (CrashLoopBackOff)
- Readiness probes failing
- Resource constraints preventing scheduling

### Rollback Decision

Use `get_deployment_history` to see previous working versions.

## Error Classification

### Non-Retryable (Stop Immediately)
- 401 Unauthorized - Invalid credentials
- 403 Forbidden - No permission
- 404 Not Found - Resource doesn't exist
- "config_required": true - Integration not configured

### Retryable (May retry once)
- 429 Too Many Requests
- 500/502/503/504 Server errors
- Timeout
- Connection refused

## Resource Investigation Pattern

For memory/CPU issues:

```
1. get_pod_resources → See allocation vs usage
2. describe_pod → See full container spec
3. get_cloudwatch_metrics/query_datadog_metrics → Historical usage
4. detect_anomalies on historical data → Find when issue started
```
