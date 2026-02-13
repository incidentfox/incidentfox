#!/usr/bin/env python3
"""Get resource allocation and usage for a Kubernetes pod.

Shows configured requests/limits alongside actual runtime usage.
Requires metrics-server in the cluster for usage data.

Usage:
    python get_resources.py <pod-name> -n <namespace>

Examples:
    python get_resources.py payment-7f8b9c6d5-x2k4m -n otel-demo
"""

import argparse
import json
import sys
from pathlib import Path

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException


def get_k8s_clients():
    """Get Kubernetes API clients.

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

    return client.CoreV1Api(), client.CustomObjectsApi()


def main():
    parser = argparse.ArgumentParser(
        description="Get pod resource allocation and usage"
    )
    parser.add_argument("pod_name", help="Name of the pod")
    parser.add_argument(
        "-n", "--namespace", default="default", help="Kubernetes namespace"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        core_v1, custom_api = get_k8s_clients()
        pod = core_v1.read_namespaced_pod(name=args.pod_name, namespace=args.namespace)

        containers_data = []
        for c in pod.spec.containers:
            container_info = {
                "name": c.name,
                "requests": {},
                "limits": {},
                "usage": None,
            }

            if c.resources:
                if c.resources.requests:
                    container_info["requests"] = dict(c.resources.requests)
                if c.resources.limits:
                    container_info["limits"] = dict(c.resources.limits)

            containers_data.append(container_info)

        # Try to get actual usage from metrics-server
        metrics_available = False
        try:
            metrics = custom_api.get_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=args.namespace,
                plural="pods",
                name=args.pod_name,
            )

            for container_metrics in metrics.get("containers", []):
                name = container_metrics["name"]
                for container in containers_data:
                    if container["name"] == name:
                        container["usage"] = {
                            "cpu": container_metrics["usage"]["cpu"],
                            "memory": container_metrics["usage"]["memory"],
                        }
                        metrics_available = True
        except Exception:
            pass  # Metrics not available

        result = {
            "pod": args.pod_name,
            "namespace": args.namespace,
            "node": pod.spec.node_name,
            "status": pod.status.phase,
            "metrics_available": metrics_available,
            "containers": containers_data,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Pod: {result['pod']}")
            print(f"Namespace: {result['namespace']}")
            print(f"Node: {result['node']}")
            print(f"Status: {result['status']}")
            print(
                f"Metrics available: {'Yes' if metrics_available else 'No (metrics-server not installed)'}"
            )
            print()

            for c in containers_data:
                print(f"Container: {c['name']}")
                print(
                    f"  Requests: cpu={c['requests'].get('cpu', 'none')}, memory={c['requests'].get('memory', 'none')}"
                )
                print(
                    f"  Limits:   cpu={c['limits'].get('cpu', 'none')}, memory={c['limits'].get('memory', 'none')}"
                )
                if c["usage"]:
                    print(
                        f"  Usage:    cpu={c['usage']['cpu']}, memory={c['usage']['memory']}"
                    )
                print()

    except ApiException as e:
        print(f"Error: Kubernetes API error: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
