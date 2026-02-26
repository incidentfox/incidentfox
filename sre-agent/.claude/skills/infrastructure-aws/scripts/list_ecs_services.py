#!/usr/bin/env python3
"""List ECS services in a cluster with task counts.

Usage:
    python list_ecs_services.py --cluster prod-api
    python list_ecs_services.py --cluster prod-api --json
"""

import argparse
import sys

from aws_client import format_output, get_client


def main():
    parser = argparse.ArgumentParser(description="List ECS services")
    parser.add_argument("--cluster", required=True, help="ECS cluster name or ARN")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        ecs = get_client("ecs")

        # List service ARNs
        service_arns = []
        paginator = ecs.get_paginator("list_services")
        for page in paginator.paginate(cluster=args.cluster):
            service_arns.extend(page.get("serviceArns", []))

        if not service_arns:
            print(f"No services found in cluster {args.cluster}")
            return

        # Describe services (max 10 per call)
        services = []
        for i in range(0, len(service_arns), 10):
            batch = service_arns[i : i + 10]
            response = ecs.describe_services(cluster=args.cluster, services=batch)
            for svc in response.get("services", []):
                services.append(
                    {
                        "name": svc["serviceName"],
                        "status": svc["status"],
                        "desired": svc.get("desiredCount", 0),
                        "running": svc.get("runningCount", 0),
                        "pending": svc.get("pendingCount", 0),
                        "launch_type": svc.get("launchType", ""),
                        "task_definition": svc.get("taskDefinition", "").split("/")[-1],
                        "created": str(svc.get("createdAt", "")),
                    }
                )

        if args.json:
            print(
                format_output(
                    {
                        "cluster": args.cluster,
                        "count": len(services),
                        "services": services,
                    }
                )
            )
        else:
            print(f"Cluster: {args.cluster}")
            print(f"Services: {len(services)}")
            print()
            print(
                f"{'NAME':<30} {'STATUS':<10} {'DESIRED':>8} {'RUNNING':>8} {'PENDING':>8} {'LAUNCH TYPE':<12} {'TASK DEF':<30}"
            )
            print("-" * 106)
            for svc in services:
                print(
                    f"{svc['name']:<30} {svc['status']:<10} {svc['desired']:>8} "
                    f"{svc['running']:>8} {svc['pending']:>8} {svc['launch_type']:<12} "
                    f"{svc['task_definition']:<30}"
                )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
