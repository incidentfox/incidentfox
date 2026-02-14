# SRE Agent Scripts

Local development scripts for the IncidentFox SRE Agent.

> **Production deploys** use Helm charts via GitHub Actions:
> ```bash
> gh workflow run deploy-eks.yml -f environment=staging -f services=all
> gh workflow run deploy-eks.yml -f environment=production -f services=all
> ```

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
```

**Run this once**, then use `make dev` for daily development.

---

### `setup-github-secrets.sh`
Push AWS/platform secrets to GitHub Actions for CI/CD.

**Usage**:
```bash
./scripts/setup-github-secrets.sh
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
```

**Press Ctrl+C** to stop and cleanup automatically.

---

### `stop-server.sh`
Stop the local server and cleanup resources.

**Usage**:
```bash
./scripts/stop-server.sh
```

---

## Quick Reference

| Task | Command |
|------|---------|
| First-time setup (local) | `make setup-local` |
| Daily development | `make dev` |
| Stop local server | `./scripts/stop-server.sh` |
| Deploy to staging | `gh workflow run deploy-eks.yml -f environment=staging` |
| Deploy to production | `gh workflow run deploy-eks.yml -f environment=production` |
| Check status | `make dev-status` |
| View logs | `make dev-logs` |
