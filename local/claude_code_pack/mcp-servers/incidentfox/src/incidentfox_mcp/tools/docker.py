"""Docker debugging tools.

Tools for debugging containers locally.
Many developers use Docker for local development and need debugging support.
"""

import json
import subprocess

from mcp.server.fastmcp import FastMCP


def _run_docker_command(args: list[str]) -> tuple[str, str, int]:
    """Run a docker command and return stdout, stderr, returncode."""
    try:
        result = subprocess.run(
            ["docker"] + args,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1
    except FileNotFoundError:
        return "", "Docker not found. Is Docker installed?", 1


def register_tools(mcp: FastMCP):
    """Register Docker tools."""

    @mcp.tool()
    def docker_ps(all_containers: bool = False, filter_name: str | None = None) -> str:
        """List running Docker containers.

        Args:
            all_containers: Include stopped containers
            filter_name: Filter by container name (partial match)

        Returns:
            JSON with container list.
        """
        args = ["ps", "--format", "{{json .}}"]
        if all_containers:
            args.append("-a")
        if filter_name:
            args.extend(["--filter", f"name={filter_name}"])

        stdout, stderr, rc = _run_docker_command(args)

        if rc != 0:
            return json.dumps({"error": stderr or "Failed to list containers"})

        # Parse JSON lines
        containers = []
        for line in stdout.strip().split("\n"):
            if line:
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return json.dumps(
            {
                "container_count": len(containers),
                "containers": containers,
            },
            indent=2,
        )

    @mcp.tool()
    def docker_logs(
        container: str,
        tail: int = 100,
        since: str | None = None,
        follow: bool = False,
    ) -> str:
        """Get logs from a Docker container.

        Args:
            container: Container name or ID
            tail: Number of lines to show (default: 100)
            since: Show logs since timestamp (e.g., "1h", "2023-01-01T00:00:00")
            follow: Not supported in this context, ignored

        Returns:
            Container logs as text.
        """
        args = ["logs", "--tail", str(tail)]
        if since:
            args.extend(["--since", since])
        args.append(container)

        stdout, stderr, rc = _run_docker_command(args)

        if rc != 0:
            return json.dumps(
                {
                    "error": stderr or f"Failed to get logs for {container}",
                    "container": container,
                }
            )

        # Return both stdout and stderr (docker logs outputs to stderr for some apps)
        logs = stdout if stdout else stderr

        return json.dumps(
            {
                "container": container,
                "tail": tail,
                "since": since,
                "log_lines": len(logs.split("\n")),
                "logs": logs,
            },
            indent=2,
        )

    @mcp.tool()
    def docker_inspect(container: str) -> str:
        """Get detailed information about a container.

        Args:
            container: Container name or ID

        Returns:
            JSON with container configuration, state, network settings.
        """
        stdout, stderr, rc = _run_docker_command(["inspect", container])

        if rc != 0:
            return json.dumps(
                {
                    "error": stderr or f"Failed to inspect {container}",
                    "container": container,
                }
            )

        try:
            data = json.loads(stdout)
            if not data:
                return json.dumps({"error": "No data returned"})

            container_info = data[0]

            # Extract useful information
            result = {
                "id": container_info.get("Id", "")[:12],
                "name": container_info.get("Name", "").lstrip("/"),
                "image": container_info.get("Config", {}).get("Image"),
                "created": container_info.get("Created"),
                "state": {
                    "status": container_info.get("State", {}).get("Status"),
                    "running": container_info.get("State", {}).get("Running"),
                    "started_at": container_info.get("State", {}).get("StartedAt"),
                    "exit_code": container_info.get("State", {}).get("ExitCode"),
                    "error": container_info.get("State", {}).get("Error"),
                    "oom_killed": container_info.get("State", {}).get("OOMKilled"),
                },
                "config": {
                    "env": container_info.get("Config", {}).get("Env"),
                    "cmd": container_info.get("Config", {}).get("Cmd"),
                    "entrypoint": container_info.get("Config", {}).get("Entrypoint"),
                    "working_dir": container_info.get("Config", {}).get("WorkingDir"),
                    "exposed_ports": list(
                        container_info.get("Config", {}).get("ExposedPorts", {}).keys()
                    ),
                },
                "network": {
                    "ip_address": container_info.get("NetworkSettings", {}).get(
                        "IPAddress"
                    ),
                    "ports": container_info.get("NetworkSettings", {}).get("Ports"),
                    "networks": list(
                        container_info.get("NetworkSettings", {})
                        .get("Networks", {})
                        .keys()
                    ),
                },
                "mounts": [
                    {
                        "type": m.get("Type"),
                        "source": m.get("Source"),
                        "destination": m.get("Destination"),
                        "mode": m.get("Mode"),
                    }
                    for m in container_info.get("Mounts", [])
                ],
                "restart_count": container_info.get("RestartCount", 0),
            }

            return json.dumps(result, indent=2)

        except json.JSONDecodeError:
            return json.dumps({"error": "Failed to parse inspect output"})

    @mcp.tool()
    def docker_stats(container: str | None = None) -> str:
        """Get resource usage statistics for containers.

        Args:
            container: Specific container (optional, all if not specified)

        Returns:
            JSON with CPU, memory, network, and disk I/O stats.
        """
        args = ["stats", "--no-stream", "--format", "{{json .}}"]
        if container:
            args.append(container)

        stdout, stderr, rc = _run_docker_command(args)

        if rc != 0:
            return json.dumps(
                {
                    "error": stderr or "Failed to get stats",
                }
            )

        # Parse JSON lines
        stats = []
        for line in stdout.strip().split("\n"):
            if line:
                try:
                    stats.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return json.dumps(
            {
                "container_count": len(stats),
                "stats": stats,
            },
            indent=2,
        )

    @mcp.tool()
    def docker_top(container: str) -> str:
        """List processes running inside a container.

        Args:
            container: Container name or ID

        Returns:
            JSON with process list.
        """
        stdout, stderr, rc = _run_docker_command(["top", container])

        if rc != 0:
            return json.dumps(
                {
                    "error": stderr or f"Failed to get processes for {container}",
                    "container": container,
                }
            )

        lines = stdout.strip().split("\n")
        if len(lines) < 2:
            return json.dumps(
                {
                    "container": container,
                    "processes": [],
                }
            )

        # Parse the output
        headers = lines[0].split()
        processes = []
        for line in lines[1:]:
            parts = line.split(None, len(headers) - 1)
            if len(parts) >= len(headers):
                process = dict(zip(headers, parts))
                processes.append(process)

        return json.dumps(
            {
                "container": container,
                "process_count": len(processes),
                "processes": processes,
            },
            indent=2,
        )

    @mcp.tool()
    def docker_events(since: str = "1h", until: str | None = None) -> str:
        """Get recent Docker events.

        Args:
            since: Show events since (default: "1h")
            until: Show events until (optional)

        Returns:
            JSON with recent Docker events (container start/stop, etc.)
        """
        args = ["events", "--since", since, "--format", "{{json .}}"]
        if until:
            args.extend(["--until", until])
        else:
            args.extend(["--until", "now"])

        stdout, stderr, rc = _run_docker_command(args)

        if rc != 0:
            return json.dumps(
                {
                    "error": stderr or "Failed to get events",
                }
            )

        # Parse JSON lines
        events = []
        for line in stdout.strip().split("\n"):
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return json.dumps(
            {
                "since": since,
                "event_count": len(events),
                "events": events,
            },
            indent=2,
        )

    @mcp.tool()
    def docker_diff(container: str) -> str:
        """Show changes to a container's filesystem.

        Args:
            container: Container name or ID

        Returns:
            JSON with added (A), changed (C), and deleted (D) files.
        """
        stdout, stderr, rc = _run_docker_command(["diff", container])

        if rc != 0:
            return json.dumps(
                {
                    "error": stderr or f"Failed to get diff for {container}",
                    "container": container,
                }
            )

        changes = {"added": [], "changed": [], "deleted": []}

        for line in stdout.strip().split("\n"):
            if line:
                change_type = line[0]
                path = line[2:] if len(line) > 2 else ""
                if change_type == "A":
                    changes["added"].append(path)
                elif change_type == "C":
                    changes["changed"].append(path)
                elif change_type == "D":
                    changes["deleted"].append(path)

        return json.dumps(
            {
                "container": container,
                "total_changes": sum(len(v) for v in changes.values()),
                "changes": changes,
            },
            indent=2,
        )

    @mcp.tool()
    def docker_exec(container: str, command: str) -> str:
        """Execute a command inside a container.

        Args:
            container: Container name or ID
            command: Command to execute

        Returns:
            Command output.

        Note: For safety, only read-only diagnostic commands are recommended.
        """
        # Split command into args
        import shlex

        try:
            cmd_args = shlex.split(command)
        except ValueError:
            cmd_args = command.split()

        stdout, stderr, rc = _run_docker_command(["exec", container] + cmd_args)

        return json.dumps(
            {
                "container": container,
                "command": command,
                "exit_code": rc,
                "stdout": stdout,
                "stderr": stderr,
            },
            indent=2,
        )
