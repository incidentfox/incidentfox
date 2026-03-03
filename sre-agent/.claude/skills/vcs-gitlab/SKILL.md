---
name: gitlab-integration
description: GitLab project management, CI/CD pipelines, merge requests, and code review. Use when investigating GitLab projects, pipeline failures, merge requests, commits, or issues.
allowed-tools: Bash(python *)
---

# GitLab Integration

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `GITLAB_TOKEN` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `GITLAB_URL` - GitLab instance URL (default: `https://gitlab.com`)

---

## Available Scripts

All scripts are in `.claude/skills/vcs-gitlab/scripts/`

### PROJECT SCRIPTS

#### list_projects.py
```bash
python .claude/skills/vcs-gitlab/scripts/list_projects.py [--search "query"] [--visibility private]
```

#### get_project.py
```bash
python .claude/skills/vcs-gitlab/scripts/get_project.py --project "group/project"
```

### CI/CD PIPELINE SCRIPTS

#### get_pipelines.py
```bash
python .claude/skills/vcs-gitlab/scripts/get_pipelines.py --project "group/project" [--status failed] [--ref main]
```

#### get_pipeline_jobs.py
```bash
python .claude/skills/vcs-gitlab/scripts/get_pipeline_jobs.py --project "group/project" --pipeline-id 12345
```

### MERGE REQUEST SCRIPTS

#### list_merge_requests.py
```bash
python .claude/skills/vcs-gitlab/scripts/list_merge_requests.py --project "group/project" [--state opened]
```

#### get_mr.py
```bash
python .claude/skills/vcs-gitlab/scripts/get_mr.py --project "group/project" --mr-iid 42
```

#### get_mr_changes.py
```bash
python .claude/skills/vcs-gitlab/scripts/get_mr_changes.py --project "group/project" --mr-iid 42
```

### COMMIT SCRIPTS

#### list_commits.py
```bash
python .claude/skills/vcs-gitlab/scripts/list_commits.py --project "group/project" [--ref main] [--since "2026-01-01T00:00:00Z"]
```

#### get_commit.py
```bash
python .claude/skills/vcs-gitlab/scripts/get_commit.py --project "group/project" --sha abc1234
```

### BRANCH/ISSUE SCRIPTS

#### list_branches.py
```bash
python .claude/skills/vcs-gitlab/scripts/list_branches.py --project "group/project" [--search "feature"]
```

#### list_issues.py
```bash
python .claude/skills/vcs-gitlab/scripts/list_issues.py --project "group/project" [--state opened] [--labels "bug,critical"]
```

#### create_issue.py
```bash
python .claude/skills/vcs-gitlab/scripts/create_issue.py --project "group/project" --title "Title" [--description "Details"]
```

---

## Investigation Workflows

### Pipeline Failure Investigation
```
1. get_pipelines.py --project X --status failed
2. get_pipeline_jobs.py --project X --pipeline-id <id>
3. get_commit.py --project X --sha <sha>
4. get_mr.py --project X --mr-iid <iid>
```

### Deployment Correlation
```
1. list_commits.py --project X --ref main --since "2026-01-15T00:00:00Z"
2. list_merge_requests.py --project X --state merged
3. get_mr_changes.py --project X --mr-iid <iid>
```
