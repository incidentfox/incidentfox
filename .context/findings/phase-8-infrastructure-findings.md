# Phase 8: Infrastructure & Deployment Security Audit Findings

**Date**: 2026-02-18
**Scope**: Helm charts, CI/CD workflows, Docker, Terraform, values files
**Status**: 6 P0 fixed (securityContext), 27 deferred

## Summary

| Severity | Count | Fixed | Deferred |
|----------|-------|-------|----------|
| P0 | 9 | 6 | 3 |
| P1 | 7 | 0 | 7 |
| P2 | 11 | 0 | 11 |
| P3 | 6 | 0 | 6 |
| **Total** | **33** | **6** | **27** |

---

## P0 — Critical (9 findings, 6 FIXED)

### INFRA-001–006: Missing securityContext in Deployments ✅ FIXED
- **Files**: `config-service.yaml`, `slack-bot.yaml`, `orchestrator.yaml`, `web-ui.yaml`, `ultimate-rag.yaml`, `k8s-gateway.yaml`
- **Issue**: No pod-level `runAsNonRoot`/`runAsUser`/`fsGroup` and no container-level `allowPrivilegeEscalation: false` / `capabilities.drop: ALL`.
- **Fix**: Added pod-level and container-level securityContext to all 6 templates. Committed as `eaf74378`.

### INFRA-007: Missing securityContext in AI Pipeline API (deferred)
- **File**: `ai-pipeline-api.yaml`
- **Status**: Deferred — service is disabled in all environments (`enabled: false`). Apply when enabling.

### INFRA-008: Missing securityContext in Sandbox Cleanup CronJob (deferred)
- **File**: `sandbox-cleanup.yaml`
- **Status**: Deferred — needs testing since CronJob runs kubectl.

### INFRA-009: gVisor DaemonSet Privileged Mode (deferred)
- **File**: `gvisor-installer.yaml`
- **Issue**: Init container runs with `privileged: true`, `hostPID: true`, `hostNetwork: true`. Required for gVisor installation.
- **Status**: Accepted risk — infrastructure installer, not user workload. Checksum validation is in place.

---

## P1 — High (7 findings, all deferred)

### INFRA-010: Missing Resource Limits in Multiple Deployments
- **Files**: slack-bot, web-ui, orchestrator, k8s-gateway, ultimate-rag, dependency-service
- **Issue**: Without resource limits, runaway containers can exhaust cluster resources.
- **Recommendation**: Add `resources.requests` and `resources.limits` to all deployments.

### INFRA-011: AWS Metadata SSRF Not Fully Blocked
- **File**: `sandbox-networkpolicy.yaml` lines 94-105
- **Issue**: NetworkPolicy blocks 169.254.0.0/16 on ports 80, 443, 6443 but not all metadata ports.

### INFRA-012: Sandbox Warm Pool JWT File Handling
- **File**: `sandbox-warmpool.yaml` lines 132-141
- **Issue**: JWT read from `/tmp` file via Lua. No protection against symlink attacks.

### INFRA-013: Secrets as Environment Variables
- **Files**: agent.yaml, slack-bot.yaml, config-service.yaml, orchestrator.yaml, credential-resolver.yaml
- **Issue**: `secretKeyRef` injects secrets as env vars, visible via `/proc/PID/environ`.
- **Recommendation**: Mount secrets as files with restricted permissions instead.

### INFRA-014: Slack Bot LoadBalancer Exposed (staging)
- **File**: `values.staging.yaml` lines 195-202
- **Issue**: Service type `LoadBalancer` exposes Slack Bot to internet.

### INFRA-015: Trivy Ignore Fragility
- **File**: `.trivyignore`
- **Issue**: Multiple CVEs ignored with "post-install upgrade" claims that aren't reproducible.

### INFRA-016: WAF Not Enabled
- **Files**: `values.staging.yaml`, `values.prod.yaml`
- **Issue**: `waf.enabled: false` in both environments. ALB unprotected.

---

## P2 — Medium (11 findings, all deferred)

### INFRA-017: Missing readOnlyRootFilesystem
- **Files**: slack-bot, web-ui, config-service, ai-pipeline, dependency-service
- **Issue**: Without read-only root, attackers can write backdoors.

### INFRA-018: Warm Pool "unclaimed" Placeholder Values
- **File**: `sandbox-warmpool.yaml` lines 290-294
- **Issue**: If `/claim` fails, sandboxes run as "unclaimed" — potential tenant isolation bypass.

### INFRA-019: No NetworkPolicy for Agent Deployment
- **File**: `sandbox-networkpolicy.yaml`
- **Issue**: Agent pod has no NetworkPolicy restricting ingress/egress.

### INFRA-020: Lua JWT Injection via /tmp File
- **File**: `sandbox-warmpool.yaml` lines 130-141
- **Issue**: Attacker with write access to /tmp could spoof JWT.

### INFRA-021: AWS STS Identity in CI Logs
- **File**: `.github/workflows/deploy-eks.yml` lines 183-186
- **Issue**: `aws sts get-caller-identity` output logged unmasked.

### INFRA-022: Long-Lived AWS Credentials in CI
- **File**: `.github/workflows/deploy-eks.yml`
- **Issue**: Uses `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` instead of OIDC federation.

### INFRA-023: Gitleaks Allowlist Over-Broad
- **File**: `.gitleaks.toml`
- **Issue**: Allows entire directories (knowledge_base/, docs/) which could hide real secrets.

### INFRA-024: Sandbox Pod ServiceAccount Too Permissive
- **File**: `sandbox-rbac.yaml` lines 150-175
- **Issue**: Can read any ConfigMap and pod logs in cluster.

### INFRA-025: sre-agent Dockerfile setuid Risk
- **File**: `sre-agent/Dockerfile` lines 31-52
- **Issue**: kubectl installed as root; if binary has setuid bit, agent user could escalate.

### INFRA-026: Warm Pool Agent Resources Not Set
- **File**: `sandbox-warmpool.yaml` lines 355-363
- **Issue**: `warmPool.agentResources` not defined in values files — unlimited container resources.

### INFRA-027: S3 Init Container No Security Context
- **File**: `ultimate-rag.yaml` lines 54-74
- **Issue**: S3 download init container has no securityContext.

---

## P3 — Low (6 findings, all deferred)

### INFRA-028: Config Service Encryption Key Rotation
### INFRA-029: Agent Health Server Port Not Documented
### INFRA-030: K8s Gateway Command Timeout Not Bounded
### INFRA-031: External Secrets Operator Version Pinning
### INFRA-032: Trivy Exit Code Confusion
### INFRA-033: Ultimate RAG S3 Init No Checksum Validation
