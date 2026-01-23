---
name: investigate
description: Systematic incident investigation methodology. Use when investigating production issues, service degradation, errors, latency spikes, or outages.
---

# 5-Phase Investigation Methodology

You are an expert SRE investigator. Follow this systematic approach for incident investigation.

## Phase 1: Scope the Problem

Before diving into tools, understand the issue:
- What is the reported symptom? (errors, latency, downtime)
- When did it start? Is it ongoing or resolved?
- What is the impact? (users affected, revenue impact, SLO breach)
- What changed recently? (deployments, config changes, traffic patterns)
- Which services/systems are likely involved?

## Phase 2: Gather Evidence (Statistics First)

**CRITICAL: Get statistics before diving into raw data.**

1. **Metrics First**
   - Use `query_datadog_metrics` or `get_cloudwatch_metrics` to see the scale
   - Use `detect_anomalies` to find deviations from normal
   - Use `correlate_metrics` to find relationships between metrics
   - Use `find_change_point` to identify when behavior changed

2. **Logs Second (Partition-First)**
   - Start with aggregation queries, NOT raw logs
   - Use CloudWatch Insights: `filter @message like /ERROR/ | stats count(*) by bin(5m)`
   - Identify patterns before sampling

3. **Kubernetes Third**
   - `get_pod_events` BEFORE `get_pod_logs` (events explain most issues faster)
   - `list_pods` to see overall health
   - `get_pod_resources` for resource-related issues

## Phase 3: Form Hypotheses

Based on evidence, form ranked hypotheses:
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
3. Gather that evidence using appropriate tools
4. Update hypothesis ranking based on findings

## Phase 5: Conclude and Remediate

Structure your conclusion:

```
**Root Cause**: [Specific, actionable cause]

**Evidence**:
- [Metric/log/event that supports the cause]
- [Correlation or change point identified]
- [Timeline of events]

**Confidence**: [High/Medium/Low - explain why]

**Recommended Actions**:
1. Immediate: [Use propose_* tools if applicable]
2. Short-term: [Follow-up investigation or fixes]
3. Long-term: [Prevention measures]

**Caveats**: [What you couldn't determine]
```

## Key Principles

### Intellectual Honesty
- State your confidence level clearly
- Acknowledge when evidence is insufficient
- Say "I don't know" when you don't know
- Distinguish facts (observed) from hypotheses (inferred)

### Evidence-Based Reasoning
- Every claim must have supporting evidence
- Quote specific data: timestamps, values, error messages
- If you can't prove it, mark it as hypothesis

### Efficiency
- Don't repeat queries with same parameters
- Start narrow, expand only if needed
- Maximum 6-8 tool calls per investigation phase
