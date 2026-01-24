#!/usr/bin/env python3
"""
One-time cleanup script to mark stuck agent runs as failed.

Agent runs can get stuck in "running" state forever if the agent process
crashes or the webhook handler doesn't call complete_agent_run() in error cases.
This was fixed in PR #38, but existing stuck runs need to be cleaned up.

Usage:
    # Dry run (preview changes)
    python scripts/cleanup_stuck_agent_runs.py --dry-run

    # Execute cleanup
    python scripts/cleanup_stuck_agent_runs.py

    # Custom timeout threshold (default: 1 hour)
    python scripts/cleanup_stuck_agent_runs.py --timeout-hours 2
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure repo root is on sys.path so `import src.*` works when running as a script.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select, update

from src.core.dotenv import load_dotenv
from src.db.models import AgentRun
from src.db.session import db_session


def cleanup_stuck_runs(timeout_hours: float, dry_run: bool) -> int:
    """
    Mark all agent runs stuck in 'running' state as 'failed'.

    Args:
        timeout_hours: Runs older than this many hours are considered stuck
        dry_run: If True, only preview changes without applying them

    Returns:
        Number of runs that were (or would be) updated
    """
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)

    with db_session() as session:
        # Find all stuck runs
        stuck_runs = session.execute(
            select(AgentRun)
            .where(AgentRun.status == "running")
            .where(AgentRun.started_at < cutoff_time)
            .order_by(AgentRun.started_at.desc())
        ).scalars().all()

        if not stuck_runs:
            print("No stuck agent runs found.")
            return 0

        print(f"Found {len(stuck_runs)} stuck agent runs:\n")

        for run in stuck_runs:
            age = datetime.now(timezone.utc) - run.started_at.replace(tzinfo=timezone.utc)
            age_str = f"{age.total_seconds() / 3600:.1f}h"
            print(f"  - {run.id[:8]}... | {run.agent_name:15} | {run.trigger_source:10} | "
                  f"started {age_str} ago | {run.trigger_message[:50] if run.trigger_message else 'N/A'}...")

        print()

        if dry_run:
            print(f"DRY RUN: Would mark {len(stuck_runs)} runs as 'failed'")
            return len(stuck_runs)

        # Update all stuck runs
        now = datetime.now(timezone.utc)
        run_ids = [run.id for run in stuck_runs]

        session.execute(
            update(AgentRun)
            .where(AgentRun.id.in_(run_ids))
            .values(
                status="failed",
                completed_at=now,
                error_message="Cleanup: Run was stuck in running state (process crash or timeout)",
            )
        )
        session.commit()

        print(f"✓ Marked {len(stuck_runs)} runs as 'failed'")
        return len(stuck_runs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean up agent runs stuck in 'running' state"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    parser.add_argument(
        "--timeout-hours",
        type=float,
        default=1.0,
        help="Consider runs stuck if older than this many hours (default: 1)",
    )
    args = parser.parse_args()

    load_dotenv()

    print(f"Cleaning up agent runs stuck for more than {args.timeout_hours} hour(s)...\n")

    count = cleanup_stuck_runs(
        timeout_hours=args.timeout_hours,
        dry_run=args.dry_run,
    )

    if args.dry_run and count > 0:
        print("\nRun without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
