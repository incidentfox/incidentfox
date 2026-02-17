#!/usr/bin/env python3
"""Show MySQL engine status (primarily InnoDB)."""

import argparse
import sys

from mysql_client import format_output, get_connection


def main():
    parser = argparse.ArgumentParser(description="Show MySQL engine status")
    parser.add_argument(
        "--engine", default="innodb", help="Storage engine (default: innodb)"
    )
    args = parser.parse_args()

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(f"SHOW ENGINE {args.engine.upper()} STATUS")
        status = cursor.fetchone()

        cursor.close()
        conn.close()

        if not status:
            print(
                format_output(
                    {
                        "engine": args.engine,
                        "message": f"No status available for {args.engine}",
                    }
                )
            )
            return

        raw_status = status.get("Status", "")

        result = {
            "engine": args.engine,
            "raw_status": raw_status[:5000] if len(raw_status) > 5000 else raw_status,
        }

        if "LATEST DETECTED DEADLOCK" in raw_status:
            start = raw_status.find("LATEST DETECTED DEADLOCK")
            end = raw_status.find("---", start + 100)
            result["deadlock_info"] = (
                raw_status[start:end]
                if end > start
                else raw_status[start : start + 2000]
            )
            result["has_recent_deadlock"] = True
        else:
            result["has_recent_deadlock"] = False

        result["has_lock_waits"] = "LOCK WAIT" in raw_status

        print(format_output(result))

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
