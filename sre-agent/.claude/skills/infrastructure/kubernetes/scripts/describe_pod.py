#!/usr/bin/env python3
"""Get detailed information about a Kubernetes pod.

Usage:
    python describe_pod.py <pod-name> -n <namespace>

Examples:
    python describe_pod.py payment-7f8b9c6d5-x2k4m -n otel-demo
"""

import argparse
import json
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
        print(
            "Error: Kubernetes not configured. Ensure ~/.kube/config exists.",
            file=sys.stderr,
        )
        sys.exit(1)

    return client.CoreV1Api()


def main():
    parser = argparse.ArgumentParser(description="Get detailed pod information")
    parser.add_argument("pod_name", help="Name of the pod")
    parser.add_argument(
        "-n", "--namespace", default="default", help="Kubernetes namespace"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        core_v1 = get_k8s_client()
        pod = core_v1.read_namespaced_pod(name=args.pod_name, namespace=args.namespace)

        containers = []
        for c in pod.spec.containers:
            container_status = next(
                (
                    cs
                    for cs in (pod.status.container_statuses or [])
                    if cs.name == c.name
                ),
                None,
            )

            resources = {}
            if c.resources:
                if c.resources.requests:
                    resources["requests"] = dict(c.resources.requests)
                if c.resources.limits:
                    resources["limits"] = dict(c.resources.limits)

            containers.append(
                {
                    "name": c.name,
                    "image": c.image,
                    "ready": container_status.ready if container_status else False,
                    "restart_count": (
                        container_status.restart_count if container_status else 0
                    ),
                    "resources": resources if resources else None,
                }
            )

        conditions = []
        for cond in pod.status.conditions or []:
            conditions.append(
                {
                    "type": cond.type,
                    "status": cond.status,
                    "reason": cond.reason,
                }
            )

        result = {
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "status": pod.status.phase,
            "node": pod.spec.node_name,
            "containers": containers,
            "conditions": conditions,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Pod: {result['name']}")
            print(f"Namespace: {result['namespace']}")
            print(f"Status: {result['status']}")
            print(f"Node: {result['node']}")
            print()

            print("Containers:")
            for c in containers:
                status_icon = "✅" if c["ready"] else "❌"
                print(f"  {status_icon} {c['name']}")
                print(f"     Image: {c['image']}")
                print(f"     Restarts: {c['restart_count']}")
                if c["resources"]:
                    print(f"     Resources: {c['resources']}")
            print()

            print("Conditions:")
            for cond in conditions:
                status_icon = "✅" if cond["status"] == "True" else "❌"
                print(f"  {status_icon} {cond['type']}: {cond['status']}")
                if cond["reason"]:
                    print(f"     Reason: {cond['reason']}")

    except ApiException as e:
        print(f"Error: Kubernetes API error: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
