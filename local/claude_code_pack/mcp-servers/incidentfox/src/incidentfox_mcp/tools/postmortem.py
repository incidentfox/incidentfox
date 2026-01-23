"""Postmortem Generation.

Generate structured incident postmortems from investigation data.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP


def _get_db_path() -> Path:
    """Get path to history database."""
    return Path.home() / ".incidentfox" / "history.db"


def register_tools(mcp: FastMCP):
    """Register postmortem tools."""

    @mcp.tool()
    def generate_postmortem(
        investigation_id: str | None = None,
        service: str | None = None,
        summary: str | None = None,
        root_cause: str | None = None,
        resolution: str | None = None,
        impact: str | None = None,
        timeline: str | None = None,
        severity: str = "P2",
        format: str = "markdown",
    ) -> str:
        """Generate a structured incident postmortem.

        Can either use data from a tracked investigation or provided details.

        Args:
            investigation_id: ID of a tracked investigation (optional)
            service: Affected service name
            summary: Brief incident summary
            root_cause: Root cause analysis
            resolution: How the incident was resolved
            impact: Impact description (users affected, duration)
            timeline: JSON string with timeline events [{"time": "...", "event": "..."}]
            severity: Incident severity (P1/P2/P3/P4)
            format: Output format (markdown, json)

        Returns:
            Formatted postmortem document.
        """
        # If investigation_id provided, load from database
        if investigation_id:
            db_path = _get_db_path()
            if db_path.exists():
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT * FROM investigations WHERE id = ?", (investigation_id,)
                )
                row = cursor.fetchone()

                if row:
                    inv = dict(row)
                    service = service or inv.get("service")
                    summary = summary or inv.get("summary")
                    root_cause = root_cause or inv.get("root_cause")
                    resolution = resolution or inv.get("resolution")
                    severity = severity or inv.get("severity", "P2")

                    # Get findings for timeline
                    cursor.execute(
                        """
                        SELECT timestamp, type, title, data
                        FROM findings
                        WHERE investigation_id = ?
                        ORDER BY timestamp
                    """,
                        (investigation_id,),
                    )
                    findings = [dict(r) for r in cursor.fetchall()]

                    if not timeline and findings:
                        timeline_events = []
                        for f in findings:
                            timeline_events.append(
                                {
                                    "time": f["timestamp"],
                                    "event": f["title"],
                                    "type": f["type"],
                                }
                            )
                        timeline = json.dumps(timeline_events)

                conn.close()

        # Parse timeline
        timeline_events = []
        if timeline:
            try:
                timeline_events = json.loads(timeline)
            except json.JSONDecodeError:
                pass

        now = datetime.utcnow().strftime("%Y-%m-%d")

        if format == "json":
            return json.dumps(
                {
                    "title": f"Incident Postmortem: {summary or 'Untitled'}",
                    "date": now,
                    "severity": severity,
                    "service": service,
                    "summary": summary,
                    "impact": impact,
                    "timeline": timeline_events,
                    "root_cause": root_cause,
                    "resolution": resolution,
                    "action_items": [],
                },
                indent=2,
            )

        # Generate Markdown
        doc = []
        doc.append(f"# Incident Postmortem: {summary or 'Untitled'}")
        doc.append("")
        doc.append(f"**Date:** {now}")
        doc.append(f"**Severity:** {severity}")
        if service:
            doc.append(f"**Service:** {service}")
        doc.append("")

        doc.append("## Summary")
        doc.append("")
        doc.append(summary or "_No summary provided_")
        doc.append("")

        if impact:
            doc.append("## Impact")
            doc.append("")
            doc.append(impact)
            doc.append("")

        if timeline_events:
            doc.append("## Timeline")
            doc.append("")
            doc.append("| Time | Event |")
            doc.append("|------|-------|")
            for event in timeline_events:
                time = event.get("time", "")
                if "T" in time:
                    time = time.split("T")[1].split(".")[0]  # Extract time part
                desc = event.get("event", event.get("title", ""))
                doc.append(f"| {time} | {desc} |")
            doc.append("")

        doc.append("## Root Cause")
        doc.append("")
        doc.append(root_cause or "_Root cause pending_")
        doc.append("")

        doc.append("## Resolution")
        doc.append("")
        doc.append(resolution or "_Resolution pending_")
        doc.append("")

        doc.append("## Action Items")
        doc.append("")
        doc.append("- [ ] _Add action items here_")
        doc.append("")

        doc.append("## Lessons Learned")
        doc.append("")
        doc.append("- _What went well?_")
        doc.append("- _What could be improved?_")
        doc.append("")

        doc.append("---")
        doc.append("_Generated by IncidentFox_")

        return "\n".join(doc)

    @mcp.tool()
    def create_timeline_event(
        time: str,
        event: str,
        event_type: str = "general",
    ) -> str:
        """Create a timeline event for use in postmortems.

        Helper tool to build timeline data.

        Args:
            time: Event time (e.g., "14:32 UTC", "2024-01-22T14:32:00Z")
            event: Event description
            event_type: Type of event (detection, action, resolution, etc.)

        Returns:
            JSON event object to add to timeline.
        """
        return json.dumps(
            {
                "time": time,
                "event": event,
                "type": event_type,
            },
            indent=2,
        )

    @mcp.tool()
    def export_postmortem(
        investigation_id: str,
        output_path: str | None = None,
    ) -> str:
        """Export a postmortem to a file.

        Args:
            investigation_id: ID of the investigation
            output_path: File path to write (default: ~/postmortems/{id}.md)

        Returns:
            Confirmation with file path.
        """
        # Generate the postmortem
        postmortem = generate_postmortem(investigation_id=investigation_id)

        if postmortem.startswith("{"):  # Error response
            return postmortem

        # Determine output path
        if not output_path:
            postmortem_dir = Path.home() / "postmortems"
            postmortem_dir.mkdir(exist_ok=True)
            output_path = str(postmortem_dir / f"{investigation_id}.md")

        # Write file
        try:
            with open(output_path, "w") as f:
                f.write(postmortem)

            return json.dumps(
                {
                    "status": "success",
                    "file": output_path,
                    "investigation_id": investigation_id,
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps(
                {
                    "error": f"Failed to write file: {e}",
                    "path": output_path,
                }
            )
