# Observability Coverage Plugin

**Turn "we have no logs for this" into an impossibility.**

A Claude Code plugin that reviews your code for observability gaps and suggests structured logging, metrics, and tracing — with justification for every suggestion.

## Install

```bash
claude --plugin-dir ./local/observability_coverage
```

Or add to your project's plugin configuration.

## Commands

### `/observability-coverage:review [file or directory]`
Full observability audit. Scans code for missing telemetry and generates a prioritized report with concrete code suggestions.

```
/observability-coverage:review src/api/
/observability-coverage:review src/services/payment.ts
```

### `/observability-coverage:observe-diff [branch or commit range]`
PR-time review mode. Checks your git diff for observability gaps before merge. Like a code reviewer that only cares about "can we debug this at 3am?"

```
/observability-coverage:observe-diff
/observability-coverage:observe-diff main..HEAD
```

### `/observability-coverage:observe-bootstrap`
Set up observability from scratch. Detects your stack and generates a minimal logging/metrics/tracing setup.

```
/observability-coverage:observe-bootstrap
```

## Auto-Detection (Skill)

The plugin includes an agent skill that Claude automatically uses when reviewing code or writing features. It nudges towards proper observability without you having to ask.

## Hook (Light Touch)

A PostToolUse hook runs after file writes/edits. It only fires when:
- The file is a source code file (.ts, .js, .py, .go, etc.)
- The file has error handling blocks but ZERO logging

This is intentionally conservative — it won't nag you on every edit.

## What It Catches

| Priority | Category | Example |
|----------|----------|---------|
| Critical | Silent error handling | `catch (e) { return null }` — no logging at all |
| Critical | Blind external calls | API calls with no error/latency tracking |
| High | Invisible auth | Login failures not logged (security blind spot) |
| High | Ghost state changes | Order status changes with no audit trail |
| Medium | Cache mystery | Cache operations with no hit/miss visibility |
| Medium | Feature flag darkness | A/B test assignments not tracked |

## What It Won't Do

- Won't add generic "entering function" noise
- Won't suggest logging PII (passwords, tokens, SSNs)
- Won't add logging in hot loops (suggests metrics instead)
- Won't fight your existing conventions (detects and matches them)
- Won't auto-commit changes (you review and approve everything)

## Philosophy

> "Every log line should answer a question you'll ask during an incident."

Most logging tools either do nothing or dump everything. This plugin is opinionated:
- **Context over coverage**: A single well-structured log > 50 generic ones
- **Incident-driven**: Every suggestion includes "when this breaks, this tells you..."
- **Performance-aware**: Flags when logging would hurt more than help
- **Convention-consistent**: Matches your existing patterns, libraries, and naming

## For Teams

When used across an org's repos, this creates:
- Consistent logging conventions across all services
- Correlation ID propagation between services
- A natural service map from the instrumentation it suggests
- Pre-built dashboard potential from standardized metric names

---

Built by [IncidentFox](https://incidentfox.com) — Reliability-as-a-service that starts at code review, not at 3am pages.
