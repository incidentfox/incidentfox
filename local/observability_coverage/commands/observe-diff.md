---
description: "Review git diff for observability gaps — catch missing telemetry before merge"
---

# Observability Coverage: Diff Review

Review the current git diff for observability gaps. This is "PR review" mode — catch missing telemetry before it merges.

## Instructions

Review the changes in: **$ARGUMENTS**

If no arguments, review the current git diff (both staged and unstaged).

## Step 1: Get Changed Files

Run `git diff --name-only` and `git diff --cached --name-only` to get the list of changed files.

## Step 2: Run Static Analyzer on Changed Files

For each changed source file (.py, .ts, .js, .go, .java, .rb, .rs), run:

```bash
python3 local/observability_coverage/analyzers/scan.py <filepath> --json
```

Collect results from all files.

## Step 3: Get the Actual Diff

Run `git diff` and `git diff --cached` to see the specific changes.

## Step 4: Cross-Reference

For each gap the scanner found, check if it's in a CHANGED section of code:
- **New gaps in changed code** — Flag these (developer just wrote this, should fix now)
- **Pre-existing gaps in unchanged code** — Mention but don't block (tech debt, not this PR's problem)

## Step 5: Output

For each new gap in changed code:

```
## <filename> (lines X-Y)

**Gap**: <what's missing>
**Priority**: Critical / High / Medium
**Suggestion**:
<code to add>
**Why**: When this breaks, you'll need to know <specific scenario>
```

## Step 6: Verdict

```
## Observability Verdict

### Ready to merge? <YES / YES with suggestions / NEEDS WORK>

### New code reviewed: N files, N+ lines changed
### Gaps in new code: N critical, N high, N medium
### Pre-existing gaps: N (tech debt, not blocking)

### Must fix before merge:
<list critical gaps in changed code>

### Should fix (but won't block):
<list high/medium gaps>

### Apply fixes? Say "fix all" or pick specific ones.
```
