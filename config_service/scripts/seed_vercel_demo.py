#!/usr/bin/env python3
"""
Seed the vercel-demo team for the Vercel error triage demo.

This creates:
1. 'vercel-demo' team node under 'incidentfox-demo' org
2. Team configuration with:
   - Routing to Vercel project, GitHub repo, and Slack channel
   - Single planner agent with detailed 3-phase triage prompt
   - Scoped tool access (only Vercel, GitHub, and Slack tools)
3. Output configuration pointing to the Slack channel

Design decisions:
- Single planner agent (no sub-agents). The triage workflow is sequential
  (investigate -> fix -> validate -> report) with no parallelism benefit.
  Sub-agents add latency and context-switching overhead for no gain here.
- Explicit tool whitelist. The agent only sees the ~25 tools it needs,
  not the full 100+ tool registry. Reduces token waste and hallucination.
- Temperature 0.3 for the planner. Needs enough creativity for hypothesis
  formation and code fix generation, but not so much it becomes erratic.

Usage:
    cd config_service
    poetry run python scripts/seed_vercel_demo.py

Environment variables:
    VERCEL_DEMO_SLACK_CHANNEL_ID: Slack channel ID (default: C0ADZHLL76V)
    VERCEL_DEMO_GITHUB_REPO: GitHub repo (default: incidentfox/vercel-demo-app)
    VERCEL_DEMO_PROJECT_ID: Vercel project ID (default: prj_PqAFlHb04G2TmgurLQqMKL7t4fXT)
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path so `import src.*` works when running as a script.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import os
import uuid

from sqlalchemy import select
from src.core.dotenv import load_dotenv
from src.db.config_models import NodeConfiguration
from src.db.models import (
    NodeType,
    OrgNode,
    TeamOutputConfig,
)
from src.db.session import db_session

# Team identity
ORG_ID = "incidentfox-demo"
TEAM_NODE_ID = "vercel-demo"
TEAM_NAME = "Vercel Error Triage Demo"

# Tools the planner agent needs (explicit whitelist)
PLANNER_TOOLS = [
    # Vercel tools (deployment context + build logs)
    "vercel_list_projects",
    "vercel_get_project",
    "vercel_list_deployments",
    "vercel_get_deployment",
    "vercel_get_deployment_events",
    # GitHub read tools (code investigation)
    "github_get_repo_info",
    "github_list_files",
    "github_read_file",
    "github_read_file_lines",
    "github_search_code",
    "github_list_directory_tree",
    "github_list_commits",
    "github_get_commit",
    "github_compare_commits",
    "github_get_file_commits",
    "github_list_workflow_runs",
    "github_get_workflow_run_logs",
    "github_get_pr",
    "github_get_pr_files",
    # GitHub write tools (create fix PR + PR comments + commit status)
    "github_create_branch",
    "github_create_or_update_file",
    "github_create_pull_request",
    "github_create_issue_comment",
    "github_create_commit_status",
    # Slack (reporting)
    "slack_post_message",
]

# =============================================================================
# System Prompt: 2-Phase Vercel Error Triage (PR Comment Flow)
# =============================================================================

VERCEL_TRIAGE_SYSTEM_PROMPT = """\
You are a Vercel Error Triage Agent. When Vercel runtime errors are detected \
on a PR deployment, you investigate the root cause and comment on the PR with \
your analysis and proposed fix. You do NOT create new PRs or commit code \
unless explicitly approved by a developer.

You operate in two phases.

========================================================================
PHASE 1: INVESTIGATE & COMMENT ON PR
========================================================================

### Step 1: Understand the Error

You receive an error context with: error message, request path, HTTP status code, \
and Vercel deployment ID(s). Start by understanding what failed.

1. Call `vercel_get_deployment` with a deployment ID to get:
   - The linked GitHub repo (`meta.githubRepo`)
   - The branch name (`meta.githubCommitRef`)
   - The commit SHA that was deployed
2. Call `vercel_get_project` to get the production branch and framework.

### Step 2: Find the PR and Set Error Status

Use the deployment metadata to find the pull request:

1. From the deployment, extract the branch name (`meta.githubCommitRef`), \
   repo (`meta.githubRepo`), and commit SHA.
2. Call `github_list_pull_requests` with `repo` and `state="open"` \
   to find the PR whose head branch matches the deployment branch.
3. If no matching PR is found, report findings without a PR comment.
4. **Set error status on the PR**: Call `github_create_commit_status` with \
   the deployment commit SHA, `state="error"`, \
   `context="IncidentFox / Vercel Triage"`, \
   `description="Runtime error detected — investigating..."`. \
   This shows a failing check in the PR UI. Always use exactly this context string.

### Step 3: Find the Buggy Code

1. `github_list_directory_tree` on the repo root to understand structure.
2. **Path-based search**: `github_search_code` for files matching the error path.
3. **Read the file**: `github_read_file_lines` with line numbers.
4. **Follow imports**: Read dependency files the handler imports.
5. **Check recent changes**: `github_get_file_commits` on the suspected file.

### Step 4: Root Cause Analysis

Form ranked hypotheses (H1 most likely, H2 alternative, H3 edge case). \
State evidence for each.

Common Vercel error patterns:
- `TypeError: Cannot read properties of undefined/null` → Missing null check
- `500 Internal Server Error` → Unhandled exception
- `FUNCTION_INVOCATION_TIMEOUT` → Slow DB query or external API
- `MODULE_NOT_FOUND` → Missing dependency or incorrect import

### Step 5: Comment on the PR

CRITICAL: You MUST post exactly ONE comment on the PR using \
`github_create_issue_comment`. Use this exact format:

```
## Vercel Error Analysis

**Error:** [error message]
**Route:** [path] — **Status:** [status code]
**Deployment:** [deployment ID]

### Root Cause

[Detailed explanation of what is wrong and why]

**Confidence:** [High/Medium/Low]

### Proposed Fix

**File:** `[exact/path/to/file.js]`

[Show the COMPLETE corrected file content in a code block:]

```javascript
[complete file content with the fix applied]
```

### Evidence

- [Evidence point 1]
- [Evidence point 2]

---

> Reply **go** to apply this fix automatically.

<!-- incidentfox:vercel_triage run_id=TRIAGE status=pending_approval -->
```

### Step 6: Update Commit Status

After posting the PR comment, update the commit status:

Call `github_create_commit_status` with the same commit SHA, \
`state="pending"`, `context="IncidentFox / Vercel Triage"`, \
`description="Analysis posted — awaiting approval"`, \
and `target_url` set to the comment `html_url` from the \
`github_create_issue_comment` response.

IMPORTANT RULES:
- Post exactly ONE comment (not multiple)
- The `<!-- incidentfox:vercel_triage ... -->` HTML comment at the bottom is \
  REQUIRED — the approval system depends on it
- Include the COMPLETE corrected file content (not just a diff), because the \
  Phase 2 agent needs to extract and commit it
- Do NOT create branches, PRs, or commit any code in Phase 1
- Do NOT skip the HTML marker comment
- If confidence is Low, write "Manual investigation recommended" instead of \
  "Reply go to apply this fix"

========================================================================
PHASE 2: APPLY FIX (Only when approved)
========================================================================

This phase only runs when a developer replies "go" on your analysis comment. \
You will receive the original analysis as context.

1. Parse the previous analysis to extract: file path, corrected file content, \
   and the PR number.
2. `github_get_pr` to get the PR head branch name.
3. `github_read_file` with `ref=<pr-branch>` to get the current file SHA.
4. `github_create_or_update_file` to commit the fix to the PR branch. \
   Use commit message: `fix: [brief description]`
5. `github_create_issue_comment` to confirm: \
   "Fix applied in commit [SHA]. Vercel will auto-deploy a preview."
6. Update commit status to success: Call `github_create_commit_status` \
   on the NEW commit SHA (from the `github_create_or_update_file` response) \
   with `state="success"`, `context="IncidentFox / Vercel Triage"`, \
   `description="Fix applied"`.
7. Do NOT create a new PR — commit directly to the existing PR branch.
"""


def main() -> None:
    load_dotenv()

    # Allow overriding via environment variables
    slack_channel_id = os.getenv("VERCEL_DEMO_SLACK_CHANNEL_ID", "C0ADZHLL76V")
    slack_channel_name = os.getenv("VERCEL_DEMO_SLACK_CHANNEL_NAME", "#vercel-demo")
    github_repo = os.getenv("VERCEL_DEMO_GITHUB_REPO", "incidentfox/vercel-demo-app")
    vercel_project_id = os.getenv(
        "VERCEL_DEMO_PROJECT_ID", "prj_PqAFlHb04G2TmgurLQqMKL7t4fXT"
    )

    print("Seeding vercel-demo team...")
    print(f"  Organization: {ORG_ID}")
    print(f"  Team: {TEAM_NODE_ID}")
    print(f"  Slack channel: {slack_channel_id} ({slack_channel_name})")
    print(f"  GitHub repo: {github_repo}")
    print(f"  Vercel project: {vercel_project_id}")

    with db_session() as s:
        # 1. Check that incidentfox-demo org exists
        org = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == ORG_ID,
                OrgNode.node_id == ORG_ID,
            )
        ).scalar_one_or_none()

        if org is None:
            print(f"  ERROR: Organization '{ORG_ID}' not found!")
            print("  Please create the organization first or use a different org_id.")
            sys.exit(1)
        else:
            print(f"  Found organization: {org.name}")

        # 2. Create vercel-demo team node
        team = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == ORG_ID,
                OrgNode.node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if team is None:
            print("  Creating vercel-demo team...")
            s.add(
                OrgNode(
                    org_id=ORG_ID,
                    node_id=TEAM_NODE_ID,
                    parent_id=ORG_ID,
                    node_type=NodeType.team,
                    name=TEAM_NAME,
                )
            )
        else:
            print("  Vercel-demo team already exists, skipping creation...")

        # Flush to satisfy FK constraints
        s.flush()

        # 3. Create/update team configuration
        team_cfg = s.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == ORG_ID,
                NodeConfiguration.node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        config_json = {
            "team_name": TEAM_NAME,
            "description": (
                "Vercel error triage demo - detects runtime errors, "
                "triages code, creates PR fix, validates via preview deployment"
            ),
            # Routing - how webhooks find this team
            "routing": {
                "slack_channel_ids": [slack_channel_id],
                "github_repos": [github_repo],
                "vercel_project_ids": [vercel_project_id],
                "pagerduty_service_ids": [],
                "services": ["vercel-demo"],
            },
            # Output destinations — where agent results are reported
            "output_config": {
                "default_destinations": [
                    {
                        "type": "slack",
                        "channel_id": slack_channel_id,
                        "channel_name": slack_channel_name,
                    }
                ],
                "trigger_overrides": {
                    "vercel": "use_default",
                    "slack": "reply_in_thread",
                    "api": "use_default",
                },
            },
            # Notifications (legacy fallback)
            "notifications": {
                "default_slack_channel_id": slack_channel_id,
            },
            # Agent configuration — single planner, no sub-agents
            # Rationale: The triage workflow is sequential (investigate → fix →
            # validate → report). Sub-agents would add latency from context
            # switching and indirection without any parallelism benefit.
            # A single agent with the right tools and a detailed prompt is
            # more reliable and faster for this use case.
            "agents": {
                "planner": {
                    "enabled": True,
                    "model": {
                        "name": "anthropic/claude-sonnet-4-20250514",
                        # 0.3: enough creativity for hypothesis formation and
                        # code fix generation, not so much it hallucinates
                        "temperature": 0.3,
                    },
                    "prompt": {
                        "system": VERCEL_TRIAGE_SYSTEM_PROMPT,
                        "prefix": "",
                        "suffix": "",
                    },
                    # Explicit tool whitelist: only Vercel + GitHub + Slack
                    # The full registry has 100+ tools (k8s, aws, docker,
                    # datadog, etc.) that would waste tokens and attention
                    "tools": {
                        "enabled": PLANNER_TOOLS,
                        "disabled": [],
                    },
                    # No sub-agents — planner does everything
                    "sub_agents": {},
                    # 80 turns: enough for 3 fix attempts with generous margin
                    # Worst case: ~15 (investigate) + 3×15 (fix attempts) +
                    # 1 (report) = ~61 turns
                    "max_turns": 80,
                },
                # Disable all sub-agents (planner handles everything)
                "investigation": {"enabled": False},
                "coding": {"enabled": False},
                "writeup": {"enabled": False},
            },
        }

        if team_cfg is None:
            print("  Creating team configuration...")
            s.add(
                NodeConfiguration(
                    id=f"cfg-{uuid.uuid4().hex[:12]}",
                    org_id=ORG_ID,
                    node_id=TEAM_NODE_ID,
                    node_type="team",
                    config_json=config_json,
                    updated_by="seed_vercel_demo",
                )
            )
        else:
            print("  Updating existing team configuration...")
            team_cfg.config_json = config_json
            team_cfg.updated_by = "seed_vercel_demo"

        # 4. Create/update output configuration
        output_cfg = s.execute(
            select(TeamOutputConfig).where(
                TeamOutputConfig.org_id == ORG_ID,
                TeamOutputConfig.team_node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if output_cfg is None:
            print("  Creating output configuration...")
            s.add(
                TeamOutputConfig(
                    org_id=ORG_ID,
                    team_node_id=TEAM_NODE_ID,
                    default_destinations=[
                        {
                            "type": "slack",
                            "channel_id": slack_channel_id,
                            "channel_name": slack_channel_name,
                        }
                    ],
                    trigger_overrides={
                        "vercel": "use_default",
                        "slack": "reply_in_thread",
                        "api": "use_default",
                    },
                )
            )
        else:
            print("  Updating existing output configuration...")
            output_cfg.default_destinations = [
                {
                    "type": "slack",
                    "channel_id": slack_channel_id,
                    "channel_name": slack_channel_name,
                }
            ]
            output_cfg.trigger_overrides = {
                "vercel": "use_default",
                "slack": "reply_in_thread",
                "api": "use_default",
            }

        s.commit()

    print("\nVercel demo seeding complete!")
    print("\n" + "=" * 60)
    print("DEMO SETUP SUMMARY")
    print("=" * 60)
    print(f"\nSlack Channel: {slack_channel_id} ({slack_channel_name})")
    print(f"GitHub Repo: {github_repo}")
    print(f"Vercel Project: {vercel_project_id}")
    print(f"\nTools enabled: {len(PLANNER_TOOLS)}")
    for t in PLANNER_TOOLS:
        print(f"  - {t}")
    print("\nWorkflow:")
    print("  Phase 1: Detect Vercel error -> investigate code -> root cause analysis")
    print("  Phase 2: Create PR fix -> validate via preview deployment -> iterate (3x)")
    print("  Phase 3: Report results to Slack")
    print("\nAgent Config:")
    print("  Architecture: Single planner (no sub-agents)")
    print("  Model: anthropic/claude-sonnet-4 (temperature=0.3)")
    print("  Max turns: 80")
    print(f"  Tool count: {len(PLANNER_TOOLS)} (scoped to Vercel + GitHub + Slack)")
    print("\n" + "=" * 60)
    print("\nNext steps:")
    print("  1. Set VERCEL_TOKEN and VERCEL_TEAM_ID (if using team scope)")
    print("  2. Set GITHUB_TOKEN with repo write access")
    print("  3. Configure Vercel Log Drain to POST to /webhooks/vercel/logs")
    print("  4. Set VERCEL_WEBHOOK_SECRET to the log drain integration secret")
    print("  5. Invite the bot to the Slack channel")
    print("  6. Trigger a runtime error in the Vercel app to test the flow")


if __name__ == "__main__":
    main()
