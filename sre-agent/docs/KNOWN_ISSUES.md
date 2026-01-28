# Known Issues & Workarounds

## Agent-Sandbox Controller: Services Missing Port Specs

### Issue
The agent-sandbox controller (from kubernetes-sigs/agent-sandbox) creates Kubernetes services for sandboxes but doesn't populate the `spec.ports` field, even when `containerPort` is specified in the SandboxTemplate.

This affects both local (Kind) and production (EKS) deployments.

### Impact
- The Sandbox Router cannot connect to sandbox pods (502 Bad Gateway)
- Investigations fail with no response
- Affects all sandboxes created by the controller

### Root Cause
Bug in agent-sandbox controller's service creation logic. The controller creates services with selectors and DNS names, but omits port specifications.

### Solution
We deploy a Kubernetes service patcher (`k8s/service-patcher.yaml`) that:
1. Runs as a lightweight deployment (10m CPU, 32Mi RAM)
2. Watches for sandbox services every 5 seconds
3. Patches any service missing port specs
4. Adds `port: 8888, targetPort: 8888` to enable router connectivity

**Local Development:**
```bash
# Automatically deployed with make dev
make dev

# Or manually:
kubectl apply -f k8s/service-patcher.yaml
```

**Production:**
Automatically deployed with production kustomization:
```bash
kubectl apply -k k8s/production/
```

The patcher runs as a Kubernetes Deployment with proper RBAC permissions and minimal resource footprint.

### Long-term Fix
This should be fixed upstream in the agent-sandbox controller. The controller should respect `containerPort` specifications in the pod template and create service port specs accordingly.

**Relevant Files:**
- `k8s/sandbox-template.yaml`: Specifies `containerPort: 8888`
- `k8s/service-patcher.yaml`: Kubernetes deployment for automated patching
- `scripts/patch-sandbox-services.sh`: Legacy shell script (kept for manual debugging)
- Router expects: `{sandbox-id}.{namespace}.svc.cluster.local:8888`

### Why Not Use Pod IPs Directly?
While we could bypass services and connect directly to pod IPs, this would:
- Defeat the purpose of the Sandbox Router (stateless, scalable routing)
- Require reimplementing routing logic in sandbox_manager.py
- Lose the router's error handling and retry logic

The service patcher is more maintainable and preserves the router architecture.

### History
- PR #20: Used `kubectl port-forward` (tunneling) - worked because it bypassed services
- PR #21: Switched to Sandbox Router - introduced this issue
- Current: Using background patcher as pragmatic workaround

### Alternatives Considered
1. ✅ **Kubernetes service patcher deployment** (current) - Production-ready, works everywhere, minimal overhead
2. ❌ Port-forwarding - Doesn't scale, inconsistent with production
3. ❌ Pod IP routing - Defeats purpose of router, adds complexity
4. ⏳ Fix upstream controller - Long-term solution, requires collaboration with kubernetes-sigs/agent-sandbox
5. ❌ Admission webhook - Overkill for this simple fix, adds operational complexity

