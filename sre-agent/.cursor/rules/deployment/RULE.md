---
description: "Deployment standards for production and local environments"
globs:
  - "scripts/deploy-*.sh"
  - "scripts/setup-*.sh"
  - "Makefile"
  - "k8s/**/*.yaml"
  - ".github/workflows/*.yml"
alwaysApply: false
---

# Deployment Standards

## Multi-Platform Builds (CRITICAL)

**ALWAYS** build multi-platform Docker images for production to prevent ARM64→AMD64 mismatch:

```bash
# Correct (automatically handled by make deploy-prod)
docker buildx build --platform linux/amd64,linux/arm64 -t <image> --push .

# Wrong (will fail on AMD64 nodes if built on ARM64 Mac)
docker build -t <image> .
docker push <image>
```

**Prevention Layers:**
1. `make deploy-prod` handles multi-platform builds automatically
2. Old `make docker-push-ecr` warns and requires confirmation
3. Documentation emphasizes using `make deploy-prod`

## Deployment Commands

### Local Development
```bash
make setup-local  # First time only (creates Kind cluster)
make dev          # Day-to-day (docker-compose-like UX, Ctrl+C to cleanup)
make test-local   # Quick sanity check
```

### Production
```bash
make setup-prod   # First time only (creates EKS, autoscaler, gVisor)
make deploy-prod  # Day-to-day (multi-platform build, ECR push, rollout)
make test-prod    # Quick sanity check
```

## Context Switching

Scripts handle context switching automatically:
- `setup-local.sh` switches to `kind-incidentfox`
- `setup-prod.sh` and `deploy-prod.sh` switch to EKS context
- Users don't need to manually switch contexts

## Environment-Specific Configuration

### Production-Specific
- `USE_GVISOR=true` - Enhanced isolation
- Multi-platform Docker images
- ECR image registry
- Cluster Autoscaler enabled
- Namespace: `incidentfox-prod`

### Local-Specific
- No gVisor (Kind doesn't support it)
- Local Docker images (loaded into Kind)
- Local image for sandbox-router
- Modified sandbox template (no `runtimeClassName`)
- Namespace: `incidentfox-local`

## Deployment Changes Require Full Apply

When updating K8s YAML (like adding `USE_GVISOR`):

```bash
# Wrong - only restarts pods, doesn't apply config changes
kubectl rollout restart deployment/incidentfox-server

# Correct - applies updated YAML then restarts
kubectl apply -f k8s/server-deployment.yaml
kubectl rollout status deployment/incidentfox-server
```

This is why `deploy-prod.sh` uses `kubectl apply`.

## Secrets Management

Production secrets via AWS Secrets Manager + K8s secrets:
```bash
# Update secrets
kubectl create secret generic incidentfox-secrets \
  --from-literal=anthropic-api-key=$ANTHROPIC_API_KEY \
  --from-literal=laminar-api-key=$LMNR_PROJECT_API_KEY \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Cluster Autoscaling

Cluster Autoscaler is auto-installed by `setup-prod.sh`:
- Min nodes: 2
- Max nodes: 6 (increase if needed)
- Scales based on pod resource requests
- Prevents "cluster full" issues

## Verification After Deployment

Always verify:
```bash
# Check image and creation time
kubectl get pods -n incidentfox-prod -o wide

# Check environment variables (like USE_GVISOR)
kubectl describe pod <pod-name> | grep -A 10 "Environment:"

# Check gVisor is being used
kubectl describe pod <sandbox-pod> | grep "Runtime Class Name"
# Should show: Runtime Class Name: gvisor
```

## One-Command Philosophy

Users should never need to remember complex sequences:
- ❌ Bad: "First run this, then wait, then run that, then..."
- ✅ Good: Single command that handles everything

This is why we have `setup-local.sh`, `dev.sh`, `setup-prod.sh`, `deploy-prod.sh`.

