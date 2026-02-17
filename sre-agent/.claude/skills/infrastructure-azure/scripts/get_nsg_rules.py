#!/usr/bin/env python3
"""Get Azure Network Security Group (NSG) rules."""

import argparse
import sys

from azure_client import format_output, get_credentials, get_subscription_id


def main():
    parser = argparse.ArgumentParser(description="Get NSG rules")
    parser.add_argument("--resource-group", required=True, help="Resource group name")
    parser.add_argument("--nsg-name", required=True, help="NSG name")
    args = parser.parse_args()

    try:
        from azure.mgmt.network import NetworkManagementClient

        credential = get_credentials()
        subscription_id = get_subscription_id()
        network_client = NetworkManagementClient(credential, subscription_id)

        nsg = network_client.network_security_groups.get(
            args.resource_group, args.nsg_name
        )

        rules = []
        if nsg.security_rules:
            for rule in nsg.security_rules:
                rules.append(
                    {
                        "name": rule.name,
                        "priority": rule.priority,
                        "direction": rule.direction,
                        "access": rule.access,
                        "protocol": rule.protocol,
                        "source_address_prefix": rule.source_address_prefix,
                        "source_port_range": rule.source_port_range,
                        "destination_address_prefix": rule.destination_address_prefix,
                        "destination_port_range": rule.destination_port_range,
                        "description": rule.description,
                    }
                )

        print(
            format_output(
                {
                    "subscription_id": subscription_id,
                    "resource_group": args.resource_group,
                    "nsg_name": args.nsg_name,
                    "rule_count": len(rules),
                    "rules": rules,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "nsg_name": args.nsg_name}))
        sys.exit(1)


if __name__ == "__main__":
    main()
