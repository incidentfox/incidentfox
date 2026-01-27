"""
CLI entry point for AI Learning Pipeline.

Usage:
    python -m ai_learning_pipeline run-scheduled --team-id TEAM --org-id ORG
    python -m ai_learning_pipeline run-ingestion --team-id TEAM --org-id ORG
    python -m ai_learning_pipeline run-teaching --team-id TEAM --org-id ORG
    python -m ai_learning_pipeline run-maintenance --team-id TEAM --org-id ORG
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime


def _log(event: str, **fields) -> None:
    """Structured logging."""
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-learning-pipeline",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


async def run_scheduled(org_id: str, team_node_id: str) -> int:
    """Run all scheduled pipeline tasks."""
    from .pipeline import SelfLearningPipeline

    _log("pipeline_started", org_id=org_id, team_node_id=team_node_id, mode="scheduled")

    try:
        pipeline = SelfLearningPipeline(org_id=org_id, team_node_id=team_node_id)
        await pipeline.initialize()

        # Run all tasks based on config
        result = await pipeline.run_scheduled_tasks()

        _log(
            "pipeline_completed",
            org_id=org_id,
            team_node_id=team_node_id,
            ingestion_docs=result.get("ingestion", {}).get("documents_processed", 0),
            teachings_processed=result.get("teaching", {}).get("processed", 0),
            maintenance_tasks=result.get("maintenance", {}).get("tasks_completed", 0),
        )

        return 0

    except Exception as e:
        _log(
            "pipeline_failed",
            org_id=org_id,
            team_node_id=team_node_id,
            error=str(e),
        )
        return 1


async def run_ingestion(org_id: str, team_node_id: str) -> int:
    """Run only knowledge ingestion."""
    from .tasks.ingestion import KnowledgeIngestionTask

    _log("ingestion_started", org_id=org_id, team_node_id=team_node_id)

    try:
        task = KnowledgeIngestionTask(org_id=org_id, team_node_id=team_node_id)
        await task.initialize()
        result = await task.run()

        _log(
            "ingestion_completed",
            org_id=org_id,
            team_node_id=team_node_id,
            documents_processed=result.get("documents_processed", 0),
            chunks_created=result.get("chunks_created", 0),
        )

        return 0

    except Exception as e:
        _log("ingestion_failed", org_id=org_id, team_node_id=team_node_id, error=str(e))
        return 1


async def run_teaching(org_id: str, team_node_id: str) -> int:
    """Run only teaching processing."""
    from .tasks.teaching import TeachingProcessorTask

    _log("teaching_started", org_id=org_id, team_node_id=team_node_id)

    try:
        task = TeachingProcessorTask(org_id=org_id, team_node_id=team_node_id)
        await task.initialize()
        result = await task.run()

        _log(
            "teaching_completed",
            org_id=org_id,
            team_node_id=team_node_id,
            processed=result.get("processed", 0),
            applied=result.get("applied", 0),
        )

        return 0

    except Exception as e:
        _log("teaching_failed", org_id=org_id, team_node_id=team_node_id, error=str(e))
        return 1


async def run_maintenance(org_id: str, team_node_id: str) -> int:
    """Run only maintenance tasks."""
    from .tasks.maintenance import MaintenanceTask

    _log("maintenance_started", org_id=org_id, team_node_id=team_node_id)

    try:
        task = MaintenanceTask(org_id=org_id, team_node_id=team_node_id)
        await task.initialize()
        result = await task.run()

        _log(
            "maintenance_completed",
            org_id=org_id,
            team_node_id=team_node_id,
            stale_detected=result.get("stale_detected", 0),
            gaps_detected=result.get("gaps_detected", 0),
        )

        return 0

    except Exception as e:
        _log(
            "maintenance_failed", org_id=org_id, team_node_id=team_node_id, error=str(e)
        )
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="AI Learning Pipeline - Self-Learning System"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Common arguments
    def add_common_args(p):
        p.add_argument("--org-id", required=True, help="Organization ID")
        p.add_argument("--team-id", required=True, help="Team node ID")

    # run-scheduled command
    scheduled_parser = subparsers.add_parser(
        "run-scheduled", help="Run all scheduled tasks"
    )
    add_common_args(scheduled_parser)

    # run-ingestion command
    ingestion_parser = subparsers.add_parser(
        "run-ingestion", help="Run knowledge ingestion only"
    )
    add_common_args(ingestion_parser)

    # run-teaching command
    teaching_parser = subparsers.add_parser(
        "run-teaching", help="Run teaching processing only"
    )
    add_common_args(teaching_parser)

    # run-maintenance command
    maintenance_parser = subparsers.add_parser(
        "run-maintenance", help="Run maintenance tasks only"
    )
    add_common_args(maintenance_parser)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    org_id = args.org_id or os.getenv("ORG_ID")
    team_node_id = args.team_id or os.getenv("TEAM_NODE_ID")

    if not org_id or not team_node_id:
        print("Error: --org-id and --team-id are required")
        sys.exit(1)

    # Run the appropriate command
    if args.command == "run-scheduled":
        exit_code = asyncio.run(run_scheduled(org_id, team_node_id))
    elif args.command == "run-ingestion":
        exit_code = asyncio.run(run_ingestion(org_id, team_node_id))
    elif args.command == "run-teaching":
        exit_code = asyncio.run(run_teaching(org_id, team_node_id))
    elif args.command == "run-maintenance":
        exit_code = asyncio.run(run_maintenance(org_id, team_node_id))
    else:
        parser.print_help()
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
