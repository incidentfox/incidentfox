#!/usr/bin/env python3
"""Scale a Kubernetes deployment.

Usage:
    python scale_deployment.py <deployment> -n <namespace> --replicas N [--dry-run]

Examples:
    # Dry run
    python scale_deployment.py payment -n otel-demo --replicas 3 --dry-run

    # Execute
    python scale_deployment.py payment -n otel-demo --replicas 3
"""

import argparse
import sys
from pathlib import Path

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException


def get_k8s_client():
    """Get Kubernetes API client."""
    kubeconfig = Path.home() / ".kube" / "config"
    in_cluster = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")

    if kubeconfig.exists():
        k8s_config.load_kube_config()
    elif in_cluster.exists():
        k8s_config.load_incluster_config()
    else:
        print("Error: Kubernetes not configured.", file=sys.stderr)
        sys.exit(1)

    return client.AppsV1Api()


def main():
    parser = argparse.ArgumentParser(description="Scale a Kubernetes deployment")
    parser.add_argument("deployment", help="Deployment name")
    parser.add_argument(
        "-n", "--namespace", default="default", help="Kubernetes namespace"
    )
    parser.add_argument(
        "--replicas", type=int, required=True, help="Target replica count"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without executing",
    )
    args = parser.parse_args()

    if args.replicas < 0:
        print("Error: Replicas must be >= 0", file=sys.stderr)
        sys.exit(1)

    try:
        apps_v1 = get_k8s_client()

        # Get current deployment state
        deployment = apps_v1.read_namespaced_deployment(
            name=args.deployment,
            namespace=args.namespace,
        )

        current_replicas = deployment.spec.replicas
        ready_replicas = deployment.status.ready_replicas or 0

        print(f"Deployment: {args.deployment}")
        print(f"Namespace: {args.namespace}")
        print(f"Current replicas: {current_replicas} ({ready_replicas} ready)")
        print(f"Target replicas: {args.replicas}")
        print()

        if current_replicas == args.replicas:
            print("ℹ️  Deployment is already at the target replica count.")
            sys.exit(0)

        action = "scale up" if args.replicas > current_replicas else "scale down"

        if args.dry_run:
            print("🔍 DRY RUN - No changes will be made")
            print("-" * 40)
            print(f"Would {action} from {current_replicas} to {args.replicas} replicas")

            if args.replicas == 0:
                print("⚠️  WARNING: Scaling to 0 will make the service unavailable!")
            elif args.replicas > 10:
                print(
                    "⚠️  NOTE: Scaling to >10 replicas - ensure cluster has capacity."
                )

            print()
            print("To execute this action, run without --dry-run")
        else:
            if args.replicas == 0:
                print("⚠️  WARNING: Scaling to 0 will make the service unavailable!")

            print(
                f"🔄 Scaling deployment from {current_replicas} to {args.replicas}..."
            )

            # Patch the deployment
            apps_v1.patch_namespaced_deployment_scale(
                name=args.deployment,
                namespace=args.namespace,
                body={"spec": {"replicas": args.replicas}},
            )

            print(f"✅ Deployment scaled to {args.replicas} replicas.")
            print()
            print("Use describe_deployment.py to monitor rollout progress.")

    except ApiException as e:
        if e.status == 404:
            print(
                f"Error: Deployment {args.deployment} not found in namespace {args.namespace}",
                file=sys.stderr,
            )
        else:
            print(f"Error: Kubernetes API error: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
