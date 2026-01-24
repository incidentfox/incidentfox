# IncidentFox Repository Sync

Bidirectional sync tooling between the private mono-repo and public incidentfox repository.

## Overview

```
┌─────────────────────────────┐         ┌─────────────────────────────┐
│  incidentfox/mono-repo      │ ──────▶ │  incidentfox/incidentfox    │
│  (Private)                  │         │  (Public / Open Core)       │
│                             │ ◀────── │                             │
│  • Full codebase            │         │  • Core features            │
│  • Premium features         │ sync-to │  • Stub READMEs for premium │
│  • Internal configs         │ -public │  • Community contributions  │
│  • Evaluation pipeline      │         │                             │
└─────────────────────────────┘         └─────────────────────────────┘
                                sync-from
                                 -public
```

## Quick Start

### 1. Install Workflows in mono-repo

Copy the workflow files to the private mono-repo:

```bash
# From mono-repo root
mkdir -p .github/workflows

# Copy sync workflows (adjust path as needed)
cp /path/to/incidentfox/scripts/repo-sync/workflows/sync-to-public.yml .github/workflows/
cp /path/to/incidentfox/scripts/repo-sync/workflows/sync-from-public.yml .github/workflows/
```

### 2. Create GitHub PAT

Create a Personal Access Token with `repo` scope that can access both repositories:

1. Go to GitHub → Settings → Developer settings → Personal access tokens
2. Create new token (classic) with `repo` scope
3. Add as secret `SYNC_PAT` in **both repositories**:
   - `incidentfox/mono-repo` → Settings → Secrets → Actions
   - `incidentfox/incidentfox` → Settings → Secrets → Actions

### 3. Run Sync

**From GitHub Actions (recommended):**

1. Go to mono-repo → Actions → "Sync to Public Repo"
2. Click "Run workflow"
3. Choose dry run first to preview changes
4. Run again without dry run to create PR

**From command line (manual):**

```bash
# From mono-repo root
./scripts/repo-sync/sync.sh to-public

# Preview first
./scripts/repo-sync/sync.sh --dry-run to-public
```

## What Gets Synced

### Private → Public (sync-to-public)

✅ **Synced to public:**
- `agent/` - Core agent code
- `config_service/` - Configuration service
- `orchestrator/` - Workflow orchestration
- `web_ui/` - Admin dashboard
- `knowledge_base/` - Knowledge base service
- `local/` - Local development setup
- `docs/` - Public documentation
- `charts/` - Helm charts
- `scripts/` - Utility scripts (except sync scripts)

❌ **Kept private (excluded):**
- `ai_pipeline/` - Full evaluation pipeline (only README.md synced)
- `sre-agent/` - SRE sandbox agent (only README.md synced)
- `correlation_service/` - Premium correlation service (only README.md synced)
- `dependency_service/` - Premium dependency tracking (only README.md synced)
- `slack-bot/` - Internal Slack bot
- `telemetry_collector/` - Internal telemetry
- `internal_test_configs.txt` - Internal test configs
- `note.md` - Internal notes
- `*.json` config files - Team/org specific configs
- Internal GHA workflows (eval-pipeline, deploy-service, etc.)
- `infra/terraform/envs/pilot/` - Pilot environment configs

### Public → Private (sync-from-public)

✅ **Synced to private:**
- Bug fixes and improvements to core services
- Documentation updates
- Community contributions (after PR review in public repo)

❌ **Skipped (preserved in private):**
- Premium service directories (would overwrite with stub)
- Internal config files
- Private-only workflows

## File Structure

```
scripts/repo-sync/
├── README.md               # This file
├── sync.sh                 # Manual sync script
└── workflows/
    ├── sync-to-public.yml  # GHA: mono-repo → incidentfox
    └── sync-from-public.yml # GHA: incidentfox → mono-repo

.syncconfig.yaml            # Sync configuration (in repo root)
```

## Configuration

The `.syncconfig.yaml` file defines sync behavior:

```yaml
sync:
  public_repo: "incidentfox/incidentfox"
  private_repo: "incidentfox/mono-repo"
  default_branch: "main"

exclude_from_public:
  - "ai_pipeline/**"
  - "!ai_pipeline/README.md"  # Keep stub README
  # ... more patterns

stub_directories:
  - "ai_pipeline"
  - "sre-agent"
  # ... directories that only have README.md in public
```

## Workflow Details

### sync-to-public.yml

**Triggers:**
- Manual dispatch (workflow_dispatch)
- Optionally on push to main (commented by default)

**Process:**
1. Checkout both repos
2. rsync with exclusion patterns
3. Ensure stub directories only have README.md
4. Create PR in public repo (or direct push)

**Inputs:**
- `dry_run` - Preview changes without creating PR
- `create_pr` - Create PR (true) or push directly (false)

### sync-from-public.yml

**Triggers:**
- Manual dispatch
- Optionally via repository_dispatch webhook

**Process:**
1. Checkout both repos
2. rsync public → private (preserving private-only content)
3. Create PR in private repo for review

**Inputs:**
- `dry_run` - Preview changes without creating PR
- `pr_number` - Sync specific PR's changes (optional)

## Manual Sync Script

For local development or debugging:

```bash
# Show help
./scripts/repo-sync/sync.sh --help

# Preview sync to public
./scripts/repo-sync/sync.sh --dry-run to-public

# Sync to public (creates PR)
./scripts/repo-sync/sync.sh to-public

# Sync from public
./scripts/repo-sync/sync.sh from-public
```

**Requirements:**
- `git` - Version control
- `rsync` - File synchronization
- `yq` - YAML parser (optional, for config file)
- GitHub CLI (`gh`) - For creating PRs

## Best Practices

### When to Sync

**Private → Public:**
- After releasing new features that should be open source
- After bug fixes to core services
- When documentation is updated
- Before major public releases

**Public → Private:**
- After merging community PRs in public repo
- After external contributors fix bugs
- When public README/docs are improved

### Review Checklist

Before approving sync PRs, verify:

- [ ] No secrets or credentials included
- [ ] No internal/premium code leaked to public
- [ ] Stub directories only contain README.md
- [ ] No internal config files synced
- [ ] Tests pass in target repo

### Handling Conflicts

If both repos have changes to the same file:

1. The sync workflow creates a PR (doesn't auto-merge)
2. Review the diff carefully
3. Resolve conflicts manually if needed
4. For frequent conflicts, consider which repo "owns" that file

## Troubleshooting

### "No changes to sync"

This is normal if repos are already in sync. Check:
- Are you on the right branch?
- Have changes been committed?

### Sync fails with permission error

Ensure `SYNC_PAT` secret:
- Has `repo` scope
- Can access both repositories
- Is not expired

### Stub directory has full content

The sync should remove everything except README.md from stub directories.
If not working, check the `STUB_DIRS` array in the workflow.

### rsync errors

Ensure rsync is available:
```bash
# Ubuntu/Debian
apt-get install rsync

# macOS
brew install rsync
```

## Security Considerations

1. **PAT Security**: The `SYNC_PAT` has write access to both repos. Rotate regularly.
2. **Review PRs**: Always review sync PRs before merging - automated doesn't mean trusted.
3. **Exclusion Patterns**: Double-check exclusion patterns when adding new private content.
4. **Secrets Scanning**: Both repos should have gitleaks/secret scanning enabled.
