# IncidentFox SRE Agent - AI Agent Instructions

## Project Overview

Production-ready AI agent service for incident investigation using Claude Agent SDK with Kubernetes sandbox isolation. Each investigation runs in an isolated sandbox (K8s pod) for safety and filesystem isolation.

## Architecture: Skills + Scripts + Subagents

This agent uses a **progressive disclosure architecture** for optimal context efficiency:

```
┌─────────────────────────────────────────────────────────────────┐
│                        Main Agent                                │
│  Tools: Read, Bash, Glob, Grep, Task                            │
│  Skills: .claude/skills/* (metadata only at startup)            │
│  Context at startup: ~500 tokens (skill metadata only!)         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Task tool (spawns subagents)
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   log-analyst   │  │  k8s-debugger   │  │   remediator    │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ Loads:          │  │ Loads:          │  │ Loads:          │
│ • observability │  │ • infrastructure│  │ • remediation   │
│ • coralogix     │  │ • kubernetes    │  │                 │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ Executes:       │  │ Executes:       │  │ Executes:       │
│ scripts/*.py    │  │ scripts/*.py    │  │ scripts/*.py    │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ Returns:        │  │ Returns:        │  │ Returns:        │
│ Summary only    │  │ Summary only    │  │ Action result   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### Why This Architecture?

| Component | Purpose | Context Cost |
|-----------|---------|--------------|
| **Skills** | Progressive knowledge disclosure | ~100 tokens metadata, loaded on-demand |
| **Scripts** | API integrations via Bash | Output only in context |
| **Subagents** | Context isolation for deep work | Findings only returned |

**No MCP tools** - All integrations use skills with scripts. This avoids context bloat from tool descriptions.

## Skill Hierarchy

```
.claude/skills/
├── investigate/
│   └── SKILL.md                    # Universal 5-phase methodology
│
├── infrastructure/
│   ├── SKILL.md                    # Overview
│   └── kubernetes/
│       ├── SKILL.md                # K8s debugging methodology
│       └── scripts/
│           ├── list_pods.py
│           ├── get_events.py       # ALWAYS check first!
│           ├── get_logs.py
│           ├── describe_pod.py
│           └── get_resources.py
│
├── observability/
│   ├── SKILL.md                    # Universal signal analysis
│   └── coralogix/
│       ├── SKILL.md                # DataPrime syntax reference
│       └── scripts/
│           ├── query_logs.py       # Execute any DataPrime query
│           ├── get_errors.py       # Get errors for a service
│           ├── list_services.py    # List active services
│           └── get_health.py       # Service health summary
│
└── remediation/
    ├── SKILL.md                    # Safe remediation methodology
    └── scripts/
        ├── restart_pod.py          # --dry-run by default
        ├── scale_deployment.py
        └── rollback_deployment.py
```

## Subagents

| Subagent | When to Use | What It Does |
|----------|-------------|--------------|
| `log-analyst` | Deep log analysis (5+ queries) | Reads observability skills, runs Coralogix scripts, returns summary |
| `k8s-debugger` | Pod/deployment issues | Reads K8s skills, runs kubectl scripts, returns summary |
| `remediator` | Safe remediation actions | Always dry-run first, requires confirmation |

### Invoking Subagents

Claude automatically invokes subagents based on the task, or you can be explicit:
- "Investigate the payment service errors" → Claude may spawn log-analyst
- "Use the k8s-debugger to check the checkout pod" → Explicit invocation

## Environment Context

The agent is pre-configured with knowledge of the **OpenTelemetry Demo Microservices** environment:

**Kubernetes:**
- Cluster: incidentfox-demo (AWS EKS)
- Namespace: `otel-demo` (default)
- Label convention: `app.kubernetes.io/name=<short-name>` (e.g., `payment` not `paymentservice`)

**Observability:**
- Platform: Coralogix (cx498.coralogix.com, US2 region)
- Domain: https://incidentfox.app.cx498.coralogix.com/

**Services (18 microservices):**
- Frontend: `frontend` (Next.js), `frontendproxy` (Envoy)
- Core: `checkout` (Go), `payment` (Node.js), `cart` (.NET), `productcatalog` (Go)
- Support: `recommendation` (Python), `currency` (C++), `shipping` (Rust), `email` (Ruby)

## Development Workflow

### Quick Commands
```bash
# Local Development
make setup-local    # Creates Kind cluster, installs controller
make dev           # Build, deploy, port-forward
make test-local    # Quick sanity check

# Production
make deploy-prod   # Multi-platform build, push to ECR, rollout
make test-prod     # Quick sanity check
```

### Testing Skills Locally

```bash
# Test Coralogix scripts
cd .claude/skills/observability/coralogix/scripts
python list_services.py --time-range 60
python get_health.py payment --app otel-demo

# Test K8s scripts
cd .claude/skills/infrastructure/kubernetes/scripts
python list_pods.py -n otel-demo
python get_events.py payment-xxx -n otel-demo
```

## Code Standards

### Philosophy
1. **Progressive disclosure** - Load knowledge only when needed
2. **Statistics before samples** - Aggregations first, raw data second
3. **Events before logs** - K8s events explain most issues faster
4. **Subagents for deep work** - Keep main context clean

### Key Files
- `agent.py` - InteractiveAgentSession with subagent definitions
- `sandbox_server.py` - Sandbox runtime
- `.claude/skills/` - Hierarchical skill structure

## Sandbox Architecture

- **One sandbox per thread** - Each investigation gets isolated K8s pod
- **Persistent sessions** - ClaudeSDKClient sessions survive interrupts
- **gVisor in production** - Enhanced isolation

### Communication Flow
```
User → Main Server → Sandbox Router → Sandbox Pod → ClaudeSDKClient → Claude API
```

## Dependencies

Key dependencies (all pinned in pyproject.toml):
- `claude-agent-sdk==0.1.19` - Core SDK with skill/subagent support
- `kubernetes>=34.1.0` - K8s client for scripts
- `httpx>=0.28.1` - HTTP client for Coralogix API
- `lmnr[claude-agent-sdk]==0.7.32` - Laminar observability

## Configuration & Credentials

### Environment Variables

Check what's configured:
- `CORALOGIX_API_KEY`, `CORALOGIX_DOMAIN` → Coralogix logs/metrics/traces
- `KUBECONFIG` → Kubernetes cluster access (auto-detected)
- `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` → AWS services & EKS auth
- `DATADOG_API_KEY`, `DATADOG_APP_KEY` → Datadog (future)

### Sandbox Credentials

All environment variables are automatically passed to sandbox pods via Kubernetes secrets:

1. **Local setup** creates secret from `.env`:
   ```bash
   ./scripts/setup-local.sh
   # Creates: kubectl create secret generic incidentfox-secrets --from-literal=...
   ```

2. **Sandbox pods** mount secrets as environment variables:
   ```yaml
   env:
   - name: CORALOGIX_API_KEY
     valueFrom:
       secretKeyRef:
         name: incidentfox-secrets
         key: coralogix-api-key
         optional: true  # Won't fail if missing
   ```

3. **Skills/scripts** use env vars directly:
   ```python
   # In .claude/skills/observability/coralogix/scripts/query_logs.py
   api_key = os.getenv("CORALOGIX_API_KEY")
   domain = os.getenv("CORALOGIX_DOMAIN")
   ```

### Updating Credentials

```bash
# Update .env
vim .env  # Add/modify credentials

# Recreate secret
kubectl delete secret incidentfox-secrets
./scripts/setup-local.sh

# Restart server (picks up new secret)
# New sandboxes automatically get updated credentials
make dev
```

### Production Setup

Use AWS Secrets Manager + External Secrets Operator:
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: incidentfox-secrets
spec:
  secretStoreRef:
    name: aws-secrets-manager
  target:
    name: incidentfox-secrets
  data:
  - secretKey: coralogix-api-key
    remoteRef:
      key: incidentfox/coralogix-api-key
```

## Troubleshooting

### Skill Not Loading
```bash
# Check skill file exists
ls -la .claude/skills/observability/coralogix/SKILL.md

# Check skill metadata is valid
cat .claude/skills/observability/coralogix/SKILL.md | head -20
```

### Script Execution Fails
```bash
# Test script directly
cd .claude/skills/observability/coralogix/scripts
python query_logs.py --help

# Check for missing dependencies
uv pip install httpx kubernetes
```

### Credentials Not Working
```bash
# Check secret exists
kubectl get secret incidentfox-secrets

# Check secret contents
kubectl get secret incidentfox-secrets -o jsonpath='{.data.coralogix-api-key}' | base64 -d

# Check sandbox environment
kubectl exec -it investigation-thread-xxx -- env | grep CORALOGIX
```

### AWS CLI or kubectl Not Working
```bash
# Manual checks:
# 1. Check AWS CLI version and architecture
kubectl exec -it investigation-thread-xxx -- aws --version
kubectl exec -it investigation-thread-xxx -- file /usr/local/bin/aws

# 2. Check kubectl version
kubectl exec -it investigation-thread-xxx -- kubectl version --client

# 3. Verify AWS credentials are set
kubectl exec -it investigation-thread-xxx -- env | grep AWS

# 4. Test EKS authentication (what kubectl uses internally)
kubectl exec -it investigation-thread-xxx -- aws eks get-token --cluster-name incidentfox-demo

# 5. Test kubectl connectivity
kubectl exec -it investigation-thread-xxx -- kubectl get nodes
```

**Common Issue: Architecture Mismatch**
If you see errors like `failed to open elf at /lib64/ld-linux-x86-64.so.2`, the AWS CLI or kubectl binary doesn't match the pod architecture. The Dockerfile now auto-detects and installs the correct binaries for both x86_64 and ARM64. See [MULTI_ARCH_AWS_FIX.md](./MULTI_ARCH_AWS_FIX.md) for details.

### Subagent Not Spawning
```bash
# Check agent logs for Task tool usage
kubectl logs <server-pod> | grep -i "task tool"

# Verify subagent definition in agent.py
grep -A 10 "log-analyst" agent.py
```

## Communication Style

When working on this project:
- **Be concise** - No filler language
- **Statistics first** - Always aggregate before sampling
- **Evidence-based** - Every claim needs supporting data
- **Subagents for depth** - Use them for 5+ queries
