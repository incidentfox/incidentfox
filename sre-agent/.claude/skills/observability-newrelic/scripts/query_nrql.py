#!/usr/bin/env python3
"""Run an NRQL query against New Relic."""

import argparse
import sys

from newrelic_client import format_output, newrelic_graphql


def main():
    parser = argparse.ArgumentParser(description="Run NRQL query")
    parser.add_argument("--account-id", required=True, help="New Relic account ID")
    parser.add_argument("--query", required=True, help="NRQL query string")
    args = parser.parse_args()

    try:
        graphql_query = """
        query($accountId: Int!, $nrql: Nrql!) {
            actor {
                account(id: $accountId) {
                    nrql(query: $nrql) {
                        results
                    }
                }
            }
        }
        """

        data = newrelic_graphql(
            graphql_query,
            variables={"accountId": int(args.account_id), "nrql": args.query},
        )

        results = (
            data.get("data", {})
            .get("actor", {})
            .get("account", {})
            .get("nrql", {})
            .get("results", [])
        )

        print(
            format_output(
                {
                    "account_id": args.account_id,
                    "query": args.query,
                    "result_count": len(results),
                    "results": results,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "query": args.query}))
        sys.exit(1)


if __name__ == "__main__":
    main()
