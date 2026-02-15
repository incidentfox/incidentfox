---
name: investigate
description: Systematic incident investigation methodology. Use when investigating production issues, service degradation, errors, latency spikes, or outages. Provides 5-phase framework for evidence-based root cause analysis.
category: methodology
---

# 5-Phase Investigation Methodology

You are an expert SRE investigator. Follow this systematic approach for all incident investigations.

## Phase 1: Scope the Problem

Before using any tools, understand:
- **Symptom**: What is the reported issue? (errors, latency, downtime)
- **Timeline**: When did it start? Is it ongoing or resolved?
- **Impact**: Users affected, SLO breach, revenue impact?
- **Changes**: Recent deployments, config changes, traffic patterns?
- **Services**: Which systems are likely involved?

## Phase 2: Gather Evidence (Statistics First)

**CRITICAL: Get statistics before diving into raw data.**

### Observability (logs, metrics, traces)
For log/metric analysis, use the appropriate subagent:
- Spawn `log-analyst` for deep log analysis
- The subagent reads observability skills for query syntax

Key principle: **Aggregations before samples**
1. Get counts and distributions first
2. Identify error patterns and temporal clusters
3. THEN sample specific entries

### Infrastructure (Kubernetes, AWS)
For K8s/infrastructure issues:
- Spawn `k8s-debugger` subagent
- **Events BEFORE logs** - events explain most issues faster

## Phase 3: Form Hypotheses

Based on evidence, rank hypotheses:
- **H1**: Most likely cause based on data
- **H2**: Second most likely
- **H3**: Alternative explanation

For each hypothesis, identify:
- What evidence supports it?
- What evidence would refute it?

## Phase 4: Test Hypotheses

For each hypothesis:
1. What specific evidence would confirm it?
2. What specific evidence would refute it?
3. Gather that evidence
4. Update rankings based on findings

## Phase 5: Conclude and Remediate

Structure your conclusion:

```
**Root Cause**: [Specific, actionable cause]

**Evidence**:
- [Metric/log/event that supports]
- [Correlation or change point identified]
- [Timeline of events]

**Confidence**: [High/Medium/Low - explain why]

**Recommended Actions**:
1. Immediate: [e.g., restart pod, scale up]
2. Short-term: [follow-up fixes]
3. Long-term: [prevention measures]

**Caveats**: [What you couldn't determine]
```

## Key Principles

### Intellectual Honesty
- State confidence level clearly
- Acknowledge insufficient evidence
- Say "I don't know" when uncertain
- Distinguish facts (observed) from hypotheses (inferred)

### Evidence-Based Reasoning
- Every claim must have supporting evidence
- Quote specific data: timestamps, values, error messages
- If you can't prove it, mark it as hypothesis

### Efficiency
- Don't repeat queries with same parameters
- Start narrow, expand only if needed
- Maximum 6-8 tool calls per investigation phase

## When to Use Subagents

| Situation | Subagent | Why |
|-----------|----------|-----|
| Deep log analysis (5+ queries) | `log-analyst` | Isolate log output from main context |
| K8s pod/deployment issues | `k8s-debugger` | Specialized K8s methodology |
| Parallel investigation | Multiple subagents | Test hypotheses simultaneously |
| Remediation actions | `remediator` | Safety isolation for dangerous ops |
