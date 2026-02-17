#!/usr/bin/env python3
"""List Azure Virtual Machines."""

import argparse
import sys

from azure_client import format_output, get_credentials, get_subscription_id


def main():
    parser = argparse.ArgumentParser(description="List Azure VMs")
    parser.add_argument("--resource-group", help="Resource group name (default: all)")
    args = parser.parse_args()

    try:
        from azure.mgmt.compute import ComputeManagementClient

        credential = get_credentials()
        subscription_id = get_subscription_id()
        compute_client = ComputeManagementClient(credential, subscription_id)

        if args.resource_group:
            vms = compute_client.virtual_machines.list(args.resource_group)
        else:
            vms = compute_client.virtual_machines.list_all()

        vm_list = []
        for vm in vms:
            vm_list.append(
                {
                    "name": vm.name,
                    "id": vm.id,
                    "location": vm.location,
                    "vm_size": vm.hardware_profile.vm_size,
                    "provisioning_state": vm.provisioning_state,
                    "tags": vm.tags or {},
                }
            )

        print(
            format_output(
                {
                    "subscription_id": subscription_id,
                    "resource_group": args.resource_group,
                    "vm_count": len(vm_list),
                    "vms": vm_list,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
