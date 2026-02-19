---
name: platform-vercel
description: Query Vercel deployments, projects, and build logs. Use when investigating Vercel deployment failures, runtime errors, or build issues.
allowed-tools: Bash(python *)
---

# Vercel Platform

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `VERCEL_TOKEN` in environment variables -- it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `VERCEL_TEAM_ID` - Vercel team ID (optional, for team-scoped requests)

---

## Available Scripts

All scripts are in `.claude/skills/platform-vercel/scripts/`

### list_projects.py - List Vercel Projects
```bash
python .claude/skills/platform-vercel/scripts/list_projects.py [--limit 20]

# Examples:
python .claude/skills/platform-vercel/scripts/list_projects.py
python .claude/skills/platform-vercel/scripts/list_projects.py --limit 50 --json
```

### get_project.py - Get Project Details
```bash
python .claude/skills/platform-vercel/scripts/get_project.py --project PROJECT_ID_OR_NAME

# Examples:
python .claude/skills/platform-vercel/scripts/get_project.py --project my-webapp
python .claude/skills/platform-vercel/scripts/get_project.py --project prj_abc123 --json
```

### list_deployments.py - List Deployments
```bash
python .claude/skills/platform-vercel/scripts/list_deployments.py [--project PROJECT] [--state STATE] [--target TARGET] [--limit 20]

# Examples:
python .claude/skills/platform-vercel/scripts/list_deployments.py --project my-webapp
python .claude/skills/platform-vercel/scripts/list_deployments.py --project my-webapp --state ERROR
python .claude/skills/platform-vercel/scripts/list_deployments.py --project my-webapp --target production --limit 5
```

### get_deployment.py - Get Deployment Details
```bash
python .claude/skills/platform-vercel/scripts/get_deployment.py --deployment DEPLOYMENT_ID_OR_URL

# Examples:
python .claude/skills/platform-vercel/scripts/get_deployment.py --deployment dpl_abc123
python .claude/skills/platform-vercel/scripts/get_deployment.py --deployment my-webapp-abc123.vercel.app --json
```

### get_deployment_events.py - Get Build Logs / Deployment Events
```bash
python .claude/skills/platform-vercel/scripts/get_deployment_events.py --deployment DEPLOYMENT_ID [--limit 50]

# Examples:
python .claude/skills/platform-vercel/scripts/get_deployment_events.py --deployment dpl_abc123
python .claude/skills/platform-vercel/scripts/get_deployment_events.py --deployment dpl_abc123 --limit 100 --json
```

### create_deployment.py - Create a New Deployment
```bash
python .claude/skills/platform-vercel/scripts/create_deployment.py --name PROJECT_NAME --repo OWNER/REPO --ref BRANCH_OR_SHA [--target preview]

# Examples:
python .claude/skills/platform-vercel/scripts/create_deployment.py --name my-webapp --repo acme/my-webapp --ref main --target production
python .claude/skills/platform-vercel/scripts/create_deployment.py --name my-webapp --repo acme/my-webapp --ref fix/login-bug
```

---

## Investigation Workflow

### Deployment Failure Investigation
```
1. list_deployments.py --project PROJECT --state ERROR
2. get_deployment.py --deployment DEPLOYMENT_ID
3. get_deployment_events.py --deployment DEPLOYMENT_ID
4. Correlate with recent commits via deployment's git metadata
```

### Production Regression Investigation
```
1. list_deployments.py --project PROJECT --target production --limit 5
2. get_deployment.py --deployment LATEST_DEPLOYMENT_ID
3. Compare git SHAs between current and previous production deployment
4. get_deployment_events.py --deployment DEPLOYMENT_ID (check build output)
```

### Build Timeout / Slow Build Investigation
```
1. list_deployments.py --project PROJECT --limit 10
2. get_deployment_events.py --deployment DEPLOYMENT_ID --limit 200
3. Look for long gaps between event timestamps in the build log
```

---

## Quick Commands Reference

| Goal | Command |
|------|---------|
| List all projects | `list_projects.py` |
| Get project config | `get_project.py --project NAME` |
| Recent deployments | `list_deployments.py --project NAME` |
| Failed deployments | `list_deployments.py --project NAME --state ERROR` |
| Production deploys | `list_deployments.py --project NAME --target production` |
| Deployment details | `get_deployment.py --deployment ID` |
| Build logs | `get_deployment_events.py --deployment ID` |
| Trigger deploy | `create_deployment.py --name NAME --repo OWNER/REPO --ref BRANCH` |

---

## Common Patterns

### Check if a deployment is still building
```bash
python .claude/skills/platform-vercel/scripts/get_deployment.py --deployment dpl_abc123 --json
# Look at "state" field: BUILDING, READY, ERROR, CANCELED, QUEUED
```

### Find the deployment for a specific commit
```bash
python .claude/skills/platform-vercel/scripts/list_deployments.py --project my-webapp --json
# Search the JSON output for the commit SHA in meta.githubCommitSha
```

### Get build errors from a failed deployment
```bash
python .claude/skills/platform-vercel/scripts/get_deployment.py --deployment dpl_abc123
# Check errorCode and errorMessage fields
python .claude/skills/platform-vercel/scripts/get_deployment_events.py --deployment dpl_abc123
# Read the full build log for error details
```

---

## Anti-Patterns

- **Do NOT** try to read `VERCEL_TOKEN` from the environment. The credential proxy injects it.
- **Do NOT** use `curl` to hit the Vercel API directly. Always use the scripts which handle auth and proxy routing.
- **Do NOT** poll deployment status in a tight loop. Check once, report the state, and let the user decide when to re-check.
- **Do NOT** create production deployments without explicit user confirmation. Default to `preview` target.
