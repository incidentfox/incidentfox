# IncidentFox - Deployment Guide

Complete deployment guide for all deployment options: Docker Compose (self-hosted), Kubernetes (Helm), and production deployments.

---

## Deployment Options

| Option | Best For | Time to Deploy |
|--------|----------|---------------|
| **Docker Compose** | Quick start, single server, testing | 5 minutes |
| **Kubernetes (Helm)** | Production, scaling, high availability | 15 minutes |
| **On-Premise** | Enterprise security requirements | Contact us |

---

## Docker Compose (Self-Hosted)

**Best for:** Quick start, development, single-server deployments

### Prerequisites

- Docker and Docker Compose
- Slack workspace (you'll create an app)
- Anthropic API key

### Quick Deploy

```bash
# Clone repository
git clone https://github.com/incidentfox/incidentfox.git
cd incidentfox

# Create configuration
cp .env.example .env

# Edit .env and add your credentials:
# - SLACK_BOT_TOKEN=xoxb-...
# - SLACK_APP_TOKEN=xapp-...
# - ANTHROPIC_API_KEY=sk-ant-...

# Start services
docker-compose up -d

# Check status
docker-compose ps
```

### What's Running

- **Slack Bot** - Connects to your Slack workspace via Socket Mode
- **SRE Agent** - Runs AI investigations with Claude

### Common Operations

```bash
# View logs
docker-compose logs -f

# Restart
docker-compose restart

# Stop
docker-compose down

# Update
git pull && docker-compose up -d --build
```

**Full setup guide:** See [Slack Integration](INTEGRATIONS.md#slack-bot-primary-interface) for detailed Slack app configuration.

### Scaling to Production

For production workloads, the SRE agent includes Kubernetes deployment with enhanced isolation:

```bash
cd sre-agent

# First time: Create cluster with gVisor
make setup-prod

# Deploy
make deploy-prod
```

This provides:
- Auto-scaling based on load
- Enhanced isolation (gVisor runtime)
- Better observability with metrics
- Multi-tenant support

See `sre-agent/README.md` for details.

### Why Self-Host?

✅ **Simple approval** - No third-party vendor review needed
✅ **Your infrastructure** - Data never leaves your environment
✅ **Fully customizable** - Add your own tools and integrations
✅ **Cost effective** - Pay only for compute + Claude API usage
✅ **No vendor lock-in** - Full control over your deployment

---

## Kubernetes (Helm)

**Best for:** Production deployments, teams, scaling

### Prerequisites

- Kubernetes cluster (1.24+)
- PostgreSQL database
- OpenAI API key
- Helm 3+

### Deploy with Helm

```bash
# Create namespace
kubectl create namespace incidentfox

# Create required secrets
kubectl create secret generic incidentfox-database-url \
  --from-literal=DATABASE_URL="postgresql://user:pass@host:5432/incidentfox" \
  -n incidentfox

kubectl create secret generic incidentfox-openai \
  --from-literal=api_key="sk-your-openai-key" \
  -n incidentfox

kubectl create secret generic incidentfox-config-service \
  --from-literal=ADMIN_TOKEN="your-admin-token" \
  --from-literal=TOKEN_PEPPER="random-32-char-string" \
  -n incidentfox

# Deploy
helm upgrade --install incidentfox ./charts/incidentfox \
  -n incidentfox \
  -f charts/incidentfox/values.yaml

# Check status
kubectl get pods -n incidentfox
```

### Helm Values Profiles

- **values.yaml** - Default configuration
- **values.pilot.yaml** - Minimal first-deploy profile (token auth, HTTP)
- **values.prod.yaml** - Production profile (OIDC, HTTPS, HPA)

See [charts/incidentfox/README.md](../charts/incidentfox/README.md) for full configuration options.

---

## Internal Deployment (IncidentFox Team)

The following sections are specific to the IncidentFox production cluster.

### Prerequisites

- AWS CLI configured for account `103002841599`
- kubectl context set to `incidentfox-demo`
- Docker Desktop running

---

### ECR Login

All services require ECR authentication:

```bash
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin \
  103002841599.dkr.ecr.us-west-2.amazonaws.com
```

---

### Deploy All Services

```bash
./scripts/deploy_all.sh
```

This script:
1. Builds all Docker images
2. Pushes to ECR
3. Restarts all deployments
4. Waits for rollout completion

---

### Deploy Individual Service

### Agent

```bash
cd agent
docker build --platform linux/amd64 -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-agent:latest .
docker push 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-agent:latest
kubectl rollout restart deployment/incidentfox-agent -n incidentfox
kubectl rollout status deployment/incidentfox-agent -n incidentfox --timeout=90s
```

See: `/agent/docs/DEPLOYMENT.md`

### Orchestrator

```bash
cd orchestrator
docker build --platform linux/amd64 -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-orchestrator:latest .
docker push 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-orchestrator:latest
kubectl rollout restart deployment/incidentfox-orchestrator -n incidentfox
```

See: `/orchestrator/docs/DEPLOYMENT.md`

### Config Service

```bash
cd config_service
docker build --platform linux/amd64 -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-config-service:latest .
docker push 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-config-service:latest
kubectl rollout restart deployment/incidentfox-config-service -n incidentfox
```

See: `/config_service/docs/DEPLOYMENT.md`

### Web UI

```bash
cd web_ui
docker build --platform linux/amd64 -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-web-ui:latest .
docker push 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-web-ui:latest
kubectl rollout restart deployment/incidentfox-web-ui -n incidentfox
```

See: `/web_ui/docs/DEPLOYMENT.md`

---

### Database Migrations

Before deploying Config Service:

```bash
cd config_service
alembic upgrade head
```

---

### Verify Deployment

### Check All Pods

```bash
kubectl get pods -n incidentfox
```

All pods should be in `Running` state.

### Check Rollout Status

```bash
kubectl rollout status deployment/incidentfox-agent -n incidentfox
kubectl rollout status deployment/incidentfox-orchestrator -n incidentfox
kubectl rollout status deployment/incidentfox-config-service -n incidentfox
kubectl rollout status deployment/incidentfox-web-ui -n incidentfox
```

### Health Checks

```bash
# Agent
curl http://k8s-incident-incident-561949e6c7-26896650.us-west-2.elb.amazonaws.com/health

# Config Service (via port-forward)
kubectl port-forward -n incidentfox svc/incidentfox-config-service 8090:8080 &
curl http://localhost:8090/health
```

---

### Rollback

### Rollback to Previous Version

```bash
kubectl rollout undo deployment/incidentfox-agent -n incidentfox
```

### Rollback to Specific Revision

```bash
# View history
kubectl rollout history deployment/incidentfox-agent -n incidentfox

# Rollback to revision 3
kubectl rollout undo deployment/incidentfox-agent -n incidentfox --to-revision=3
```

---

### Troubleshooting

### Pod Won't Start

```bash
# Check events
kubectl describe pod -n incidentfox <pod-name>

# Check logs
kubectl logs -n incidentfox <pod-name>
```

### Image Pull Errors

- Verify ECR login is valid (expires after 12 hours)
- Check image exists: `aws ecr describe-images --repository-name incidentfox-agent --region us-west-2`

### OOM on Build

If Docker build fails with OOM:
1. Increase Docker Desktop memory: Settings → Resources → 12+ GB
2. Clean up: `docker system prune -af --volumes`
3. Always use: `--platform linux/amd64`

---

### CI/CD Integration

For automated deployments:
1. GitHub Actions can use same build/push/deploy commands
2. Store AWS credentials as secrets
3. Use `kubectl` with service account token

---

## Related Documentation

- `/docs/OPERATIONS.md` - Operations manual
- `/docs/TROUBLESHOOTING.md` - Common issues
- Service-specific deployment docs in `*/docs/DEPLOYMENT.md`
