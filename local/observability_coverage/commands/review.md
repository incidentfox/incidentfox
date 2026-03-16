---
description: "Review code for observability gaps — find missing logging, metrics, and tracing"
---

# Observability Coverage Review

You are performing an observability coverage review. Your mission: find every code path that would leave an on-call engineer blind during an incident, and suggest specific, actionable telemetry to add.

## Instructions

The user wants you to review: **$ARGUMENTS**

If no arguments provided, review the current working directory or recently changed files.

## Step 1: Run Static Analyzer + Pattern Learner (ALWAYS DO BOTH FIRST)

Run BOTH tools to get mechanical gap detection AND org-specific patterns:

```bash
python3 local/observability_coverage/analyzers/scan.py "$ARGUMENTS" --json
```

Then learn the org's logging patterns from the broader codebase (run on parent directory or repo root):

```bash
python3 local/observability_coverage/analyzers/pattern_learner.py . --json
```

**The scanner** finds gaps mechanically: bare excepts, silent catches, auth without logging.
**The pattern learner** tells you what "good" looks like in THIS codebase: field names, conventions, exemplar files.

Together, you don't suggest generic logging — you suggest logging that matches how this team already does it in their best-instrumented code.

Parse both outputs. Use the pattern learner to:
- Match field names to what the org already uses (e.g., if they use `org_id` not `organization_id`)
- Reference well-instrumented files as exemplars ("see how agent_tools.py does this")
- Flag cross-service inconsistencies ("agent uses correlation_id but orchestrator doesn't")
- Use the org's naming convention for event names (snake_case, camelCase, etc.)

## Step 2: Detect Existing Conventions

From the pattern learner output AND your own analysis:

1. What logging library is used? (structlog, pino, winston, slog, etc.)
2. What's the structured format? (JSON key-value, printf, etc.)
3. Are there metrics? Tracing?
4. What naming conventions exist?
5. Is there request context propagation?

Report:
```
Logging: <library> | Format: <structured/unstructured> | Convention: <pattern>
Metrics: <library or "none detected">
Tracing: <library or "none detected">
Context propagation: <pattern or "none detected">
```

## Step 3: Enhance Scanner Findings with LLM Intelligence

For each gap the scanner found, add what static analysis CAN'T do:

1. **Business context** — What does this code path DO? What user action triggers it?
2. **Incident scenario** — "At 3am when X breaks, this log tells you Y"
3. **Concrete code suggestion** — Real code using the project's existing libraries
4. **Priority adjustment** — The scanner assigns severity mechanically. You can upgrade/downgrade based on understanding the code's importance.

Also find gaps the scanner MISSED:
- State transitions without logging (scanner can't understand business logic)
- Missing correlation ID propagation between services
- High-throughput paths that need metrics instead of logs
- Retry/fallback logic without visibility

## Step 4: Generate Suggestions

For each gap:

1. **File:Line** — exact location
2. **Priority** — Critical / High / Medium
3. **Category** — Error Handling / External Call / State Transition / Auth / Data Mutation / Branching Logic / Performance
4. **Current code** — what's there now (brief snippet)
5. **Suggested addition** — concrete code using the project's existing libraries and conventions
6. **Incident justification** — "When this breaks at 3am, this tells you..."

## Step 5: Summary Report

```
## Observability Coverage Report

### Score: X/10
(from static analyzer, adjusted by your analysis)

### Summary
- Files scanned: N (by static analyzer)
- Critical gaps: N (must fix before next deploy)
- High priority gaps: N (fix this sprint)
- Medium priority gaps: N (nice to have)

### Top 3 Recommendations
1. <most impactful suggestion>
2. <second most impactful>
3. <third most impactful>

### Quick Wins (< 5 min each)
- <easy additions that add high value>

### Apply Fixes?
I can apply these changes now. Say "fix all", "fix critical only", or pick specific suggestions.
```

## Important

- ALWAYS run the static analyzer first — don't skip it
- Match existing code style and conventions EXACTLY
- Don't suggest logging PII (passwords, tokens, credit card numbers)
- Consider log volume — don't create a cost bomb
- Every suggestion must have a clear "this helps during incidents because..." justification
- Be specific: show real code, not vague advice
- If there's NO logging library set up, suggest running `/observability-coverage:observe-bootstrap` first
