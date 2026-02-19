#!/usr/bin/env python3
"""Restart a Kubernetes pod by deleting it (deployment will recreate).

Usage:
    python restart_pod.py <pod-name> -n <namespace> [--dry-run]

Examples:
    # Dry run
    python restart_pod.py payment-7f8b9c6d5-x2k4m -n otel-demo --dry-run

    # Execute
    python restart_pod.py payment-7f8b9c6d5-x2k4m -n otel-demo
"""

import argparse
import re
import sys
from pathlib import Path

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException

_RFC1123_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")


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

    return client.CoreV1Api()


def main():
    parser = argparse.ArgumentParser(description="Restart a Kubernetes pod")
    parser.add_argument("pod_name", help="Name of the pod to restart")
    parser.add_argument(
        "-n", "--namespace", default="default", help="Kubernetes namespace"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without executing",
    )
    args = parser.parse_args()

    try:
        _validate_k8s_name(args.pod_name, "pod")
        _validate_k8s_name(args.namespace, "namespace")
        core_v1 = get_k8s_client()

        # First, verify the pod exists
        pod = core_v1.read_namespaced_pod(name=args.pod_name, namespace=args.namespace)

        # Get owner reference to check if managed by deployment
        owner_refs = pod.metadata.owner_references or []
        managed_by = None
        for ref in owner_refs:
            if ref.kind in ("ReplicaSet", "DaemonSet", "StatefulSet"):
                managed_by = f"{ref.kind}/{ref.name}"
                break

        print(f"Pod: {args.pod_name}")
        print(f"Namespace: {args.namespace}")
        print(f"Status: {pod.status.phase}")
        print(f"Managed by: {managed_by or 'None (standalone pod)'}")
        print()

        if args.dry_run:
            print("🔍 DRY RUN - No changes will be made")
            print("-" * 40)
            print(f"Would delete pod: {args.pod_name}")
            if managed_by:
                print(
                    f"The {managed_by.split('/')[0]} will create a new pod automatically."
                )
            else:
                print(
                    "⚠️  WARNING: This is a standalone pod - it will NOT be recreated!"
                )
            print()
            print("To execute this action, run without --dry-run")
        else:
            if not managed_by:
                print(
                    "⚠️  WARNING: This is a standalone pod - it will NOT be recreated!"
                )
                print("Are you sure you want to delete it?")
                # In non-interactive mode, we should not proceed with standalone pods
                print(
                    "Aborting: Standalone pod deletion requires explicit confirmation."
                )
                sys.exit(1)

            print("🔄 Deleting pod...")
            core_v1.delete_namespaced_pod(
                name=args.pod_name,
                namespace=args.namespace,
            )
            print(f"✅ Pod {args.pod_name} deleted successfully.")
            print(f"   A new pod will be created by {managed_by}.")
            print()
            print("Use list_pods.py to verify the new pod is running.")

    except ApiException as e:
        if e.status == 404:
            print(
                f"Error: Pod {args.pod_name} not found in namespace {args.namespace}",
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
