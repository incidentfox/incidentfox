# IncidentFox Evaluation Framework

A comprehensive evaluation framework to measure agent performance on real incident scenarios. This framework uses fault injection, automated scoring, and iterative improvement to ensure IncidentFox delivers reliable incident investigations.

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Scoring Dimensions](#scoring-dimensions)
- [Latest Results](#latest-results)
- [Running Evaluations](#running-evaluations)
- [Adding New Scenarios](#adding-new-scenarios)
- [Continuous Improvement](#continuous-improvement)

---

## Overview

The evaluation framework validates that IncidentFox can:

1. **Identify root causes** - Correctly diagnose what went wrong
2. **Gather evidence** - Cite specific logs, metrics, and events
3. **Reconstruct timelines** - Understand the sequence of events
4. **Assess impact** - Identify affected systems and services
5. **Recommend fixes** - Suggest actionable remediation steps

This ensures consistent, high-quality investigations across different incident types.

---

## How It Works

### 1. Fault Injection

We inject real failures into a test environment running the [OpenTelemetry Demo App](https://github.com/open-telemetry/opentelemetry-demo) on Kubernetes:

- **Service crashes** - Kill pods to simulate application failures
- **Performance degradation** - Introduce latency or resource constraints
- **Dependency failures** - Break connections between services
- **Configuration errors** - Apply invalid configs
- **Resource exhaustion** - Consume CPU/memory/disk

Each fault is injected programmatically with known ground truth about:
- Root cause
- Expected symptoms
- Affected services
- Timeline of events
- Proper remediation

### 2. Agent Investigation

The agent investigates the incident using available tools:
- Query Prometheus for metrics
- Search logs via Grafana/Loki
- Inspect Kubernetes pods and events
- Analyze service dependencies
- Correlate across multiple signals

The agent produces a diagnosis with:
- Root cause analysis
- Supporting evidence
- Timeline reconstruction
- Impact assessment
- Recommended actions

### 3. Automated Scoring

Responses are scored against ground truth across 5 dimensions (see below).

Scoring uses an LLM judge (GPT-4o) to evaluate whether the agent's response:
- Matches the known root cause
- Includes relevant evidence
- Reconstructs the timeline correctly
- Identifies affected services
- Suggests appropriate fixes

### 4. Iteration

Results guide improvements:
- **Failed scenarios** → Identify missing tools or context
- **Low scores** → Refine prompts or add knowledge
- **Slow investigations** → Optimize tool selection
- **Repeated errors** → Add guardrails or validation

---

## Scoring Dimensions

Each investigation is scored on 5 dimensions with different weights:

| Dimension | Weight | What We Measure | Scoring Criteria |
|-----------|--------|-----------------|------------------|
| **Root Cause** | 30 pts | Did the agent identify the correct root cause? | Full: Exact match (30pts)<br>Partial: Related but incomplete (15pts)<br>None: Wrong or missing (0pts) |
| **Evidence** | 20 pts | Did the agent cite specific logs, events, or metrics? | Full: Multiple relevant citations (20pts)<br>Partial: Some evidence (10pts)<br>None: No citations (0pts) |
| **Timeline** | 15 pts | Did the agent reconstruct what happened when? | Full: Complete sequence (15pts)<br>Partial: Some events (8pts)<br>None: No timeline (0pts) |
| **Impact** | 15 pts | Did the agent identify affected systems? | Full: All affected services (15pts)<br>Partial: Some services (8pts)<br>None: Missing or wrong (0pts) |
| **Recommendations** | 20 pts | Did the agent suggest actionable fixes? | Full: Correct, specific actions (20pts)<br>Partial: Generic suggestions (10pts)<br>None: Wrong or missing (0pts) |

**Total possible score:** 100 points

**Pass threshold:** 60 points (scenarios below 60 are considered failures)

---

## Latest Results

Results from the most recent evaluation run:

```
┌─────────────────────────┬───────┬────────┬───────────┐
│ Scenario                │ Score │ Time   │ Status    │
├─────────────────────────┼───────┼────────┼───────────┤
│ healthCheck             │ 60    │ 14.3s  │ ✅ Pass   │
│ cartCrash               │ 90    │ 17.2s  │ ✅ Pass   │
│ adCrash                 │ 90    │ 16.7s  │ ✅ Pass   │
│ cartFailure             │ 85    │ 27.6s  │ ✅ Pass   │
│ adFailure               │ 90    │ 15.4s  │ ✅ Pass   │
│ productCatalogFailure   │ 85    │ 16.1s  │ ✅ Pass   │
├─────────────────────────┼───────┼────────┼───────────┤
│ Average                 │ 83.3  │ 17.9s  │           │
│ Pass Rate               │ 75%   │        │ 6/8       │
└─────────────────────────┴───────┴────────┴───────────┘
```

### Key Metrics

- **Average Score:** 83.3 / 100
- **Pass Rate:** 75% (6 out of 8 scenarios)
- **Average Time:** 17.9 seconds per investigation
- **Fastest:** 14.3s (healthCheck)
- **Slowest:** 27.6s (cartFailure - multi-step investigation)

### Insights

**What's Working:**
- Service crash scenarios (90pts) - Agent quickly identifies pod failures
- Dependency failures (85-90pts) - Good at tracing cascade effects
- Fast investigations (avg 18s) - Efficient tool usage

**Areas for Improvement:**
- Health check scenarios (60pts) - Need better heuristics for probe failures
- Timeline reconstruction - Could be more precise with timestamps
- Evidence gathering - Sometimes misses relevant log entries

---

## Running Evaluations

### Prerequisites

- Kubernetes cluster (minikube, kind, or cloud)
- OpenTelemetry Demo App deployed
- IncidentFox agent running
- Python 3.9+ with dependencies

### Quick Start

Run the full evaluation suite against a local agent:

```bash
# Clone the repo
git clone https://github.com/incidentfox/incidentfox.git
cd incidentfox

# Run full evaluation suite
python3 scripts/eval_agent_performance.py

# Output:
# - Deploys otel-demo to K8s
# - Injects faults for each scenario
# - Runs agent investigations
# - Scores responses
# - Generates report
```

### Quick Validation (3 scenarios)

For faster iteration during development:

```bash
# Run subset of scenarios
python3 scripts/run_agent_eval.py --agent-url http://localhost:8080

# Runs: healthCheck, cartCrash, adCrash (takes ~2 min)
```

### Against Deployed Agent

Evaluate a production or staging deployment:

```bash
python3 scripts/eval_agent_performance.py \
  --agent-url http://agent.internal:8080 \
  --kubeconfig ~/.kube/prod-cluster
```

### Custom Scenarios

Run specific scenarios:

```bash
python3 scripts/eval_agent_performance.py \
  --scenarios cartCrash,productCatalogFailure
```

### Options

```
--agent-url URL       Agent API endpoint (default: http://localhost:8080)
--kubeconfig PATH     Path to kubeconfig (default: ~/.kube/config)
--namespace NS        K8s namespace for otel-demo (default: otel-demo)
--scenarios LIST      Comma-separated list of scenarios
--output PATH         Output file for results (default: eval_results.json)
--verbose             Enable debug logging
```

---

## Adding New Scenarios

### Scenario Structure

Each scenario is defined in `scripts/eval_scenarios/`:

```python
{
    "name": "cartCrash",
    "description": "Cart service crashes due to OOM",
    "fault_injection": {
        "type": "pod_kill",
        "target": "cartservice",
        "namespace": "otel-demo"
    },
    "ground_truth": {
        "root_cause": "cartservice pod killed due to OOMKilled",
        "affected_services": ["cartservice", "frontend", "checkoutservice"],
        "timeline": [
            {"time": "t0", "event": "Pod memory usage exceeds limit"},
            {"time": "t0+2s", "event": "Pod killed by kubelet"},
            {"time": "t0+5s", "event": "Frontend shows cart errors"}
        ],
        "remediation": "Increase memory limit or optimize cart caching"
    },
    "scoring_weights": {
        "root_cause": 30,
        "evidence": 20,
        "timeline": 15,
        "impact": 15,
        "recommendations": 20
    }
}
```

### Steps to Add a Scenario

1. **Create scenario file**: `scripts/eval_scenarios/my_scenario.py`
2. **Implement fault injection**: Use K8s API or custom scripts
3. **Define ground truth**: Document expected root cause, impact, timeline
4. **Add to scenario list**: Register in `scripts/eval_agent_performance.py`
5. **Run and validate**: Test scenario works correctly
6. **Commit and PR**: Add to the evaluation suite

### Example: Network Latency Scenario

```python
{
    "name": "networkLatency",
    "description": "High latency between frontend and recommendation service",
    "fault_injection": {
        "type": "network_delay",
        "source": "frontend",
        "target": "recommendationservice",
        "delay_ms": 2000
    },
    "ground_truth": {
        "root_cause": "Network latency 2000ms between frontend and recommendationservice",
        "affected_services": ["frontend", "recommendationservice"],
        "timeline": [
            {"time": "t0", "event": "Network policy applies latency"},
            {"time": "t0+1s", "event": "Frontend response time increases"},
            {"time": "t0+10s", "event": "User-facing errors appear"}
        ],
        "remediation": "Check network policies, investigate CNI issues"
    }
}
```

---

## Continuous Improvement

### Tracking Progress Over Time

Run evaluations regularly to track improvements:

```bash
# Run weekly evaluations
python3 scripts/eval_agent_performance.py --output results/2024-01-15.json

# Compare with baseline
python3 scripts/compare_eval_results.py \
  results/baseline.json \
  results/2024-01-15.json
```

### Integration with CI/CD

Add evaluation to your CI pipeline:

```yaml
# .github/workflows/eval.yml
name: Agent Evaluation

on:
  pull_request:
    paths:
      - 'agent/**'
      - 'scripts/eval_scenarios/**'

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Kubernetes
        uses: helm/kind-action@v1
      - name: Deploy Agent
        run: |
          docker-compose up -d agent
      - name: Run Evaluation
        run: |
          python3 scripts/run_agent_eval.py --output pr-results.json
      - name: Compare with Main
        run: |
          python3 scripts/compare_eval_results.py \
            results/main.json \
            pr-results.json
      - name: Comment Results
        uses: actions/github-script@v6
        with:
          script: |
            // Post results as PR comment
```

### Identifying Gaps

Use evaluation results to guide development:

1. **Low scores** → Missing tools or knowledge
   - Example: Low "Evidence" scores → Add log search tool
2. **Failed scenarios** → Agent limitations
   - Example: Can't diagnose network issues → Add network tracing
3. **Slow investigations** → Inefficient tool usage
   - Example: Agent checks all pods → Add service filtering
4. **Inconsistent results** → Prompt ambiguity
   - Example: Sometimes wrong → Clarify prompt guidance

### Feedback Loop

```
Evaluation → Gap Analysis → Implementation → Re-evaluation
    ↑                                              ↓
    └──────────── Continuous Improvement ─────────┘
```

---

## Advanced Topics

### Custom Scoring

Override default scoring for specific scenarios:

```python
def custom_scorer(agent_response, ground_truth):
    score = 0

    # Custom logic for your domain
    if "database" in agent_response and "connection" in agent_response:
        score += 20  # Bonus for mentioning DB connection issues

    return score
```

### Multi-Agent Evaluation

Evaluate agent handoffs and collaboration:

```python
scenario = {
    "name": "multiAgentInvestigation",
    "agents": ["planner", "k8s", "metrics"],
    "expected_flow": [
        {"agent": "planner", "action": "route_to_k8s"},
        {"agent": "k8s", "action": "identify_pod_issue"},
        {"agent": "metrics", "action": "confirm_memory_spike"}
    ]
}
```

### Real-World Incident Replay

Replay past production incidents:

```bash
# Export incident from production
python3 scripts/export_incident.py --incident-id INC-12345

# Replay for evaluation
python3 scripts/eval_agent_performance.py \
  --scenario-file incidents/INC-12345.json \
  --compare-with-resolution
```

---

## What's Next?

- **[FEATURES.md](FEATURES.md)** - Learn about agent capabilities
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Understand agent design
- **[CONTRIBUTING.md](../CONTRIBUTING.md)** - Contribute scenarios or improvements
- **[../agent/README.md](../agent/README.md)** - Agent development guide
