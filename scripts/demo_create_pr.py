#!/usr/bin/env python3
"""
Step 1: Create a demo PR (simulates a developer filing a pull request).

Creates a fresh PR on vercel-demo-app that adds a new order (ORD-1005)
with a null customer field. This introduces a bug in /api/orders — when
the endpoint transforms orders, it calls .toUpperCase() on the null
customer, triggering a TypeError at runtime.

Prerequisites:
  - gh CLI authenticated with access to incidentfox/vercel-demo-app
  - VERCEL_TOKEN env var (for polling deployment status)
  - VERCEL_TEAM_ID env var (optional, for team-scoped Vercel projects)

Usage:
  python scripts/demo_create_pr.py
"""

import base64
import json
import os
import subprocess
import time
from datetime import datetime

REPO = "incidentfox/vercel-demo-app"
VERCEL_PROJECT_ID = "prj_PqAFlHb04G2TmgurLQqMKL7t4fXT"
BRANCH_PREFIX = "demo/add-order"
DEPLOY_TIMEOUT = 300  # 5 minutes


def run_gh(*args: str, check: bool = True) -> str:
    """Run a gh CLI command and return stdout."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        print(f"  gh error: {result.stderr.strip()}")
    return result.stdout.strip()


def cleanup_old_demos() -> None:
    """Close old demo PRs and delete stale branches."""
    raw = run_gh(
        "pr",
        "list",
        "--repo",
        REPO,
        "--state",
        "open",
        "--json",
        "number,headRefName",
        check=False,
    )
    if not raw:
        return
    for pr in json.loads(raw):
        if pr["headRefName"].startswith("demo/"):
            run_gh(
                "pr",
                "close",
                str(pr["number"]),
                "--repo",
                REPO,
                "--delete-branch",
                check=False,
            )
            print(f"  Closed PR #{pr['number']} ({pr['headRefName']})")

    # Delete orphan demo branches
    raw = run_gh("api", f"repos/{REPO}/branches", "--jq", ".[].name", check=False)
    for branch in raw.splitlines():
        if branch.startswith("demo/"):
            run_gh(
                "api",
                "-X",
                "DELETE",
                f"repos/{REPO}/git/refs/heads/{branch}",
                check=False,
            )
            print(f"  Deleted branch {branch}")


def create_demo_pr() -> tuple[str, int, str]:
    """Create a fresh demo PR. Returns (branch_name, pr_number, pr_url)."""
    timestamp = datetime.now().strftime("%m%d-%H%M")
    branch_name = f"{BRANCH_PREFIX}-{timestamp}"

    # Get main branch SHA
    main_sha = run_gh("api", f"repos/{REPO}/git/ref/heads/main", "--jq", ".object.sha")

    # Create branch
    run_gh(
        "api",
        f"repos/{REPO}/git/refs",
        "--method",
        "POST",
        "-f",
        f"ref=refs/heads/{branch_name}",
        "-f",
        f"sha={main_sha}",
    )
    print(f"  Branch: {branch_name}")

    # Get current route.js content and SHA
    file_info = json.loads(
        run_gh("api", f"repos/{REPO}/contents/app/api/orders/route.js")
    )
    file_sha = file_info["sha"]
    current_content = base64.b64decode(file_info["content"]).decode()

    # Add ORD-1005 with null customer (this is the bug the agent should find)
    old_entry = "  { id: 'ORD-1004', customer: 'Fresh Foods Co', status: 'pending', total: 430.75, items: 5 },\n]"
    new_entry = (
        "  { id: 'ORD-1004', customer: 'Fresh Foods Co', status: 'pending', total: 430.75, items: 5 },\n"
        "  { id: 'ORD-1005', customer: null, status: 'processing', total: 75.00, items: 2 },\n]"
    )
    new_content = current_content.replace(old_entry, new_entry)
    encoded = base64.b64encode(new_content.encode()).decode()

    run_gh(
        "api",
        f"repos/{REPO}/contents/app/api/orders/route.js",
        "--method",
        "PUT",
        "-f",
        "message=feat: add new order ORD-1005",
        "-f",
        f"content={encoded}",
        "-f",
        f"branch={branch_name}",
        "-f",
        f"sha={file_sha}",
    )

    # Create PR
    pr_url = run_gh(
        "pr",
        "create",
        "--repo",
        REPO,
        "--head",
        branch_name,
        "--title",
        f"feat: Add new order ORD-1005 ({timestamp})",
        "--body",
        "Adds a new order (ORD-1005) to the orders database.\n\n"
        "*Automated demo PR for IncidentFox Vercel error triage.*",
    )

    pr_number = int(pr_url.rstrip("/").split("/")[-1])
    return branch_name, pr_number, pr_url


def wait_for_deployment(branch_name: str) -> str | None:
    """Poll Vercel until preview deployment for the branch is READY."""
    import httpx

    token = os.environ.get("VERCEL_TOKEN", "")
    if not token:
        print("  WARNING: VERCEL_TOKEN not set, skipping deployment wait")
        return None

    team_id = os.environ.get("VERCEL_TEAM_ID", "")
    headers = {"Authorization": f"Bearer {token}"}
    params: dict = {"projectId": VERCEL_PROJECT_ID, "limit": 10}
    if team_id:
        params["teamId"] = team_id

    start = time.time()
    last_state = ""
    while time.time() - start < DEPLOY_TIMEOUT:
        resp = httpx.get(
            "https://api.vercel.com/v6/deployments",
            headers=headers,
            params=params,
            timeout=10,
        )
        for d in resp.json().get("deployments", []):
            meta = d.get("meta", {})
            if meta.get("githubCommitRef") == branch_name:
                state = d.get("state", "")
                if state != last_state:
                    print(f"  Deployment state: {state}")
                    last_state = state
                if state == "READY":
                    url = d.get("url", "")
                    return f"https://{url}"
                if state in ("ERROR", "CANCELED"):
                    print(f"  Deployment failed: {state}")
                    return None
        time.sleep(10)

    print("  Timeout waiting for deployment!")
    return None


def main() -> None:
    print("=" * 60)
    print("  STEP 1: Developer creates a PR")
    print("=" * 60)

    print("\n[1/3] Cleaning up old demos...")
    cleanup_old_demos()

    print("\n[2/3] Creating demo PR...")
    branch_name, pr_number, pr_url = create_demo_pr()
    print(f"  PR #{pr_number}: {pr_url}")

    print("\n[3/3] Waiting for Vercel preview deployment...")
    deployment_url = wait_for_deployment(branch_name)

    print("\n" + "=" * 60)
    print("  PR CREATED")
    print("=" * 60)
    print(f"\n  PR: {pr_url}")
    if deployment_url:
        print(f"  Preview: {deployment_url}")
        print("\n  Next step — trigger the runtime error:")
        print(f"    python scripts/demo_trigger_error.py {deployment_url}")
    else:
        print("\n  Vercel preview not ready yet. Check the PR for the preview URL,")
        print("  then run:")
        print("    python scripts/demo_trigger_error.py <preview-url>")
    print()


if __name__ == "__main__":
    main()
