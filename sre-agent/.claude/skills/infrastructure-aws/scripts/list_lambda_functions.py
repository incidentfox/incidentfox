#!/usr/bin/env python3
"""List Lambda functions with runtime, memory, and last modified.

Usage:
    python list_lambda_functions.py
    python list_lambda_functions.py --prefix api-
    python list_lambda_functions.py --json
"""

import argparse
import sys

from aws_client import format_output, get_client


def main():
    parser = argparse.ArgumentParser(description="List Lambda functions")
    parser.add_argument("--prefix", help="Filter by function name prefix")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        lam = get_client("lambda")

        functions = []
        paginator = lam.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                name = fn["FunctionName"]
                if args.prefix and not name.startswith(args.prefix):
                    continue
                functions.append(
                    {
                        "name": name,
                        "runtime": fn.get("Runtime", ""),
                        "memory": fn.get("MemorySize", 0),
                        "timeout": fn.get("Timeout", 0),
                        "code_size_mb": round(fn.get("CodeSize", 0) / 1024 / 1024, 1),
                        "last_modified": fn.get("LastModified", ""),
                        "handler": fn.get("Handler", ""),
                        "description": fn.get("Description", ""),
                        "architecture": fn.get("Architectures", ["x86_64"])[0],
                    }
                )

        if args.json:
            print(format_output({"count": len(functions), "functions": functions}))
        else:
            print(f"Lambda Functions: {len(functions)}")
            print()
            if functions:
                print(
                    f"{'NAME':<40} {'RUNTIME':<16} {'MEMORY':>8} {'TIMEOUT':>8} {'LAST MODIFIED':<26}"
                )
                print("-" * 98)
                for fn in functions:
                    print(
                        f"{fn['name']:<40} {fn['runtime']:<16} {fn['memory']:>6}MB "
                        f"{fn['timeout']:>6}s {fn['last_modified']:<26}"
                    )
            else:
                print("No Lambda functions found.")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
