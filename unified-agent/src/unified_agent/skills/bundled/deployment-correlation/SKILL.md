---
name: deployment-correlation
description: Correlate incidents with recent deployments and code changes. Use when investigating if a deployment caused an issue, finding what changed, or identifying the commit that introduced a bug.
category: code
required_integrations:
  - github
allowed-tools: Bash(python *)
---

# Deployment Correlation

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `GITHUB_TOKEN` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

---

## Core Question: "What Changed?"

The first question in any incident investigation should be: **"What deployed recently?"**

## Available Scripts

All scripts are in `.claude/skills/deployment-correlation/scripts/`

### list_commits.py - Find Recent Deployments
```bash
python .claude/skills/deployment-correlation/scripts/list_commits.py --repo OWNER/REPO [--branch BRANCH] [--since TIMESTAMP] [--limit N]

# Examples:
python .claude/skills/deployment-correlation/scripts/list_commits.py --repo incidentfox/api --branch main --limit 20
python .claude/skills/deployment-correlation/scripts/list_commits.py --repo incidentfox/api --since "2026-01-27T00:00:00Z"
```

### compare_commits.py - Diff Between Versions
```bash
python .claude/skills/deployment-correlation/scripts/compare_commits.py --repo OWNER/REPO --base BASE --head HEAD

# Examples:
python .claude/skills/deployment-correlation/scripts/compare_commits.py --repo incidentfox/api --base v1.2.3 --head main
python .claude/skills/deployment-correlation/scripts/compare_commits.py --repo incidentfox/api --base abc123 --head def456
```

### get_commit.py - Detailed Commit Info
```bash
python .claude/skills/deployment-correlation/scripts/get_commit.py --repo OWNER/REPO --sha COMMIT_SHA

# Examples:
python .claude/skills/deployment-correlation/scripts/get_commit.py --repo incidentfox/api --sha abc1234
```

---

## 3-Step Correlation Process

### Step 1: Get Recent Deployments

Find deployments around the incident time:
```bash
# List recent commits to production branch
python list_commits.py --repo org/repo --branch main --limit 20
```

**Key questions:**
- What deployed in the last 1-2 hours before the incident?
- Did the deployment succeed or fail?
- Who triggered the deployment?

### Step 2: Identify Suspicious Commits

Compare code changes around the incident time:
```bash
# Compare current state to previous known-good state
python compare_commits.py --repo org/repo --base v1.2.3 --head main

# Get specific commit details
python get_commit.py --repo org/repo --sha abc123
```

**Look for:**
- Changes to the failing component/service
- Config changes (environment variables, feature flags)
- Dependency updates
- Database migrations

### Step 3: Correlate with Symptoms

Match code changes to observed symptoms.

**Correlation checklist:**
- [ ] Timeline match: Did symptoms start after deploy completed?
- [ ] Component match: Did the deploy touch the failing service?
- [ ] Pattern match: Does the error message relate to changed code?

---

## Correlation Patterns

### Pattern 1: Latency Spike After Deploy

```
Timeline:
14:00 - Deploy completed
14:05 - Latency increases
14:10 - Alerts fire

Investigation:
1. list_commits.py --repo org/repo --branch main → Find 14:00 deploy
2. get_commit.py --repo org/repo --sha <sha> → See files changed
3. Look for: connection pool changes, timeout configs, new external calls
```

### Pattern 2: Errors in Specific Service

```
Symptom: "Service X throwing NullPointerException"

Investigation:
1. compare_commits.py --base last-good-deploy --head current → What changed?
2. Filter for changes to Service X files
3. get_commit.py on suspicious commits
```

### Pattern 3: Gradual Degradation

```
Symptom: Memory usage creeping up over days

Investigation:
1. list_commits.py --since "7 days ago" → All recent changes
2. Look for: new caching, data structure changes, memory allocations
```

---

## Quick Commands Reference

| Goal | Command |
|------|---------|
| Recent commits | `list_commits.py --repo X --branch main` |
| Compare versions | `compare_commits.py --repo X --base v1 --head v2` |
| Commit details | `get_commit.py --repo X --sha abc123` |
| Time-filtered | `list_commits.py --repo X --since "2026-01-27T00:00:00Z"` |

---

## Output Format

```markdown
## Deployment Correlation Summary

### Timeline
- **Incident start**: [timestamp]
- **Last successful deploy**: [timestamp, commit sha]
- **Previous deploy**: [timestamp, commit sha]

### Changes Since Last Known Good
- **Commits**: N commits
- **Files changed**: M files
- **Authors**: [list]

### Suspicious Changes
1. **[commit sha]** - [summary]
   - Files: [list of changed files]
   - Reason for suspicion: [why this might be related]

### Correlation Confidence
- **High**: Deploy clearly matches timeline and touches failing component
- **Medium**: Timeline matches but changes are indirect
- **Low**: No obvious correlation, consider other causes

### Recommended Actions
1. [If high confidence] Consider rollback to [commit sha]
2. [If medium] Investigate specific change
3. [If low] Look at infrastructure, dependencies, or external factors
```

---

## Anti-Patterns to Avoid

1. ❌ **Assuming latest deploy is always the cause** - Check the timeline carefully
2. ❌ **Ignoring indirect changes** - Config files, dependencies can cause issues
3. ❌ **Missing multi-repo deployments** - Check all services that deployed
4. ❌ **Forgetting feature flags** - Deploy might enable dormant code
5. ❌ **Skipping CI failures** - A "successful" deploy might have skipped tests
