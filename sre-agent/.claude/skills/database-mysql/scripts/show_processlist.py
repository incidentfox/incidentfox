#!/usr/bin/env python3
"""Show current MySQL processes/connections."""

import argparse
import sys

from mysql_client import format_output, get_connection


def main():
    parser = argparse.ArgumentParser(description="Show MySQL processlist")
    parser.add_argument("--full", action="store_true", help="Show full query text")
    args = parser.parse_args()

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        if args.full:
            cursor.execute("SHOW FULL PROCESSLIST")
        else:
            cursor.execute("SHOW PROCESSLIST")

        processes = []
        for proc in cursor.fetchall():
            processes.append(
                {
                    "id": proc["Id"],
                    "user": proc["User"],
                    "host": proc["Host"],
                    "database": proc["db"],
                    "command": proc["Command"],
                    "time_seconds": proc["Time"],
                    "state": proc["State"],
                    "info": proc["Info"],
                }
            )

        active_queries = [p for p in processes if p["command"] == "Query" and p["info"]]
        sleeping = [p for p in processes if p["command"] == "Sleep"]
        long_running = [
            p for p in processes if p["time_seconds"] and p["time_seconds"] > 60
        ]

        cursor.close()
        conn.close()

        print(
            format_output(
                {
                    "total_connections": len(processes),
                    "active_queries": len(active_queries),
                    "sleeping_connections": len(sleeping),
                    "long_running_queries": len(long_running),
                    "processes": processes,
                    "long_running": long_running,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
