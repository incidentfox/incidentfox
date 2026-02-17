#!/usr/bin/env python3
"""Get details about an Azure Virtual Machine."""

import argparse
import sys

from azure_client import format_output, get_credentials, get_subscription_id


def main():
    parser = argparse.ArgumentParser(description="Describe Azure VM")
    parser.add_argument("--resource-group", required=True, help="Resource group name")
    parser.add_argument("--vm-name", required=True, help="VM name")
    args = parser.parse_args()

    try:
        from azure.mgmt.compute import ComputeManagementClient

        credential = get_credentials()
        subscription_id = get_subscription_id()
        compute_client = ComputeManagementClient(credential, subscription_id)

        vm = compute_client.virtual_machines.get(
            args.resource_group, args.vm_name, expand="instanceView"
        )

        statuses = []
        if vm.instance_view and vm.instance_view.statuses:
            statuses = [
                {"code": s.code, "level": s.level.value, "message": s.message}
                for s in vm.instance_view.statuses
            ]

        result = {
            "name": vm.name,
            "id": vm.id,
            "location": vm.location,
            "vm_size": vm.hardware_profile.vm_size,
            "os_type": (
                vm.storage_profile.os_disk.os_type.value
                if vm.storage_profile.os_disk.os_type
                else None
            ),
            "provisioning_state": vm.provisioning_state,
            "statuses": statuses,
            "tags": vm.tags or {},
            "zones": vm.zones,
            "network_interfaces": (
                [ni.id for ni in vm.network_profile.network_interfaces]
                if vm.network_profile
                else []
            ),
        }

        print(format_output(result))

    except Exception as e:
        print(format_output({"error": str(e), "vm_name": args.vm_name}))
        sys.exit(1)


if __name__ == "__main__":
    main()
