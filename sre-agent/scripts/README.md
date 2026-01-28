# SRE Agent Scripts

Development and operational scripts for the IncidentFox SRE Agent.

## Setup Scripts

### `setup-local.sh`
First-time setup for local development environment.

**What it does**:
- Creates Kind cluster with agent-sandbox controller
- Deploys Sandbox Router
- Deploys Service Patcher
- Creates Kubernetes secrets from `.env`
- Deploys sandbox template

**Usage**:
```bash
make setup-local
# or
./scripts/setup-local.sh
```

**Run this once**, then use `make dev` for daily development.

---

### `setup-prod.sh`
First-time setup for production EKS cluster.

**What it does**:
- Creates EKS cluster
- Installs agent-sandbox CRDs and controller
- Deploys production infrastructure
- Creates secrets from AWS Secrets Manager

**Usage**:
```bash
make setup-prod
# or
./scripts/setup-prod.sh
```

---

## Development Scripts

### `dev.sh`
Start local development environment (like docker-compose).

**What it does**:
- Validates tools and dependencies
- Builds fresh Docker image
- Loads image into Kind cluster
- Starts port-forward to Sandbox Router
- Starts server on port 8000
- Streams sandbox logs automatically

**Usage**:
```bash
make dev
# or
./scripts/dev.sh
```

**Press Ctrl+C** to stop and cleanup automatically.

---

### `stop-server.sh`
Stop the local server and cleanup resources.

**What it does**:
- Kills server process
- Stops port-forwards
- Deletes active sandboxes

**Usage**:
```bash
./scripts/stop-server.sh
```

---

## Deployment Scripts

### `deploy-prod.sh`
Build and deploy to production.

**What it does**:
- Builds multi-platform Docker image (amd64 + arm64)
- Pushes to ECR
- Updates K8s deployment
- Verifies rollout

**Usage**:
```bash
make deploy-prod
# or
./scripts/deploy-prod.sh
```

---

## Quick Reference

| Task | Command |
|------|---------|
| First-time setup (local) | `make setup-local` |
| Daily development | `make dev` |
| Stop local server | `./scripts/stop-server.sh` |
| Deploy to production | `make deploy-prod` |
| Check status | `make dev-status` |
| View logs | `make dev-logs` |

---

## Troubleshooting

### Docker build fails
```bash
# Check Docker is running
docker info

# Check disk space
docker system df
```

### Kind cluster not found
```bash
# List clusters
kind get clusters

# Recreate cluster
make setup-local
```

### Port 8000 already in use
```bash
# Find process using port
lsof -i :8000

# Kill it
pkill -9 -f "python.*server.py"
```

### AWS CLI fails in sandbox
```bash
# Check architecture mismatch
kubectl exec investigation-XXX -- file /usr/local/bin/aws
kubectl exec investigation-XXX -- uname -m
```

See [../AGENTS.md](../AGENTS.md) for more troubleshooting tips.
