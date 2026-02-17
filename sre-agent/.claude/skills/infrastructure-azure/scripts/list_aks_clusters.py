#!/usr/bin/env python3
"""List Azure Kubernetes Service (AKS) clusters."""

import argparse
import sys

from azure_client import format_output, get_credentials, get_subscription_id


def main():
    parser = argparse.ArgumentParser(description="List AKS clusters")
    parser.add_argument("--resource-group", help="Resource group name (default: all)")
    args = parser.parse_args()

    try:
        from azure.mgmt.containerservice import ContainerServiceClient

        credential = get_credentials()
        subscription_id = get_subscription_id()
        aks_client = ContainerServiceClient(credential, subscription_id)

        if args.resource_group:
            clusters = aks_client.managed_clusters.list_by_resource_group(
                args.resource_group
            )
        else:
            clusters = aks_client.managed_clusters.list()

        cluster_list = []
        for cluster in clusters:
            cluster_list.append(
                {
                    "name": cluster.name,
                    "id": cluster.id,
                    "location": cluster.location,
                    "kubernetes_version": cluster.kubernetes_version,
                    "provisioning_state": cluster.provisioning_state,
                    "fqdn": cluster.fqdn,
                    "tags": cluster.tags or {},
                }
            )

        print(
            format_output(
                {
                    "subscription_id": subscription_id,
                    "resource_group": args.resource_group,
                    "cluster_count": len(cluster_list),
                    "clusters": cluster_list,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
