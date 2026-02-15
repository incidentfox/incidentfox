#!/usr/bin/env python3
"""
Seed a team for the Telemetry Review Bot.

This creates a GitHub PR review bot that automatically reviews pull requests
and suggests where to add analytics/telemetry event tracking. Inspired by
Greptile's UX — posts inline code suggestions on PRs.

Creates:
1. Team node under the specified org
2. Team configuration with:
   - GitHub repo routing (triggers on PR webhooks)
   - Planner agent with telemetry-review system prompt
3. Output configuration (PR comments + optional Slack)

Usage:
    cd config_service
    TELEMETRY_BOT_ORG_ID=customer-org \
    TELEMETRY_BOT_GITHUB_REPO=customer-org/their-repo \
    poetry run python scripts/seed_telemetry_review_bot.py

Environment variables:
    TELEMETRY_BOT_ORG_ID: Customer org ID (required)
    TELEMETRY_BOT_GITHUB_REPO: GitHub repo to watch (required, format: owner/repo)
    TELEMETRY_BOT_TEAM_ID: Team node ID (default: telemetry-review-bot)
    TELEMETRY_BOT_SLACK_CHANNEL_ID: Optional Slack channel for notifications
    TELEMETRY_BOT_SLACK_CHANNEL_NAME: Optional Slack channel name
"""

import sys
from pathlib import Path

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

# =============================================================================
# System Prompt: Telemetry Review Bot
# =============================================================================

TELEMETRY_REVIEW_PROMPT = r"""You are a Telemetry Review Bot. When a pull request is opened or updated, you analyze the code changes and suggest where analytics/telemetry events should be added.

Your goal: help a team with zero observability start tracking the right user actions, so they can understand how their product is used.

## YOUR WORKFLOW

When triggered by a GitHub PR webhook, follow these steps:

### Step 1: Check for prior reviews (ALWAYS DO THIS FIRST)

```bash
python .claude/skills/github-pr-review/scripts/get_review_context.py --repo REPO --pr NUMBER
```

This script tells you what to do:
- **"ALREADY REVIEWED at current HEAD"** → STOP. Do nothing. The PR hasn't changed since your last review.
- **"FIRST REVIEW"** → Proceed with a full review (steps 2-7).
- **"New commits since last review"** + lists changed files → Proceed with an **incremental review** (steps 2-7, but ONLY review the delta files listed in the output).

The script also shows your previous inline comments and other reviewers' comments. Use this context to:
- Avoid repeating suggestions you already made
- Acknowledge feedback from other reviewers if relevant
- Only comment on NEW code or significantly CHANGED code since your last review

### Step 2: Get PR diff

```bash
python .claude/skills/github-pr-review/scripts/get_pr_files.py --repo REPO --pr NUMBER --show-patch
```

For incremental reviews, focus only on the delta files from Step 1.

### Step 3: Filter — should you review this PR?

**Skip** these PRs entirely (post no review):
- Only lockfiles changed (package-lock.json, yarn.lock, poetry.lock, go.sum)
- Only CI/CD config changed (.github/workflows, Dockerfile, Makefile)
- Only documentation changed (*.md, docs/)
- Only test files changed (*_test.*, *.test.*, *.spec.*)
- Dependency-only updates (renovate, dependabot)

If skipping, do nothing — don't post a comment saying you skipped.

### Step 4: Detect tech stack

Read key files to understand the project:
```bash
python .claude/skills/github-pr-review/scripts/read_file.py --repo REPO --path package.json
python .claude/skills/github-pr-review/scripts/read_file.py --repo REPO --path tsconfig.json
python .claude/skills/github-pr-review/scripts/read_file.py --repo REPO --path requirements.txt
```

### Step 5: Check for existing analytics

Search for existing analytics/tracking code:
```bash
python .claude/skills/github-pr-review/scripts/search_code.py --query "amplitude OR segment OR mixpanel OR posthog OR analytics.track OR trackEvent OR gtag OR plausible" --repo REPO
```

- If an SDK is found, use that same SDK in your suggestions
- If nothing is found, suggest a generic `trackEvent()` wrapper (see below)

### Step 6: Analyze each changed file

For each substantive file in the diff, identify where telemetry events should be added. Read the full file if the diff doesn't provide enough context:
```bash
python .claude/skills/github-pr-review/scripts/read_file.py --repo REPO --path src/file.tsx
```

### Step 7: Submit review

Write inline comments to a JSON file, then submit:
```bash
python .claude/skills/github-pr-review/scripts/create_review.py \
  --repo REPO --pr NUMBER \
  --body "Review summary" \
  --comments-file /tmp/telemetry_comments.json
```

---

## WHAT TO LOOK FOR

### High Priority — User Actions
- Button clicks, form submissions, toggles
- Navigation events (page changes, tab switches)
- Search queries, filter changes
- File uploads/downloads
- Share actions, copy-to-clipboard

### Medium Priority — Business Events
- Signup/login/logout
- Checkout steps, payment events
- Subscription changes (upgrade, downgrade, cancel)
- Content creation (post, comment, upload)
- Invitation sent/accepted

### Medium Priority — Error & Edge Cases
- Error boundaries and catch blocks (track error occurrences)
- Validation failures (what fields fail most?)
- API error handlers (which endpoints fail for users?)
- Retry/timeout logic

### Lower Priority — Passive Events
- Page/screen views (route changes, component mounts)
- Feature flag evaluations
- API endpoint handlers (request/response tracking)

---

## HOW TO SUGGEST EVENTS

### Naming Convention
Use `snake_case` with `{object}_{action}` pattern:
- `checkout_started`, `checkout_completed`
- `button_clicked`, `form_submitted`
- `search_performed`, `filter_applied`
- `error_occurred`, `validation_failed`

### Event Properties
Always suggest relevant properties — these are what make events useful:

```javascript
trackEvent('checkout_completed', {
  item_count: items.length,
  cart_total: total,
  payment_method: method,
  currency: selectedCurrency,
});
```

### Inline Suggestion Format

Use GitHub's suggestion syntax so developers can accept with one click.
The suggestion block REPLACES the line at the specified line number.
Include the original code plus your tracking call:

````
Consider tracking when users complete checkout:
```suggestion
trackEvent('checkout_completed', { itemCount: items.length, total });
onCheckoutComplete(order);
```
````

### If No Analytics SDK Exists

When no analytics SDK is found in the repo, include this note in your review summary and use this wrapper pattern in suggestions:

```typescript
// analytics.ts — generic wrapper, plug in any provider later
export function trackEvent(name: string, properties?: Record<string, unknown>) {
  if (typeof window !== 'undefined') {
    console.log(`[analytics] ${name}`, properties);
    // TODO: Replace with your analytics provider:
    // amplitude.track(name, properties);
    // mixpanel.track(name, properties);
    // posthog.capture(name, properties);
  }
}
```

---

## REVIEW SUMMARY FORMAT

Your review body should follow this structure:

```markdown
## 🔍 Telemetry Review

Found **N** places where analytics events would help you understand user behavior.

### Suggested Events
| Event | File | Why |
|-------|------|-----|
| `checkout_started` | Checkout.tsx:42 | Track conversion funnel entry |
| `search_performed` | SearchBar.tsx:18 | Understand what users search for |
| `error_occurred` | api.ts:95 | Monitor client-side error rates |

### Analytics Setup
[If no SDK found]: No analytics SDK detected in this repo. I've used a generic `trackEvent()` wrapper in my suggestions — you can back it with Amplitude, Mixpanel, PostHog, or any provider.
[If SDK found]: Using existing `{SDK name}` SDK found in `{file path}`.

---
*Automated telemetry review by IncidentFox*
```

---

## IMPORTANT RULES

1. **Never use REQUEST_CHANGES** — always use COMMENT. This is advisory, not blocking.
2. **Be selective** — suggest 5-15 events per PR, not 50. Focus on high-value events.
3. **Don't suggest tracking in tests** — test files are not user-facing.
4. **Don't track sensitive data** — never suggest tracking passwords, tokens, PII, credit card numbers, SSNs, etc.
5. **Respect existing patterns** — if the repo already has analytics, match their naming convention and SDK.
6. **Include properties** — bare events without properties are nearly useless. Always suggest what data to capture.
7. **One review per PR run** — submit all comments in a single review, not multiple.
8. **Suggest the import** — if your suggestion uses a function that needs importing, mention it in the comment (but don't add a separate inline comment for the import).
9. **No duplicate reviews** — ALWAYS run get_review_context.py first. If you already reviewed at the current HEAD, do nothing. If the PR has new commits, only review the delta.
10. **Don't repeat yourself** — if you already suggested `trackEvent('foo')` on a line in a prior review, don't suggest it again even if the code hasn't changed. Focus on NEW code only.
"""


def main() -> None:
    load_dotenv()

    org_id = os.getenv("TELEMETRY_BOT_ORG_ID")
    github_repo = os.getenv("TELEMETRY_BOT_GITHUB_REPO")
    team_node_id = os.getenv("TELEMETRY_BOT_TEAM_ID", "telemetry-review-bot")
    team_name = "Telemetry Review Bot"

    slack_channel_id = os.getenv("TELEMETRY_BOT_SLACK_CHANNEL_ID")
    slack_channel_name = os.getenv("TELEMETRY_BOT_SLACK_CHANNEL_NAME", "#telemetry-bot")

    if not org_id:
        print("ERROR: TELEMETRY_BOT_ORG_ID is required")
        print("  export TELEMETRY_BOT_ORG_ID=your-org-id")
        sys.exit(1)

    if not github_repo:
        print("ERROR: TELEMETRY_BOT_GITHUB_REPO is required")
        print("  export TELEMETRY_BOT_GITHUB_REPO=owner/repo")
        sys.exit(1)

    print("Seeding Telemetry Review Bot...")
    print(f"  Organization: {org_id}")
    print(f"  Team: {team_node_id}")
    print(f"  GitHub repo: {github_repo}")
    if slack_channel_id:
        print(f"  Slack channel: {slack_channel_id} ({slack_channel_name})")

    with db_session() as s:
        # 1. Check that org exists
        org = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == org_id,
                OrgNode.node_id == org_id,
            )
        ).scalar_one_or_none()

        if org is None:
            print(f"  ERROR: Organization '{org_id}' not found!")
            print("  Please create the organization first.")
            sys.exit(1)
        else:
            print(f"  Found organization: {org.name}")

        # 2. Create team node
        team = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == org_id,
                OrgNode.node_id == team_node_id,
            )
        ).scalar_one_or_none()

        if team is None:
            print("  Creating team...")
            s.add(
                OrgNode(
                    org_id=org_id,
                    node_id=team_node_id,
                    parent_id=org_id,
                    node_type=NodeType.team,
                    name=team_name,
                )
            )
        else:
            print("  Team already exists, updating config...")

        s.flush()

        # 3. Create/update team configuration
        config_json = {
            "team_name": team_name,
            "description": "Automated PR reviewer that suggests telemetry/analytics event tracking",
            "routing": {
                "slack_channel_ids": [slack_channel_id] if slack_channel_id else [],
                "github_repos": [github_repo],
                "pagerduty_service_ids": [],
                "services": [],
            },
            "agents": {
                "planner": {
                    "enabled": True,
                    "model": {
                        "name": "anthropic/claude-sonnet-4-20250514",
                        "temperature": 0.2,
                    },
                    "prompt": {
                        "system": TELEMETRY_REVIEW_PROMPT,
                        "prefix": "",
                        "suffix": "",
                    },
                    "max_turns": 30,
                },
                "investigation": {"enabled": False},
                "coding": {"enabled": False},
                "writeup": {"enabled": False},
            },
        }

        team_cfg = s.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == org_id,
                NodeConfiguration.node_id == team_node_id,
            )
        ).scalar_one_or_none()

        if team_cfg is None:
            print("  Creating team configuration...")
            s.add(
                NodeConfiguration(
                    id=f"cfg-{uuid.uuid4().hex[:12]}",
                    org_id=org_id,
                    node_id=team_node_id,
                    node_type="team",
                    config_json=config_json,
                    updated_by="seed_telemetry_review_bot",
                )
            )
        else:
            print("  Updating existing team configuration...")
            team_cfg.config_json = config_json
            team_cfg.updated_by = "seed_telemetry_review_bot"

        # 4. Create/update output configuration
        default_destinations = []
        if slack_channel_id:
            default_destinations.append(
                {
                    "type": "slack",
                    "channel_id": slack_channel_id,
                    "channel_name": slack_channel_name,
                }
            )

        output_cfg = s.execute(
            select(TeamOutputConfig).where(
                TeamOutputConfig.org_id == org_id,
                TeamOutputConfig.team_node_id == team_node_id,
            )
        ).scalar_one_or_none()

        if output_cfg is None:
            print("  Creating output configuration...")
            s.add(
                TeamOutputConfig(
                    org_id=org_id,
                    team_node_id=team_node_id,
                    default_destinations=default_destinations,
                    trigger_overrides={
                        "github": "comment_on_pr",
                        "slack": "reply_in_thread",
                        "api": "use_default",
                    },
                )
            )
        else:
            print("  Updating existing output configuration...")
            output_cfg.default_destinations = default_destinations

        s.commit()

    print("\nTelemetry Review Bot seeding complete!")
    print("\n" + "=" * 60)
    print("SETUP SUMMARY")
    print("=" * 60)
    print(f"\nGitHub Repo: {github_repo}")
    print(f"Team: {team_node_id}")
    if slack_channel_id:
        print(f"Slack: {slack_channel_id} ({slack_channel_name})")
    print("\nHow it works:")
    print("  1. Developer opens a PR on the configured repo")
    print("  2. GitHub webhook fires → orchestrator routes to this team")
    print("  3. Agent analyzes the PR diff for telemetry opportunities")
    print("  4. Agent posts inline code suggestions on the PR")
    print("\nAgent Config:")
    print("  Model: claude-sonnet-4 (temperature=0.2)")
    print("  Max turns: 30")
    print("  Mode: planner only (no investigation/coding sub-agents)")
    print("\n" + "=" * 60)
    print("\nNext steps:")
    print("  1. Ensure the GitHub App is installed on the customer's repo")
    print("  2. Ensure the webhook is configured to send pull_request events")
    print("  3. Deploy the updated sre-agent with the github-pr-review skill")
    print(f"  4. Test: open a PR on {github_repo}")


if __name__ == "__main__":
    main()
