#!/usr/bin/env python3
"""Show MySQL replication status."""

import sys

from mysql_client import format_output, get_connection


def main():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Try MySQL 8.0+ syntax first
        try:
            cursor.execute("SHOW REPLICA STATUS")
        except Exception:
            cursor.execute("SHOW SLAVE STATUS")

        status = cursor.fetchone()
        cursor.close()
        conn.close()

        if not status:
            print(
                format_output(
                    {
                        "is_replica": False,
                        "message": "This server is not configured as a replica",
                    }
                )
            )
            return

        result = {
            "is_replica": True,
            "master_host": status.get("Master_Host") or status.get("Source_Host"),
            "master_port": status.get("Master_Port") or status.get("Source_Port"),
            "io_running": status.get("Slave_IO_Running")
            or status.get("Replica_IO_Running"),
            "sql_running": status.get("Slave_SQL_Running")
            or status.get("Replica_SQL_Running"),
            "seconds_behind_master": status.get("Seconds_Behind_Master")
            or status.get("Seconds_Behind_Source"),
            "master_log_file": status.get("Master_Log_File")
            or status.get("Source_Log_File"),
            "relay_log_file": status.get("Relay_Log_File"),
            "last_io_error": status.get("Last_IO_Error")
            or status.get("Last_IO_Error_Message"),
            "last_sql_error": status.get("Last_SQL_Error")
            or status.get("Last_SQL_Error_Message"),
            "gtid_mode": status.get("Retrieved_Gtid_Set") is not None,
            "retrieved_gtid_set": status.get("Retrieved_Gtid_Set"),
            "executed_gtid_set": status.get("Executed_Gtid_Set"),
        }

        io_ok = result["io_running"] in ("Yes", True)
        sql_ok = result["sql_running"] in ("Yes", True)
        lag = result["seconds_behind_master"]

        if io_ok and sql_ok and (lag is None or lag < 30):
            result["health"] = "healthy"
        elif io_ok and sql_ok and lag < 300:
            result["health"] = "lagging"
        elif io_ok and sql_ok:
            result["health"] = "severely_lagging"
        else:
            result["health"] = "broken"

        print(format_output(result))

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
