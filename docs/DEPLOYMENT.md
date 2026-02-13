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
- An LLM API key (Anthropic recommended, or any [supported provider](#using-a-different-ai-model))

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

| Service | Port | Description |
|---------|------|-------------|
| **Slack Bot** | - | Connects to your Slack workspace via Socket Mode |
| **SRE Agent** | 8000 | Runs AI investigations |
| **Envoy Proxy** | 8001 | Routes requests, injects credentials |
| **Credential Resolver** | 8002 | Manages API keys, translates LLM requests |

### Using a Different AI Model

By default, IncidentFox uses Claude (Anthropic). You can use any model from any supported provider by setting two things in `.env`:

1. `LLM_MODEL` — the model in `provider/model-name` format
2. The provider's API key

```bash
# Example: Use OpenAI GPT-4o Mini
LLM_MODEL=openai/gpt-4o-mini
OPENAI_API_KEY=sk-your-openai-key
```

The model name always follows the format `provider/model-name`. You can use **any model** the provider offers — the examples below are just common starting points.

#### Direct Providers

These providers have their own API. Set the API key and use any model they offer.

| Provider | Env Var | Example Models |
|----------|---------|---------------|
| **OpenAI** | `OPENAI_API_KEY` | `openai/gpt-4o`, `openai/gpt-4o-mini`, `openai/o1`, `openai/o3-mini` |
| **Google Gemini** | `GEMINI_API_KEY` | `gemini/gemini-2.5-flash`, `gemini/gemini-2.5-pro`, `gemini/gemini-2.0-flash` |
| **DeepSeek** | `DEEPSEEK_API_KEY` | `deepseek/deepseek-chat`, `deepseek/deepseek-reasoner` |
| **Mistral** | `MISTRAL_API_KEY` | `mistral/mistral-small-latest`, `mistral/mistral-large-latest`, `mistral/codestral-latest` |
| **xAI (Grok)** | `XAI_API_KEY` | `xai/grok-3-mini`, `xai/grok-3` |
| **Moonshot (Kimi)** | `MOONSHOT_API_KEY` | `moonshot/kimi-k2-turbo-preview`, `moonshot/moonshot-v1-8k` |
| **MiniMax** | `MINIMAX_API_KEY` | `minimax/MiniMax-Text-01` |

#### Cloud Platforms

These give you access to models from multiple providers (Claude, Llama, Mistral, etc.) through a single platform.

**AWS Bedrock** — Access Claude, Llama, Mistral, and more through your AWS account.

```bash
# Use Claude on Bedrock
LLM_MODEL=bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0

# Use Llama on Bedrock
LLM_MODEL=bedrock/meta.llama3-1-70b-instruct-v1:0

# Auth option A: Bedrock API key (from Bedrock console → API keys)
AWS_BEARER_TOKEN_BEDROCK=your-bearer-token

# Auth option B: IAM credentials
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1
```

Bedrock model IDs follow AWS naming (e.g., `anthropic.claude-3-haiku-20240307-v1:0`). Find available models in the [AWS Bedrock console](https://console.aws.amazon.com/bedrock/).

**Azure AI Foundry** — Deploy and use models through Azure serverless endpoints.

```bash
# Use your deployed model (deployment name from Azure portal)
LLM_MODEL=azure_ai/DeepSeek-V3
AZURE_AI_API_KEY=your-key
AZURE_AI_API_BASE=https://your-endpoint.services.ai.azure.com
```

The model name after `azure_ai/` must match your **deployment name** in Azure AI Foundry. Create deployments in the [Azure AI Foundry portal](https://ai.azure.com/).

**OpenRouter** — Access 300+ models from dozens of providers with a single API key. Useful as a fallback for models without direct API support.

```bash
# Use any model on OpenRouter
LLM_MODEL=openrouter/qwen/qwen-2.5-72b-instruct
LLM_MODEL=openrouter/cohere/command-a
LLM_MODEL=openrouter/meta-llama/llama-3.1-70b-instruct
LLM_MODEL=openrouter/anthropic/claude-3.5-haiku
OPENROUTER_API_KEY=sk-or-your-key
```

Model IDs follow the format `openrouter/org/model-name`. Browse available models at [openrouter.ai/models](https://openrouter.ai/models).

#### After Changing Models

Restart the services to pick up the new configuration:

```bash
docker compose up -d --build credential-resolver
docker compose restart envoy
```

### Testing Models

To verify your model configuration works end-to-end:

```bash
cd sre-agent/credential-proxy
pip install httpx    # if not installed
python test_models.py --proxy          # test all models through docker-compose
python test_models.py --proxy openai   # test only OpenAI
```

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
