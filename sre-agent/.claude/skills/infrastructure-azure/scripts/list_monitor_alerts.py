#!/usr/bin/env python3
"""List Azure Monitor alert rules."""

import argparse
import sys

from azure_client import format_output, get_credentials, get_subscription_id


def main():
    parser = argparse.ArgumentParser(description="List Azure Monitor alerts")
    parser.add_argument("--resource-group", help="Resource group name (default: all)")
    args = parser.parse_args()

    try:
        from azure.mgmt.monitor import MonitorManagementClient

        credential = get_credentials()
        subscription_id = get_subscription_id()
        client = MonitorManagementClient(credential, subscription_id)

        if args.resource_group:
            alerts = client.alert_rules.list_by_resource_group(args.resource_group)
        else:
            alerts = client.alert_rules.list_by_subscription()

        alert_list = []
        for alert in alerts:
            alert_list.append(
                {
                    "name": alert.name,
                    "id": alert.id,
                    "location": alert.location,
                    "enabled": alert.is_enabled,
                    "description": getattr(alert, "description", None),
                }
            )

        print(
            format_output(
                {
                    "resource_group": args.resource_group,
                    "subscription_id": subscription_id,
                    "alert_count": len(alert_list),
                    "alerts": alert_list,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
