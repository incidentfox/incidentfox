# Kubernetes Integration Guide (SaaS)

Connect your on-premise or private Kubernetes clusters to IncidentFox SaaS without firewall changes.

---

## How It Works

IncidentFox uses an **outbound agent pattern** to access your private Kubernetes clusters:

```
Your Kubernetes Cluster              IncidentFox SaaS
====================                 ================

┌──────────────────┐                ┌──────────────────┐
│ incidentfox-     │   outbound     │  K8s Gateway     │
│ k8s-agent        │───────────────>│  Service         │
│ (Helm chart)     │   HTTPS/SSE    │                  │
└────────┬─────────┘                └────────┬─────────┘
         │                                   │
         ▼                                   ▼
┌──────────────────┐                ┌──────────────────┐
│ K8s API Server   │                │ AI Agent         │
│ (your cluster)   │                │ (investigations) │
└──────────────────┘                └──────────────────┘
```

**Key benefits:**
- No inbound firewall rules needed
- Agent connects outbound to IncidentFox (port 443)
- You control RBAC permissions via Helm values
- Multiple clusters supported per team

---

## Prerequisites

Before you start:

- ✅ IncidentFox SaaS account with a team created
- ✅ Kubernetes cluster (v1.24+)
- ✅ `kubectl` configured and able to access your cluster
- ✅ `helm` v3.x installed
- ✅ Outbound HTTPS access to `ui.incidentfox.ai` (or your self-hosted gateway)

---

## Setup Steps

### Step 1: Generate API Key

1. Log in to the IncidentFox dashboard
2. Navigate to **Settings** → **Integrations** → **Kubernetes**
3. Click **"Add Cluster"**
4. Enter a **Cluster Name** (e.g., `prod-us-east-1`, `staging`)
5. Click **"Generate API Key"**
6. **Copy the API key** (starts with `ixfx_k8s_`) — you won't see it again!

The API key authenticates your agent with IncidentFox. Each cluster needs its own key.

---

### Step 2: Add the Helm Repository

```bash
helm repo add incidentfox https://charts.incidentfox.ai
helm repo update
```

---

### Step 3: Install the Agent

Create a namespace and install the agent:

```bash
# Create namespace
kubectl create namespace incidentfox

# Install the agent
helm install incidentfox-agent incidentfox/incidentfox-k8s-agent \
  --namespace incidentfox \
  --set apiKey=ixfx_k8s_YOUR_API_KEY \
  --set clusterName=prod-us-east-1
```

**Configuration options:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `apiKey` | API key from Step 1 (required) | — |
| `clusterName` | Name shown in IncidentFox dashboard | — |
| `gatewayUrl` | IncidentFox gateway URL | `https://orchestrator.incidentfox.ai/gateway` |
| `replicaCount` | Number of agent replicas | `1` |
| `logLevel` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) | `INFO` |

---

### Step 4: Verify Connection

1. Check agent pod is running:
   ```bash
   kubectl get pods -n incidentfox
   ```

   You should see:
   ```
   NAME                                READY   STATUS    RESTARTS   AGE
   incidentfox-agent-xxx-yyy           1/1     Running   0          30s
   ```

2. Check agent logs for successful connection:
   ```bash
   kubectl logs -n incidentfox -l app.kubernetes.io/name=incidentfox-k8s-agent
   ```

   Look for:
   ```
   {"event": "connected_to_gateway", "cluster_name": "prod-us-east-1"}
   ```

3. Verify in dashboard:
   - Go to **Settings** → **Integrations** → **Kubernetes**
   - Your cluster should show **Status: Connected**

---

## Using Kubernetes in Investigations

Once connected, ask IncidentFox about your cluster:

```
@incidentfox show me failing pods in prod-us-east-1
@incidentfox what's happening with deployment nginx in staging?
@incidentfox get logs from pod api-server-xxx in production
```

If you have multiple clusters, specify which one:
```
@incidentfox list pods in namespace payments on cluster prod-us-east-1
```

---

## RBAC Permissions

The agent uses a ClusterRole to access Kubernetes resources. By default, it has **read-only** access to:

| Resource | Permissions |
|----------|-------------|
| Pods | get, list, watch |
| Pod logs | get |
| Deployments | get, list, watch |
| ReplicaSets | get, list, watch |
| Services | get, list, watch |
| Nodes | get, list, watch |
| Events | get, list, watch |
| ConfigMaps | get, list, watch |
| Namespaces | get, list |

### Customizing RBAC

To restrict or expand permissions, use Helm values:

```yaml
# values.yaml
rbac:
  # Only allow access to specific namespaces
  namespaceRestriction:
    enabled: true
    namespaces:
      - production
      - staging

  # Add custom rules
  additionalRules:
    - apiGroups: ["apps"]
      resources: ["statefulsets"]
      verbs: ["get", "list", "watch"]
```

Apply with:
```bash
helm upgrade incidentfox-agent incidentfox/incidentfox-k8s-agent \
  --namespace incidentfox \
  -f values.yaml
```

---

## Managing Multiple Clusters

Add multiple clusters by repeating the setup for each:

1. Generate a new API key for each cluster
2. Install the agent with a unique release name:

```bash
# Production cluster
helm install incidentfox-agent-prod incidentfox/incidentfox-k8s-agent \
  --namespace incidentfox \
  --set apiKey=ixfx_k8s_PROD_KEY \
  --set clusterName=prod-us-east-1

# Staging cluster (in a different cluster context)
helm install incidentfox-agent-staging incidentfox/incidentfox-k8s-agent \
  --namespace incidentfox \
  --set apiKey=ixfx_k8s_STAGING_KEY \
  --set clusterName=staging
```

In the dashboard, you'll see all connected clusters and can query any of them.

---

## Revoking Access

To disconnect a cluster:

1. **Uninstall the agent:**
   ```bash
   helm uninstall incidentfox-agent -n incidentfox
   ```

2. **Revoke the API key** in the dashboard:
   - Go to **Settings** → **Integrations** → **Kubernetes**
   - Find the cluster and click **"Revoke"**

Revoking the key immediately disconnects the agent, even if it's still running.

---

## Troubleshooting

### Agent not connecting

**Check pod status:**
```bash
kubectl describe pod -n incidentfox -l app.kubernetes.io/name=incidentfox-k8s-agent
```

**Common issues:**

| Symptom | Cause | Solution |
|---------|-------|----------|
| `ImagePullBackOff` | Can't pull agent image | Check network/registry access |
| `CrashLoopBackOff` | Invalid API key | Verify API key in secret |
| `Running` but not connected | Network blocked | Allow outbound HTTPS to gateway |

**Check logs:**
```bash
kubectl logs -n incidentfox -l app.kubernetes.io/name=incidentfox-k8s-agent --tail=100
```

### Connection drops frequently

The agent automatically reconnects with exponential backoff. Frequent disconnections may indicate:
- Unstable network connection
- Gateway maintenance (check status.incidentfox.ai)
- Resource constraints on the agent pod

**Check resource usage:**
```bash
kubectl top pod -n incidentfox
```

**Increase resources if needed:**
```bash
helm upgrade incidentfox-agent incidentfox/incidentfox-k8s-agent \
  --namespace incidentfox \
  --set resources.requests.memory=256Mi \
  --set resources.limits.memory=512Mi
```

### Permission denied errors

If IncidentFox reports permission errors when querying resources:

1. Check the ClusterRole exists:
   ```bash
   kubectl get clusterrole incidentfox-agent
   ```

2. Verify ClusterRoleBinding:
   ```bash
   kubectl get clusterrolebinding incidentfox-agent
   ```

3. Test permissions manually:
   ```bash
   kubectl auth can-i list pods --as=system:serviceaccount:incidentfox:incidentfox-agent
   ```

---

## Security

| Concern | How we address it |
|---------|-------------------|
| **API key security** | Keys are hashed with SHA-256 + pepper; plaintext never stored |
| **Transport** | All traffic encrypted via TLS (HTTPS) |
| **Agent permissions** | You control RBAC; default is read-only |
| **Multi-tenant isolation** | Each team's clusters are isolated; agents can only access their team's data |
| **Audit logging** | All commands from IncidentFox are logged |

---

## Support

- **Email:** support@incidentfox.ai
- **Documentation:** [docs.incidentfox.ai](https://docs.incidentfox.ai)
- **Status:** [status.incidentfox.ai](https://status.incidentfox.ai)

---

## Next Steps

- [Configure other integrations](../INTEGRATIONS.md) (Slack, GitHub, PagerDuty)
- [Learn about investigation capabilities](../FEATURES.md)
- [API Reference](./api-reference.md) for programmatic access
