#!/usr/bin/env python3
"""
Run the Vercel error triage demo end-to-end.

Creates a fresh PR on vercel-demo-app with buggy code, waits for
Vercel to deploy the preview, then hits the buggy endpoint to trigger
the error → IncidentFox agent investigates → comments on PR.

Prerequisites:
  - gh CLI authenticated with access to incidentfox/vercel-demo-app
  - VERCEL_TOKEN env var (for polling deployment status)
  - VERCEL_TEAM_ID env var (optional, for team-scoped Vercel projects)

Usage:
  python scripts/run_vercel_demo.py
"""

import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime

REPO = "incidentfox/vercel-demo-app"
VERCEL_PROJECT_ID = "prj_PqAFlHb04G2TmgurLQqMKL7t4fXT"
BUGGY_ENDPOINT = "/api/orders"
BRANCH_PREFIX = "demo/order-tracking"
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

    # Get current page.js SHA for update
    file_sha = run_gh("api", f"repos/{REPO}/contents/app/page.js", "--jq", ".sha")

    # Push an innocuous change (the bug is already on main)
    new_content = f"""\
export default function Home() {{
  return (
    <main style={{{{ padding: '2rem', fontFamily: 'sans-serif' }}}}>
      <h1>Order Service API</h1>
      <p>Endpoints:</p>
      <ul>
        <li><code>GET /api/orders</code> - List all orders</li>
        <li><code>GET /api/orders?status=pending</code> - Filter by status</li>
      </ul>
      <p style={{{{ color: '#666', fontSize: '0.8rem' }}}}>v1.1 — {timestamp}</p>
    </main>
  )
}}
"""
    encoded = base64.b64encode(new_content.encode()).decode()

    run_gh(
        "api",
        f"repos/{REPO}/contents/app/page.js",
        "--method",
        "PUT",
        "-f",
        "message=feat: update order service landing page",
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
        f"feat: Update order service ({timestamp})",
        "--body",
        "Updates the order service landing page.\n\n"
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


def trigger_error(deployment_url: str) -> None:
    """Hit the buggy endpoint to produce a 500 error."""
    import httpx

    url = f"{deployment_url}{BUGGY_ENDPOINT}"
    print(f"  GET {url}")
    resp = httpx.get(url, timeout=10)
    print(f"  Status: {resp.status_code}")

    # Hit it a couple more times to ensure Vercel log drain fires
    for _ in range(2):
        time.sleep(2)
        httpx.get(url, timeout=10)


def main() -> None:
    print("=" * 60)
    print("  INCIDENTFOX — VERCEL ERROR TRIAGE DEMO")
    print("=" * 60)

    print("\n[1/4] Cleaning up old demos...")
    cleanup_old_demos()

    print("\n[2/4] Creating demo PR...")
    branch_name, pr_number, pr_url = create_demo_pr()
    print(f"  PR #{pr_number}: {pr_url}")

    print("\n[3/4] Waiting for Vercel preview deployment...")
    deployment_url = wait_for_deployment(branch_name)
    if not deployment_url:
        print("\n  No deployment URL. You can manually trigger the error:")
        print(f"  curl https://vercel-demo-app-one.vercel.app{BUGGY_ENDPOINT}")
        print(f"\n  PR: {pr_url}")
        return

    print("\n[4/4] Triggering runtime error...")
    trigger_error(deployment_url)

    print("\n" + "=" * 60)
    print("  DEMO STARTED")
    print("=" * 60)
    print(f"\n  PR:      {pr_url}")
    print(f"  Preview: {deployment_url}")
    print("\n  What happens next:")
    print("    1. Vercel log drain sends error to IncidentFox (~30s)")
    print("    2. Agent investigates the code (~60s)")
    print("    3. Agent posts analysis + fix on the PR")
    print("    4. PR shows a failing 'IncidentFox' check")
    print("    5. Reply 'go' to auto-apply the fix")
    print("\n  Watch the PR for the IncidentFox comment!")
    print()


if __name__ == "__main__":
    main()
