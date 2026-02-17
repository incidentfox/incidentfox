#!/usr/bin/env python3
"""Get long-running queries in PostgreSQL."""

import argparse
import sys

from pg_client import format_output, get_connection


def main():
    parser = argparse.ArgumentParser(description="Get long-running PostgreSQL queries")
    parser.add_argument(
        "--min-duration",
        type=int,
        default=60,
        help="Min duration in seconds (default: 60)",
    )
    args = parser.parse_args()

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                pid, usename, datname, state, query, query_start,
                EXTRACT(EPOCH FROM (now() - query_start)) AS duration_seconds,
                wait_event_type, wait_event, client_addr, application_name
            FROM pg_stat_activity
            WHERE state != 'idle'
                AND query NOT LIKE '%%pg_stat_activity%%'
                AND EXTRACT(EPOCH FROM (now() - query_start)) > %s
            ORDER BY query_start
        """,
            (args.min_duration,),
        )

        queries = []
        for row in cursor.fetchall():
            queries.append(
                {
                    "pid": row[0],
                    "user": row[1],
                    "database": row[2],
                    "state": row[3],
                    "query": row[4][:500] if row[4] else None,
                    "query_start": row[5].isoformat() if row[5] else None,
                    "duration_seconds": round(row[6], 1) if row[6] else None,
                    "wait_event_type": row[7],
                    "wait_event": row[8],
                    "client_addr": str(row[9]) if row[9] else None,
                    "application_name": row[10],
                }
            )

        cursor.close()
        conn.close()

        print(
            format_output(
                {
                    "min_duration_seconds": args.min_duration,
                    "query_count": len(queries),
                    "queries": queries,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
