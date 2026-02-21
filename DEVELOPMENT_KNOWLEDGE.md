# IncidentFox - Quick Reference

> **Purpose**: Fast lookup and navigation index for developers and AI assistants

---

## 📚 Documentation Index

### Getting Started
- **[GETTING_STARTED.md](docs/GETTING_STARTED.md)** - Day 1 guide for new developers (30-minute first change)
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - System design, service interactions, multi-tenancy
- **[DEPLOYMENT.md](docs/DEPLOYMENT.md)** - Cross-service deployment procedures
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** - Common issues and solutions

### Design Documents
- **[ROUTING_DESIGN.md](docs/ROUTING_DESIGN.md)** - Webhook routing architecture
- **[MULTI_TENANT_DESIGN.md](docs/MULTI_TENANT_DESIGN.md)** - Multi-tenancy patterns (shared vs dedicated)
- **[CANONICAL_CONFIG_REFERENCE.md](docs/CANONICAL_CONFIG_REFERENCE.md)** - Config format reference
- **[CONFIG_INHERITANCE.md](docs/CONFIG_INHERITANCE.md)** - Config inheritance tutorial
- **[TELEMETRY_SYSTEM.md](docs/TELEMETRY_SYSTEM.md)** - Telemetry system design
- **[ARCHITECTURE_DECISIONS.md](docs/ARCHITECTURE_DECISIONS.md)** - Key ADRs and rationale

### Service-Specific Documentation

**Orchestrator Service** (`/orchestrator/docs/`):
- `WEBHOOKS.md` - Webhook routing implementation
- `PROVISIONING.md` - Team provisioning with K8s resources
- `SLACK_INTEGRATION.md` - Complete Slack flow
- `ARCHITECTURE.md` - Control plane design
- `NORTH_STAR.md` - Target architecture
- `DEPLOYMENT.md` - Orchestrator deployment

**Config Service** (`/config_service/docs/`):
- `API_REFERENCE.md` - Complete REST API documentation
- `DATABASE_SCHEMA.md` - PostgreSQL schema
- `TECH_SPEC.md` - Design specification
- `DEPLOYMENT.md` - Config service deployment

**Web UI** (`/web_ui/docs/`):
- `README.md` - Next.js structure overview
- `BFF_PATTERN.md` - Backend-for-Frontend pattern
- `DEPLOYMENT.md` - UI deployment

**SRE Agent** (`/sre-agent/docs/`):
- `README.md` - Claude SDK overview, when to use vs main agent
- `SANDBOX_ARCHITECTURE.md` - K8s sandboxes, gVisor, isolation
- `SDK_COMPARISON.md` - Claude SDK vs OpenAI Agents SDK (24 pages)
- `KNOWN_ISSUES.md` - Known limitations

---

## 🏗️ System Overview

### Services (K8s namespace: `incidentfox`)
| Service | Purpose | Port |
|---------|---------|------|
| `incidentfox-sre-agent` | Claude SDK agent, sandbox management | 8080 |
| `incidentfox-slack-bot` | Slack UI layer (Socket Mode) | 3000 |
| `incidentfox-orchestrator` | Webhook routing, provisioning | 8080 |
| `incidentfox-config-service` | Config, auth, DB | 8080 |
| `incidentfox-web-ui` | Next.js frontend | 3000 |

### Key URLs (Configure for Your Environment)
```
Web UI:        https://ui.<your-domain>
API Gateway:   https://api.<your-domain> (or your cloud provider's API Gateway)
ALB (HTTP):    http://<your-load-balancer>.<region>.elb.amazonaws.com
RAPTOR KB:     http://<raptor-kb-service>.<region>.elb.amazonaws.com
```

### Infrastructure (Example AWS)
```
Account: <your-aws-account-id>
Region:  <your-region> (e.g., us-west-2)
Cluster: <your-cluster-name>
ECR:     <account-id>.dkr.ecr.<region>.amazonaws.com
```

---

## 🔐 Authentication Cheat Sheet

### Token Types
```bash
# Global Admin (env: ADMIN_TOKEN)
export ADMIN_TOKEN=<secret>

# Org Admin Token (format: {org_id}.{random})
curl -H "Authorization: Bearer extend.xEyGnPw3RCH1l08q2gSb8A" ...

# Team Token (format: {org_id}.{team_id}.{random})
curl -H "Authorization: Bearer extend.extend-sre.J2KnE8rVmCfPWq..." ...
```

### Check Token Identity
```bash
curl -H "Authorization: Bearer <token>" \
  http://config-service:8080/api/v1/auth/me
```

**See**: [config_service/docs/API_REFERENCE.md](config_service/docs/API_REFERENCE.md)

---

## 🚀 Quick Commands

### Deploy All Services
```bash
./scripts/deploy_all.sh
```

### Deploy Individual Service
```bash
cd sre-agent
docker build --platform linux/amd64 -t <your-registry>/incidentfox-sre-agent:latest .
docker push <your-registry>/incidentfox-sre-agent:latest
kubectl rollout restart deployment/incidentfox-sre-agent -n incidentfox
```

**See**: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for detailed procedures

### View Logs
```bash
kubectl logs -n incidentfox deploy/incidentfox-agent --tail=50 -f
```

### Port Forward
```bash
kubectl port-forward -n incidentfox svc/incidentfox-config-service 8090:8080
```

### Check Pod Status
```bash
kubectl get pods -n incidentfox
```

**See**: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for common issues

---

## 🔧 Integration Quick Reference

Integrations are configured per-team via config-service. sre-agent accesses them through skills and scripts that run inside gVisor sandboxes. Credentials are injected at request time by credential-proxy (Envoy).

**See**: [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) for complete configuration

---

## 🌐 Webhook Quick Reference

### Webhook Endpoints (Orchestrator)
```
POST /webhooks/slack/events        - Slack @mentions
POST /webhooks/slack/interactions  - Slack buttons
POST /webhooks/github              - GitHub App
POST /webhooks/pagerduty           - PagerDuty V3
POST /webhooks/incidentio          - Incident.io
```

### External URL (API Gateway)
```
https://on3vboii0g.execute-api.us-west-2.amazonaws.com/webhooks/<service>
```

### Test Routing Lookup
```bash
kubectl run -n incidentfox test-routing --image=curlimages/curl --rm -it --restart=Never -- \
  curl -s -X POST "http://incidentfox-config-service:8080/api/v1/internal/routing/lookup" \
  -H "X-Internal-Service: orchestrator" \
  -H "Content-Type: application/json" \
  -d '{"identifiers":{"slack_channel_id":"C0A4967KRBM"}}'
```

**See**: [orchestrator/docs/WEBHOOKS.md](orchestrator/docs/WEBHOOKS.md) for implementation details

---

## 🤖 Agent Quick Reference

### SRE Agent (Claude SDK)

The active agent system. Runs in isolated gVisor K8s sandbox pods. Uses 45 skills with progressive knowledge loading.

### Run Agent Directly
```bash
curl -X POST http://sre-agent:8080/investigate \
  -H "Authorization: Bearer <TEAM_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Investigate error spike in payment service",
    "team_id": "default"
  }'
```

**See**: [sre-agent/docs/README.md](sre-agent/docs/README.md) for agent architecture

---

## 📊 RAPTOR Knowledge Base Quick Reference

### API Endpoints
```bash
# Tree stats
curl "http://<raptor-kb-host>/api/v1/tree/stats?tree_name=<tree_name>"

# Ask question
curl -X POST "http://<raptor-kb-host>/api/v1/answer" \
  -H "Content-Type: application/json" \
  -d '{"question":"How does webhook routing work?","tree_name":"<tree_name>"}'
```

### Deploy RAPTOR KB (Ultimate RAG)
```bash
cd ultimate_rag
docker buildx build --platform linux/arm64 -t <your-registry>/ultimate-rag:latest --push .
kubectl rollout restart deployment/ultimate-rag -n incidentfox
```

---

## 🗄️ Database Quick Reference

### Connection
```python
DATABASE_URL = "postgresql://incidentfox_user:password@incidentfox-db.xxx.us-west-2.rds.amazonaws.com:5432/incidentfox"
```

### Key Tables
- `org_nodes` - Organization hierarchy
- `node_configurations` - Config JSON per node
- `team_tokens` - Team authentication tokens
- `org_admin_tokens` - Org admin tokens
- `agent_runs` - Agent execution history
- `integration_schemas` - Integration field definitions

### Run Migrations
```bash
cd config_service
alembic upgrade head
```

**See**: [config_service/docs/DATABASE_SCHEMA.md](config_service/docs/DATABASE_SCHEMA.md)

---

## 🧪 Testing Quick Reference

### Test Config Service
```bash
kubectl port-forward -n incidentfox svc/incidentfox-config-service 8090:8080 &
curl http://localhost:8090/health
```

### Test SRE Agent Health
```bash
kubectl port-forward -n incidentfox svc/incidentfox-sre-agent 8080:8080 &
curl http://localhost:8080/health
```

---

## 📦 Container Registry Quick Reference

### Login to ECR (AWS)
```bash
aws ecr get-login-password --region <region> | \
  docker login --username AWS --password-stdin \
  <account-id>.dkr.ecr.<region>.amazonaws.com
```

### Login to Other Registries
```bash
# Docker Hub
docker login -u <username>

# GCR (Google)
gcloud auth configure-docker

# ACR (Azure)
az acr login --name <registry-name>
```

### List Images (AWS ECR)
```bash
aws ecr describe-images --repository-name incidentfox-agent --region <region>
```

---

## 🆘 Emergency Procedures

### Restart All Services
```bash
kubectl rollout restart deployment/incidentfox-sre-agent -n incidentfox
kubectl rollout restart deployment/incidentfox-slack-bot -n incidentfox
kubectl rollout restart deployment/incidentfox-orchestrator -n incidentfox
kubectl rollout restart deployment/incidentfox-config-service -n incidentfox
kubectl rollout restart deployment/incidentfox-web-ui -n incidentfox
```

### Check All Pods
```bash
kubectl get pods -n incidentfox
```

### Rollback Deployment
```bash
kubectl rollout undo deployment/incidentfox-sre-agent -n incidentfox
```

**See**: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for detailed troubleshooting

---

## 📖 Where to Find Information

| Topic | Document |
|-------|----------|
| **First time setup** | [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) |
| **System architecture** | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **How to deploy** | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| **Something is broken** | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| **Integration configuration** | [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) |
| **Webhook routing** | [orchestrator/docs/WEBHOOKS.md](orchestrator/docs/WEBHOOKS.md) |
| **API endpoints** | [config_service/docs/API_REFERENCE.md](config_service/docs/API_REFERENCE.md) |
| **Database schema** | [config_service/docs/DATABASE_SCHEMA.md](config_service/docs/DATABASE_SCHEMA.md) |
| **SRE Agent (Claude SDK)** | [sre-agent/docs/README.md](sre-agent/docs/README.md) |

---

**Last Updated**: 2026-01-12
