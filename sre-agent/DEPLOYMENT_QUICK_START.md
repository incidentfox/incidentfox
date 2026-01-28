# 🚀 Deployment Quick Start

Dead simple deployment. No confusion.

## Local Development

### First Time (Setup Once)

```bash
./scripts/setup-local.sh
```

This creates the Kind cluster and installs all components. **Run once.**

### Day-to-Day (Every Time You Test)

```bash
make dev
```

This:
- Builds latest code
- Loads into Kind
- Starts server
- **Auto-cleanup on Ctrl+C** (docker-compose-like!)

Test with:
```bash
curl -X POST http://localhost:8000/investigate \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "What is 2+2?"}'
```

**Press Ctrl+C to stop** - everything cleans up automatically.

---

## Production Deployment

### First Time (Setup Once)

```bash
./scripts/setup-prod.sh
```

This creates the EKS cluster and installs all components. **Run once per environment.**

What it does:
- Creates EKS cluster (15 min)
- Installs agent-sandbox controller
- Installs gVisor runtime
- Configures IAM, networking, secrets
- Sets up ECR repository

**Prerequisites:**
- AWS credentials configured (`aws configure`)
- `eksctl` installed
- `.env` file with `ANTHROPIC_API_KEY`

### Day-to-Day (Deploy Code Changes)

```bash
make deploy-prod
```

This:
- Builds multi-platform image (AMD64 + ARM64)
- Pushes to ECR
- Updates secrets
- Rolls out deployment

**That's it!** No platform mismatch, no manual steps.

Get production URL:
```bash
make prod-url
```

Test production:
```bash
make test-prod
```

---

## Quick Reference

### Local
```bash
make setup-local    # First-time only
make dev            # Day-to-day (Ctrl+C to stop)
make dev-status     # Check what's running
make dev-reset      # Nuclear option (delete cluster)
```

### Production
```bash
make setup-prod     # First-time only
make deploy-prod    # Day-to-day (deploy code)
make prod-url       # Get URL
make test-prod      # Quick test
```

### Utilities
```bash
make help           # Show all commands
make dev-logs       # View logs
make dev-clean      # Manual cleanup
```

---

## Common Issues & Solutions

### "Kind cluster not found"
❌ Problem: First-time setup not done
✅ Solution: Run `make setup-local`

### "Router not deployed"
❌ Problem: First-time setup not done
✅ Solution: Run `make setup-local`

### "Platform mismatch" in production
✅ **IMPOSSIBLE** - `make deploy-prod` always builds multi-platform

### "ErrImagePull" in production
❌ Problem: ECR credentials expired (rare)
✅ Solution: Run `make deploy-prod` again (refreshes credentials automatically)

### Local server won't start
❌ Problem: Port 8000 or 8080 in use
✅ Solution: Kill other processes or change ports in `.env`

---

## Architecture

### Local (Kind Cluster)
```
make dev
  ↓
Build image (AMD64, your Mac)
  ↓
Load into Kind
  ↓
Start server (Python) → Router (pod) → Sandboxes (pods)
  ↓
Ctrl+C = auto cleanup
```

### Production (EKS Cluster)
```
make deploy-prod
  ↓
Build multi-platform (AMD64 + ARM64)
  ↓
Push to ECR
  ↓
Rolling deployment
  ↓
LoadBalancer → Server (pods) → Router (pods) → Sandboxes (pods)
```

---

## What's What

### Scripts

**Local:**
- `scripts/setup-local.sh` - First-time setup (Kind cluster, router, controller)
- `scripts/dev.sh` - Day-to-day dev (build, run, cleanup)

**Production:**
- `scripts/setup-prod.sh` - First-time setup (EKS cluster, ECR, IAM)
- `scripts/deploy-prod.sh` - Day-to-day deploy (build, push, deploy)

### Makefile Targets

All commands are simple wrappers around the scripts above.
Run `make help` to see everything.

---

## Design Philosophy

**Separate setup from deployment:**
- Setup = slow, complex, one-time
- Deployment = fast, simple, many times

**Docker-compose-like UX:**
- `make dev` = one command to start everything
- Ctrl+C = auto cleanup, no orphaned resources

**No platform mismatch:**
- Local: single-platform OK (your machine)
- Production: always multi-platform (AMD64 + ARM64)

**Single source of truth:**
- One way to do local dev: `make dev`
- One way to deploy prod: `make deploy-prod`
- No confusion possible

---

## Cost Estimate (Production)

**Base Infrastructure:**
- EKS control plane: $73/month
- 3x t3.medium nodes: $93/month
- **Total: ~$166/month**

**Per Investigation:**
- ~$0.001-0.01 (depending on complexity)

**Auto-scaling:**
- Pods: 2-10 replicas (HPA)
- Nodes: 2-6 nodes (Cluster Autoscaler)
- Scales down when idle

---

## Troubleshooting

### Everything is broken locally
```bash
make dev-reset      # Nuclear option
make setup-local    # Fresh start
make dev            # Should work now
```

### Everything is broken in prod
```bash
# Check pods
kubectl get pods -n incidentfox-prod

# Check logs
kubectl logs -n incidentfox-prod -l app=incidentfox-server --tail=50

# Redeploy
make deploy-prod
```

### Need help?
1. Run `make dev-status` or `make prod-url` to see current state
2. Check logs with `make dev-logs`
3. Read `BUG_FIX_SUMMARY.md` for known issues

---

**TL;DR:**

Local: `make setup-local` (once) then `make dev` (daily)
Production: `make setup-prod` (once) then `make deploy-prod` (daily)

That's it. 🎯
