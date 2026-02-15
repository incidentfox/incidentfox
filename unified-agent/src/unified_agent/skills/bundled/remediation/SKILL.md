---
name: remediation
description: Safe remediation actions for Kubernetes. Use when proposing or executing pod restarts, deployment scaling, or rollbacks. Always use dry-run first.
category: infrastructure
required_integrations:
  - kubernetes
---

# Remediation Actions

## Safety Principles

1. **ALWAYS dry-run first** - All scripts support `--dry-run` flag
2. **Confirm before executing** - Show what will happen, ask for confirmation
3. **Document the action** - Log what was done and why
4. **Have a rollback plan** - Know how to undo the action

## Available Scripts

All scripts are in `.claude/skills/remediation/scripts/`

### restart_pod.py - Restart a pod by deleting it
```bash
# Dry run (shows what would happen)
python .claude/skills/remediation/scripts/restart_pod.py <pod-name> -n <namespace> --dry-run

# Execute
python .claude/skills/remediation/scripts/restart_pod.py <pod-name> -n <namespace>
```

### scale_deployment.py - Scale a deployment
```bash
# Dry run
python .claude/skills/remediation/scripts/scale_deployment.py <deployment> -n <namespace> --replicas N --dry-run

# Execute
python .claude/skills/remediation/scripts/scale_deployment.py <deployment> -n <namespace> --replicas N
```

### rollback_deployment.py - Rollback to previous revision
```bash
# Dry run (shows current and target revision)
python .claude/skills/remediation/scripts/rollback_deployment.py <deployment> -n <namespace> --dry-run

# Execute
python .claude/skills/remediation/scripts/rollback_deployment.py <deployment> -n <namespace>
```

## Remediation Workflow

1. **Diagnose first** - Use k8s-debugger to understand the issue
2. **Propose action** - State what you plan to do and why
3. **Dry run** - Show what will happen
4. **Get confirmation** - Ask user to confirm
5. **Execute** - Run the action
6. **Verify** - Check that the issue is resolved

## Common Remediation Scenarios

### Pod stuck in CrashLoopBackOff
```bash
# 1. Check events
python .claude/skills/infrastructure/kubernetes/scripts/get_events.py <pod> -n <namespace>

# 2. If fixable by restart, dry-run first
python .claude/skills/remediation/scripts/restart_pod.py <pod> -n <namespace> --dry-run

# 3. Execute restart
python .claude/skills/remediation/scripts/restart_pod.py <pod> -n <namespace>
```

### Deployment stuck with bad image
```bash
# 1. Check history
python .claude/skills/infrastructure/kubernetes/scripts/get_history.py <deployment> -n <namespace>

# 2. Dry-run rollback
python .claude/skills/remediation/scripts/rollback_deployment.py <deployment> -n <namespace> --dry-run

# 3. Execute rollback
python .claude/skills/remediation/scripts/rollback_deployment.py <deployment> -n <namespace>
```

### Service under high load
```bash
# 1. Check current state
python .claude/skills/infrastructure/kubernetes/scripts/describe_deployment.py <deployment> -n <namespace>

# 2. Dry-run scale up
python .claude/skills/remediation/scripts/scale_deployment.py <deployment> -n <namespace> --replicas 5 --dry-run

# 3. Execute scale
python .claude/skills/remediation/scripts/scale_deployment.py <deployment> -n <namespace> --replicas 5
```

## Output Format

When proposing remediation, use this structure:

```
## Proposed Remediation

**Action**: [e.g., Restart pod, Scale deployment, Rollback]
**Target**: [resource name and namespace]
**Reason**: [why this action will help]
**Risk**: [potential side effects]

### Dry Run Output
[output from --dry-run]

### Confirmation Required
Please confirm you want to proceed with this action.
```
