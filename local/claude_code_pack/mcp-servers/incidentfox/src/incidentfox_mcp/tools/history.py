"""Investigation History.

Local SQLite-based storage for investigation history.
Enables "what did I investigate last week?" and pattern learning.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP


def _get_db_path() -> Path:
    """Get path to history database."""
    incidentfox_dir = Path.home() / ".incidentfox"
    incidentfox_dir.mkdir(exist_ok=True)
    return incidentfox_dir / "history.db"


def _init_db():
    """Initialize database schema."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS investigations (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            service TEXT,
            summary TEXT,
            root_cause TEXT,
            resolution TEXT,
            severity TEXT,
            tags TEXT,
            status TEXT DEFAULT 'in_progress'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY,
            investigation_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT,
            data TEXT,
            FOREIGN KEY (investigation_id) REFERENCES investigations(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS known_patterns (
            id TEXT PRIMARY KEY,
            pattern TEXT NOT NULL,
            cause TEXT,
            solution TEXT,
            services TEXT,
            occurrence_count INTEGER DEFAULT 1,
            last_seen TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_investigations_service
        ON investigations(service)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_investigations_started
        ON investigations(started_at)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_findings_investigation
        ON findings(investigation_id)
    """)

    conn.commit()
    conn.close()


def register_tools(mcp: FastMCP):
    """Register history tools."""

    # Ensure database is initialized
    _init_db()

    @mcp.tool()
    def start_investigation(
        service: str | None = None,
        summary: str | None = None,
        severity: str = "unknown",
        tags: str | None = None,
    ) -> str:
        """Start a new investigation and return its ID.

        Call this at the beginning of an investigation to track it.

        Args:
            service: Service being investigated
            summary: Brief description of the issue
            severity: P1/P2/P3/P4 or critical/high/medium/low
            tags: Comma-separated tags (e.g., "latency,database,production")

        Returns:
            JSON with the new investigation ID.
        """
        investigation_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat() + "Z"

        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO investigations (id, started_at, service, summary, severity, tags, status)
            VALUES (?, ?, ?, ?, ?, ?, 'in_progress')
        """,
            (investigation_id, now, service, summary, severity, tags),
        )

        conn.commit()
        conn.close()

        return json.dumps(
            {
                "investigation_id": investigation_id,
                "started_at": now,
                "service": service,
                "status": "in_progress",
                "message": f"Investigation {investigation_id} started. Use this ID to add findings and complete the investigation.",
            },
            indent=2,
        )

    @mcp.tool()
    def add_finding(
        investigation_id: str,
        finding_type: str,
        title: str,
        data: str | None = None,
    ) -> str:
        """Add a finding to an investigation.

        Args:
            investigation_id: ID of the investigation
            finding_type: Type of finding (metric_anomaly, log_error, event, hypothesis, etc.)
            title: Brief description of the finding
            data: Optional JSON string with detailed data

        Returns:
            Confirmation of the added finding.
        """
        finding_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat() + "Z"

        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()

        # Verify investigation exists
        cursor.execute(
            "SELECT id FROM investigations WHERE id = ?", (investigation_id,)
        )
        if not cursor.fetchone():
            conn.close()
            return json.dumps(
                {
                    "error": f"Investigation {investigation_id} not found",
                }
            )

        cursor.execute(
            """
            INSERT INTO findings (id, investigation_id, timestamp, type, title, data)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (finding_id, investigation_id, now, finding_type, title, data),
        )

        conn.commit()
        conn.close()

        return json.dumps(
            {
                "finding_id": finding_id,
                "investigation_id": investigation_id,
                "type": finding_type,
                "title": title,
                "timestamp": now,
            },
            indent=2,
        )

    @mcp.tool()
    def complete_investigation(
        investigation_id: str,
        root_cause: str,
        resolution: str,
        summary: str | None = None,
    ) -> str:
        """Complete an investigation with root cause and resolution.

        Args:
            investigation_id: ID of the investigation
            root_cause: The identified root cause
            resolution: How the issue was resolved
            summary: Optional updated summary

        Returns:
            Confirmation with investigation details.
        """
        now = datetime.utcnow().isoformat() + "Z"

        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()

        # Update investigation
        if summary:
            cursor.execute(
                """
                UPDATE investigations
                SET ended_at = ?, root_cause = ?, resolution = ?, summary = ?, status = 'completed'
                WHERE id = ?
            """,
                (now, root_cause, resolution, summary, investigation_id),
            )
        else:
            cursor.execute(
                """
                UPDATE investigations
                SET ended_at = ?, root_cause = ?, resolution = ?, status = 'completed'
                WHERE id = ?
            """,
                (now, root_cause, resolution, investigation_id),
            )

        if cursor.rowcount == 0:
            conn.close()
            return json.dumps({"error": f"Investigation {investigation_id} not found"})

        conn.commit()
        conn.close()

        return json.dumps(
            {
                "investigation_id": investigation_id,
                "status": "completed",
                "root_cause": root_cause,
                "resolution": resolution,
                "ended_at": now,
            },
            indent=2,
        )

    @mcp.tool()
    def get_investigation(investigation_id: str) -> str:
        """Get details of a specific investigation.

        Args:
            investigation_id: ID of the investigation

        Returns:
            JSON with investigation details and findings.
        """
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM investigations WHERE id = ?", (investigation_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return json.dumps({"error": f"Investigation {investigation_id} not found"})

        investigation = dict(row)

        # Get findings
        cursor.execute(
            """
            SELECT * FROM findings WHERE investigation_id = ? ORDER BY timestamp
        """,
            (investigation_id,),
        )
        findings = [dict(r) for r in cursor.fetchall()]

        conn.close()

        investigation["findings"] = findings
        investigation["finding_count"] = len(findings)

        return json.dumps(investigation, indent=2)

    @mcp.tool()
    def search_investigations(
        query: str | None = None,
        service: str | None = None,
        days_ago: int = 30,
        limit: int = 20,
    ) -> str:
        """Search past investigations.

        Args:
            query: Text to search in summary, root_cause, resolution
            service: Filter by service name
            days_ago: How far back to search (default: 30 days)
            limit: Maximum results (default: 20)

        Returns:
            JSON with matching investigations.
        """
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        conditions = []
        params = []

        if query:
            conditions.append("""
                (summary LIKE ? OR root_cause LIKE ? OR resolution LIKE ? OR tags LIKE ?)
            """)
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern, pattern])

        if service:
            conditions.append("service = ?")
            params.append(service)

        from datetime import timedelta

        cutoff = (datetime.utcnow() - timedelta(days=days_ago)).isoformat() + "Z"
        conditions.append("started_at >= ?")
        params.append(cutoff)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor.execute(
            f"""
            SELECT * FROM investigations
            WHERE {where_clause}
            ORDER BY started_at DESC
            LIMIT ?
        """,
            params + [limit],
        )

        investigations = [dict(r) for r in cursor.fetchall()]
        conn.close()

        return json.dumps(
            {
                "query": query,
                "service": service,
                "days_ago": days_ago,
                "count": len(investigations),
                "investigations": investigations,
            },
            indent=2,
        )

    @mcp.tool()
    def find_similar_investigations(
        error_message: str | None = None,
        service: str | None = None,
        limit: int = 5,
    ) -> str:
        """Find past investigations similar to the current issue.

        Useful for "have I seen this before?" queries.

        Args:
            error_message: Error message to match against past findings
            service: Service to filter by
            limit: Maximum results

        Returns:
            JSON with similar past investigations and their resolutions.
        """
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        conditions = ["status = 'completed'"]  # Only completed investigations
        params = []

        if service:
            conditions.append("service = ?")
            params.append(service)

        where_clause = " AND ".join(conditions)

        # Get completed investigations
        cursor.execute(
            f"""
            SELECT * FROM investigations
            WHERE {where_clause}
            ORDER BY started_at DESC
            LIMIT 100
        """,
            params,
        )

        candidates = [dict(r) for r in cursor.fetchall()]

        # Simple text matching for now
        if error_message:
            error_lower = error_message.lower()
            scored = []
            for inv in candidates:
                score = 0
                # Check root cause
                if inv.get("root_cause") and error_lower in inv["root_cause"].lower():
                    score += 10
                # Check summary
                if inv.get("summary") and error_lower in inv["summary"].lower():
                    score += 5
                # Check tags
                if inv.get("tags") and any(
                    t in error_lower for t in (inv["tags"] or "").split(",")
                ):
                    score += 3

                if score > 0:
                    scored.append((score, inv))

            scored.sort(key=lambda x: x[0], reverse=True)
            similar = [inv for _, inv in scored[:limit]]
        else:
            similar = candidates[:limit]

        conn.close()

        return json.dumps(
            {
                "query": {
                    "error_message": error_message[:100] if error_message else None,
                    "service": service,
                },
                "similar_count": len(similar),
                "similar_investigations": similar,
            },
            indent=2,
        )

    @mcp.tool()
    def record_pattern(
        pattern: str,
        cause: str,
        solution: str,
        services: str | None = None,
    ) -> str:
        """Record a pattern for future reference.

        Call this when you identify a recurring issue pattern.

        Args:
            pattern: Error pattern or symptom (e.g., "OOMKilled in payment-service")
            cause: Root cause of the pattern
            solution: How to resolve it
            services: Comma-separated list of affected services

        Returns:
            Confirmation of the recorded pattern.
        """
        pattern_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat() + "Z"

        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()

        # Check if similar pattern exists
        cursor.execute(
            """
            SELECT id, occurrence_count FROM known_patterns WHERE pattern = ?
        """,
            (pattern,),
        )
        existing = cursor.fetchone()

        if existing:
            # Update existing pattern
            cursor.execute(
                """
                UPDATE known_patterns
                SET occurrence_count = occurrence_count + 1, last_seen = ?, cause = ?, solution = ?
                WHERE id = ?
            """,
                (now, cause, solution, existing[0]),
            )
            pattern_id = existing[0]
            message = f"Updated existing pattern (seen {existing[1] + 1} times)"
        else:
            # Create new pattern
            cursor.execute(
                """
                INSERT INTO known_patterns (id, pattern, cause, solution, services, created_at, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (pattern_id, pattern, cause, solution, services, now, now),
            )
            message = "New pattern recorded"

        conn.commit()
        conn.close()

        return json.dumps(
            {
                "pattern_id": pattern_id,
                "pattern": pattern,
                "cause": cause,
                "solution": solution,
                "message": message,
            },
            indent=2,
        )

    @mcp.tool()
    def get_statistics() -> str:
        """Get investigation statistics.

        Returns:
            JSON with total investigations, common services, patterns, etc.
        """
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()

        # Total investigations
        cursor.execute("SELECT COUNT(*) FROM investigations")
        total = cursor.fetchone()[0]

        # Completed vs in-progress
        cursor.execute("SELECT status, COUNT(*) FROM investigations GROUP BY status")
        by_status = dict(cursor.fetchall())

        # Top services
        cursor.execute("""
            SELECT service, COUNT(*) as count
            FROM investigations
            WHERE service IS NOT NULL
            GROUP BY service
            ORDER BY count DESC
            LIMIT 10
        """)
        top_services = [{"service": r[0], "count": r[1]} for r in cursor.fetchall()]

        # Known patterns count
        cursor.execute("SELECT COUNT(*) FROM known_patterns")
        patterns = cursor.fetchone()[0]

        # Recent investigations
        cursor.execute("""
            SELECT id, started_at, service, summary, status
            FROM investigations
            ORDER BY started_at DESC
            LIMIT 5
        """)
        recent = [
            {
                "id": r[0],
                "started_at": r[1],
                "service": r[2],
                "summary": r[3],
                "status": r[4],
            }
            for r in cursor.fetchall()
        ]

        conn.close()

        return json.dumps(
            {
                "total_investigations": total,
                "by_status": by_status,
                "top_services": top_services,
                "known_patterns": patterns,
                "recent_investigations": recent,
            },
            indent=2,
        )
