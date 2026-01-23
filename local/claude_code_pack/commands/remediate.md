---
description: Propose a Kubernetes remediation action
allowed-tools:
  - incidentfox__propose_pod_restart
  - incidentfox__propose_deployment_restart
  - incidentfox__propose_scale_deployment
  - incidentfox__list_pods
  - incidentfox__describe_deployment
---

# Remediation Actions

Available remediation actions:

1. **Pod Restart**: Delete a specific pod (controller will recreate)
   ```
   /remediate restart pod <pod-name> [namespace] [reason]
   ```

2. **Deployment Restart**: Rolling restart of all pods in a deployment
   ```
   /remediate restart deployment <deployment-name> [namespace] [reason]
   ```

3. **Scale Deployment**: Change replica count
   ```
   /remediate scale <deployment-name> <replicas> [namespace] [reason]
   ```

**Request**: $ARGUMENTS

All remediation actions will show a confirmation before execution.

Let me help you with this remediation.
