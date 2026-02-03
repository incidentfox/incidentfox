---
name: deployment-correlation
description: Correlate incidents with recent deployments and code changes. Use when investigating if a deployment caused an issue, finding what changed, or identifying the commit that introduced a bug.
---

# Deployment Correlation

## Core Question: "What Changed?"

The first question in any incident investigation should be: **"What deployed recently?"**

## 3-Step Correlation Process

### Step 1: Get Recent Deployments

Find deployments around the incident time:

```
# List recent deployments to production
github_list_commits(repo="org/repo", branch="main", max_results=20)

# Or check GitHub deployments API
list_deployments(repo="org/repo", environment="production", max_results=10)

# Check workflow runs (CI/CD)
list_workflow_runs(repo="org/repo", status="completed", max_results=15)
```

**Key questions:**
- What deployed in the last 1-2 hours before the incident?
- Did the deployment succeed or fail?
- Who triggered the deployment?

### Step 2: Identify Suspicious Commits

Compare code changes around the incident time:

```
# Compare current state to previous known-good state
github_compare_commits(repo="org/repo", base="v1.2.3", head="main")

# Get commits in a time range
github_search_commits_by_timerange(
    repo="org/repo",
    since="2024-01-15T10:00:00Z",
    until="2024-01-15T14:00:00Z"
)

# Get specific commit details
github_get_commit(repo="org/repo", sha="abc123")
```

**Look for:**
- Changes to the failing component/service
- Config changes (environment variables, feature flags)
- Dependency updates
- Database migrations

### Step 3: Correlate with Symptoms

Match code changes to observed symptoms:

```
# Find files changed in a PR
github_get_pr_files(repo="org/repo", pr_number=123)

# Search code for the failing pattern
search_github_code(query="timeout config", repo="org/repo")
```

**Correlation checklist:**
- [ ] Timeline match: Did symptoms start after deploy completed?
- [ ] Component match: Did the deploy touch the failing service?
- [ ] Pattern match: Does the error message relate to changed code?

## Available Tools

| Tool | Purpose |
|------|---------|
| `github_list_commits` | Recent commits on a branch |
| `github_get_commit` | Detailed commit info with files changed |
| `github_compare_commits` | Diff between two commits/branches |
| `github_search_commits_by_timerange` | Commits in a specific time window |
| `list_deployments` | GitHub deployment history |
| `get_deployment_status` | Specific deployment details |
| `list_workflow_runs` | CI/CD workflow execution history |
| `get_workflow_run_jobs` | Individual job statuses in a workflow |
| `get_failed_workflow_annotations` | Error annotations from failed CI |
| `github_get_pr` | PR details (linked to deploy) |
| `github_get_pr_files` | Files changed in a PR |
| `github_list_pr_commits` | All commits in a PR |

## Correlation Patterns

### Pattern 1: Latency Spike After Deploy

```
Timeline:
14:00 - Deploy completed
14:05 - Latency increases
14:10 - Alerts fire

Investigation:
1. github_list_commits(repo, branch="main") → Find 14:00 deploy
2. github_get_commit(repo, sha) → See files changed
3. Look for: connection pool changes, timeout configs, new external calls
```

### Pattern 2: Errors in Specific Service

```
Symptom: "Service X throwing NullPointerException"

Investigation:
1. search_github_code(query="NullPointerException", repo) → Find related code
2. github_compare_commits(base="last-good-deploy", head="current") → What changed?
3. Filter for changes to Service X files
```

### Pattern 3: Gradual Degradation

```
Symptom: Memory usage creeping up over days

Investigation:
1. github_search_commits_by_timerange(since="7 days ago") → All recent changes
2. Look for: new caching, data structure changes, memory allocations
3. git_blame on suspected file to find introducing commit
```

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

2. **[commit sha]** - [summary]
   - Files: [list]
   - Reason: [why]

### Correlation Confidence
- **High**: Deploy clearly matches timeline and touches failing component
- **Medium**: Timeline matches but changes are indirect
- **Low**: No obvious correlation, consider other causes

### Recommended Actions
1. [If high confidence] Consider rollback to [commit sha]
2. [If medium] Investigate specific change: [link]
3. [If low] Look at infrastructure, dependencies, or external factors
```

## Anti-Patterns

1. **Assuming latest deploy is always the cause** - Check the timeline carefully
2. **Ignoring indirect changes** - Config files, dependencies can cause issues
3. **Missing multi-repo deployments** - Check all services that deployed
4. **Forgetting feature flags** - Deploy might enable dormant code
5. **Skipping CI failures** - A "successful" deploy might have skipped tests

## Pro Tips

**Efficient queries:**
- Start with `github_list_commits` (simple, fast)
- Use `github_compare_commits` for detailed diffs
- Use `search_github_code` to find specific patterns

**Timeline reconstruction:**
- Deployments don't take effect instantly - account for rolling deploys
- Check if canary deployments showed early symptoms
- Look at deploy duration, not just start time

**Multi-service correlation:**
- An issue in Service A might be caused by a deploy to Service B
- Check all services that interact with the failing component
- Look for API contract changes, schema migrations
