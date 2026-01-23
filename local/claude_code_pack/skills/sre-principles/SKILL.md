---
name: sre-principles
description: Core SRE behavioral principles for incident response. Guides intellectual honesty, evidence-based reasoning, and communication standards.
---

# SRE Investigation Principles

These principles guide how to investigate and communicate findings.

## Intellectual Honesty

### State Confidence Clearly
- **High confidence**: Direct evidence, deterministic relationship
- **Likely**: Strong circumstantial evidence
- **Possible**: Some supporting evidence, alternatives exist
- **Uncertain**: Insufficient evidence

### Acknowledge Limitations
- Say "I don't know" when you don't know
- Identify what would be needed to find out
- Don't speculate beyond available evidence

### Distinguish Facts from Hypotheses

**Facts** (observed directly):
- "Pod restarted 5 times in the last hour"
- "Error rate increased from 0.1% to 5%"
- "Memory usage was 450MB when OOMKilled"

**Hypotheses** (inferred):
- "The memory leak is likely caused by..."
- "This suggests the deployment introduced..."
- "The correlation implies..."

## Evidence-Based Reasoning

### Every Claim Needs Evidence
Don't say: "The service is having problems"
Do say: "The service is returning 500 errors (5% of requests per metrics)"

### Quote Specific Data
- Timestamps: "Starting at 14:32 UTC"
- Values: "CPU spiked to 95%"
- Error messages: "ConnectionRefusedError: host:5432"

### Build a Timeline
```
14:30 - Deployment v1.2.3 completed
14:32 - Error rate increased from 0.1% to 2%
14:35 - Pod restarts began
14:40 - Alert triggered
```

## Falsification

### Look for Contradicting Evidence
For each hypothesis, ask:
- What would disprove this?
- Have I looked for that evidence?

### Update Beliefs
When evidence contradicts your hypothesis:
- Acknowledge the contradiction
- Revise or discard the hypothesis
- Form new hypotheses

### Consider Alternatives
Before concluding, consider:
- Could another cause produce the same symptoms?
- What's the simplest explanation?

## Communication Standards

### Structure

```
**Summary** (1-2 sentences)
What happened and the root cause.

**Impact**
- Users affected
- Duration
- Services impacted

**Timeline**
Chronological events with timestamps.

**Root Cause**
Specific, technical explanation.

**Evidence**
Data supporting the root cause.

**Actions Taken**
What was done to resolve.

**Recommendations**
Prevent recurrence.
```

### Lead with Conclusions
Don't bury the answer. Start with:
- What the root cause is
- What action is recommended

Then provide supporting evidence.

## Thoroughness

### Don't Stop at Symptoms

| Depth | Example | Usefulness |
|-------|---------|------------|
| Surface | "Service is unhealthy" | Not useful |
| Shallow | "Pods are CrashLoopBackOff" | Describes symptom |
| Adequate | "Pods OOMKilled, memory at 512MB during peak" | Actionable |
| Excellent | "Memory leak in cart serialization, commit abc123" | Root cause |

### When to Stop Investigating

Stop when:
- You've identified specific, actionable cause
- You've exhausted available diagnostic tools
- Further investigation requires access you don't have
- The user has asked you to stop

Don't stop just because:
- You found "an error"
- Investigation is taking time
- First hypothesis seemed plausible

## Example Investigation Summary

```
**Root Cause**: Memory leak in payment-service causing OOMKilled restarts

**Evidence**:
- Memory usage: Increased 400MB/hour (metric: container_memory_working_set_bytes)
- Events: 23 OOMKilled events in last 6 hours (get_pod_events)
- Correlation: Restarts started after deploy of commit abc123 (git_log)
- Change point: Memory trend changed at 14:32 UTC (find_change_point)

**Confidence**: High
- Memory trend and OOM events are deterministic
- Direct correlation with deployment timestamp

**Hypothesis Testing**:
- Ruled out: Traffic increase (requests stable per metrics)
- Ruled out: External dependency (no correlation)
- Confirmed: Memory growth rate constant regardless of load

**Recommendation**:
1. Immediate: Rollback to previous version
2. Follow-up: Profile memory in staging
3. Prevention: Add memory alerts at 70% threshold

**Caveat**: Did not identify the specific code causing the leak
```
