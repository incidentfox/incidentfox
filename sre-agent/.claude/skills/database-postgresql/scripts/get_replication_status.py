#!/usr/bin/env python3
"""Get PostgreSQL replication status."""

import sys

from pg_client import format_output, get_connection


def main():
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT pg_is_in_recovery()")
        is_standby = cursor.fetchone()[0]

        result = {"is_standby": is_standby}

        if is_standby:
            cursor.execute("""
                SELECT
                    pg_last_wal_receive_lsn(),
                    pg_last_wal_replay_lsn(),
                    pg_last_xact_replay_timestamp(),
                    EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))
            """)
            standby = cursor.fetchone()

            lag = float(standby[3]) if standby[3] else None
            result["standby_status"] = {
                "receive_lsn": str(standby[0]) if standby[0] else None,
                "replay_lsn": str(standby[1]) if standby[1] else None,
                "last_replay_time": standby[2].isoformat() if standby[2] else None,
                "lag_seconds": lag,
            }

            if lag is None:
                result["health"] = "unknown"
            elif lag < 10:
                result["health"] = "healthy"
            elif lag < 60:
                result["health"] = "lagging"
            elif lag < 300:
                result["health"] = "severely_lagging"
            else:
                result["health"] = "critical"
        else:
            cursor.execute("""
                SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
                       pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes,
                       sync_state, application_name
                FROM pg_stat_replication
            """)

            replicas = []
            for row in cursor.fetchall():
                replicas.append(
                    {
                        "client_addr": str(row[0]) if row[0] else None,
                        "state": row[1],
                        "sent_lsn": str(row[2]) if row[2] else None,
                        "replay_lsn": str(row[5]) if row[5] else None,
                        "lag_bytes": row[6],
                        "sync_state": row[7],
                        "application_name": row[8],
                    }
                )

            result["replicas"] = replicas
            result["replica_count"] = len(replicas)

            # Replication slots
            cursor.execute("""
                SELECT slot_name, slot_type, active,
                       pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS lag_bytes
                FROM pg_replication_slots
            """)

            slots = []
            for row in cursor.fetchall():
                slots.append(
                    {
                        "slot_name": row[0],
                        "slot_type": row[1],
                        "active": row[2],
                        "lag_bytes": row[3],
                    }
                )

            result["replication_slots"] = slots

            max_lag = max([r["lag_bytes"] or 0 for r in replicas], default=0)
            if len(replicas) == 0:
                result["health"] = "no_replicas"
            elif max_lag < 1024 * 1024:
                result["health"] = "healthy"
            elif max_lag < 100 * 1024 * 1024:
                result["health"] = "lagging"
            else:
                result["health"] = "severely_lagging"

        cursor.close()
        conn.close()

        print(format_output(result))

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
