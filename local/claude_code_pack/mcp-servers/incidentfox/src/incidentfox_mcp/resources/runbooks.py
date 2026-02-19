"""Runbook Resources.

Loads runbooks from a runbooks/ directory as MCP resources.
Runbooks are markdown files that describe procedures for handling specific issues.
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP


def _find_runbooks_dir() -> Path | None:
    """Find runbooks directory."""
    # Check current directory and parents
    current = Path.cwd()
    for directory in [current] + list(current.parents):
        runbooks_dir = directory / "runbooks"
        if runbooks_dir.is_dir():
            return runbooks_dir

    # Check .incidentfox directory
    incidentfox_dir = Path.home() / ".incidentfox" / "runbooks"
    if incidentfox_dir.is_dir():
        return incidentfox_dir

    return None


def _list_runbooks() -> list[dict]:
    """List all available runbooks."""
    runbooks_dir = _find_runbooks_dir()
    if not runbooks_dir:
        return []

    runbooks = []
    for path in runbooks_dir.glob("**/*.md"):
        relative = path.relative_to(runbooks_dir)
        name = str(relative).replace(".md", "").replace("/", "-")
        runbooks.append(
            {
                "name": name,
                "path": str(path),
                "relative": str(relative),
            }
        )

    return runbooks


def register_resources(mcp: FastMCP):
    """Register runbook resources."""

    @mcp.resource("incidentfox://runbooks")
    def list_runbooks() -> str:
        """List all available runbooks.

        Runbooks are markdown files in a runbooks/ directory that describe
        procedures for handling specific issues.
        """
        runbooks = _list_runbooks()

        if not runbooks:
            return """# No Runbooks Found

Create a `runbooks/` directory in your project with markdown files:

```
runbooks/
├── high-latency.md
├── oom-killed.md
├── database-connection-errors.md
└── deployment-rollback.md
```

Each runbook should contain step-by-step procedures for handling specific issues.
The IncidentFox agent will reference these during investigations.
"""

        output = ["# Available Runbooks", ""]
        for rb in runbooks:
            output.append(f"- **{rb['name']}**: `{rb['relative']}`")

        output.append("")
        output.append("Use `get_runbook(name)` to read a specific runbook.")

        return "\n".join(output)

    @mcp.tool()
    def get_runbook(name: str) -> str:
        """Get the contents of a specific runbook.

        Args:
            name: Name of the runbook (without .md extension)

        Returns:
            The runbook contents as markdown, or error if not found.
        """
        import json

        runbooks = _list_runbooks()

        # Find matching runbook
        for rb in runbooks:
            if rb["name"] == name or rb["relative"].replace(".md", "") == name:
                try:
                    with open(rb["path"]) as f:
                        content = f.read()
                    return content
                except Exception as e:
                    return json.dumps({"error": f"Failed to read runbook: {e}"})

        # Not found
        available = [rb["name"] for rb in runbooks]
        return json.dumps(
            {
                "error": f"Runbook '{name}' not found",
                "available_runbooks": available,
                "hint": "Create runbooks in a runbooks/ directory",
            }
        )

    @mcp.tool()
    def search_runbooks(query: str) -> str:
        """Search runbooks for relevant content.

        Args:
            query: Search term (e.g., "OOM", "latency", "rollback")

        Returns:
            JSON with matching runbooks and relevant excerpts.
        """
        import json

        runbooks = _list_runbooks()
        if not runbooks:
            return json.dumps(
                {
                    "matches": [],
                    "hint": "No runbooks found. Create a runbooks/ directory.",
                }
            )

        matches = []
        query_lower = query.lower()

        for rb in runbooks:
            try:
                with open(rb["path"]) as f:
                    content = f.read()

                if query_lower in content.lower() or query_lower in rb["name"].lower():
                    # Find relevant lines
                    lines = content.split("\n")
                    relevant_lines = []
                    for i, line in enumerate(lines):
                        if query_lower in line.lower():
                            # Include context (1 line before/after)
                            start = max(0, i - 1)
                            end = min(len(lines), i + 2)
                            excerpt = "\n".join(lines[start:end])
                            relevant_lines.append(excerpt)

                    matches.append(
                        {
                            "name": rb["name"],
                            "path": rb["relative"],
                            "excerpts": relevant_lines[:3],  # Limit excerpts
                        }
                    )

            except Exception:
                continue

        return json.dumps(
            {
                "query": query,
                "match_count": len(matches),
                "matches": matches,
            },
            indent=2,
        )
