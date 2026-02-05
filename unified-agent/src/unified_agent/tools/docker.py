"""
Docker tools for container operations.

Provides Docker CLI access for container debugging and management.
"""

import json
import logging
import subprocess
from typing import Optional

from ..core.agent import function_tool
from . import register_tool

logger = logging.getLogger(__name__)


def _run_docker(args: list[str], timeout_s: float = 300.0) -> dict:
    """Run a docker command and return structured output."""
    cmd = ["docker"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[-20000:] if result.stdout else "",
            "stderr": result.stderr[-5000:] if result.stderr else "",
            "cmd": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "cmd": " ".join(cmd)}
    except FileNotFoundError:
        return {"ok": False, "error": "docker_not_found", "cmd": " ".join(cmd)}
    except Exception as e:
        return {"ok": False, "error": str(e), "cmd": " ".join(cmd)}


@function_tool
def docker_ps(all_containers: bool = False) -> str:
    """
    List Docker containers.

    Args:
        all_containers: Include stopped containers (default False)

    Returns:
        JSON with containers list
    """
    logger.info(f"docker_ps: all={all_containers}")

    args = ["ps", "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}"]
    if all_containers:
        args.append("-a")

    result = _run_docker(args)

    if result.get("ok"):
        containers = []
        for line in result.get("stdout", "").strip().split("\n"):
            if line:
                parts = line.split("|")
                if len(parts) >= 4:
                    containers.append(
                        {
                            "id": parts[0],
                            "name": parts[1],
                            "image": parts[2],
                            "status": parts[3],
                            "ports": parts[4] if len(parts) > 4 else "",
                        }
                    )
        result["containers"] = containers

    return json.dumps(result)


@function_tool
def docker_logs(container: str, tail: int = 100) -> str:
    """
    Get container logs.

    Args:
        container: Container name or ID
        tail: Number of lines from the end (default 100)

    Returns:
        JSON with logs content
    """
    if not container:
        return json.dumps({"ok": False, "error": "container is required"})

    logger.info(f"docker_logs: container={container}, tail={tail}")

    result = _run_docker(["logs", "--tail", str(tail), container])
    if result.get("ok"):
        result["logs"] = result.get("stdout", "") + result.get("stderr", "")
    return json.dumps(result)


@function_tool
def docker_inspect(container: str) -> str:
    """
    Get detailed container information.

    Args:
        container: Container name or ID

    Returns:
        JSON with container details
    """
    if not container:
        return json.dumps({"ok": False, "error": "container is required"})

    logger.info(f"docker_inspect: container={container}")
    result = _run_docker(["inspect", container])

    if result.get("ok"):
        try:
            result["inspection"] = json.loads(result.get("stdout", "[]"))
        except json.JSONDecodeError:
            result["inspection"] = []

    return json.dumps(result)


@function_tool
def docker_stats(container: Optional[str] = None) -> str:
    """
    Get container resource usage statistics.

    Args:
        container: Container name or ID (optional, shows all if omitted)

    Returns:
        JSON with resource stats
    """
    logger.info(f"docker_stats: container={container}")

    args = [
        "stats",
        "--no-stream",
        "--format",
        "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}|{{.BlockIO}}",
    ]
    if container:
        args.append(container)

    result = _run_docker(args)

    if result.get("ok"):
        stats = []
        for line in result.get("stdout", "").strip().split("\n"):
            if line:
                parts = line.split("|")
                if len(parts) >= 5:
                    stats.append(
                        {
                            "name": parts[0],
                            "cpu_percent": parts[1],
                            "memory": parts[2],
                            "net_io": parts[3],
                            "block_io": parts[4],
                        }
                    )
        result["stats"] = stats

    return json.dumps(result)


@function_tool
def docker_exec(container: str, command: str) -> str:
    """
    Execute a command in a running container.

    Args:
        container: Container name or ID
        command: Command to execute

    Returns:
        JSON with command output
    """
    if not container or not command:
        return json.dumps({"ok": False, "error": "container and command are required"})

    logger.info(f"docker_exec: container={container}, command={command}")

    result = _run_docker(["exec", container, "sh", "-c", command])
    return json.dumps(result)


@function_tool
def docker_images() -> str:
    """
    List Docker images.

    Returns:
        JSON with images list
    """
    logger.info("docker_images")

    args = [
        "images",
        "--format",
        "{{.Repository}}|{{.Tag}}|{{.ID}}|{{.Size}}|{{.CreatedSince}}",
    ]
    result = _run_docker(args)

    if result.get("ok"):
        images = []
        for line in result.get("stdout", "").strip().split("\n"):
            if line:
                parts = line.split("|")
                if len(parts) >= 5:
                    images.append(
                        {
                            "repository": parts[0],
                            "tag": parts[1],
                            "id": parts[2],
                            "size": parts[3],
                            "created": parts[4],
                        }
                    )
        result["images"] = images

    return json.dumps(result)


# Register tools
register_tool("docker_ps", docker_ps)
register_tool("docker_logs", docker_logs)
register_tool("docker_inspect", docker_inspect)
register_tool("docker_stats", docker_stats)
register_tool("docker_exec", docker_exec)
register_tool("docker_images", docker_images)
