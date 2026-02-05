#!/usr/bin/env python3
"""Get events related to a Kubernetes pod.

ALWAYS check events BEFORE logs - events explain most issues faster.
Common events: OOMKilled, ImagePullBackOff, FailedScheduling, CrashLoopBackOff

Usage:
    python get_events.py <pod-name> -n <namespace>

Examples:
    python get_events.py payment-7f8b9c6d5-x2k4m -n otel-demo
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
    parser = argparse.ArgumentParser(description="Get events for a Kubernetes pod")
    parser.add_argument("pod_name", help="Name of the pod")
    parser.add_argument(
        "-n", "--namespace", default="default", help="Kubernetes namespace"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        core_v1 = get_k8s_client()
        events = core_v1.list_namespaced_event(
            namespace=args.namespace,
            field_selector=f"involvedObject.name={args.pod_name}",
        )

        event_list = []
        for event in events.items:
            event_list.append(
                {
                    "type": event.type,
                    "reason": event.reason,
                    "message": event.message,
                    "count": event.count,
                    "first_timestamp": str(event.first_timestamp),
                    "last_timestamp": str(event.last_timestamp),
                }
            )

        # Sort by last timestamp (most recent first)
        event_list.sort(key=lambda x: x["last_timestamp"] or "", reverse=True)

        if args.json:
            print(
                json.dumps(
                    {
                        "pod": args.pod_name,
                        "namespace": args.namespace,
                        "event_count": len(event_list),
                        "events": event_list,
                    },
                    indent=2,
                )
            )
        else:
            print(f"Pod: {args.pod_name}")
            print(f"Namespace: {args.namespace}")
            print(f"Event count: {len(event_list)}")
            print()

            if not event_list:
                print("No events found for this pod.")
            else:
                for event in event_list:
                    event_type = "⚠️" if event["type"] == "Warning" else "ℹ️"
                    print(
                        f"{event_type} [{event['last_timestamp']}] {event['reason']}: {event['message']}"
                    )
                    if event["count"] and event["count"] > 1:
                        print(f"   (occurred {event['count']} times)")
                    print()

    except ApiException as e:
        print(f"Error: Kubernetes API error: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
