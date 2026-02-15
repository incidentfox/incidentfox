---
name: github-pr-review
description: Review pull requests and post inline comments with code suggestions. Use when you need to analyze PR diffs, read repo files, search for code patterns, or submit PR reviews with line-level feedback.
allowed-tools: Bash(python *)
---

# GitHub PR Review

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `GITHUB_TOKEN` in environment variables. Just run the scripts directly; authentication is handled transparently.

---

## Available Scripts

All scripts are in `.claude/skills/github-pr-review/scripts/`

### get_pr_files.py — Get PR diff and changed files
```bash
python .claude/skills/github-pr-review/scripts/get_pr_files.py --repo OWNER/REPO --pr NUMBER [--show-patch]

# Examples:
python .claude/skills/github-pr-review/scripts/get_pr_files.py --repo acme/webapp --pr 42
python .claude/skills/github-pr-review/scripts/get_pr_files.py --repo acme/webapp --pr 42 --show-patch
```

### read_file.py — Read full file from repo
```bash
python .claude/skills/github-pr-review/scripts/read_file.py --repo OWNER/REPO --path FILE_PATH [--ref BRANCH]

# Examples:
python .claude/skills/github-pr-review/scripts/read_file.py --repo acme/webapp --path src/components/Checkout.tsx
python .claude/skills/github-pr-review/scripts/read_file.py --repo acme/webapp --path package.json --ref main
```

### search_code.py — Search for code patterns in repo
```bash
python .claude/skills/github-pr-review/scripts/search_code.py --query "SEARCH_TERM" --repo OWNER/REPO

# Examples:
python .claude/skills/github-pr-review/scripts/search_code.py --query "trackEvent" --repo acme/webapp
python .claude/skills/github-pr-review/scripts/search_code.py --query "amplitude" --repo acme/webapp
python .claude/skills/github-pr-review/scripts/search_code.py --query "analytics.track" --repo acme/webapp
```

### get_review_context.py — Check for prior reviews (incremental mode)
```bash
python .claude/skills/github-pr-review/scripts/get_review_context.py --repo OWNER/REPO --pr NUMBER

# Output tells you:
# - Whether you already reviewed this PR
# - Which commit you last reviewed
# - What files changed since then (delta)
# - Your previous inline comments
# - Other reviewers' comments
```

### create_review.py — Submit PR review with inline comments
```bash
python .claude/skills/github-pr-review/scripts/create_review.py \
  --repo OWNER/REPO \
  --pr NUMBER \
  --body "Review summary text" \
  --comments-file /tmp/review_comments.json \
  --event COMMENT

# The --comments-file is a JSON array of inline comments:
# [
#   {
#     "path": "src/components/Checkout.tsx",
#     "line": 42,
#     "body": "Consider tracking this event:\n```suggestion\ntrackEvent('checkout_started', { itemCount });\n```"
#   }
# ]
```

---

## PR Review Workflow

### Step 1: Check for prior reviews (ALWAYS DO THIS FIRST)
```bash
python .claude/skills/github-pr-review/scripts/get_review_context.py --repo OWNER/REPO --pr NUMBER
```

This tells you whether to skip, do a full review, or an incremental review:
- **"ALREADY REVIEWED at current HEAD"** → Skip, do nothing
- **"FIRST REVIEW"** → Full review (proceed to steps 2-5)
- **"New commits since last review"** → Incremental review (only review the listed delta files)

### Step 2: Analyze the PR
```bash
# Get PR details and changed files with diffs
python .claude/skills/github-pr-review/scripts/get_pr_files.py --repo OWNER/REPO --pr NUMBER --show-patch
```

### Step 3: Read full file context (when diff is not enough)
```bash
# Read the complete file to understand surrounding code
python .claude/skills/github-pr-review/scripts/read_file.py --repo OWNER/REPO --path src/file.tsx
```

### Step 4: Search for existing patterns
```bash
# Check if analytics/tracking is already set up
python .claude/skills/github-pr-review/scripts/search_code.py --query "trackEvent OR analytics.track OR amplitude" --repo OWNER/REPO
```

### Step 5: Write comments file and submit review
```bash
# Write the comments JSON (use the Write tool or echo)
# Then submit the review
python .claude/skills/github-pr-review/scripts/create_review.py \
  --repo OWNER/REPO --pr NUMBER \
  --body "## Telemetry Review\n\nFound 5 places where analytics events should be added." \
  --comments-file /tmp/review_comments.json
```

---

## Inline Comment Format

Use GitHub's **suggestion** syntax to propose specific code changes that the developer can accept with one click:

````markdown
Consider adding a telemetry event here:
```suggestion
trackEvent('button_clicked', { buttonId: props.id, page: 'checkout' });
handleClick(e);
```
````

**Important rules for `suggestion` blocks:**
- The suggestion **replaces** the line(s) at the specified `line` number
- Include the original code plus your addition (the whole replacement)
- Keep suggestions minimal — add the tracking call, keep existing code intact
- If adding a line, include the original line plus your new line in the suggestion

---

## Quick Reference

| Goal | Command |
|------|---------|
| Check prior reviews | `get_review_context.py --repo X --pr N` |
| Get PR files + diffs | `get_pr_files.py --repo X --pr N --show-patch` |
| Read a file | `read_file.py --repo X --path src/app.tsx` |
| Search for patterns | `search_code.py --query "amplitude" --repo X` |
| Submit review | `create_review.py --repo X --pr N --body "..." --comments-file F` |
