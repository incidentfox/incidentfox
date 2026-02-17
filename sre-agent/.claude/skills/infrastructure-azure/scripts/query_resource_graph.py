#!/usr/bin/env python3
"""Query Azure resources using Azure Resource Graph (KQL-based)."""

import argparse
import sys
from datetime import datetime

from azure_client import format_output, get_credentials, get_subscription_id


def main():
    parser = argparse.ArgumentParser(description="Query Azure Resource Graph")
    parser.add_argument("--query", required=True, help="KQL query string")
    parser.add_argument(
        "--subscriptions", nargs="*", help="Subscription IDs (defaults to configured)"
    )
    args = parser.parse_args()

    try:
        from azure.mgmt.resourcegraph import ResourceGraphClient
        from azure.mgmt.resourcegraph.models import QueryRequest

        credential = get_credentials()
        client = ResourceGraphClient(credential)

        subscriptions = args.subscriptions or [get_subscription_id()]
        query_request = QueryRequest(subscriptions=subscriptions, query=args.query)
        response = client.resources(query_request)

        results = []
        for item in response.data:
            item_dict = dict(item)
            for key, value in item_dict.items():
                if isinstance(value, datetime):
                    item_dict[key] = value.isoformat()
            results.append(item_dict)

        print(
            format_output(
                {
                    "query": args.query,
                    "total_records": response.total_records,
                    "count": response.count,
                    "results": results,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "query": args.query}))
        sys.exit(1)


if __name__ == "__main__":
    main()
