#!/usr/bin/env python3
"""Rollback a Kubernetes deployment to previous revision.

Usage:
    python rollback_deployment.py <deployment> -n <namespace> [--revision N] [--dry-run]

Examples:
    # Dry run (rollback to previous)
    python rollback_deployment.py payment -n otel-demo --dry-run

    # Execute rollback to previous
    python rollback_deployment.py payment -n otel-demo

    # Rollback to specific revision
    python rollback_deployment.py payment -n otel-demo --revision 2
"""

import argparse
import sys
from pathlib import Path

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException


def get_k8s_clients():
    """Get Kubernetes API clients."""
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
    parser = argparse.ArgumentParser(description="Rollback a Kubernetes deployment")
    parser.add_argument("deployment", help="Deployment name")
    parser.add_argument(
        "-n", "--namespace", default="default", help="Kubernetes namespace"
    )
    parser.add_argument(
        "--revision", type=int, help="Target revision (default: previous)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without executing",
    )
    args = parser.parse_args()

    try:
        apps_v1 = get_k8s_clients()

        # Get current deployment
        deployment = apps_v1.read_namespaced_deployment(
            name=args.deployment,
            namespace=args.namespace,
        )

        current_revision = deployment.metadata.annotations.get(
            "deployment.kubernetes.io/revision", "unknown"
        )

        # Get replica sets to find revisions
        selector = deployment.spec.selector.match_labels
        label_selector = ",".join([f"{k}={v}" for k, v in selector.items()])

        rs_list = apps_v1.list_namespaced_replica_set(
            namespace=args.namespace,
            label_selector=label_selector,
        )

        # Build revision history
        revisions = []
        for rs in rs_list.items:
            rev = rs.metadata.annotations.get("deployment.kubernetes.io/revision", "0")
            revisions.append(
                {
                    "revision": int(rev),
                    "name": rs.metadata.name,
                    "replicas": rs.spec.replicas,
                    "image": (
                        rs.spec.template.spec.containers[0].image
                        if rs.spec.template.spec.containers
                        else "unknown"
                    ),
                }
            )

        revisions.sort(key=lambda x: x["revision"], reverse=True)

        print(f"Deployment: {args.deployment}")
        print(f"Namespace: {args.namespace}")
        print(f"Current revision: {current_revision}")
        print()

        print("Revision history:")
        for rev in revisions[:5]:
            marker = " (current)" if str(rev["revision"]) == current_revision else ""
            print(f"  {rev['revision']}: {rev['image']}{marker}")
        print()

        # Determine target revision
        if args.revision:
            target_revision = args.revision
        else:
            # Find previous revision
            current_rev_int = int(current_revision) if current_revision.isdigit() else 0
            previous_revs = [r for r in revisions if r["revision"] < current_rev_int]
            if not previous_revs:
                print(
                    "Error: No previous revision available for rollback.",
                    file=sys.stderr,
                )
                sys.exit(1)
            target_revision = previous_revs[0]["revision"]

        # Find target revision info
        target_info = next(
            (r for r in revisions if r["revision"] == target_revision), None
        )
        if not target_info:
            print(f"Error: Revision {target_revision} not found.", file=sys.stderr)
            sys.exit(1)

        print(f"Target revision: {target_revision}")
        print(f"Target image: {target_info['image']}")
        print()

        if args.dry_run:
            print("🔍 DRY RUN - No changes will be made")
            print("-" * 40)
            print(
                f"Would rollback from revision {current_revision} to {target_revision}"
            )
            print(f"Image would change to: {target_info['image']}")
            print()
            print("To execute this action, run without --dry-run")
        else:
            print(f"🔄 Rolling back to revision {target_revision}...")

            # Use kubectl-style rollback by patching annotations
            # This triggers a new rollout to the previous revision's spec
            patch = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": str(
                                    target_revision
                                )
                            }
                        }
                    }
                }
            }

            # Actually, the proper way is to use rollout undo via subprocess
            # since the API doesn't have a direct rollback endpoint
            import subprocess

            result = subprocess.run(
                [
                    "kubectl",
                    "rollout",
                    "undo",
                    f"deployment/{args.deployment}",
                    "-n",
                    args.namespace,
                    f"--to-revision={target_revision}",
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                print(f"✅ Rollback initiated to revision {target_revision}")
                print(result.stdout)
                print()
                print("Use describe_deployment.py to monitor rollout progress.")
            else:
                print("Error: Rollback failed", file=sys.stderr)
                print(result.stderr, file=sys.stderr)
                sys.exit(1)

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
