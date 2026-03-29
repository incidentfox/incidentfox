#!/usr/bin/env python3
"""
Step 2: Trigger a runtime error (simulates a user hitting a buggy endpoint).

Hits the /api/orders endpoint on the Vercel preview deployment, which
triggers a 500 error. Vercel's log drain sends the error to IncidentFox,
which triggers the agent to investigate and comment on the PR.

Usage:
  python scripts/demo_trigger_error.py <preview-url>

  # Or use the production URL if no preview is available:
  python scripts/demo_trigger_error.py https://vercel-demo-app.vercel.app
"""

import sys
import time

BUGGY_ENDPOINT = "/api/orders"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/demo_trigger_error.py <preview-url>")
        print(
            "Example: python scripts/demo_trigger_error.py https://vercel-demo-xxx.vercel.app"
        )
        sys.exit(1)

    import httpx

    deployment_url = sys.argv[1].rstrip("/")

    print("=" * 60)
    print("  STEP 2: Runtime error occurs")
    print("=" * 60)

    url = f"{deployment_url}{BUGGY_ENDPOINT}"
    print(f"\n  GET {url}")
    resp = httpx.get(url, timeout=10)
    print(f"  Status: {resp.status_code}")

    # Hit it a couple more times to ensure Vercel log drain fires
    for i in range(2):
        time.sleep(2)
        resp = httpx.get(url, timeout=10)
        print(f"  Status: {resp.status_code}")

    print("\n" + "=" * 60)
    print("  ERROR TRIGGERED")
    print("=" * 60)
    print("\n  What happens next:")
    print("    1. Vercel log drain sends error to IncidentFox (~30s)")
    print("    2. IncidentFox agent investigates the code (~60s)")
    print("    3. Agent posts analysis + proposed fix on the PR")
    print("    4. PR shows a failing 'IncidentFox / Vercel Triage' check")
    print("    5. Reply 'go' on the PR comment to auto-apply the fix")
    print()


if __name__ == "__main__":
    main()
