#!/usr/bin/env python3
"""Get logs from a Kubernetes pod.

Usage:
    python get_logs.py <pod-name> -n <namespace> [--tail N] [--container NAME]

Examples:
    python get_logs.py payment-7f8b9c6d5-x2k4m -n otel-demo --tail 100
    python get_logs.py payment-7f8b9c6d5-x2k4m -n otel-demo --container payment
"""

import argparse
import json
import sys
from pathlib import Path

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException


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
    parser = argparse.ArgumentParser(description="Get logs from a Kubernetes pod")
    parser.add_argument("pod_name", help="Name of the pod")
    parser.add_argument(
        "-n", "--namespace", default="default", help="Kubernetes namespace"
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=100,
        help="Number of lines to retrieve (default: 100)",
    )
    parser.add_argument("--container", help="Container name (for multi-container pods)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        core_v1 = get_k8s_client()
        logs = core_v1.read_namespaced_pod_log(
            name=args.pod_name,
            namespace=args.namespace,
            container=args.container,
            tail_lines=args.tail,
        )

        if args.json:
            print(
                json.dumps(
                    {
                        "pod": args.pod_name,
                        "namespace": args.namespace,
                        "container": args.container,
                        "lines": args.tail,
                        "logs": logs,
                    },
                    indent=2,
                )
            )
        else:
            print(f"Pod: {args.pod_name}")
            print(f"Namespace: {args.namespace}")
            if args.container:
                print(f"Container: {args.container}")
            print(f"Tail: {args.tail} lines")
            print("-" * 60)
            print(logs)

    except ApiException as e:
        print(f"Error: Kubernetes API error: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
