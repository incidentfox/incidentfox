"""Investigation History and Discovery Storage.

Local SQLite-based storage for:
- Investigation history ("what did I investigate last week?")
- Pattern learning (known issues)
- Infrastructure discovery (services, dependencies found during investigations)

The discovery tables enable Claude to learn about your infrastructure over time
and suggest updates to .incidentfox.yaml via the /sync-catalog command.
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

    # === Discovery Tables (for self-learning) ===

    # Discovered services - services found during investigations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS discovered_services (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            namespace TEXT,
            deployments TEXT,
            description TEXT,
            team TEXT,
            discovered_at TEXT NOT NULL,
            source_tool TEXT,
            synced_at TEXT
        )
    """)

    # Discovered dependencies - service relationships inferred from investigations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS discovered_dependencies (
            id TEXT PRIMARY KEY,
            from_service TEXT NOT NULL,
            to_service TEXT NOT NULL,
            evidence TEXT,
            confidence REAL DEFAULT 0.5,
            discovered_at TEXT NOT NULL,
            synced_at TEXT,
            UNIQUE(from_service, to_service)
        )
    """)

    # Suggested known issues - patterns that could be added to .incidentfox.yaml
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suggested_known_issues (
            id TEXT PRIMARY KEY,
            pattern TEXT NOT NULL UNIQUE,
            cause TEXT,
            solution TEXT,
            services TEXT,
            occurrences INTEGER DEFAULT 1,
            investigation_ids TEXT,
            discovered_at TEXT NOT NULL,
            synced_at TEXT
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

    # ==========================================================================
    # Discovery Tools - For self-learning infrastructure catalog
    # ==========================================================================

    @mcp.tool()
    def record_discovered_service(
        name: str,
        namespace: str | None = None,
        deployments: str | None = None,
        description: str | None = None,
        team: str | None = None,
        source_tool: str | None = None,
    ) -> str:
        """Record a discovered service for later sync to .incidentfox.yaml.

        Call this when you discover a service during investigation that isn't
        in the service catalog. The user can later review and approve discoveries
        using the /sync-catalog command.

        Args:
            name: Service name (e.g., "payment-api")
            namespace: Kubernetes namespace (e.g., "production")
            deployments: JSON array of deployment names (e.g., '["payment-api", "payment-worker"]')
            description: Brief description of what the service does
            team: Team that owns the service
            source_tool: Tool that discovered this (e.g., "list_pods")

        Returns:
            Confirmation of recorded discovery.
        """
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()

        now = datetime.utcnow().isoformat() + "Z"

        # Check if already exists
        cursor.execute(
            "SELECT id, namespace, deployments FROM discovered_services WHERE name = ?",
            (name,),
        )
        existing = cursor.fetchone()

        if existing:
            # Update with any new info
            updates = []
            params = []
            if namespace and not existing[1]:
                updates.append("namespace = ?")
                params.append(namespace)
            if deployments and not existing[2]:
                updates.append("deployments = ?")
                params.append(deployments)
            if description:
                updates.append("description = ?")
                params.append(description)
            if team:
                updates.append("team = ?")
                params.append(team)

            if updates:
                params.append(name)
                cursor.execute(
                    f"UPDATE discovered_services SET {', '.join(updates)} WHERE name = ?",
                    params,
                )
                conn.commit()

            conn.close()
            return json.dumps(
                {
                    "status": "updated",
                    "service": name,
                    "message": f"Updated existing discovery for {name}",
                },
                indent=2,
            )

        # Insert new discovery
        service_id = str(uuid.uuid4())[:8]
        cursor.execute(
            """
            INSERT INTO discovered_services
            (id, name, namespace, deployments, description, team, discovered_at, source_tool)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                service_id,
                name,
                namespace,
                deployments,
                description,
                team,
                now,
                source_tool,
            ),
        )

        conn.commit()
        conn.close()

        return json.dumps(
            {
                "status": "recorded",
                "id": service_id,
                "service": name,
                "message": f"Discovered service '{name}' recorded. Run /sync-catalog to add to .incidentfox.yaml",
            },
            indent=2,
        )

    @mcp.tool()
    def record_discovered_dependency(
        from_service: str,
        to_service: str,
        evidence: str | None = None,
        confidence: float = 0.5,
    ) -> str:
        """Record a discovered dependency between services.

        Call this when you discover that one service depends on another
        (e.g., from logs, traces, or error messages).

        Args:
            from_service: Service that depends on another (e.g., "payment-api")
            to_service: Service being depended on (e.g., "postgres")
            evidence: How this was discovered (e.g., "Connection error in logs")
            confidence: Confidence score 0.0-1.0 (default 0.5)

        Returns:
            Confirmation of recorded dependency.
        """
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()

        now = datetime.utcnow().isoformat() + "Z"

        # Check if exists
        cursor.execute(
            """
            SELECT id, confidence, evidence FROM discovered_dependencies
            WHERE from_service = ? AND to_service = ?
        """,
            (from_service, to_service),
        )
        existing = cursor.fetchone()

        if existing:
            # Update confidence if higher, append evidence
            new_confidence = max(existing[1] or 0, confidence)
            new_evidence = existing[2]
            if evidence:
                if new_evidence:
                    new_evidence = f"{new_evidence}; {evidence}"
                else:
                    new_evidence = evidence

            cursor.execute(
                """
                UPDATE discovered_dependencies
                SET confidence = ?, evidence = ?
                WHERE id = ?
            """,
                (new_confidence, new_evidence, existing[0]),
            )
            conn.commit()
            conn.close()

            return json.dumps(
                {
                    "status": "updated",
                    "dependency": f"{from_service} -> {to_service}",
                    "confidence": new_confidence,
                },
                indent=2,
            )

        # Insert new
        dep_id = str(uuid.uuid4())[:8]
        cursor.execute(
            """
            INSERT INTO discovered_dependencies
            (id, from_service, to_service, evidence, confidence, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (dep_id, from_service, to_service, evidence, confidence, now),
        )

        conn.commit()
        conn.close()

        return json.dumps(
            {
                "status": "recorded",
                "id": dep_id,
                "dependency": f"{from_service} -> {to_service}",
                "confidence": confidence,
                "message": "Dependency recorded. Run /sync-catalog to add to .incidentfox.yaml",
            },
            indent=2,
        )

    @mcp.tool()
    def suggest_known_issue(
        pattern: str,
        cause: str,
        solution: str,
        services: str | None = None,
        investigation_id: str | None = None,
    ) -> str:
        """Suggest a known issue pattern for the service catalog.

        Call this after resolving an incident that might recur. The pattern
        will be stored as a suggestion and can be added to .incidentfox.yaml
        via /sync-catalog.

        Args:
            pattern: Regex pattern matching the error (e.g., "OOMKilled.*payment")
            cause: Root cause explanation
            solution: How to fix it
            services: JSON array of affected services (e.g., '["payment-api"]')
            investigation_id: ID of investigation that discovered this

        Returns:
            Confirmation of recorded suggestion.
        """
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()

        now = datetime.utcnow().isoformat() + "Z"

        # Check for existing pattern
        cursor.execute(
            "SELECT id, occurrences, investigation_ids FROM suggested_known_issues WHERE pattern = ?",
            (pattern,),
        )
        existing = cursor.fetchone()

        if existing:
            occurrences = existing[1] + 1
            inv_ids = json.loads(existing[2] or "[]")
            if investigation_id and investigation_id not in inv_ids:
                inv_ids.append(investigation_id)

            cursor.execute(
                """
                UPDATE suggested_known_issues
                SET occurrences = ?, investigation_ids = ?, cause = ?, solution = ?, services = ?
                WHERE id = ?
            """,
                (
                    occurrences,
                    json.dumps(inv_ids),
                    cause,
                    solution,
                    services,
                    existing[0],
                ),
            )
            conn.commit()
            conn.close()

            return json.dumps(
                {
                    "status": "updated",
                    "pattern": pattern,
                    "occurrences": occurrences,
                    "message": f"Pattern seen {occurrences} times. Run /sync-catalog to add to .incidentfox.yaml",
                },
                indent=2,
            )

        # Insert new
        issue_id = str(uuid.uuid4())[:8]
        inv_ids = [investigation_id] if investigation_id else []

        cursor.execute(
            """
            INSERT INTO suggested_known_issues
            (id, pattern, cause, solution, services, occurrences, investigation_ids, discovered_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
            (issue_id, pattern, cause, solution, services, json.dumps(inv_ids), now),
        )

        conn.commit()
        conn.close()

        return json.dumps(
            {
                "status": "recorded",
                "id": issue_id,
                "pattern": pattern,
                "message": "Known issue suggestion recorded. Run /sync-catalog to add to .incidentfox.yaml",
            },
            indent=2,
        )

    @mcp.tool()
    def get_pending_discoveries() -> str:
        """Get all discoveries not yet synced to .incidentfox.yaml.

        Returns services, dependencies, and known issues that have been
        discovered but not yet added to the service catalog.

        Returns:
            JSON with pending discoveries organized by type.
        """
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Pending services
        cursor.execute(
            "SELECT * FROM discovered_services WHERE synced_at IS NULL ORDER BY discovered_at DESC"
        )
        services = [dict(r) for r in cursor.fetchall()]

        # Pending dependencies
        cursor.execute(
            "SELECT * FROM discovered_dependencies WHERE synced_at IS NULL ORDER BY confidence DESC"
        )
        dependencies = [dict(r) for r in cursor.fetchall()]

        # Pending known issues
        cursor.execute(
            "SELECT * FROM suggested_known_issues WHERE synced_at IS NULL ORDER BY occurrences DESC"
        )
        known_issues = [dict(r) for r in cursor.fetchall()]

        conn.close()

        total = len(services) + len(dependencies) + len(known_issues)

        return json.dumps(
            {
                "total_pending": total,
                "services": {
                    "count": len(services),
                    "items": services,
                },
                "dependencies": {
                    "count": len(dependencies),
                    "items": dependencies,
                },
                "known_issues": {
                    "count": len(known_issues),
                    "items": known_issues,
                },
                "hint": (
                    "Use /sync-catalog to review and add these to .incidentfox.yaml"
                    if total > 0
                    else "No pending discoveries"
                ),
            },
            indent=2,
        )

    @mcp.tool()
    def mark_discoveries_synced(
        service_ids: str | None = None,
        dependency_ids: str | None = None,
        known_issue_ids: str | None = None,
    ) -> str:
        """Mark discoveries as synced after adding to .incidentfox.yaml.

        Call this after successfully writing discoveries to the service catalog.

        Args:
            service_ids: JSON array of service discovery IDs to mark synced
            dependency_ids: JSON array of dependency discovery IDs to mark synced
            known_issue_ids: JSON array of known issue IDs to mark synced

        Returns:
            Confirmation of marked items.
        """
        conn = sqlite3.connect(_get_db_path())
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat() + "Z"

        counts = {"services": 0, "dependencies": 0, "known_issues": 0}

        if service_ids:
            ids = json.loads(service_ids)
            for sid in ids:
                cursor.execute(
                    "UPDATE discovered_services SET synced_at = ? WHERE id = ?",
                    (now, sid),
                )
                counts["services"] += cursor.rowcount

        if dependency_ids:
            ids = json.loads(dependency_ids)
            for did in ids:
                cursor.execute(
                    "UPDATE discovered_dependencies SET synced_at = ? WHERE id = ?",
                    (now, did),
                )
                counts["dependencies"] += cursor.rowcount

        if known_issue_ids:
            ids = json.loads(known_issue_ids)
            for kid in ids:
                cursor.execute(
                    "UPDATE suggested_known_issues SET synced_at = ? WHERE id = ?",
                    (now, kid),
                )
                counts["known_issues"] += cursor.rowcount

        conn.commit()
        conn.close()

        total = counts["services"] + counts["dependencies"] + counts["known_issues"]

        return json.dumps(
            {
                "marked_synced": counts,
                "total": total,
                "message": f"Marked {total} discoveries as synced",
            },
            indent=2,
        )
