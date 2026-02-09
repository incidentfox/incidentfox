"""
Package manager tools for installing dependencies.

Ported from cto-ai-agent, adapted for OpenAI Agents SDK.
Wraps common package managers (pip, npm, yarn, poetry).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import logging

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


def _run_cmd(
    cmd: list[str],
    cwd: str | None = None,
    timeout_s: float = 300.0,
) -> str:
    """Run a command and return structured output."""
    run_env = os.environ.copy()

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=run_env,
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[-15000:] if result.stdout else "",
            "stderr": result.stderr[-5000:] if result.stderr else "",
            "cmd": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "cmd": " ".join(cmd)}
    except FileNotFoundError:
        return {
            "ok": False,
            "error": f"command_not_found: {cmd[0]}",
            "cmd": " ".join(cmd),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "cmd": " ".join(cmd)}


@function_tool
def pip_install(
    packages: str, requirements_file: str = "", upgrade: bool = False, cwd: str = "."
) -> str:
    """
    Install Python packages using pip.

    Use cases:
    - Install project dependencies
    - Add new libraries during development
    - Install from requirements.txt

    Args:
        packages: Space-separated package names (e.g., "requests flask>=2.0")
        requirements_file: Path to requirements.txt (alternative to packages)
        upgrade: Upgrade if already installed
        cwd: Working directory

    Returns:
        JSON with ok, packages, and output
    """
    logger.info(
        "pip_install",
        packages=packages[:50] if packages else "",
        requirements_file=requirements_file,
    )

    cmd = ["pip", "install"]
    if upgrade:
        cmd.append("--upgrade")

    if requirements_file:
        cmd.extend(["-r", requirements_file])
    elif packages:
        cmd.extend(packages.split())
    else:
        return json.dumps(
            {"ok": False, "error": "packages or requirements_file required"}
        )

    result = _run_cmd(cmd, cwd=cwd or None, timeout_s=600.0)
    result["packages"] = packages
    return json.dumps(result)


@function_tool
def pip_list(outdated: bool = False) -> str:
    """
    List installed Python packages.

    Use cases:
    - Check what's installed
    - Verify package versions
    - Find outdated packages

    Args:
        outdated: Show only outdated packages

    Returns:
        JSON with packages list
    """
    logger.info("pip_list", outdated=outdated)

    cmd = ["pip", "list", "--format=json"]
    if outdated:
        cmd.append("--outdated")

    result = _run_cmd(cmd)

    if result.get("ok"):
        try:
            result["packages"] = json.loads(result.get("stdout", "[]"))
        except json.JSONDecodeError:
            result["packages"] = []

    return json.dumps(result)


@function_tool
def pip_freeze(cwd: str = ".") -> str:
    """
    Generate requirements.txt content from installed packages.

    Use cases:
    - Create reproducible dependency list
    - Export current environment

    Returns:
        JSON with requirements content
    """
    logger.info("pip_freeze")

    result = _run_cmd(["pip", "freeze"], cwd=cwd or None)
    if result.get("ok"):
        result["requirements"] = result.get("stdout", "")
    return json.dumps(result)


@function_tool
def npm_install(packages: str = "", save_dev: bool = False, cwd: str = ".") -> str:
    """
    Install Node.js packages using npm.

    Use cases:
    - Install project dependencies from package.json
    - Add new packages
    - Install dev dependencies

    Args:
        packages: Space-separated package names (empty = install from package.json)
        save_dev: Save as devDependency
        cwd: Working directory

    Returns:
        JSON with ok and output
    """
    logger.info("npm_install", packages=packages[:50] if packages else "")

    cmd = ["npm", "install"]
    if packages:
        cmd.extend(packages.split())
    if save_dev:
        cmd.append("--save-dev")

    return json.dumps(_run_cmd(cmd, cwd=cwd or None, timeout_s=600.0))


@function_tool
def npm_run(script: str, cwd: str = ".", timeout_s: int = 300) -> str:
    """
    Run npm scripts defined in package.json.

    Use cases:
    - Run build scripts
    - Run tests
    - Start development server

    Args:
        script: Script name to run
        cwd: Working directory
        timeout_s: Timeout in seconds

    Returns:
        JSON with ok, stdout, stderr
    """
    if not script:
        return json.dumps({"ok": False, "error": "script is required"})

    logger.info("npm_run", script=script)

    cmd = ["npm", "run", script]
    return json.dumps(_run_cmd(cmd, cwd=cwd or None, timeout_s=timeout_s))


@function_tool
def yarn_install(packages: str = "", dev: bool = False, cwd: str = ".") -> str:
    """
    Install packages using Yarn.

    Use cases:
    - Install from yarn.lock
    - Add new dependencies

    Args:
        packages: Space-separated package names (empty = install from yarn.lock)
        dev: Save as dev dependency
        cwd: Working directory

    Returns:
        JSON with ok and output
    """
    logger.info("yarn_install", packages=packages[:50] if packages else "")

    if packages:
        cmd = ["yarn", "add"] + packages.split()
        if dev:
            cmd.append("--dev")
    else:
        cmd = ["yarn", "install"]

    return json.dumps(_run_cmd(cmd, cwd=cwd or None, timeout_s=600.0))


@function_tool
def poetry_install(
    packages: str = "", dev: bool = False, extras: str = "", cwd: str = "."
) -> str:
    """
    Install dependencies using Poetry.

    Use cases:
    - Install from pyproject.toml/poetry.lock
    - Add new dependencies

    Args:
        packages: Space-separated package names (empty = install from lock)
        dev: Save as dev dependency
        extras: Comma-separated extras to install
        cwd: Working directory

    Returns:
        JSON with ok and output
    """
    logger.info(
        "poetry_install", packages=packages[:50] if packages else "", extras=extras
    )

    if packages:
        cmd = ["poetry", "add"] + packages.split()
        if dev:
            cmd.append("--group=dev")
    else:
        cmd = ["poetry", "install"]
        if extras:
            for extra in extras.split(","):
                cmd.extend(["--extras", extra.strip()])

    return json.dumps(_run_cmd(cmd, cwd=cwd or None, timeout_s=600.0))


@function_tool
def venv_create(path: str = ".venv", python: str = "python3", cwd: str = ".") -> str:
    """
    Create a Python virtual environment.

    Use cases:
    - Isolate project dependencies
    - Set up a clean development environment

    Args:
        path: Virtual environment path (default ".venv")
        python: Python executable
        cwd: Working directory

    Returns:
        JSON with ok, path, activate_cmd
    """
    logger.info("venv_create", path=path)

    cmd = [python, "-m", "venv", path]
    result = _run_cmd(cmd, cwd=cwd or None)

    if result.get("ok"):
        result["path"] = path
        result["activate_cmd"] = f"source {path}/bin/activate"

    return json.dumps(result)


@function_tool
def check_tool_available(tools: str) -> str:
    """
    Check if CLI tools are available.

    Use cases:
    - Verify toolchain before operations
    - Provide helpful errors when tools are missing

    Args:
        tools: Comma-separated tool names (e.g., "pip,npm,docker")

    Returns:
        JSON with available status for each tool
    """
    if not tools:
        return json.dumps({"ok": False, "error": "tools is required"})

    logger.info("check_tool_available", tools=tools)

    available = {}
    for tool in tools.split(","):
        tool_name = tool.strip()
        available[tool_name] = shutil.which(tool_name) is not None

    return json.dumps({"ok": True, "available": available})


# Register tools
register_tool("pip_install", pip_install)
register_tool("pip_list", pip_list)
register_tool("pip_freeze", pip_freeze)
register_tool("npm_install", npm_install)
register_tool("npm_run", npm_run)
register_tool("yarn_install", yarn_install)
register_tool("poetry_install", poetry_install)
register_tool("venv_create", venv_create)
register_tool("check_tool_available", check_tool_available)
