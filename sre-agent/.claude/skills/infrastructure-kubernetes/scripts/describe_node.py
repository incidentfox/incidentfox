#!/usr/bin/env python3
"""Describe a Kubernetes node with status, conditions, capacity, and resource usage.

Shows node health, allocatable resources, running pods count, and actual
CPU/memory usage from metrics-server. Use to diagnose node-level issues
like FailedScheduling, high CPU, memory pressure, or NotReady nodes.

Usage:
    python describe_node.py <node-name>
    python describe_node.py --all
    python describe_node.py --all --json

Examples:
    python describe_node.py ip-10-0-1-42.ec2.internal
    python describe_node.py --all
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

    return client.CoreV1Api(), client.CustomObjectsApi()


def parse_cpu(cpu_str):
    """Parse CPU string to millicores."""
    if not cpu_str:
        return 0
    if cpu_str.endswith("n"):
        return int(cpu_str[:-1]) / 1_000_000
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1])
    return int(float(cpu_str) * 1000)


def parse_memory(mem_str):
    """Parse memory string to MiB."""
    if not mem_str:
        return 0
    units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024}
    for suffix, multiplier in units.items():
        if mem_str.endswith(suffix):
            return int(float(mem_str[: -len(suffix)]) * multiplier)
    return int(mem_str) / (1024 * 1024)


def describe_node(core_v1, custom_api, node_name):
    """Get detailed info for a single node."""
    node = core_v1.read_node(name=node_name)

    # Basic info
    labels = node.metadata.labels or {}
    info = {
        "name": node.metadata.name,
        "labels": {
            k: v
            for k, v in labels.items()
            if k
            in (
                "node.kubernetes.io/instance-type",
                "topology.kubernetes.io/zone",
                "kubernetes.io/arch",
                "kubernetes.io/os",
            )
        },
        "creation": str(node.metadata.creation_timestamp),
    }

    # Node info
    node_info = node.status.node_info
    if node_info:
        info["runtime"] = {
            "kubelet": node_info.kubelet_version,
            "container_runtime": node_info.container_runtime_version,
            "os_image": node_info.os_image,
            "kernel": node_info.kernel_version,
        }

    # Conditions
    conditions = []
    for c in node.status.conditions or []:
        conditions.append(
            {
                "type": c.type,
                "status": c.status,
                "reason": c.reason,
                "message": c.message,
                "last_transition": str(c.last_transition_time),
            }
        )
    info["conditions"] = conditions

    # Capacity and allocatable
    capacity = node.status.capacity or {}
    allocatable = node.status.allocatable or {}
    info["capacity"] = {
        "cpu": capacity.get("cpu", ""),
        "memory": capacity.get("memory", ""),
        "pods": capacity.get("pods", ""),
    }
    info["allocatable"] = {
        "cpu": allocatable.get("cpu", ""),
        "memory": allocatable.get("memory", ""),
        "pods": allocatable.get("pods", ""),
    }

    # Taints
    taints = []
    for t in node.spec.taints or []:
        taints.append({"key": t.key, "value": t.value or "", "effect": t.effect})
    info["taints"] = taints

    # Pod count on this node
    pods = core_v1.list_pod_for_all_namespaces(
        field_selector=f"spec.nodeName={node_name},status.phase!=Succeeded,status.phase!=Failed"
    )
    info["running_pods"] = len(pods.items)

    # Metrics from metrics-server
    info["usage"] = None
    try:
        metrics = custom_api.get_cluster_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            plural="nodes",
            name=node_name,
        )
        cpu_usage = parse_cpu(metrics.get("usage", {}).get("cpu", "0"))
        mem_usage = parse_memory(metrics.get("usage", {}).get("memory", "0"))
        cpu_capacity = parse_cpu(allocatable.get("cpu", "0"))
        mem_capacity = parse_memory(allocatable.get("memory", "0"))

        info["usage"] = {
            "cpu": metrics["usage"]["cpu"],
            "cpu_millicores": int(cpu_usage),
            "cpu_percent": (
                round(cpu_usage / cpu_capacity * 100, 1) if cpu_capacity else 0
            ),
            "memory": metrics["usage"]["memory"],
            "memory_mib": int(mem_usage),
            "memory_percent": (
                round(mem_usage / mem_capacity * 100, 1) if mem_capacity else 0
            ),
        }
    except Exception:
        pass

    return info


def main():
    parser = argparse.ArgumentParser(description="Describe Kubernetes node(s)")
    parser.add_argument("node_name", nargs="?", help="Node name")
    parser.add_argument("--all", action="store_true", help="Describe all nodes")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if not args.node_name and not args.all:
        parser.error("Specify a node name or --all")

    try:
        core_v1, custom_api = get_k8s_clients()

        if args.all:
            nodes = core_v1.list_node()
            results = []
            for node in nodes.items:
                results.append(describe_node(core_v1, custom_api, node.metadata.name))
        else:
            results = [describe_node(core_v1, custom_api, args.node_name)]

        if args.json:
            print(json.dumps(results if args.all else results[0], indent=2))
        else:
            for info in results:
                print(f"Node: {info['name']}")
                if info.get("labels"):
                    for k, v in info["labels"].items():
                        short_key = k.split("/")[-1]
                        print(f"  {short_key}: {v}")
                print()

                # Conditions
                print("Conditions:")
                for c in info["conditions"]:
                    status_icon = (
                        "OK"
                        if (c["type"] == "Ready" and c["status"] == "True")
                        or (c["type"] != "Ready" and c["status"] == "False")
                        else "PROBLEM"
                    )
                    print(
                        f"  {c['type']}: {c['status']} [{status_icon}] - {c['reason']}"
                    )
                print()

                # Resources
                print(
                    f"Capacity:    cpu={info['capacity']['cpu']}, memory={info['capacity']['memory']}, pods={info['capacity']['pods']}"
                )
                print(
                    f"Allocatable: cpu={info['allocatable']['cpu']}, memory={info['allocatable']['memory']}, pods={info['allocatable']['pods']}"
                )
                print(f"Running pods: {info['running_pods']}")
                print()

                if info["usage"]:
                    print(
                        f"Usage:       cpu={info['usage']['cpu_millicores']}m ({info['usage']['cpu_percent']}%), "
                        f"memory={info['usage']['memory_mib']}Mi ({info['usage']['memory_percent']}%)"
                    )
                else:
                    print("Usage:       metrics-server not available")
                print()

                if info["taints"]:
                    print("Taints:")
                    for t in info["taints"]:
                        print(f"  {t['key']}={t['value']}:{t['effect']}")
                    print()

                print("-" * 60)

    except ApiException as e:
        print(f"Error: Kubernetes API error: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
