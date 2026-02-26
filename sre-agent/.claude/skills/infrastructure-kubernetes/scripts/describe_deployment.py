#!/usr/bin/env python3
"""Describe a Kubernetes deployment with replica status, conditions, and rollout history.

Shows desired vs ready replicas, deployment conditions, revision history,
and current pod template. Use to diagnose deployment rollout issues,
scaling problems, or failed updates.

Usage:
    python describe_deployment.py <deployment-name> -n <namespace>
    python describe_deployment.py <deployment-name> -n <namespace> --json

Examples:
    python describe_deployment.py payment -n otel-demo
    python describe_deployment.py frontend -n otel-demo --json
"""

import argparse
import json
import sys
from pathlib import Path

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException


def get_k8s_clients():
    """Get Kubernetes API clients."""
    in_cluster = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    kubeconfig = Path.home() / ".kube" / "config"

    if in_cluster.exists():
        k8s_config.load_incluster_config()
    elif kubeconfig.exists():
        k8s_config.load_kube_config()
    else:
        print(
            "Error: Kubernetes not configured. No in-cluster token or ~/.kube/config.",
            file=sys.stderr,
        )
        sys.exit(1)

    return client.AppsV1Api(), client.CoreV1Api()


def main():
    parser = argparse.ArgumentParser(description="Describe Kubernetes deployment")
    parser.add_argument("deployment_name", help="Deployment name")
    parser.add_argument(
        "-n", "--namespace", default="default", help="Kubernetes namespace"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        apps_v1, core_v1 = get_k8s_clients()

        deploy = apps_v1.read_namespaced_deployment(
            name=args.deployment_name, namespace=args.namespace
        )

        # Basic info
        result = {
            "name": deploy.metadata.name,
            "namespace": deploy.metadata.namespace,
            "created": str(deploy.metadata.creation_timestamp),
            "labels": dict(deploy.metadata.labels or {}),
        }

        # Replicas
        spec = deploy.spec
        status = deploy.status
        result["replicas"] = {
            "desired": spec.replicas,
            "ready": status.ready_replicas or 0,
            "available": status.available_replicas or 0,
            "unavailable": status.unavailable_replicas or 0,
            "updated": status.updated_replicas or 0,
        }

        # Strategy
        strategy = spec.strategy
        if strategy:
            result["strategy"] = {"type": strategy.type}
            if strategy.rolling_update:
                result["strategy"]["maxSurge"] = str(
                    strategy.rolling_update.max_surge or ""
                )
                result["strategy"]["maxUnavailable"] = str(
                    strategy.rolling_update.max_unavailable or ""
                )

        # Conditions
        conditions = []
        for c in status.conditions or []:
            conditions.append(
                {
                    "type": c.type,
                    "status": c.status,
                    "reason": c.reason,
                    "message": c.message,
                    "last_transition": str(c.last_transition_time),
                }
            )
        result["conditions"] = conditions

        # Pod template
        template = spec.template.spec
        containers = []
        for c in template.containers:
            container = {
                "name": c.name,
                "image": c.image,
            }
            if c.resources:
                container["resources"] = {
                    "requests": dict(c.resources.requests or {}),
                    "limits": dict(c.resources.limits or {}),
                }
            containers.append(container)
        result["containers"] = containers

        # ReplicaSets (rollout history)
        selector = deploy.spec.selector.match_labels
        label_selector = ",".join(f"{k}={v}" for k, v in selector.items())
        rs_list = apps_v1.list_namespaced_replica_set(
            namespace=args.namespace, label_selector=label_selector
        )

        revisions = []
        for rs in sorted(
            rs_list.items,
            key=lambda r: int(
                r.metadata.annotations.get("deployment.kubernetes.io/revision", "0")
            ),
            reverse=True,
        )[
            :5
        ]:  # Last 5 revisions
            rev = {
                "revision": rs.metadata.annotations.get(
                    "deployment.kubernetes.io/revision", "?"
                ),
                "name": rs.metadata.name,
                "replicas": rs.status.replicas or 0,
                "ready": rs.status.ready_replicas or 0,
                "created": str(rs.metadata.creation_timestamp),
            }
            # Get image from first container
            if rs.spec.template.spec.containers:
                rev["image"] = rs.spec.template.spec.containers[0].image
            revisions.append(rev)
        result["revisions"] = revisions

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Deployment: {result['name']}")
            print(f"Namespace:  {result['namespace']}")
            print(f"Created:    {result['created']}")
            print()

            r = result["replicas"]
            print(
                f"Replicas:   {r['desired']} desired, {r['ready']} ready, "
                f"{r['available']} available, {r['unavailable']} unavailable"
            )
            if result.get("strategy"):
                s = result["strategy"]
                print(
                    f"Strategy:   {s['type']}"
                    + (
                        f" (maxSurge={s.get('maxSurge')}, maxUnavailable={s.get('maxUnavailable')})"
                        if s["type"] == "RollingUpdate"
                        else ""
                    )
                )
            print()

            print("Conditions:")
            for c in result["conditions"]:
                print(f"  {c['type']}: {c['status']} - {c['reason']}: {c['message']}")
            print()

            print("Containers:")
            for c in result["containers"]:
                print(f"  {c['name']}: {c['image']}")
                if c.get("resources"):
                    req = c["resources"].get("requests", {})
                    lim = c["resources"].get("limits", {})
                    if req:
                        print(
                            f"    requests: cpu={req.get('cpu', '-')}, memory={req.get('memory', '-')}"
                        )
                    if lim:
                        print(
                            f"    limits:   cpu={lim.get('cpu', '-')}, memory={lim.get('memory', '-')}"
                        )
            print()

            if revisions:
                print("Rollout History (last 5):")
                for rev in revisions:
                    active = " (active)" if rev["replicas"] > 0 else ""
                    print(
                        f"  Rev {rev['revision']}: {rev['name']} "
                        f"[{rev['ready']}/{rev['replicas']} ready]{active}"
                    )
                    if rev.get("image"):
                        print(f"    image: {rev['image']}")

    except ApiException as e:
        if e.status == 404:
            print(
                f"Deployment '{args.deployment_name}' not found in namespace '{args.namespace}'",
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
