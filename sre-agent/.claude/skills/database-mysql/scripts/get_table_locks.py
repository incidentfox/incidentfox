#!/usr/bin/env python3
"""Get MySQL table locks and lock waits."""

import sys

from mysql_client import format_output, get_connection


def main():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Check if performance_schema is available
        cursor.execute("SELECT @@performance_schema as ps_enabled")
        ps_enabled = cursor.fetchone()["ps_enabled"]

        if not ps_enabled:
            cursor.close()
            conn.close()
            print(
                format_output(
                    {
                        "message": "performance_schema is not enabled",
                        "locks": [],
                    }
                )
            )
            return

        # Get current locks
        locks = []
        try:
            cursor.execute("""
                SELECT OBJECT_SCHEMA as `database`, OBJECT_NAME as `table`,
                       LOCK_TYPE as lock_type, LOCK_MODE as lock_mode,
                       LOCK_STATUS as status, OWNER_THREAD_ID as thread_id
                FROM performance_schema.metadata_locks
                WHERE OBJECT_TYPE = 'TABLE'
                ORDER BY OBJECT_SCHEMA, OBJECT_NAME
            """)
            locks = cursor.fetchall()
        except Exception:
            pass

        # Get lock waits
        waits = []
        try:
            cursor.execute("""
                SELECT r.trx_id AS waiting_trx_id, r.trx_mysql_thread_id AS waiting_thread,
                       r.trx_query AS waiting_query,
                       b.trx_id AS blocking_trx_id, b.trx_mysql_thread_id AS blocking_thread,
                       b.trx_query AS blocking_query
                FROM information_schema.innodb_lock_waits w
                JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
                JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id
            """)
            waits = cursor.fetchall()
        except Exception:
            try:
                cursor.execute("""
                    SELECT REQUESTING_ENGINE_TRANSACTION_ID AS waiting_trx_id,
                           REQUESTING_THREAD_ID AS waiting_thread,
                           BLOCKING_ENGINE_TRANSACTION_ID AS blocking_trx_id,
                           BLOCKING_THREAD_ID AS blocking_thread
                    FROM performance_schema.data_lock_waits LIMIT 100
                """)
                waits = cursor.fetchall()
            except Exception:
                pass

        cursor.close()
        conn.close()

        print(
            format_output(
                {
                    "lock_count": len(locks),
                    "wait_count": len(waits),
                    "locks": locks,
                    "lock_waits": waits,
                    "has_contention": len(waits) > 0,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
