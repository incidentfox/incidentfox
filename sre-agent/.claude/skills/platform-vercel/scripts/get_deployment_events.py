#!/usr/bin/env python3
"""Get build log events for a Vercel deployment.

Usage:
    python get_deployment_events.py --deployment DEPLOYMENT_ID [--limit 50] [--json]

Examples:
    python get_deployment_events.py --deployment dpl_abc123
    python get_deployment_events.py --deployment dpl_abc123 --limit 100
    python get_deployment_events.py --deployment dpl_abc123 --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vercel_client import get_deployment_events


def _format_event(event: dict) -> str:
    """Format a single deployment event for human-readable output."""
    created = event.get("created", "")
    event_type = event.get("type", "")
    payload = event.get("payload", {})

    # Build log events have text in payload
    text = ""
    if isinstance(payload, dict):
        text = payload.get("text", payload.get("message", ""))
    elif isinstance(payload, str):
        text = payload

    # Format timestamp if it's epoch millis
    ts_str = ""
    if isinstance(created, (int, float)):
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
        ts_str = dt.strftime("%H:%M:%S")
    elif created:
        ts_str = str(created)

    if text:
        return f"[{ts_str}] {text}"
    return f"[{ts_str}] ({event_type})"


def main():
    parser = argparse.ArgumentParser(description="Get Vercel deployment build logs")
    parser.add_argument("--deployment", required=True, help="Deployment ID")
    parser.add_argument(
        "--limit", type=int, default=50, help="Max events to return (default: 50)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        events = get_deployment_events(args.deployment, limit=args.limit)

        if args.json:
            result = {
                "ok": True,
                "deployment_id": args.deployment,
                "events": events,
                "count": len(events),
            }
            print(json.dumps(result, indent=2))
        else:
            print(f"Deployment Events ({args.deployment}): {len(events)} entries\n")
            for event in events:
                print(_format_event(event))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
