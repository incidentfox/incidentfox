#!/usr/bin/env python3
"""Get current locks and blocking queries in PostgreSQL."""

import sys

from pg_client import format_output, get_connection


def main():
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Get current locks
        cursor.execute("""
            SELECT
                l.locktype, l.relation::regclass AS table_name, l.mode, l.granted,
                l.pid, a.usename, a.query, a.state,
                age(now(), a.query_start) AS duration,
                a.wait_event_type, a.wait_event
            FROM pg_locks l
            JOIN pg_stat_activity a ON l.pid = a.pid
            WHERE l.relation IS NOT NULL
            ORDER BY a.query_start
        """)

        locks = []
        for row in cursor.fetchall():
            locks.append(
                {
                    "lock_type": row[0],
                    "table_name": str(row[1]) if row[1] else None,
                    "mode": row[2],
                    "granted": row[3],
                    "pid": row[4],
                    "user": row[5],
                    "query": row[6][:200] if row[6] else None,
                    "state": row[7],
                    "duration": str(row[8]) if row[8] else None,
                    "wait_event_type": row[9],
                    "wait_event": row[10],
                }
            )

        # Get blocking queries
        cursor.execute("""
            SELECT
                blocked_locks.pid AS blocked_pid,
                blocked_activity.usename AS blocked_user,
                blocked_activity.query AS blocked_query,
                blocking_locks.pid AS blocking_pid,
                blocking_activity.usename AS blocking_user,
                blocking_activity.query AS blocking_query,
                age(now(), blocked_activity.query_start) AS blocked_duration
            FROM pg_catalog.pg_locks blocked_locks
            JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
            JOIN pg_catalog.pg_locks blocking_locks
                ON blocking_locks.locktype = blocked_locks.locktype
                AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
                AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
                AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
                AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
                AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
                AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
                AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
                AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
                AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
                AND blocking_locks.pid != blocked_locks.pid
            JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
            WHERE NOT blocked_locks.granted
        """)

        blocking = []
        for row in cursor.fetchall():
            blocking.append(
                {
                    "blocked_pid": row[0],
                    "blocked_user": row[1],
                    "blocked_query": row[2][:200] if row[2] else None,
                    "blocking_pid": row[3],
                    "blocking_user": row[4],
                    "blocking_query": row[5][:200] if row[5] else None,
                    "blocked_duration": str(row[6]) if row[6] else None,
                }
            )

        cursor.close()
        conn.close()

        waiting_locks = [l for l in locks if not l["granted"]]

        print(
            format_output(
                {
                    "total_locks": len(locks),
                    "waiting_locks": len(waiting_locks),
                    "blocking_relationships": len(blocking),
                    "has_contention": len(blocking) > 0,
                    "locks": locks,
                    "blocking": blocking,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
