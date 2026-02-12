---
name: runtime-config-flagd
description: Feature flag management via flagd (OpenFeature). Use to list, inspect, and toggle feature flags in the OTel Demo environment. Flags control incident injection scenarios (payment failures, CPU spikes, memory leaks, etc.) and can be toggled for remediation.
category: runtime-config
required_integrations:
  - kubernetes
---

# Feature Flag Management (flagd)

## How It Works

The OpenTelemetry Demo uses [flagd](https://flagd.dev/) as its feature flag provider. Flags are stored in a Kubernetes ConfigMap and loaded by the flagd service. Services check flags at runtime via the OpenFeature SDK to decide whether to inject failures.

**Flag lifecycle:**
1. Flag definitions live in a ConfigMap (`flagd-config` in `otel-demo` namespace)
2. flagd watches the ConfigMap and hot-reloads on changes
3. Services evaluate flags via gRPC and behave accordingly
4. To remediate an incident, set the flag's default variant to `off`

## Available Scripts

All scripts are in `.claude/skills/runtime-config-flagd/scripts/`

### list_scenarios.py - List Incident Scenarios (START HERE)
Shows all available incident scenarios with their current status.
```bash
python .claude/skills/runtime-config-flagd/scripts/list_scenarios.py

# Only show currently active scenarios
python .claude/skills/runtime-config-flagd/scripts/list_scenarios.py --active-only

# JSON output
python .claude/skills/runtime-config-flagd/scripts/list_scenarios.py --json
```

Output includes: flag name, current state (active/inactive), affected service, effect description, detection method, and remediation steps.

### list_flags.py - List All Feature Flags
```bash
python .claude/skills/runtime-config-flagd/scripts/list_flags.py

# Show full variant details
python .claude/skills/runtime-config-flagd/scripts/list_flags.py --verbose

# Only incident-related flags
python .claude/skills/runtime-config-flagd/scripts/list_flags.py --incidents-only
```

### get_flag.py - Inspect a Specific Flag
```bash
python .claude/skills/runtime-config-flagd/scripts/get_flag.py <flag_key>

# Examples:
python .claude/skills/runtime-config-flagd/scripts/get_flag.py paymentFailure
python .claude/skills/runtime-config-flagd/scripts/get_flag.py adHighCpu --json
```

### set_flag.py - Toggle a Flag (Remediation)
```bash
# ALWAYS dry-run first
python .claude/skills/runtime-config-flagd/scripts/set_flag.py <flag_key> <variant> --dry-run

# Then apply
python .claude/skills/runtime-config-flagd/scripts/set_flag.py <flag_key> <variant>

# Examples:
python .claude/skills/runtime-config-flagd/scripts/set_flag.py paymentFailure off --dry-run
python .claude/skills/runtime-config-flagd/scripts/set_flag.py paymentFailure off
python .claude/skills/runtime-config-flagd/scripts/set_flag.py adHighCpu off
python .claude/skills/runtime-config-flagd/scripts/set_flag.py emailMemoryLeak off
```

## Incident Scenarios Reference

| Scenario | Flag | Service | Effect | Remediation |
|----------|------|---------|--------|-------------|
| Payment Failure | `paymentFailure` | payment (Node.js) | Configurable % of requests fail | Set to `off` |
| Payment Unreachable | `paymentUnreachable` | payment | Complete unavailability | Set to `off` |
| High CPU | `adHighCpu` | ad (Java) | CPU spike 80-100% | Set to `off` |
| GC Pressure | `adManualGc` | ad (Java) | Frequent full GC pauses | Set to `off` |
| Ad Failure | `adFailure` | ad (Java) | Ad service errors | Set to `off` |
| Memory Leak | `emailMemoryLeak` | email (Ruby) | OOM after minutes | Set to `off` + restart pod |
| Latency Spike | `imageSlowLoad` | image-provider | 5-10s delay | Set to `off` |
| Kafka Lag | `kafkaQueueProblems` | checkout/accounting | Consumer lag | Set to `off` |
| Cache Failure | `recommendationCacheFailure` | recommendation | Cache miss storm | Set to `off` |
| Catalog Failure | `productCatalogFailure` | product-catalog | Product query errors | Set to `off` |
| Cart Failure | `cartFailure` | cart (.NET) | Cart ops fail | Set to `off` |
| Traffic Spike | `loadGeneratorFloodHomepage` | all services | Request flood | Set to `off` |
| LLM Inaccuracy | `llmInaccurateResponse` | product-reviews | Wrong AI content | Set to `off` |
| LLM Rate Limit | `llmRateLimitError` | product-reviews | 429 errors | Set to `off` |

## Flag Variant Reference

Flags have different variant types:

**Boolean flags** (on/off):
- `adHighCpu`, `adManualGc`, `adFailure`, `paymentUnreachable`, `cartFailure`
- `recommendationCacheFailure`, `productCatalogFailure`
- `llmInaccurateResponse`, `llmRateLimitError`
- Variants: `on` (true), `off` (false)

**Percentage flags** (graduated failure rate):
- `paymentFailure`: `off` (0), `10%` (0.1), `25%` (0.25), `50%` (0.5), `75%` (0.75), `90%` (0.95), `100%` (1)

**Intensity flags** (graduated effect):
- `emailMemoryLeak`: `off` (0), `1x` (1), `10x` (10), `100x` (100), `1000x` (1000), `10000x` (10000)
- `imageSlowLoad`: `off` (0), `5sec` (5000ms), `10sec` (10000ms)

**Numeric flags**:
- `kafkaQueueProblems`: `off` (0), `on` (100)
- `loadGeneratorFloodHomepage`: `off` (0), `on` (100)

## Remediation Workflow

1. **Identify the scenario** - Use `list_scenarios.py --active-only` to see active incidents
2. **Confirm the flag** - Use `get_flag.py <flag_key>` to verify current state
3. **Dry-run** - Use `set_flag.py <flag_key> off --dry-run` to preview change
4. **Apply** - Use `set_flag.py <flag_key> off` to disable the incident
5. **Verify** - Check metrics/logs to confirm the issue is resolving
6. **Post-remediation** - Some scenarios (memory leak) may also require a pod restart

## Safety

- **ALWAYS dry-run first** before setting flags
- Setting a flag to `off` is always safe — it restores normal behavior
- Setting a flag to `on` or a non-zero variant **injects failures** — only do this intentionally
- Flag changes take effect within seconds (flagd hot-reload)
- For `emailMemoryLeak`, after setting to `off` you may also need to restart the email pod to reclaim leaked memory

## Quick Commands

| Goal | Command |
|------|---------|
| See active incidents | `list_scenarios.py --active-only` |
| Check a specific flag | `get_flag.py paymentFailure` |
| Disable payment failure | `set_flag.py paymentFailure off` |
| Enable payment failure at 50% | `set_flag.py paymentFailure 50%` |
| Disable all CPU spikes | `set_flag.py adHighCpu off` |
| See all flags verbose | `list_flags.py --verbose` |
