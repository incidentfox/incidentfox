#!/usr/bin/env bash
#
# IncidentFox Repository Sync Script
# Bidirectional sync between mono-repo (private) and incidentfox (public)
#
# Usage:
#   ./sync.sh to-public    # Sync changes from mono-repo → incidentfox
#   ./sync.sh from-public  # Sync changes from incidentfox → mono-repo
#   ./sync.sh --dry-run to-public  # Preview without making changes
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../../.syncconfig.yaml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PRIVATE_REPO="incidentfox/mono-repo"
PUBLIC_REPO="incidentfox/incidentfox"
SYNC_BRANCH_PREFIX="sync"
DRY_RUN=false

# Files/directories to EXCLUDE from public repo
EXCLUDE_FROM_PUBLIC=(
    # Premium services (full content)
    "ai_pipeline/*"
    "sre-agent/*"
    "correlation_service/*"
    "dependency_service/*"
    "slack-bot"
    "telemetry_collector"

    # Internal config files
    "internal_test_configs.txt"
    "note.md"
    "org_internal_test_config.json"
    "team_a_config.json"
    "team_a_full_config.json"
    "test_mcp_config.py"

    # Internal workflows
    ".github/workflows/eval-pipeline.yml"
    ".github/workflows/deploy-service.yml"
    ".github/workflows/deploy-knowledge-base.yml"
    ".github/workflows/publish-dockerhub.yml"
    ".github/workflows/raptor-kb-deploy.yml"
    ".github/workflows/web-ui-deploy.yml"

    # Internal infrastructure
    "infra/terraform/envs/pilot"

    # Sync tooling itself
    ".syncconfig.yaml"
    "scripts/repo-sync"
)

# Stub directories - keep only README.md in public
STUB_DIRS=(
    "ai_pipeline"
    "sre-agent"
    "correlation_service"
    "dependency_service"
)

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

usage() {
    cat << EOF
IncidentFox Repository Sync Script

Usage:
    $0 [options] <direction>

Directions:
    to-public     Sync changes from mono-repo → incidentfox (public)
    from-public   Sync changes from incidentfox → mono-repo (private)

Options:
    --dry-run     Preview changes without making them
    --help        Show this help message

Examples:
    $0 to-public              # Sync to public repo
    $0 --dry-run to-public    # Preview sync to public
    $0 from-public            # Sync community contributions back
EOF
    exit 0
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check for required tools
    for cmd in git rsync yq; do
        if ! command -v "$cmd" &> /dev/null; then
            log_error "$cmd is required but not installed."
            exit 1
        fi
    done

    # Check we're in a git repo
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        log_error "Not in a git repository"
        exit 1
    fi

    log_success "Prerequisites check passed"
}

detect_repo_type() {
    local remote_url
    remote_url=$(git remote get-url origin 2>/dev/null || echo "")

    if [[ "$remote_url" == *"mono-repo"* ]]; then
        echo "private"
    elif [[ "$remote_url" == *"incidentfox/incidentfox"* ]] || [[ "$remote_url" == *"incidentfox.git"* ]]; then
        echo "public"
    else
        echo "unknown"
    fi
}

build_rsync_excludes() {
    local excludes=""
    for pattern in "${EXCLUDE_FROM_PUBLIC[@]}"; do
        excludes="$excludes --exclude='$pattern'"
    done
    echo "$excludes"
}

sync_to_public() {
    local repo_type
    repo_type=$(detect_repo_type)

    if [[ "$repo_type" != "private" ]]; then
        log_error "This command must be run from the mono-repo (private)"
        log_info "Current repo appears to be: $repo_type"
        exit 1
    fi

    log_info "Syncing from mono-repo → incidentfox (public)"

    local current_branch
    current_branch=$(git branch --show-current)

    if [[ "$current_branch" != "main" ]]; then
        log_warn "You're on branch '$current_branch', not 'main'"
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    # Create temp directory for sync
    local tmp_dir
    tmp_dir=$(mktemp -d)
    trap "rm -rf $tmp_dir" EXIT

    log_info "Cloning public repo to temp directory..."
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] Would clone $PUBLIC_REPO"
    else
        git clone --depth 1 "git@github.com:${PUBLIC_REPO}.git" "$tmp_dir/public"
    fi

    # Build rsync command with excludes
    local rsync_cmd="rsync -av --delete"
    for pattern in "${EXCLUDE_FROM_PUBLIC[@]}"; do
        rsync_cmd="$rsync_cmd --exclude='$pattern'"
    done

    # Also exclude .git
    rsync_cmd="$rsync_cmd --exclude='.git'"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] Would sync files with:"
        log_info "  $rsync_cmd ./ $tmp_dir/public/"

        # Show what would be synced
        log_info "Files that would be synced (excluding private content):"
        eval "$rsync_cmd --dry-run ./ $tmp_dir/public/ 2>/dev/null" || true
    else
        log_info "Syncing files..."
        eval "$rsync_cmd ./ $tmp_dir/public/"

        # Ensure stub directories have only README.md
        for stub_dir in "${STUB_DIRS[@]}"; do
            if [[ -d "$tmp_dir/public/$stub_dir" ]]; then
                # Keep only README.md
                find "$tmp_dir/public/$stub_dir" -type f ! -name 'README.md' -delete
                find "$tmp_dir/public/$stub_dir" -type d -empty -delete
            fi
        done

        # Create sync branch and PR
        cd "$tmp_dir/public"
        local sync_branch="${SYNC_BRANCH_PREFIX}/from-private-$(date +%Y%m%d-%H%M%S)"

        git checkout -b "$sync_branch"
        git add -A

        if git diff --cached --quiet; then
            log_info "No changes to sync"
        else
            git commit -m "sync: Update from mono-repo

Automated sync from private mono-repo to public incidentfox repo.

Changes synced at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Source commit: $(cd - > /dev/null && git rev-parse HEAD)"

            git push -u origin "$sync_branch"

            log_success "Changes pushed to branch: $sync_branch"
            log_info "Create a PR at: https://github.com/${PUBLIC_REPO}/compare/main...$sync_branch"
        fi
    fi
}

sync_from_public() {
    local repo_type
    repo_type=$(detect_repo_type)

    if [[ "$repo_type" != "private" ]]; then
        log_error "This command must be run from the mono-repo (private)"
        log_info "Current repo appears to be: $repo_type"
        exit 1
    fi

    log_info "Syncing from incidentfox (public) → mono-repo"

    # Create temp directory for sync
    local tmp_dir
    tmp_dir=$(mktemp -d)
    trap "rm -rf $tmp_dir" EXIT

    log_info "Cloning public repo..."
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] Would clone $PUBLIC_REPO"
    else
        git clone --depth 1 "git@github.com:${PUBLIC_REPO}.git" "$tmp_dir/public"
    fi

    # Files to exclude when syncing FROM public (they don't exist in public)
    local exclude_from_sync=(
        ".git"
        "ai_pipeline"      # Stub only in public
        "sre-agent"        # Stub only in public
        "correlation_service"
        "dependency_service"
        "slack-bot"
        "telemetry_collector"
    )

    # Build rsync command
    local rsync_cmd="rsync -av"
    for pattern in "${exclude_from_sync[@]}"; do
        rsync_cmd="$rsync_cmd --exclude='$pattern'"
    done

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] Would sync files from public repo:"
        eval "$rsync_cmd --dry-run $tmp_dir/public/ ./ 2>/dev/null" || true
    else
        log_info "Syncing files from public..."
        eval "$rsync_cmd $tmp_dir/public/ ./"

        # Check for changes
        if git diff --quiet && git diff --cached --quiet; then
            log_info "No changes from public repo"
        else
            log_success "Changes synced from public repo"
            log_info "Review changes with: git diff"
            log_info "Commit with: git add -A && git commit -m 'sync: Merge changes from public repo'"
        fi
    fi
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            usage
            ;;
        to-public)
            check_prerequisites
            sync_to_public
            exit 0
            ;;
        from-public)
            check_prerequisites
            sync_from_public
            exit 0
            ;;
        *)
            log_error "Unknown argument: $1"
            usage
            ;;
    esac
done

# No direction specified
log_error "No sync direction specified"
usage
