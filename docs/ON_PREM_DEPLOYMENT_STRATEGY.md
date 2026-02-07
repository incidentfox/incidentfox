# On-Premise Deployment Strategy for IncidentFox

> ⚠️ **Internal Business Document**: This document contains business strategy, pricing, and sales information intended for internal use. For technical deployment guidance, see [DEPLOYMENT.md](DEPLOYMENT.md).

**Document Purpose**: Guide for selling and deploying IncidentFox to enterprise customers in their own infrastructure.

**Last Updated**: 2026-01-10

---

## Executive Summary

IncidentFox is currently architected as a cloud-native SaaS product running on AWS. To sell to enterprise customers who require on-premise deployment, we need to:

1. **Package for portability** - Remove AWS-specific dependencies
2. **Build commercial infrastructure** - License management, usage tracking, billing analytics
3. **Enable customer self-sufficiency** - Installation automation, monitoring, updates
4. **Maintain support visibility** - Remote telemetry (with customer consent)

**Estimated Development**: 4-8 weeks for MVP on-prem package + commercial infrastructure

---

## Table of Contents

1. [Current Architecture Analysis](#current-architecture-analysis)
2. [On-Prem Deployment Models](#on-prem-deployment-models)
3. [Customer Deployment Process](#customer-deployment-process)
4. [What We Need to Build](#what-we-need-to-build)
5. [Licensing & Entitlement Strategy](#licensing--entitlement-strategy)
6. [Billing & Usage Analytics](#billing--usage-analytics)
7. [Remote Monitoring & Support](#remote-monitoring--support)
8. [Installation Package](#installation-package)
9. [Implementation Roadmap](#implementation-roadmap)
10. [Pricing Models](#pricing-models)

---

## Current Architecture Analysis

### What We Have Today (SaaS on AWS)

```
┌─────────────────────────────────────────────────────────────┐
│                    AWS US-WEST-2                             │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   EKS        │  │  RDS Postgres│  │  Secrets Mgr │     │
│  │  (K8s)       │  │  (Private)   │  │  (API Keys)  │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │     ALB      │  │     ECR      │  │   Route53    │     │
│  │ (Load Bal.)  │  │  (Images)    │  │    (DNS)     │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                         ▲
                         │ API Calls
                         │
              ┌──────────┴──────────┐
              │   OpenAI API        │
              │   (gpt-5.2/4-turbo)  │
              └─────────────────────┘
```

### AWS-Specific Dependencies (Need Alternatives)

| AWS Service | Purpose | On-Prem Alternative |
|-------------|---------|---------------------|
| **EKS** | Kubernetes cluster | Customer's K8s (OpenShift, Rancher, vanilla) |
| **RDS** | PostgreSQL database | Customer's DB (managed Postgres, CloudNativePG) |
| **ALB** | Load balancing | Ingress Controller (NGINX, Traefik, HAProxy) |
| **Secrets Manager** | Secret storage | Sealed Secrets, Vault, External Secrets Operator |
| **ECR** | Container registry | Customer's registry (Harbor, Artifactory, Quay) |
| **Route53** | DNS | Customer's DNS |
| **IAM + IRSA** | Pod identity | K8s Service Accounts + customer IAM |
| **CloudWatch** | Logging/metrics | Customer's observability (Prometheus, ELK) |

### External SaaS Dependencies

| Dependency | Required? | On-Prem Consideration |
|------------|-----------|----------------------|
| **OpenAI API** | ✅ Yes (LLM inference) | **BLOCKER**: Air-gapped environments need alternative |
| **Customer Tools** | Optional | Slack, GitHub, Grafana, Datadog (customer provides access) |

**Key Insight**: OpenAI API access is the biggest constraint. We need:
- **Connected deployment**: Requires outbound HTTPS to api.openai.com
- **Air-gapped option**: Local LLM support (Ollama, vLLM, Azure OpenAI on-prem)

---

## On-Prem Deployment Models

### Model 1: Connected On-Prem (Recommended for MVP)

**Customer Environment**: Kubernetes cluster with **outbound internet access**

```
┌──────────────────────────────────────────────────────────────┐
│              CUSTOMER DATA CENTER                             │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         Customer Kubernetes Cluster                  │    │
│  │                                                       │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │    │
│  │  │  Agent   │  │  Config  │  │  Web UI  │          │    │
│  │  │  Pods    │  │  Service │  │          │          │    │
│  │  └──────────┘  └──────────┘  └──────────┘          │    │
│  │                                                       │    │
│  │  ┌──────────────────────────────────────┐           │    │
│  │  │  PostgreSQL (StatefulSet or External)│           │    │
│  │  └──────────────────────────────────────┘           │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                               │
│  Outbound HTTPS (Port 443):                                  │
│    ├─> api.openai.com (LLM inference)                        │
│    ├─> license.incidentfox.ai (license validation)          │
│    └─> telemetry.incidentfox.ai (usage metrics, optional)   │
└───────────────────────────────────────────────────────────────┘
```

**Pros**:
- Simplest to deploy and support
- Uses OpenAI's latest models
- Remote telemetry for proactive support
- License validation in real-time

**Cons**:
- Requires firewall rules for outbound HTTPS
- Some enterprises have strict egress policies

**Target Customers**: 70% of enterprise buyers

---

### Model 2: Air-Gapped On-Prem (Advanced)

**Customer Environment**: Isolated network with **no internet access**

```
┌──────────────────────────────────────────────────────────────┐
│         CUSTOMER AIR-GAPPED DATA CENTER                       │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         Customer Kubernetes Cluster                  │    │
│  │                                                       │    │
│  │  ┌──────────┐  ┌──────────┐  ┌─────────────┐       │    │
│  │  │  Agent   │  │  Config  │  │  Local LLM  │       │    │
│  │  │  Pods    │  │  Service │  │  (vLLM/     │       │    │
│  │  │          │  │          │  │   Ollama)   │       │    │
│  │  └──────────┘  └──────────┘  └─────────────┘       │    │
│  │                                                       │    │
│  │  ┌──────────────────────────────────────┐           │    │
│  │  │  PostgreSQL + License File (offline) │           │    │
│  │  └──────────────────────────────────────┘           │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                               │
│  NO INTERNET ACCESS                                           │
│    ├─ Manual license file delivery (.lic file)               │
│    └─ Manual update packages (USB/Bastion)                   │
└───────────────────────────────────────────────────────────────┘
```

**Pros**:
- Meets strictest security requirements (finance, defense, healthcare)
- All data stays in customer environment
- No vendor dependency after deployment

**Cons**:
- Complex setup (requires local LLM infrastructure)
- Manual updates and license renewals
- Limited support visibility (can't diagnose remotely)
- Potential performance degradation vs OpenAI models

**Target Customers**: 15% of enterprise buyers (banks, defense, regulated industries)

**Requirements**:
- Customer provides GPU nodes for local LLM (NVIDIA A100/H100)
- We deliver pre-trained model files (e.g., Llama 3 70B)
- Offline license validation via signed JWT files

---

### Model 3: Hybrid (Connected Control Plane)

**Customer Environment**: Workloads on-prem, control plane in our cloud

```
┌──────────────────────────────┐
│  INCIDENTFOX CLOUD (AWS)     │
│                              │
│  ┌────────────────────────┐ │
│  │  License Service       │ │
│  │  Telemetry Aggregator  │ │
│  │  Billing Analytics     │ │
│  └────────────────────────┘ │
└──────────────┬───────────────┘
               │ HTTPS
               │ (License checks, metrics)
               ▼
┌──────────────────────────────────────┐
│     CUSTOMER DATA CENTER              │
│                                       │
│  ┌─────────────────────────────────┐ │
│  │   IncidentFox (Full Stack)      │ │
│  │   (Agent, Config, Web UI, DB)   │ │
│  └─────────────────────────────────┘ │
│                                       │
│  Customer Data NEVER Leaves Network  │
└───────────────────────────────────────┘
```

**Pros**:
- Balance between control and convenience
- Real-time license enforcement
- Rich telemetry for support
- Easier updates (we push to customer)

**Cons**:
- Requires persistent outbound connection
- Customer concerns about "calling home"

**Target Customers**: 15% of enterprise buyers (mid-market, less strict compliance)

---

## Customer Deployment Process

### Phase 1: Pre-Sales (Sales Engineering)

**Objective**: Qualify customer environment and requirements

1. **Discovery Questions**:
   - What Kubernetes distribution? (EKS, AKS, GKE, OpenShift, Rancher, vanilla)
   - Outbound internet access allowed? (Whitelist IPs/domains?)
   - Air-gapped requirement? (How do you receive updates?)
   - GPU availability? (For air-gapped local LLM)
   - Database preference? (Managed Postgres, operator-based, external)
   - Secret management? (Vault, Sealed Secrets, External Secrets Operator)
   - Observability stack? (Prometheus, Grafana, Datadog, Splunk)
   - Ingress controller? (NGINX, Traefik, HAProxy, Istio)
   - Storage class for StatefulSets? (What provisioner?)

2. **Prerequisites Assessment**:
   ```
   ✅ Kubernetes 1.24+ (ideally 1.28+)
   ✅ PostgreSQL 13+ accessible from cluster (or we deploy it)
   ✅ 4+ CPU, 8GB+ RAM per node (3 nodes minimum for HA)
   ✅ Storage class with dynamic provisioning
   ✅ Ingress controller installed
   ✅ (Optional) GPU nodes if air-gapped
   ```

3. **Architecture Design**:
   - Choose deployment model (Connected / Air-Gapped / Hybrid)
   - Design network topology (LoadBalancer vs NodePort vs Ingress)
   - Plan secret injection (ESO + Vault? Sealed Secrets?)
   - Define backup/DR strategy

4. **Deliverables**:
   - Deployment architecture diagram
   - Bill of materials (CPU, memory, storage requirements)
   - Network requirements (firewall rules, DNS entries)
   - License quote (tier, seat count, term)

---

### Phase 2: Installation (Customer Success / PS)

**Timeline**: 1-3 days for connected, 5-7 days for air-gapped

#### Step 1: Environment Preparation (Customer Side)

```bash
# Create namespace
kubectl create namespace incidentfox

# Create image pull secret (for our private registry)
kubectl create secret docker-registry incidentfox-registry \
  --docker-server=docker.io \
  --docker-username=incidentfox \
  --docker-password=<LICENSE_KEY> \
  --namespace=incidentfox

# Deploy database (if not using external)
helm install incidentfox-postgres bitnami/postgresql \
  --namespace incidentfox \
  --set auth.database=incidentfox \
  --set primary.persistence.size=100Gi
```

#### Step 2: License Activation

**Connected Mode**:
```bash
# License server validates and returns config
curl https://license.incidentfox.ai/api/v1/activate \
  -H "Authorization: Bearer <CUSTOMER_LICENSE_KEY>" \
  -d '{
    "customer_id": "acme-corp",
    "deployment_id": "prod-us-east",
    "k8s_cluster_uid": "<auto-detected>"
  }'

# Returns JWT license token + entitlements
{
  "license_token": "eyJhbGc...",
  "entitlements": {
    "max_teams": 50,
    "max_agent_runs_per_month": 100000,
    "features": ["slack", "github", "pagerduty", "sso"],
    "expiry": "2027-01-10T00:00:00Z"
  }
}
```

**Air-Gapped Mode**:
```bash
# Customer receives license file via email/USB
# incidentfox-acme-corp-2026.lic (signed JWT)
kubectl create secret generic incidentfox-license \
  --from-file=license.jwt=incidentfox-acme-corp-2026.lic \
  --namespace=incidentfox
```

#### Step 3: Install Helm Chart

```bash
# Download installation package
# For connected: wget https://releases.incidentfox.ai/v1.2.0/incidentfox-helm.tgz
# For air-gapped: Receive via secure transfer

# Create values file
cat > values-customer.yaml <<EOF
global:
  license:
    # Connected: license server URL
    serverUrl: https://license.incidentfox.ai
    licenseKey: <CUSTOMER_LICENSE_KEY>

    # Air-gapped: license file
    # useFile: true
    # secretName: incidentfox-license
    # secretKey: license.jwt

  database:
    host: incidentfox-postgres-postgresql.incidentfox.svc.cluster.local
    port: 5432
    name: incidentfox
    user: postgres
    passwordSecretName: incidentfox-postgres-postgresql
    passwordSecretKey: postgres-password

  openai:
    # Connected: OpenAI API
    apiKey: sk-proj-xxxx
    model: gpt-5.2

    # Air-gapped: Local LLM
    # provider: vllm
    # baseUrl: http://vllm-service.ai-infra.svc.cluster.local:8000/v1
    # model: meta-llama/Llama-3-70b-instruct

ingress:
  enabled: true
  className: nginx
  host: incidentfox.acme.internal
  tls:
    enabled: true
    secretName: incidentfox-tls

services:
  agent:
    image: incidentfox/agent:v1.0.0
    replicas: 3
  configService:
    image: incidentfox/config-service:v1.0.0
  webUi:
    image: incidentfox/web-ui:v1.0.0

# Customer integrations (optional)
integrations:
  slack:
    botToken: xoxb-customer-token
    signingSecret: customer-secret
  github:
    token: ghp_customer_token
EOF

# Install
helm install incidentfox ./incidentfox-helm.tgz \
  --namespace incidentfox \
  --values values-customer.yaml \
  --timeout 10m
```

#### Step 4: Verification

```bash
# Check all pods running
kubectl get pods -n incidentfox

# Expected output:
# incidentfox-agent-xxx         2/2  Running
# incidentfox-config-service-xxx 1/1  Running
# incidentfox-web-ui-xxx         1/1  Running
# incidentfox-orchestrator-xxx   1/1  Running

# Test health endpoints
kubectl port-forward -n incidentfox svc/incidentfox-agent 8080:8080
curl http://localhost:8080/health
# {"status": "healthy", "license": "active", "version": "1.2.0"}

# Access Web UI
# https://incidentfox.acme.internal
```

#### Step 5: Initial Configuration

1. **Admin Setup**:
   - Log into Web UI with default admin credentials
   - Change admin password
   - Configure SSO/OIDC (if required)

2. **Organization Setup**:
   - Create organization tree (Business Units, Teams)
   - Assign team tokens
   - Configure integrations (Slack, GitHub, PagerDuty)

3. **Test Investigation**:
   - Run test scenario via Slack: `@incidentfox test connection`
   - Verify agent can access customer's observability tools

---

### Phase 3: Ongoing Operations

#### Customer Responsibilities

1. **Infrastructure**:
   - Kubernetes cluster maintenance (upgrades, node scaling)
   - Database backups and maintenance
   - Certificate renewal (TLS)
   - Monitoring infrastructure health

2. **IncidentFox Operations**:
   - User management (team provisioning)
   - Configuration updates (prompts, MCPs, tools)
   - Integration credentials rotation
   - Agent run monitoring

#### IncidentFox Responsibilities (Support)

1. **Software Updates**:
   - Release notes and changelogs
   - Helm chart upgrades (backward compatible)
   - Database migration scripts
   - Critical security patches

2. **Telemetry Collection** (if customer opts in):
   - Anonymized usage metrics (agent runs, API calls)
   - Error rates and performance metrics
   - Feature adoption analytics
   - License compliance monitoring

3. **Support**:
   - Slack/email support (SLA based on tier)
   - Bug fixes and patches
   - Performance tuning guidance
   - Custom integration development (Professional Services)

---

## What We Need to Build

### Critical (Must-Have for Launch)

#### 1. License Service (New Microservice)

**Purpose**: Validate licenses, enforce entitlements, track usage

**API Endpoints**:
```
POST /api/v1/activate
  - Input: customer_id, license_key, deployment_id
  - Output: license_token (JWT), entitlements
  - Used during initial installation

POST /api/v1/validate
  - Input: license_token
  - Output: {valid: true/false, entitlements, expiry}
  - Called by agent/orchestrator on startup and periodically

POST /api/v1/heartbeat
  - Input: license_token, usage_stats {agent_runs, teams, users}
  - Output: {status: "ok", warnings: [...]}
  - Called every 5 minutes (connected) or stored locally (air-gapped)

GET /api/v1/entitlements
  - Input: license_token
  - Output: {max_teams, max_runs, features, add_ons}
  - Called before provisioning new teams or features
```

**Storage**:
- PostgreSQL: license_keys, activations, usage_logs
- Redis: rate limiting, caching validated tokens

**Deployment**:
- Hosted by us: `https://license.incidentfox.ai`
- HA: Multi-region (us-west-2, us-east-1, eu-west-1)
- DR: <5 min failover

**Tech Stack**:
- Python 3.11 + FastAPI
- PostgreSQL 14+ (AWS RDS)
- Redis 7+ (AWS ElastiCache)
- JWT signing: RS256 (private key secured in AWS KMS)

**Air-Gapped Support**:
- Generate offline license files (signed JWTs, valid 1 year)
- Customer receives .lic file via secure channel
- Agent validates signature using embedded public key
- No phone-home required

---

#### 2. License Enforcement in Agent/Orchestrator

**Integration Points**:

```python
# agent/src/ai_agent/licensing.py

class LicenseValidator:
    def __init__(self, config):
        self.mode = config.license_mode  # "online" | "offline"
        self.license_token = load_license_token()
        self.public_key = load_public_key()  # For offline JWT validation

    async def validate(self) -> LicenseEntitlements:
        if self.mode == "online":
            # Call license.incidentfox.ai
            response = await http_client.post(
                "https://license.incidentfox.ai/api/v1/validate",
                headers={"Authorization": f"Bearer {self.license_token}"}
            )
            return LicenseEntitlements(**response.json())
        else:
            # Offline: validate JWT signature
            claims = jwt.decode(self.license_token, self.public_key, algorithms=["RS256"])
            if claims["exp"] < time.time():
                raise LicenseExpiredError()
            return LicenseEntitlements(**claims["entitlements"])

    async def enforce_agent_run(self, org_id: str, team_id: str):
        entitlements = await self.validate()
        usage = await get_monthly_usage(org_id)

        if usage.agent_runs >= entitlements.max_agent_runs_per_month:
            raise LicenseQuotaExceededError(
                f"Monthly quota exceeded: {usage.agent_runs}/{entitlements.max_agent_runs_per_month}"
            )

    async def enforce_team_provisioning(self, org_id: str):
        entitlements = await self.validate()
        team_count = await count_teams(org_id)

        if team_count >= entitlements.max_teams:
            raise LicenseQuotaExceededError(
                f"Team limit reached: {team_count}/{entitlements.max_teams}"
            )
```

**Enforcement Rules**:

| Entitlement | Enforced At | Behavior on Exceed |
|-------------|-------------|-------------------|
| `max_teams` | Team provisioning | Block new team creation, show upgrade prompt |
| `max_agent_runs_per_month` | Agent run start | Block new runs, show quota exceeded error |
| `features: ["sso"]` | Config service OIDC setup | Disable SSO config UI, return 403 |
| `features: ["github"]` | Webhook handling | Return 402 Payment Required for GitHub webhooks |
| `expiry` | Every request | Grace period 7 days, then block all operations |

---

#### 3. Telemetry Service (Optional but Recommended)

**Purpose**: Collect anonymized usage metrics for support and billing

**What We Collect** (Customer Opt-In):

```json
{
  "deployment_id": "acme-prod-us-east",
  "customer_id_hash": "sha256(acme-corp)",
  "timestamp": "2026-01-10T12:00:00Z",
  "metrics": {
    "agent_runs": {
      "total": 1234,
      "by_agent": {
        "planner": 500,
        "k8s": 300,
        "aws": 200
      },
      "success_rate": 0.95,
      "avg_duration_seconds": 18.5
    },
    "teams": {
      "total": 12,
      "active": 8
    },
    "integrations": {
      "slack": {"enabled": true, "events": 450},
      "github": {"enabled": true, "events": 200}
    },
    "errors": {
      "total": 23,
      "top_errors": [
        "OpenAI API timeout (10)",
        "Kubernetes API unreachable (5)"
      ]
    }
  },
  "health": {
    "license_status": "active",
    "version": "1.2.0",
    "uptime_hours": 720
  }
}
```

**Privacy Guarantees**:
- NO customer data (logs, alerts, investigation results)
- NO PII (usernames, emails, IP addresses)
- Hashed identifiers only
- Customer can disable anytime

**API Endpoint**:
```
POST https://telemetry.incidentfox.ai/api/v1/metrics
  - Input: deployment_id, encrypted_payload
  - Output: {status: "received"}
  - Called every 5 minutes from orchestrator
```

**Benefits**:
- **For Us**: Usage analytics, proactive support (detect issues before customer notices)
- **For Customer**: Faster support resolution, usage insights dashboard

**Tech Stack**:
- Python + FastAPI
- ClickHouse or TimescaleDB (time-series metrics)
- Grafana dashboards (internal + customer-facing)

---

#### 4. Installation Package Automation

**Deliverables**:

1. **Helm Chart Improvements**:
   ```
   charts/incidentfox-enterprise/
   ├── Chart.yaml               # Version, dependencies
   ├── values.yaml              # Defaults (connected mode)
   ├── values.airgapped.yaml    # Air-gapped overrides
   ├── templates/
   │   ├── license-validator-configmap.yaml  # NEW
   │   ├── agent-deployment.yaml             # Add license env vars
   │   ├── orchestrator-deployment.yaml      # Add license checks
   │   └── ...
   └── README.md                # Installation guide
   ```

2. **CLI Installation Tool** (`incidentfox-installer`):
   ```bash
   # Interactive installer
   ./incidentfox-installer install

   # Prompts:
   # - License key: ****
   # - Deployment mode: [Connected / Air-Gapped]
   # - Database: [Deploy PostgreSQL / Use Existing]
   # - Ingress: [NGINX / Traefik / HAProxy]
   # - Domain: incidentfox.acme.internal
   #
   # Output:
   # ✅ Namespace created
   # ✅ License activated
   # ✅ Secrets configured
   # ✅ Helm chart deployed
   # ✅ Health checks passed
   #
   # Access: https://incidentfox.acme.internal
   # Admin user: admin@acme.com
   # Admin password: <generated>
   ```

3. **Container Images**:
   - Private registry: `docker.io/incidentfox`
   - Authentication: Docker registry token (license key)
   - Air-gapped: Deliver tarball with `docker load` instructions
   - Multi-arch: AMD64 + ARM64 (for Graviton compatibility)

4. **Documentation**:
   - `INSTALLATION_GUIDE.md` (step-by-step, screenshots)
   - `ARCHITECTURE_GUIDE.md` (diagrams, troubleshooting)
   - `OPERATIONS_GUIDE.md` (backup, upgrades, monitoring)
   - `AIRGAPPED_GUIDE.md` (local LLM setup, offline updates)

---

### Nice-to-Have (Post-MVP)

#### 5. Customer Portal (Self-Service)

**URL**: `https://portal.incidentfox.ai`

**Features**:
- License management (view entitlements, usage, expiry)
- Download installation packages (Helm charts, container images)
- Release notes and changelogs
- Support ticket system
- Usage analytics dashboard (if telemetry enabled)
- Invoice history and billing

**Tech Stack**:
- Next.js + React
- Backend: FastAPI + PostgreSQL
- Auth: Auth0 or Clerk

---

#### 6. Update Service

**Purpose**: Automated version checking and upgrade orchestration

**Flow**:
```
┌─────────────────────┐
│  Customer Cluster   │
│                     │
│  Orchestrator calls │
│  every 24 hours     │
└──────────┬──────────┘
           │ HTTPS
           ▼
┌─────────────────────────────┐
│  updates.incidentfox.ai     │
│                             │
│  GET /api/v1/versions       │
│  ?current=1.2.0             │
│  &channel=stable            │
│                             │
│  Response:                  │
│  {                          │
│    "latest": "1.3.0",       │
│    "release_notes": "...",  │
│    "breaking_changes": [],  │
│    "upgrade_path": [...]    │
│  }                          │
└─────────────────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Customer sees banner in    │
│  Web UI:                    │
│                             │
│  "New version 1.3.0         │
│   available. Upgrade?"      │
│                             │
│  [View Release Notes]       │
│  [Upgrade Now]              │
└─────────────────────────────┘
```

**Upgrade Automation** (Opt-In):
```bash
# In customer's cluster, orchestrator can auto-upgrade Helm
helm upgrade incidentfox incidentfox/incidentfox-enterprise \
  --version 1.3.0 \
  --reuse-values \
  --atomic
```

**Air-Gapped**: Manual download of upgrade package

---

#### 7. Support Diagnostics Tool

**Purpose**: Collect logs and metrics for support cases

**Customer Usage**:
```bash
# Run diagnostics collector
kubectl exec -n incidentfox deploy/incidentfox-orchestrator -- \
  incidentfox-diagnostics collect \
  --output /tmp/diagnostics.tar.gz \
  --anonymize  # Remove PII

# Upload to support (or attach to ticket)
curl -X POST https://support.incidentfox.ai/api/v1/diagnostics \
  -F "ticket_id=TICKET-123" \
  -F "file=@/tmp/diagnostics.tar.gz"
```

**What's Collected**:
- Pod logs (last 1000 lines, anonymized)
- Resource usage (CPU, memory, disk)
- Configuration (sanitized, no secrets)
- Recent agent runs (summaries, no customer data)
- Error traces

---

## Licensing & Entitlement Strategy

### License Tiers

| Tier | Price/Year | Max Teams | Max Runs/Month | Features | Support |
|------|-----------|-----------|----------------|----------|---------|
| **Starter** | $25,000 | 5 | 10,000 | Slack, GitHub, Basic tools | Email (48h SLA) |
| **Professional** | $75,000 | 20 | 50,000 | + PagerDuty, Datadog, Grafana, SSO | Email + Slack (24h) |
| **Enterprise** | $200,000+ | Unlimited | 200,000+ | + Air-gapped, Custom MCPs, SLA | Dedicated Slack, 4h SLA |
| **Enterprise Plus** | Custom | Unlimited | Unlimited | + PS hours, Custom agents | 24/7, 1h SLA, TAM |

### License Keys

**Format**: `IFOX-<TIER>-<CUSTOMER_ID>-<UUID>`

Example: `IFOX-ENT-ACME-a7b3c9d1e2f4g5h6`

**JWT Claims**:
```json
{
  "iss": "license.incidentfox.ai",
  "sub": "acme-corp",
  "iat": 1704067200,
  "exp": 1735689600,  // 1 year
  "entitlements": {
    "tier": "enterprise",
    "max_teams": -1,  // unlimited
    "max_agent_runs_per_month": 200000,
    "features": [
      "slack", "github", "pagerduty", "datadog", "grafana",
      "sso", "approval_workflows", "custom_mcps", "airgapped"
    ],
    "support_sla_hours": 4,
    "custom_fields": {
      "account_manager": "jane.doe@incidentfox.ai",
      "renewal_date": "2027-01-10"
    }
  }
}
```

**Rotation**:
- Licenses expire after 1 year (require renewal)
- Grace period: 30 days (warning banner at 14 days)
- After grace: Non-critical operations continue, new runs blocked

---

## Billing & Usage Analytics

### What We Track (for Billing)

1. **Metered Usage**:
   - Agent runs (per month)
   - Teams (peak concurrent)
   - Users (monthly active)
   - Tool calls (optional: charge per API call to expensive tools)

2. **Feature Usage**:
   - Integration usage (Slack events, GitHub webhooks, PagerDuty alerts)
   - Knowledge base ingestion (documents, proposals)
   - Custom MCPs loaded

### Billing Models

**Model A: Tiered (Recommended)**
- Fixed annual fee based on tier
- Soft limits on usage (warnings, not hard blocks)
- Overages: $0.50 per agent run above quota

**Model B: Consumption-Based**
- $1.00 per agent run
- Volume discounts: >10k runs/month = $0.75, >50k = $0.50
- Minimum commit: $10,000/year

**Model C: Seat-Based**
- $500/team/month
- Unlimited agent runs per team
- Annual prepay discount: 20%

### Invoice Generation

**Flow**:
```
1. Usage data collected via telemetry heartbeats
2. Aggregated monthly in license service DB
3. Finance team exports CSV or API call to billing system (Stripe, Zuora)
4. Invoice sent to customer (Net 30)
```

**For Air-Gapped**:
- Annual pre-payment (no usage metering)
- True-up process: Customer reports usage quarterly, pay difference

---

## Remote Monitoring & Support

### Telemetry Consent

**Opt-In During Installation**:
```yaml
# values-customer.yaml
telemetry:
  enabled: true  # Default: false
  endpoint: https://telemetry.incidentfox.ai
  interval_minutes: 5
  anonymize: true  # Hash all identifiers
```

**What Customers Get**:
- Proactive alerts (e.g., "Your license expires in 14 days")
- Performance benchmarking (vs other customers)
- Usage insights dashboard in portal

### Support Tiers

| Tier | Channels | Response SLA | Resolution SLA | On-Call |
|------|----------|--------------|----------------|---------|
| **Starter** | Email | 48h | 5 business days | No |
| **Professional** | Email + Shared Slack | 24h | 3 business days | No |
| **Enterprise** | Dedicated Slack | 4h | 1 business day | Yes (Sev 1) |
| **Enterprise Plus** | Dedicated Slack + Phone | 1h | 4h (Sev 1) | Yes (24/7) |

### Proactive Monitoring (Our Side)

**Alerts We Watch** (if telemetry enabled):
- License expiring <30 days
- Error rate >5%
- Agent run success rate <90%
- OpenAI API errors (suggests customer key issue)
- Deployment stuck in CrashLoopBackOff

**Runbook**:
1. Alert fires in our PagerDuty
2. On-call engineer checks customer tier
3. If Enterprise+: Reach out proactively via Slack
4. Otherwise: Email customer with diagnostics and suggested fix

---

## Installation Package

### Directory Structure

```
incidentfox-enterprise-v1.2.0/
├── README.md                          # Quick start
├── INSTALLATION_GUIDE.md              # Detailed step-by-step
├── LICENSE_AGREEMENT.pdf              # EULA
├── incidentfox-installer              # CLI tool (Linux/macOS binary)
├── charts/
│   └── incidentfox-enterprise-1.2.0.tgz  # Helm chart
├── images/                            # Container images (air-gapped)
│   ├── agent-v1.2.0.tar
│   ├── config-service-v1.2.0.tar
│   ├── orchestrator-v1.2.0.tar
│   ├── web-ui-v1.2.0.tar
│   ├── ai-pipeline-v1.2.0.tar
│   └── knowledge-base-v1.2.0.tar
├── examples/
│   ├── values-connected.yaml
│   ├── values-airgapped.yaml
│   └── values-production.yaml
├── scripts/
│   ├── load-images.sh                 # docker load for air-gapped
│   ├── check-prerequisites.sh         # Verify K8s setup
│   └── backup-database.sh             # Backup helper
└── docs/
    ├── ARCHITECTURE.md
    ├── OPERATIONS.md
    ├── TROUBLESHOOTING.md
    └── AIRGAPPED.md
```

### Delivery Methods

**Connected Customers**:
- Download link from customer portal
- Helm chart: `helm pull oci://registry-1.docker.io/incidentfox/incidentfox --version 0.1.0`
- Docker images: `docker pull incidentfox/agent:v1.0.0`

**Air-Gapped Customers**:
- Encrypted USB drive (mailed via FedEx)
- Secure file transfer (SFTP to customer's bastion host)
- Checksum verification: `sha256sum incidentfox-enterprise-v1.2.0.tar.gz`

---

## Implementation Roadmap

### Phase 1: MVP for Connected On-Prem (Weeks 1-4)

**Week 1: License Service**
- [ ] Build FastAPI service (activate, validate, heartbeat endpoints)
- [ ] PostgreSQL schema (license_keys, activations, usage_logs)
- [ ] JWT signing/verification (RS256)
- [ ] Deploy to AWS (us-west-2, HA setup)
- [ ] Integration tests

**Week 2: License Enforcement**
- [ ] Add license validation to agent startup
- [ ] Add license checks before agent runs (orchestrator)
- [ ] Add license checks before team provisioning (config service)
- [ ] Quota tracking in PostgreSQL (monthly agent runs)
- [ ] Grace period logic (30 days post-expiry)

**Week 3: Telemetry Service**
- [ ] Build telemetry API (metrics endpoint)
- [ ] ClickHouse or TimescaleDB setup
- [ ] Add telemetry client to orchestrator
- [ ] Anonymization helpers (hash customer IDs)
- [ ] Opt-in configuration in Helm chart

**Week 4: Helm Chart Refactoring**
- [ ] Remove AWS-specific dependencies (ALB annotations optional)
- [ ] Support generic Ingress (NGINX, Traefik)
- [ ] Support external vs in-cluster PostgreSQL
- [ ] Add license configuration (online/offline modes)
- [ ] Add telemetry configuration
- [ ] Test on non-AWS K8s (GKE, AKS, Rancher)

**Deliverables**:
- ✅ Connected on-prem deployment works on any K8s
- ✅ License validation enforced
- ✅ Telemetry collecting anonymized metrics

---

### Phase 2: Air-Gapped Support (Weeks 5-6)

**Week 5: Offline License Validation**
- [ ] Generate offline license files (signed JWTs, 1-year expiry)
- [ ] Embed public key in agent Docker image
- [ ] Offline validation logic (no API calls)
- [ ] Test license expiry handling
- [ ] Document license renewal process (customer receives new .lic file)

**Week 6: Local LLM Integration**
- [ ] Add support for OpenAI-compatible APIs (vLLM, Ollama, LM Studio)
- [ ] Test with Llama 3 70B (open-source model)
- [ ] Document GPU requirements (NVIDIA A100 recommended)
- [ ] Create air-gapped Helm values example
- [ ] Test full air-gapped deployment (no internet)

**Deliverables**:
- ✅ Air-gapped deployment works with offline licenses
- ✅ Local LLM integration tested and documented

---

### Phase 3: Customer Portal & Automation (Weeks 7-8)

**Week 7: Customer Portal**
- [ ] Build Next.js app (portal.incidentfox.ai)
- [ ] License management UI (view entitlements, usage)
- [ ] Download center (Helm charts, images, docs)
- [ ] Support ticket system (or integrate with Zendesk)
- [ ] Auth: Email/password + 2FA

**Week 8: Installation Automation**
- [ ] Build CLI installer (`incidentfox-installer`)
- [ ] Interactive prompts (license key, mode, database, ingress)
- [ ] Helm install automation
- [ ] Health check validation
- [ ] Generate installation report (PDF)

**Deliverables**:
- ✅ Customer self-service portal live
- ✅ One-command installer for customers

---

### Phase 4: Pilot with Design Partner (Weeks 9-10)

**Week 9: Design Partner Deployment**
- [ ] Select 1-2 enterprise customers (existing or new)
- [ ] Schedule deployment (2-day engagement)
- [ ] Run through full installation process
- [ ] Collect feedback (pain points, missing features)
- [ ] Document edge cases

**Week 10: Iteration & Docs**
- [ ] Fix bugs discovered in pilot
- [ ] Improve documentation based on feedback
- [ ] Create video tutorials (installation, operations)
- [ ] Prepare sales collateral (one-pager, architecture diagrams)

**Deliverables**:
- ✅ 2 successful on-prem deployments
- ✅ Polished docs and installation package
- ✅ Ready for general availability

---

## Pricing Models

### Recommendation: Tiered Annual Licensing

**Rationale**:
- Predictable revenue for us
- Budget-friendly for customers (vs consumption surprises)
- Encourages usage (no fear of overage charges)

### Sample Pricing

| Tier | Annual License | Included | Best For |
|------|---------------|----------|----------|
| **Starter** | $25,000 | 5 teams, 10k runs/mo | Small SRE teams (10-50 engineers) |
| **Professional** | $75,000 | 20 teams, 50k runs/mo, SSO | Mid-market (100-500 engineers) |
| **Enterprise** | $200,000 | Unlimited teams, 200k runs/mo | Large enterprises (500+ engineers) |
| **Enterprise Plus** | Custom | Unlimited + PS hours | Strategic accounts, custom integrations |

**Overages** (soft enforcement):
- Starter/Professional: $0.50/run above quota
- Enterprise: Unlimited with annual true-up

**Discounts**:
- Multi-year: 10% (2 years), 15% (3 years)
- Non-profit/education: 50%
- Early adopters (first 10 customers): 20%

**Professional Services** (optional add-on):
- Custom MCP development: $15,000/MCP
- Custom agent: $25,000/agent
- Air-gapped deployment assistance: $10,000 (one-time)
- Annual training package: $20,000 (4 sessions)

---

## Summary & Next Steps

### What You Have Today
✅ Production-ready SaaS product on AWS
✅ Kubernetes-based architecture (portable)
✅ Multi-tenant with team isolation
✅ Comprehensive tool suite (50+ tools)
✅ Evaluation-driven quality (85/100 score)

### What You Need to Build
🔨 **License Service** (4 weeks) - Activation, validation, entitlement enforcement
🔨 **Telemetry Service** (2 weeks) - Usage tracking, proactive support
🔨 **Helm Chart Refactoring** (2 weeks) - Portable to any K8s, no AWS lock-in
🔨 **Air-Gapped Support** (2 weeks) - Offline licenses, local LLM integration
🔨 **Customer Portal** (2 weeks) - Self-service license management
🔨 **Installation Automation** (1 week) - CLI installer, one-click setup

**Total Estimated Effort**: 8-10 weeks (1 full-time backend engineer + 1 DevOps/infra engineer)

### Immediate Next Steps

1. **Validate Demand** (Week 1):
   - Talk to 5-10 enterprise prospects
   - Ask: "Would you deploy IncidentFox on-prem? What's your K8s setup?"
   - Prioritize: Connected vs Air-gapped demand

2. **Design License Model** (Week 1):
   - Define tiers (Starter, Pro, Enterprise)
   - Set pricing (benchmark: PagerDuty, Datadog, LLM tool competitors)
   - Draft EULA (legal review)

3. **Spike: Portable Helm Chart** (Week 2):
   - Test current Helm chart on GKE or AKS
   - Identify all AWS-specific dependencies
   - Prototype generic Ingress (NGINX)

4. **Build License Service** (Weeks 3-4):
   - Start with MVP: activate + validate endpoints
   - Integrate into agent (startup license check)

5. **Alpha Test** (Week 5):
   - Deploy in a non-AWS K8s cluster (your own or friendly customer)
   - Validate full installation flow
   - Collect feedback

6. **Beta Program** (Weeks 6-8):
   - Recruit 2-3 design partners
   - Assisted deployments (learn pain points)
   - Iterate on docs and installer

7. **GA Launch** (Week 10):
   - Announce on-prem availability
   - Publish pricing and documentation
   - Enable self-service downloads

---

## Appendix: Competitive Analysis

### How Others Do On-Prem

| Product | Model | Licensing | Support | Air-Gapped |
|---------|-------|-----------|---------|------------|
| **Datadog Agent** | Open-source agent, SaaS backend | Usage-based (hosts) | Community + Paid | No (requires Datadog SaaS) |
| **PagerDuty** | SaaS-only | Seat-based | Tiered SLA | No |
| **GitHub Enterprise Server** | On-prem appliance | Seat-based (annual) | Dedicated support | Yes |
| **GitLab Self-Managed** | Docker/K8s | Tiered (Free/Premium/Ultimate) | Community + Paid | Yes |
| **Elastic Enterprise** | Helm chart | Tiered + Usage | Community + Support contract | Yes (with X-Pack) |
| **HashiCorp Vault** | Binary/Helm | OSS + Enterprise tiers | Community + Support contract | Yes |

**Key Insight**: Most enterprise dev tools offer on-prem with:
1. Helm chart or appliance (we'll use Helm ✅)
2. Annual licensing with tiers (we'll copy this ✅)
3. Usage tracking via phone-home (we'll build telemetry ✅)
4. Air-gapped for regulated industries (we'll support with local LLM ✅)

---

**Questions?** Contact the IncidentFox team.
