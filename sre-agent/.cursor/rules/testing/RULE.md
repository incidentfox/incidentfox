---
description: "Testing standards and strategies for reliable verification"
globs:
  - "test*.sh"
  - "tests/**/*.py"
  - "tests/**/*.sh"
alwaysApply: false
---

# Testing Standards

## Testing Philosophy

**Quick tests are for sanity checks. Comprehensive tests are for confidence.**

Don't over-engineer quick tests to be 100% reliable. That's what comprehensive E2E tests are for.

## Test Types

### Quick Sanity Checks
```bash
make test-local   # Simple HTTP request to localhost
make test-prod    # Simple HTTP request to production
```

**Purpose:** Fast feedback that basic connectivity works
**Limitations:** May fail due to timing (sandbox startup), cluster capacity
**Acceptable:** These can be flaky - they're just smoke tests

**Don't add:**
- Complex retry logic
- Long waits
- Multiple request patterns
- Thread ID management

**Keep it simple:** Single HTTP request with reasonable timeout (30s)

### Comprehensive E2E Tests
```bash
./test_all_features_e2e.sh local
./test_all_features_e2e.sh prod
```

**Purpose:** Reliable verification before merging
**Features:** Retry logic, proper waits, multiple test scenarios
**Tests:**
- New thread investigation
- Follow-up messages
- Interrupt mid-execution
- Resume after interrupt

**Always run these before merging!**

## Testing Interrupt/Resume

Use prompts that guarantee long execution for reliable interrupt testing:

```bash
# ✅ GOOD - Takes 30+ seconds
PROMPT="Write a comprehensive 10,000 word essay on the history of computing"

# ❌ BAD - Too short, finishes before interrupt
PROMPT="Count from 1 to 100"
```

**Why?** Need enough time to send interrupt before completion. Essay generation ensures consistent long execution.

## Timing Expectations

### Local (Kind, no gVisor)
- Sandbox becomes Ready: ~2 seconds
- First output: ~3-5 seconds
- Total request: ~8-12 seconds

### Production (EKS with gVisor)
- Sandbox becomes Ready: ~2 seconds
- First output: ~4-5 seconds
- Total request: ~10-15 seconds

**These timings are acceptable UX!** Don't optimize further unless user complaints.

## When Tests Fail

### 502 Errors from Quick Tests
**Cause:** Sandbox not fully started (timing issue)
**Solution:** This is expected behavior for quick tests
**Action:** Run comprehensive E2E test instead

### Cluster Full Errors
**Cause:** All nodes at capacity, pods stuck in Pending
**Solution:** Cluster Autoscaler will scale up (wait or increase max nodes)
**Prevention:** Properly configured autoscaling (handled by `setup-prod.sh`)

### Race Condition / Hanging Requests
**Cause:** Session created after StreamingResponse in `sandbox_server.py`
**Solution:** Ensure session creation happens BEFORE StreamingResponse (line 113)
**Test:** Run follow-up requests - if they hang, race condition exists

## Test Environment Setup

### Local Environment
```bash
# Fresh setup
make dev-reset     # Delete everything
make setup-local   # Recreate cluster
make dev           # Start services

# Verify
make dev-status    # Check all components
make test-local    # Quick check
./test_all_features_e2e.sh local  # Full check
```

### Production Environment
```bash
# Deploy latest
make deploy-prod   # Multi-platform build, push, deploy

# Verify
kubectl get pods -n incidentfox-prod  # Check pod status
make test-prod     # Quick check
./test_all_features_e2e.sh prod  # Full check
```

## Debugging Failed Tests

### Check Sandbox Status
```bash
# List sandboxes
kubectl get sandbox -n <namespace>

# Check specific sandbox
kubectl describe sandbox <sandbox-name>

# Check sandbox pod
kubectl get pod <sandbox-pod-name>
kubectl logs <sandbox-pod-name>
```

### Check Router
```bash
# Local
kubectl logs deployment/sandbox-router -n incidentfox-local

# Production
kubectl logs deployment/sandbox-router -n incidentfox-prod
```

### Check Main Server
```bash
# Local
make dev-logs

# Production
kubectl logs deployment/incidentfox-server -n incidentfox-prod
```

## Test Data Cleanup

### Local
```bash
make dev-clean    # Delete sandboxes only
make dev-reset    # Nuclear: delete entire cluster
```

### Production
```bash
# Manual cleanup if needed
kubectl delete sandbox --all -n incidentfox-prod

# Sandboxes auto-cleanup via TTL (no action needed)
```

## Continuous Integration

Tests run in CI on every PR:
```yaml
# .github/workflows/test.yml
- name: Build Docker image
  run: docker build -t incidentfox-agent:test .

- name: Run unit tests
  run: poetry run pytest

- name: Lint code
  run: poetry run black --check . && poetry run isort --check .
```

**Note:** E2E tests require K8s cluster, so they're manual for now.

## Test Coverage Philosophy

**Don't test implementation details.** Test behavior and contracts:

✅ Test:
- HTTP endpoints return correct status codes
- Streaming works across sandbox boundaries
- Interrupts actually stop execution
- Follow-ups work after interrupts
- Sandboxes are isolated (can't access each other)

❌ Don't test:
- Internal function call order
- Private method implementations
- Log message formats
- Exact timing (use ranges)

## Performance Testing

Not currently needed. If you add it later:
- Measure sandbox creation time
- Measure first-token latency
- Measure concurrent investigation capacity
- Test cluster autoscaling behavior

**Current metrics:**
- Sandbox Ready: ~2s
- First output: ~4-5s
- These are acceptable, no optimization needed

