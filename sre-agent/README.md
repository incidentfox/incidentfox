# IncidentFox - AI SRE Agent

AI-powered SRE agent for automated incident investigation using Claude Agent SDK.

## Quick Start

```bash
cd sre-agent

# Setup
uv venv && source .venv/bin/activate
uv pip install claude-agent-sdk python-dotenv fastapi uvicorn 'lmnr[claude-agent-sdk]'

# Configure
cp env.example .env
# Add your ANTHROPIC_API_KEY and LMNR_PROJECT_API_KEY to .env

# Run standalone agent
python agent.py

# Run server
python server.py
```

## API

### Simple Investigation

```bash
curl -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What files are in this directory?"}' \
  --no-buffer
```

Returns SSE stream of agent output.

## Architecture

### Local Development (No Sandbox)
```
Request → server.py:8000 → agent.py (in-process) → Stream Results
```

### Sandbox Mode - Pattern 3: Hybrid Sessions
```
Request (new)      → server.py:8000 → Create Sandbox → Sandbox Router → sandbox_server.py:8888 → agent.py → Results
                                   ↓
Request (follow-up) → server.py:8000 → Reuse Sandbox → Sandbox Router → sandbox_server.py:8888 → agent.py → Results
```

**Key Components:**
- **server.py**: External API server (port 8000)
- **sandbox_manager.py**: Creates/manages Sandbox CRs, routes via Router
- **sandbox_router**: Routes requests to sandboxes via X-Sandbox-ID header
- **sandbox_server.py**: FastAPI server inside sandbox (port 8888) with `/execute` endpoint
- **agent.py**: Claude Agent SDK logic

**Hybrid approach for follow-ups:**
- Each investigation gets a unique `thread_id`
- New thread → Create Sandbox → Execute agent
- Same thread → Reuse Sandbox → Execute agent
- Each sandbox provides:
  - **Dedicated filesystem**: 1-5GB ephemeral storage (tied to pod lifecycle)
  - **Resource limits**: 512MB-2GB RAM, 0.1-2 CPU (optimized for I/O-bound workloads)
  - **Security**: Non-root, no privilege escalation, all capabilities dropped
  - **Lifecycle**: 2h TTL with automatic cleanup
  - **Communication**: FastAPI server on port 8888 (agent-sandbox standard)

## K8s Sandbox Deployment

### Setup (One-time)

```bash
# 1. Setup local kind cluster with agent-sandbox CRDs
make kind-setup

# 2. Install gVisor runtime
make gvisor-install

# 3. Build and deploy Sandbox Router (from kubernetes-sigs/agent-sandbox)
make router-deploy

# 4. Build and load agent image
make docker-load

# 5. Create secrets
export ANTHROPIC_API_KEY=your-key
export LMNR_PROJECT_API_KEY=your-laminar-key  # Optional
make k8s-secrets

# 6. Deploy sandbox template
kubectl apply -f k8s/sandbox-template.yaml
```

**What happens:**
- `make kind-setup` installs agent-sandbox controller and CRDs
- `make gvisor-install` configures gVisor runtime for kernel-level isolation
- `make router-deploy` builds the router from the official agent-sandbox repo and deploys it
- Your sandboxes will use gVisor (`runtimeClassName: "gvisor"`) automatically

### Running with Sandboxes + gVisor

**Both local and production use the Sandbox Router (no tunneling):**

```bash
# Terminal 1: Ensure router is running
kubectl get deploy sandbox-router-deployment

# Terminal 2: Start server (uses router via K8s service DNS)
source .venv/bin/activate
python server.py
```

**Environment variables:**
- Local: Router accessed via `sandbox-router-svc.default.svc.cluster.local:8080`
- Production: Same! Cloud-agnostic architecture

```bash
# Each investigation gets its own isolated sandbox
curl -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Investigate this issue"}'
# Returns: [Thread: thread-xxxxx]
#          [Sandbox: investigation-thread-xxxxx created]

# Follow-up questions reuse the same sandbox
curl -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Tell me more", "thread_id": "thread-xxxxx"}'
# Returns: [Thread: thread-xxxxx]
#          [Sandbox: investigation-thread-xxxxx (reused)]
```

### What Gets Isolated (Per Investigation)

Each sandbox provides:
- **Dedicated filesystem** - 1-5GB ephemeral storage (deleted when pod terminates)
- **Resource limits** - 512MB-2GB RAM, 0.1-2 CPU per investigation (I/O-bound)
- **Security** - Non-root user, dropped capabilities, no privilege escalation
- **Session persistence** - Kept alive for follow-ups, automatic cleanup after 2h TTL
- **Concurrent** - Multiple investigations can run simultaneously
- **Lifecycle** - Automatic deletion via shutdownPolicy after shutdownTime

### gVisor Kernel-Level Isolation ✅

**What is gVisor?**

gVisor intercepts system calls in **userspace** before they reach the host kernel, providing kernel-level isolation without VM overhead.

**Security Benefits:**
- ❌ **Blocks kernel exploits**: Malicious LLM-generated code cannot directly access host kernel
- 🔒 **60% attack surface reduction**: Only ~180/300 syscalls supported
- 🛡️ **Prompt injection mitigation**: Even if Claude is tricked, syscall filter prevents harm
- 📊 **Memory isolation**: Guest memory invisible to host processes

**Performance:**
- CPU-bound work: ~0% overhead (no syscall interception)
- Typical AI agents: **2-5% overall** (dominated by Claude API latency)
- Network I/O: ~2-5× slower (acceptable for investigation workloads)

**Architecture with gVisor:**
```
Request → server.py:8000
    ↓
Sandbox Router (port 8080)
    ↓ (X-Sandbox-ID header routing)
Sandbox Pod (gVisor runtime)
    ↓
sandbox_server.py:8888 → agent.py
```

**Why Router is Required:**

The Router enables scalable communication with thousands of ephemeral sandboxes using **HTTP header-based routing**:

```bash
# Router receives requests with headers
X-Sandbox-ID: investigation-thread-xxx
X-Sandbox-Port: 8888

# Routes to: http://investigation-thread-xxx.default.svc.cluster.local:8888
```

**Benefits:**
- ✅ Works with gVisor (no network syscall issues)
- ✅ Scales to thousands of sandboxes (no port forwarding needed)
- ✅ Same architecture for local dev and production

**Router Source:**

The Sandbox Router is provided by the official [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) project. When you run `make router-deploy`, it:
1. Clones the agent-sandbox repo to `~/.cache/agent-sandbox`
2. Builds the router image from their code
3. Loads it into your cluster

This ensures you're using the official, maintained router implementation.

### Hybrid Sessions Architecture

✅ **Fully Working:**
- Thread-based investigation tracking (`thread_id`)
- Programmatic sandbox creation via Kubernetes API
- Sandbox reuse for follow-up questions
- Concurrent multi-investigation support
- Automatic thread_id generation
- **Agent execution inside sandbox** (FastAPI server on port 8888)
- HTTP-based communication via Sandbox Router
- Ephemeral storage (5Gi per sandbox) - cloud-agnostic
- Automatic TTL-based cleanup (2h for resource efficiency)

✅ **gVisor Enabled:**
- **Kernel-level isolation** with syscall interception in userspace
- **Sandbox Router** deployed for gVisor-compatible communication
- **Production-ready** security architecture

## Local Development

**First-time setup:**
```bash
make setup-local  # Creates Kind cluster, installs components (run once)
```

**Day-to-day development:**
```bash
make dev  # Builds, runs server, auto-cleanup on Ctrl+C (docker-compose-like!)
```

Test with `curl`.

## Production Deployment

**First-time setup:**
```bash
make setup-prod  # Creates EKS cluster, installs components (run once)
```

**Day-to-day deployment:**
```bash
make deploy-prod  # Builds multi-platform, pushes to ECR, deploys
```

Get production URL: `make prod-url`

See [DEPLOYMENT_QUICK_START.md](DEPLOYMENT_QUICK_START.md) for detailed instructions.

**CI/CD deployment:**
Deployment via GitHub Actions (manual trigger only):
- Run from GitHub UI: Actions → Deploy SRE Agent to Production → Run workflow
- Or via CLI: `gh workflow run deploy-sre-agent-prod.yml`

Configure required secrets in GitHub repository settings:
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` - AWS credentials with ECR and EKS access
- `ANTHROPIC_API_KEY` - Claude API key
- `JWT_SECRET` - JWT signing secret (generate with: `openssl rand -hex 32`)
- Optional: `LMNR_PROJECT_API_KEY`, `CORALOGIX_API_KEY`, `CORALOGIX_DOMAIN`

See [../.github/GITHUB_SECRETS.md](../.github/GITHUB_SECRETS.md) for detailed setup instructions.

**Production architecture:**
- AWS EKS cluster with gVisor-enabled sandboxes
- LoadBalancer service for external access (NLB auto-provisioned)
- Sandbox Router for scalable communication
- Horizontal autoscaling (2-10 replicas)
- Cluster autoscaling (3-6 nodes)

**Cost:** ~$166/month base + ~$0.001-0.01 per investigation

### Testing

```bash
# Check sandbox status
kubectl get sandbox

# View sandbox server logs
kubectl logs investigation-thread-xxxxx
# Should show: INFO:     Uvicorn running on http://0.0.0.0:8888

# Test investigation
curl -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is 2+2?"}' --no-buffer

# Delete specific sandbox
kubectl delete sandbox investigation-thread-xxxxx

# Delete all sandboxes
make k8s-clean
```

## Key Files

- **agent.py** - Core agent logic using Claude SDK with Laminar tracing
- **server.py** - External API server (port 8000) that manages investigations
- **sandbox_server.py** - FastAPI server inside sandbox (port 8888) with /execute endpoint
- **sandbox_manager.py** - Kubernetes sandbox lifecycle management (Router-based)
- **pyproject.toml** - Python dependencies
- **Dockerfile** - Sandbox container image
- **Makefile** - Build, deploy, and test targets
- **k8s/sandbox-template.yaml** - SandboxTemplate CRD (with gVisor enabled)
- **k8s/gvisor-runtimeclass.yaml** - gVisor RuntimeClass definition
- **k8s/sandbox_router.yaml** - Sandbox Router deployment manifest
- **k8s/install-gvisor-kind.sh** - gVisor installation script
- **k8s/setup-kind.sh** - Kind cluster setup script

**Note:** The Sandbox Router code itself comes from [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) and is built automatically via `make router-deploy`.

## Integrations

Integrations are implemented via **skills with Python scripts**, not MCP tools. This keeps the agent's context clean and enables progressive disclosure of knowledge.

### Available Integrations

| Integration | What It Provides | Environment Variables |
|-------------|------------------|----------------------|
| **Kubernetes** | Pod inspection, logs, events, resource status | `KUBECONFIG` (auto-detected) |
| **Coralogix** | Logs, metrics, traces, alerts (DataPrime queries) | `CORALOGIX_API_KEY`, `CORALOGIX_DOMAIN` |
| **AWS** | EC2, CloudWatch, ECS (planned) | `AWS_REGION`, `AWS_ACCESS_KEY_ID` |
| **Git** | Commit history, deployment correlation | Always available (uses local git) |

### How Integrations Work

Each integration is a skill containing:
- **SKILL.md** - Methodology and reference documentation
- **scripts/** - Python scripts that call the actual APIs (Kubernetes, Coralogix, etc.)

When the agent needs to use an integration:
1. Reads the skill metadata (progressive disclosure)
2. Executes relevant Python scripts via Bash
3. Gets structured output without bloating context with tool descriptions

### Quick Setup

**Required for Demo:**
```bash
# Core
export ANTHROPIC_API_KEY=sk-ant-...
export LMNR_PROJECT_API_KEY=lm_...  # Optional

# Coralogix (logs/metrics/traces)
export CORALOGIX_API_KEY=your-key
export CORALOGIX_DOMAIN=https://yourteam.app.cx498.coralogix.com/

# Kubernetes (auto-configured for incidentfox-demo)
# No setup needed - kubeconfig-demo.yaml is baked into image
```

See `env.example` for all available integrations.

## Quick Start Examples

With the pre-configured OTel Demo environment:

```bash
# Investigate checkout service errors
curl -X POST http://localhost:8000/investigate \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Investigate high error rate in checkout service"}' \
  --no-buffer

# Analyze payment service logs
curl -X POST http://localhost:8000/investigate \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Use the log-analyst subagent to analyze payment service errors in the last hour"}' \
  --no-buffer

# Check blast radius for cart service
curl -X POST http://localhost:8000/investigate \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "What would be the blast radius if the cart service fails?"}' \
  --no-buffer

# Correlate deployment with incidents
curl -X POST http://localhost:8000/investigate \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Did any deployments happen around the time checkout started failing?"}' \
  --no-buffer
```

The agent knows:
- ✅ Kubernetes namespace (`otel-demo`)
- ✅ Label convention (`app.kubernetes.io/name=payment`)
- ✅ Service dependencies (checkout → payment → kafka)
- ✅ Coralogix domain (incidentfox.app.cx498.coralogix.com)
- ✅ Service criticality levels
- ✅ Known runbooks and patterns

## Skills

**6 expert skills** provide on-demand methodology and best practices:

- **`investigate`** - 5-phase systematic investigation (Scope → Evidence → Hypotheses → Test → Conclude)
- **`coralogix-analysis`** - Partition-first Coralogix log analysis with DataPrime
- **`log-analysis`** - Multi-backend log analysis (Datadog, CloudWatch, Elasticsearch)
- **`k8s-debug`** - Kubernetes debugging (events-before-logs, resource analysis)
- **`aws-troubleshoot`** - AWS service troubleshooting workflows
- **`sre-principles`** - Evidence-based reasoning, confidence levels, intellectual honesty

Skills are automatically invoked when relevant to the task. Located in `.claude/skills/` directory.

## Subagents

**2 specialized subagents** for focused analysis:

- **`investigator`** - Expert incident investigator with full tool access, follows 5-phase methodology
- **`log-analyst`** - Log analysis specialist with Coralogix tools only, read-only access

Subagents provide isolated context and can run in parallel. Invoke explicitly: "Use the investigator subagent to..."

## Default Environment

The agent Docker image comes with a **demo kubeconfig** that connects to the **OpenTelemetry Demo Microservices** stack on AWS EKS. All other configuration is provided via environment variables or discovered at runtime.

**Pre-configured (baked into image):**
- ✅ Kubeconfig file (`/home/agent/.kube/config`) pointing to OTel Demo EKS clusters

**Runtime configuration (via env vars):**
- Observability platform credentials (`CORALOGIX_API_KEY`, `DATADOG_API_KEY`, etc.)
- AWS credentials (if using CloudWatch/AWS integrations)
- Namespace to investigate (defaults to `default` if not specified)

**Discovered dynamically by agent:**
- Services and pods (via `kubectl`)
- Service topology and dependencies
- Log/metric/trace patterns
- Label conventions and naming patterns

**Example demo stack (when using default kubeconfig):**
- Stack: OTel Demo on AWS EKS (us-east-1, us-west-2, eu-west-1)
- Namespace: `otel-demo`
- Services: 18 microservices (Go, Node.js, Python, .NET, Rust, Java, etc.)
- Observability: Coralogix (cx498.coralogix.com) - requires API key

## Verification

After setup, verify integrations are working:

```bash
# Check Coralogix
curl -X POST http://localhost:8000/investigate \
  -d '{"prompt": "List all services in Coralogix"}' --no-buffer
# Expected: List of services from otel-demo

# Check Kubernetes
curl -X POST http://localhost:8000/investigate \
  -d '{"prompt": "List all pods in otel-demo namespace"}' --no-buffer
# Expected: List of running pods with status

# Check service catalog
curl -X POST http://localhost:8000/investigate \
  -d '{"prompt": "What is the blast radius if cart service fails?"}' --no-buffer
# Expected: Impact analysis showing frontend and checkout affected
```

## Troubleshooting

### "Coralogix tools not available"
```bash
# Check if API key is set
echo $CORALOGIX_API_KEY

# If empty, add to .env and recreate secrets
echo "CORALOGIX_API_KEY=your-key" >> .env
./scripts/setup-local.sh  # Recreates K8s secret
```

### "kubectl: unauthorized"
```bash
# Ensure AWS credentials are set (for EKS authentication)
echo $AWS_ACCESS_KEY_ID
echo $AWS_SECRET_ACCESS_KEY

# Test AWS CLI access
aws eks describe-cluster --name incidentfox-demo --region us-west-2

# Rebuild image (includes kubeconfig)
make build && make dev
```

### Sandbox pod crashes
```bash
# Check sandbox logs
kubectl logs -l app=incidentfox-agent --tail=100

# Check for import errors or missing dependencies
# Rebuild if needed
make build && make dev
```

## Features

- **Claude Agent SDK** - Agentic AI with skill-based progressive disclosure
- **Skills + Scripts Architecture** - Context-efficient integrations via Python scripts
- **gVisor Isolation** - Kernel-level security with syscall interception ✅
- **Sandbox Router** - Header-based routing for gVisor compatibility ✅
- **Kubernetes Sandboxes** - Isolated environments per investigation
- **Hybrid Sessions** - Sandbox reuse for follow-up questions
- **Laminar Tracing** - Full observability and debugging
- **Ephemeral Storage** - 1-5GB per sandbox (deleted with pod, cloud-agnostic)
- **Security** - Non-root, dropped capabilities, resource limits, gVisor runtime
- **TTL Cleanup** - Automatic deletion after 2 hours (optimized for cost)
