#!/usr/bin/env python3
"""Describe an ECS service with events, task definition, and deployment info.

Usage:
    python describe_ecs_service.py --cluster prod-api --service api-handler
"""

import argparse
import sys

from aws_client import format_output, get_client


def main():
    parser = argparse.ArgumentParser(description="Describe ECS service")
    parser.add_argument("--cluster", required=True, help="ECS cluster name or ARN")
    parser.add_argument("--service", required=True, help="ECS service name or ARN")
    args = parser.parse_args()

    try:
        ecs = get_client("ecs")

        response = ecs.describe_services(
            cluster=args.cluster,
            services=[args.service],
        )

        if not response.get("services"):
            print(
                f"Service {args.service} not found in cluster {args.cluster}",
                file=sys.stderr,
            )
            sys.exit(1)

        svc = response["services"][0]

        # Get task definition details
        task_def = {}
        if svc.get("taskDefinition"):
            td_response = ecs.describe_task_definition(
                taskDefinition=svc["taskDefinition"]
            )
            td = td_response.get("taskDefinition", {})
            task_def = {
                "arn": td.get("taskDefinitionArn", ""),
                "cpu": td.get("cpu", ""),
                "memory": td.get("memory", ""),
                "containers": [
                    {
                        "name": c["name"],
                        "image": c.get("image", ""),
                        "cpu": c.get("cpu", 0),
                        "memory": c.get("memory", 0),
                        "essential": c.get("essential", True),
                    }
                    for c in td.get("containerDefinitions", [])
                ],
            }

        # Get recent events
        events = [
            {
                "timestamp": str(e.get("createdAt", "")),
                "message": e.get("message", ""),
            }
            for e in svc.get("events", [])[:10]
        ]

        # Get deployments
        deployments = [
            {
                "id": d.get("id", ""),
                "status": d.get("status", ""),
                "desired": d.get("desiredCount", 0),
                "running": d.get("runningCount", 0),
                "pending": d.get("pendingCount", 0),
                "task_definition": d.get("taskDefinition", "").split("/")[-1],
                "created": str(d.get("createdAt", "")),
                "updated": str(d.get("updatedAt", "")),
                "rollout_state": d.get("rolloutState", ""),
            }
            for d in svc.get("deployments", [])
        ]

        # List running tasks
        tasks_response = ecs.list_tasks(
            cluster=args.cluster,
            serviceName=args.service,
            desiredStatus="RUNNING",
        )
        running_task_arns = tasks_response.get("taskArns", [])

        result = {
            "name": svc["serviceName"],
            "status": svc["status"],
            "cluster": args.cluster,
            "desired_count": svc.get("desiredCount", 0),
            "running_count": svc.get("runningCount", 0),
            "pending_count": svc.get("pendingCount", 0),
            "launch_type": svc.get("launchType", ""),
            "created": str(svc.get("createdAt", "")),
            "task_definition": task_def,
            "deployments": deployments,
            "running_tasks": len(running_task_arns),
            "recent_events": events,
            "load_balancers": [
                {
                    "target_group_arn": lb.get("targetGroupArn", ""),
                    "container_name": lb.get("containerName", ""),
                    "container_port": lb.get("containerPort", 0),
                }
                for lb in svc.get("loadBalancers", [])
            ],
        }

        print(format_output(result))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
