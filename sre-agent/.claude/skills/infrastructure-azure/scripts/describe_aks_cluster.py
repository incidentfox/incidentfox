#!/usr/bin/env python3
"""Get details about an AKS cluster."""

import argparse
import sys

from azure_client import format_output, get_credentials, get_subscription_id


def main():
    parser = argparse.ArgumentParser(description="Describe AKS cluster")
    parser.add_argument("--resource-group", required=True, help="Resource group name")
    parser.add_argument("--cluster-name", required=True, help="AKS cluster name")
    args = parser.parse_args()

    try:
        from azure.mgmt.containerservice import ContainerServiceClient

        credential = get_credentials()
        subscription_id = get_subscription_id()
        aks_client = ContainerServiceClient(credential, subscription_id)

        cluster = aks_client.managed_clusters.get(
            args.resource_group, args.cluster_name
        )

        agent_pools = []
        if cluster.agent_pool_profiles:
            for pool in cluster.agent_pool_profiles:
                agent_pools.append(
                    {
                        "name": pool.name,
                        "count": pool.count,
                        "vm_size": pool.vm_size,
                        "os_type": pool.os_type.value if pool.os_type else None,
                        "mode": pool.mode.value if pool.mode else None,
                    }
                )

        result = {
            "name": cluster.name,
            "id": cluster.id,
            "location": cluster.location,
            "kubernetes_version": cluster.kubernetes_version,
            "provisioning_state": cluster.provisioning_state,
            "fqdn": cluster.fqdn,
            "node_resource_group": cluster.node_resource_group,
            "agent_pools": agent_pools,
            "tags": cluster.tags or {},
        }

        print(format_output(result))

    except Exception as e:
        print(format_output({"error": str(e), "cluster_name": args.cluster_name}))
        sys.exit(1)


if __name__ == "__main__":
    main()
