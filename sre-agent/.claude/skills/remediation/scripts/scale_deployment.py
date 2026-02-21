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
import re
import sys
from pathlib import Path

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException

_RFC1123_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")
_MAX_REPLICAS = 50


def _validate_k8s_name(value: str, label: str) -> str:
    """Validate a Kubernetes resource name against RFC 1123."""
    if not _RFC1123_RE.match(value):
        raise ValueError(
            f"Invalid {label} name '{value}': must be lowercase alphanumeric/hyphens, 1-63 chars"
        )
    return value


def get_k8s_client():
    """Get Kubernetes API client.

    Prefers in-cluster service account auth (correct RBAC identity)
    over kubeconfig (which may resolve to the EC2 node IAM identity).
    """
    in_cluster = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    kubeconfig = Path.home() / ".kube" / "config"

    if in_cluster.exists():
        k8s_config.load_incluster_config()
        print("[k8s-auth] Using in-cluster service account", file=sys.stderr)
    elif kubeconfig.exists():
        k8s_config.load_kube_config()
        print("[k8s-auth] Using kubeconfig (fallback)", file=sys.stderr)
    else:
        print(
            "Error: Kubernetes not configured. No in-cluster token or ~/.kube/config.",
            file=sys.stderr,
        )
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
    parser.add_argument(
        "--confirm-zero",
        action="store_true",
        help="Required flag when scaling to 0 replicas",
    )
    args = parser.parse_args()

    if args.replicas < 0:
        print("Error: Replicas must be >= 0", file=sys.stderr)
        sys.exit(1)
    if args.replicas > _MAX_REPLICAS:
        print(
            f"Error: Replicas must be <= {_MAX_REPLICAS} to prevent resource exhaustion.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        _validate_k8s_name(args.deployment, "deployment")
        _validate_k8s_name(args.namespace, "namespace")
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
            if args.replicas == 0 and not args.confirm_zero:
                print(
                    "Error: Scaling to 0 replicas requires --confirm-zero flag.",
                    file=sys.stderr,
                )
                sys.exit(1)
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
