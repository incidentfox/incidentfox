#!/usr/bin/env python3
"""
IncidentFox CLI - Interactive terminal for AI-powered investigations.

Uses the Planner agent as entry point, which delegates to sub-agents:
- Investigation Agent (full toolkit, autonomous)
- K8s Agent (Kubernetes specialist)
- AWS Agent (AWS specialist)
- Metrics Agent (performance analysis)
- Coding Agent (code analysis)
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import click
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install click prompt-toolkit rich httpx")
    sys.exit(1)

from .client import AgentClient, ConfigServiceClient
from .multimodal import (
    build_image_message,
    get_image_size,
    get_voice_recorder,
    is_image_path,
)

# =============================================================================
# Session State Tracking
# =============================================================================


@dataclass
class QueryStats:
    """Statistics for a single query."""

    query: str
    response: str
    agent: str
    tool_calls: int
    duration_seconds: float
    timestamp: datetime = field(default_factory=datetime.now)
    token_usage: dict | None = None


@dataclass
class SessionState:
    """Tracks session-wide statistics and conversation history."""

    queries: list[QueryStats] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)

    @property
    def total_queries(self) -> int:
        return len(self.queries)

    @property
    def total_tool_calls(self) -> int:
        return sum(q.tool_calls for q in self.queries)

    @property
    def total_duration(self) -> float:
        return sum(q.duration_seconds for q in self.queries)

    @property
    def session_duration(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()

    def add_query(
        self,
        query: str,
        response: str,
        agent: str,
        tool_calls: int,
        duration: float,
        token_usage: dict | None = None,
    ):
        self.queries.append(
            QueryStats(
                query=query,
                response=response,
                agent=agent,
                tool_calls=tool_calls,
                duration_seconds=duration,
                token_usage=token_usage,
            )
        )

    def clear(self):
        """Clear conversation history but keep session start time."""
        self.queries.clear()


# =============================================================================
# Local Context Detection
# =============================================================================

# Default path for key_context.txt file
KEY_CONTEXT_DIR = Path.home() / ".incidentfox"
KEY_CONTEXT_FILE = KEY_CONTEXT_DIR / "key_context.txt"

# Default template for key_context.txt
KEY_CONTEXT_TEMPLATE = """# Key Context for IncidentFox Agent
# This information helps the agent understand your environment and team knowledge.
# Edit this file directly or use: /context edit
#
# Lines starting with # are comments and will be ignored.

## Service Information
# Describe the service(s) you typically work with
# Example: Service: checkout-service
# Example: Team: payments-team

## Dependencies
# List upstream/downstream services and external APIs
# Example: - stripe-api: External payment gateway. Check status.stripe.com first.
# Example: - postgres-payments: Primary RDS database in us-west-2

## Common Issues & Mitigations
# Document known issues and how to resolve them
# Example: - High latency during peak: Usually DB connection pool exhaustion. Scale RDS read replicas.
# Example: - Stripe webhook failures: Check Stripe status page, then retry with backoff.

## Team Knowledge
# Add team-specific knowledge, preferences, and procedures
# Example: - Deploys happen at 10am and 4pm PT
# Example: - Always check recent PRs first for new issues
# Example: - DBA approval needed for database scaling
"""


def get_k8s_context() -> dict | None:
    """
    Auto-detect Kubernetes context from kubeconfig.

    Returns:
        Dict with cluster, context, namespace info, or None if not available
    """
    kubeconfig_path = Path.home() / ".kube" / "config"
    if not kubeconfig_path.exists():
        return None

    try:
        import yaml

        with open(kubeconfig_path) as f:
            kc = yaml.safe_load(f)

        current_context = kc.get("current-context")
        if not current_context:
            return None

        # Find context details
        for ctx in kc.get("contexts", []):
            if ctx.get("name") == current_context:
                context_info = ctx.get("context", {})
                return {
                    "context": current_context,
                    "cluster": context_info.get("cluster"),
                    "namespace": context_info.get("namespace", "default"),
                    "user": context_info.get("user"),
                }

        return {"context": current_context}
    except ImportError:
        # yaml not installed, try kubectl command
        try:
            result = subprocess.run(
                ["kubectl", "config", "current-context"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return {"context": result.stdout.strip()}
        except Exception:
            pass
    except Exception:
        pass

    return None


def get_git_context() -> dict | None:
    """
    Auto-detect Git repository info.

    Returns:
        Dict with repo, branch, recent commits, or None if not in a git repo
    """

    def run_git(args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    # Check if we're in a git repo
    repo_root = run_git(["rev-parse", "--show-toplevel"])
    if not repo_root:
        return None

    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    remote_url = run_git(["remote", "get-url", "origin"])

    # Extract repo name from URL
    # git@github.com:org/repo.git → org/repo
    # https://github.com/org/repo.git → org/repo
    repo_name = None
    if remote_url:
        if ":" in remote_url and "@" in remote_url:
            # SSH format: git@github.com:org/repo.git
            repo_name = remote_url.split(":")[-1].replace(".git", "")
        elif "/" in remote_url:
            # HTTPS format
            parts = remote_url.rstrip("/").split("/")
            if len(parts) >= 2:
                repo_name = "/".join(parts[-2:]).replace(".git", "")

    # Get recent commits (just subjects, for context)
    recent_commits_raw = run_git(["log", "--oneline", "-3", "--no-decorate"])
    recent_commits = []
    if recent_commits_raw:
        recent_commits = recent_commits_raw.split("\n")

    return {
        "repo": repo_name,
        "branch": branch,
        "recent_commits": recent_commits,
    }


def get_aws_context() -> dict | None:
    """
    Auto-detect AWS context from environment.

    Returns:
        Dict with region, profile info, or None if not configured
    """
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    profile = os.getenv("AWS_PROFILE")

    # If no environment vars, try reading from config file
    if not region:
        aws_config = Path.home() / ".aws" / "config"
        if aws_config.exists():
            try:
                # Simple parsing - look for region in default profile
                with open(aws_config) as f:
                    in_default = False
                    for line in f:
                        line = line.strip()
                        if line == "[default]":
                            in_default = True
                        elif line.startswith("["):
                            in_default = False
                        elif in_default and line.startswith("region"):
                            region = line.split("=")[-1].strip()
                            break
            except Exception:
                pass

    if not region and not profile:
        return None

    return {
        "region": region,
        "profile": profile or "default",
    }


def load_key_context() -> str | None:
    """
    Load key context from ~/.incidentfox/key_context.txt.

    Returns:
        Content of key_context.txt (without comment lines), or None if not found
    """
    if not KEY_CONTEXT_FILE.exists():
        return None

    try:
        with open(KEY_CONTEXT_FILE) as f:
            lines = f.readlines()

        # Filter out comment lines and empty lines, keep meaningful content
        content_lines = []
        for line in lines:
            stripped = line.strip()
            # Skip pure comment lines
            if stripped.startswith("#"):
                continue
            # Keep non-empty lines
            if stripped:
                content_lines.append(line.rstrip())

        if not content_lines:
            return None

        return "\n".join(content_lines)
    except Exception:
        return None


def gather_local_context() -> dict:
    """
    Gather all local context: auto-detected + key_context.txt.

    Returns:
        Dict with all local context information
    """
    from datetime import datetime

    context = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    # Auto-detected context
    k8s = get_k8s_context()
    if k8s:
        context["kubernetes"] = k8s

    git = get_git_context()
    if git:
        context["git"] = git

    aws = get_aws_context()
    if aws:
        context["aws"] = aws

    # User-provided key context
    key_context = load_key_context()
    if key_context:
        context["key_context"] = key_context

    return context


def ensure_key_context_file() -> Path:
    """
    Ensure key_context.txt exists with template if not present.

    Returns:
        Path to the key_context.txt file
    """
    KEY_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

    if not KEY_CONTEXT_FILE.exists():
        with open(KEY_CONTEXT_FILE, "w") as f:
            f.write(KEY_CONTEXT_TEMPLATE)

    return KEY_CONTEXT_FILE


async def show_context_status():
    """Display current local context status."""
    console.print(
        Panel.fit(
            "[bold cyan]Local Context Status[/bold cyan]",
            title="🔍 Context",
        )
    )

    # Auto-detected context
    console.print("\n[bold]Auto-Detected:[/bold]")

    k8s = get_k8s_context()
    if k8s:
        console.print(
            f"  [green]✓[/green] Kubernetes: {k8s.get('context')} / {k8s.get('namespace', 'default')}"
        )
    else:
        console.print("  [dim]○[/dim] Kubernetes: Not configured")

    git = get_git_context()
    if git:
        console.print(
            f"  [green]✓[/green] Git: {git.get('repo') or 'unknown'} ({git.get('branch')})"
        )
    else:
        console.print("  [dim]○[/dim] Git: Not in a repository")

    aws = get_aws_context()
    if aws:
        console.print(
            f"  [green]✓[/green] AWS: {aws.get('region')} ({aws.get('profile')})"
        )
    else:
        console.print("  [dim]○[/dim] AWS: Not configured")

    # Key context file
    console.print("\n[bold]Key Context File:[/bold]")
    if KEY_CONTEXT_FILE.exists():
        key_context = load_key_context()
        if key_context:
            console.print(f"  [green]✓[/green] {KEY_CONTEXT_FILE}")
            # Show preview
            preview_lines = key_context.split("\n")[:5]
            for line in preview_lines:
                console.print(
                    f"    [dim]{line[:60]}{'...' if len(line) > 60 else ''}[/dim]"
                )
            if len(key_context.split("\n")) > 5:
                console.print(
                    f"    [dim]... ({len(key_context.split(chr(10)))} lines total)[/dim]"
                )
        else:
            console.print(
                f"  [yellow]⚠[/yellow] {KEY_CONTEXT_FILE} (empty or only comments)"
            )
    else:
        console.print(f"  [dim]○[/dim] {KEY_CONTEXT_FILE} (not created yet)")
        console.print("    [dim]Use '/context edit' to create it[/dim]")

    console.print()


async def edit_key_context(session) -> bool:
    """
    Open key_context.txt in user's editor.

    Returns:
        True if file was edited
    """
    file_path = ensure_key_context_file()

    # Determine editor
    editor = os.getenv("EDITOR") or os.getenv("VISUAL") or "nano"

    console.print(f"\n[dim]Opening {file_path} in {editor}...[/dim]")
    console.print("[dim]Save and close the editor when done.[/dim]\n")

    try:
        # Run editor
        result = subprocess.run([editor, str(file_path)])
        if result.returncode == 0:
            console.print("[green]✓ Context file saved[/green]")
            return True
        else:
            console.print(
                f"[yellow]Editor exited with code {result.returncode}[/yellow]"
            )
    except FileNotFoundError:
        console.print(f"[red]Editor '{editor}' not found[/red]")
        console.print(
            f"[dim]Set EDITOR environment variable or edit manually: {file_path}[/dim]"
        )
    except Exception as e:
        console.print(f"[red]Error opening editor: {e}[/red]")

    return False


async def handle_context_command(cmd: str, session) -> bool:
    """
    Handle /context commands.

    Returns:
        True if command was handled
    """
    parts = cmd.split(maxsplit=1)
    subcommand = parts[1] if len(parts) > 1 else ""

    if subcommand == "" or subcommand == "show":
        await show_context_status()
        return True

    elif subcommand == "edit":
        await edit_key_context(session)
        return True

    elif subcommand == "path":
        console.print(f"\n[cyan]{KEY_CONTEXT_FILE}[/cyan]\n")
        return True

    elif subcommand == "reload":
        # Just show status - context is loaded fresh each request
        console.print("[green]✓ Context will be reloaded on next query[/green]")
        return True

    elif subcommand == "clear":
        if KEY_CONTEXT_FILE.exists():
            response = await session.prompt_async(f"Delete {KEY_CONTEXT_FILE}? [y/N]: ")
            if response.lower() in ("y", "yes"):
                KEY_CONTEXT_FILE.unlink()
                console.print("[green]✓ Context file deleted[/green]")
            else:
                console.print("[dim]Cancelled[/dim]")
        else:
            console.print("[dim]No context file to delete[/dim]")
        return True

    else:
        console.print(f"[red]Unknown context command: {subcommand}[/red]")
        console.print("[dim]Available: /context [show|edit|path|reload|clear][/dim]")
        return True


console = Console()

# RAPTOR Knowledge Base helpers
RAPTOR_URL = os.getenv("RAPTOR_URL", "http://localhost:8000")
RAPTOR_DEFAULT_TREE = os.getenv("RAPTOR_DEFAULT_TREE", "mega_ultra_v2")


def _get_raptor_client():
    """Get HTTP client for RAPTOR API."""
    try:
        import httpx
    except ImportError:
        console.print("[red]httpx not installed. Run: pip install httpx[/red]")
        return None
    return httpx.Client(base_url=RAPTOR_URL, timeout=60.0)


async def rag_list_trees():
    """List available knowledge trees."""
    client = _get_raptor_client()
    if not client:
        return
    try:
        with client:
            response = client.get("/api/v1/trees")
            if response.status_code == 200:
                data = response.json()
                table = Table(title="Knowledge Trees")
                table.add_column("Tree", style="cyan")
                table.add_column("Status")
                table.add_column("Default")

                trees = data.get("trees", [])
                default_tree = data.get("default", "")
                loaded = data.get("loaded", [])

                for tree in trees:
                    status = (
                        "[green]loaded[/green]"
                        if tree in loaded
                        else "[dim]available[/dim]"
                    )
                    is_default = "[yellow]*[/yellow]" if tree == default_tree else ""
                    table.add_row(tree, status, is_default)

                console.print(table)
                console.print(f"[dim]Default tree: {default_tree}[/dim]")
            else:
                console.print(
                    f"[red]Failed to list trees: {response.status_code}[/red]"
                )
                console.print(f"[dim]{response.text}[/dim]")
    except Exception as e:
        console.print(f"[red]Error connecting to RAPTOR at {RAPTOR_URL}: {e}[/red]")
        console.print("[dim]Make sure RAPTOR is running: make start-raptor[/dim]")


async def rag_add_content(content: str, tree: str = ""):
    """Add text content to knowledge base."""
    client = _get_raptor_client()
    if not client:
        return
    tree = tree or RAPTOR_DEFAULT_TREE
    try:
        with client:
            console.print(f"[dim]Adding content to tree '{tree}'...[/dim]")
            response = client.post(
                "/api/v1/tree/documents",
                json={
                    "content": content,
                    "tree": tree,
                    "save": True,
                },
                timeout=120.0,  # Can take a while for embeddings
            )
            if response.status_code == 200:
                data = response.json()
                console.print(
                    f"[green]Added {data.get('new_leaves', 0)} new chunks to '{tree}'[/green]"
                )
                if data.get("updated_clusters"):
                    console.print(
                        f"[dim]Updated {data.get('updated_clusters', 0)} clusters[/dim]"
                    )
            else:
                console.print(
                    f"[red]Failed to add content: {response.status_code}[/red]"
                )
                console.print(f"[dim]{response.text}[/dim]")
    except Exception as e:
        console.print(f"[red]Error connecting to RAPTOR at {RAPTOR_URL}: {e}[/red]")
        console.print("[dim]Make sure RAPTOR is running: make start-raptor[/dim]")


async def rag_upload_file(file_path: str, tree: str = ""):
    """Upload a file to knowledge base."""
    import os.path

    if not os.path.exists(file_path):
        console.print(f"[red]File not found: {file_path}[/red]")
        return

    # Read file content
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        console.print(f"[red]Cannot read file (not text): {file_path}[/red]")
        return
    except Exception as e:
        console.print(f"[red]Error reading file: {e}[/red]")
        return

    if not content.strip():
        console.print("[yellow]File is empty[/yellow]")
        return

    file_name = os.path.basename(file_path)
    console.print(f"[dim]Uploading {file_name} ({len(content)} chars)...[/dim]")
    await rag_add_content(content, tree)


async def rag_search_direct(query: str, tree: str = "", top_k: int = 5):
    """Search knowledge base directly (without going through agent)."""
    client = _get_raptor_client()
    if not client:
        return
    tree = tree or RAPTOR_DEFAULT_TREE
    try:
        with client:
            console.print(f"[dim]Searching '{tree}' for: {query}[/dim]")
            response = client.post(
                "/api/v1/search",
                json={
                    "query": query,
                    "tree": tree,
                    "top_k": top_k,
                    "include_summaries": True,
                },
            )
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                if not results:
                    console.print("[yellow]No results found[/yellow]")
                    return

                console.print(f"\n[green]Found {len(results)} results:[/green]\n")
                for i, r in enumerate(results, 1):
                    score = r.get("score", 0)
                    text = r.get("text", "")[:500]  # Truncate for display
                    layer = r.get("layer", 0)
                    is_summary = r.get("is_summary", False)

                    label = "[dim](summary)[/dim]" if is_summary else ""
                    console.print(
                        f"[cyan]{i}.[/cyan] [dim]L{layer}[/dim] {label} [dim]score: {score:.3f}[/dim]"
                    )
                    console.print(Panel(text, border_style="dim"))
                    console.print()
            else:
                console.print(f"[red]Search failed: {response.status_code}[/red]")
                console.print(f"[dim]{response.text}[/dim]")
    except Exception as e:
        console.print(f"[red]Error connecting to RAPTOR at {RAPTOR_URL}: {e}[/red]")
        console.print("[dim]Make sure RAPTOR is running: make start-raptor[/dim]")


async def rag_answer_direct(question: str, tree: str = "", top_k: int = 5):
    """Get an answer from knowledge base directly (without going through agent)."""
    client = _get_raptor_client()
    if not client:
        return
    tree = tree or RAPTOR_DEFAULT_TREE
    try:
        with client:
            console.print(f"[dim]Asking '{tree}': {question}[/dim]")
            response = client.post(
                "/api/v1/answer",
                json={
                    "question": question,
                    "tree": tree,
                    "top_k": top_k,
                },
            )
            if response.status_code == 200:
                data = response.json()
                answer = data.get("answer", "")
                if not answer:
                    console.print("[yellow]No answer generated[/yellow]")
                    return

                console.print("\n[green]Answer:[/green]\n")
                console.print(Panel(answer, border_style="green"))

                # Show supporting context if available
                context_chunks = data.get("context_chunks", [])[:3]
                if context_chunks:
                    console.print(
                        f"\n[dim]Supporting context ({len(context_chunks)} chunks):[/dim]"
                    )
                    for i, chunk in enumerate(context_chunks, 1):
                        text = (
                            chunk[:300]
                            if isinstance(chunk, str)
                            else chunk.get("text", "")[:300]
                        )
                        console.print(f"[dim]{i}. {text}...[/dim]")
            else:
                console.print(f"[red]Answer failed: {response.status_code}[/red]")
                console.print(f"[dim]{response.text}[/dim]")
    except Exception as e:
        console.print(f"[red]Error connecting to RAPTOR at {RAPTOR_URL}: {e}[/red]")
        console.print("[dim]Make sure RAPTOR is running: make start-raptor[/dim]")


@click.command()
@click.option("--agent", "-a", default="planner", help="Entry agent (default: planner)")
@click.option("--list-agents", is_flag=True, help="List available agents")
@click.option(
    "--agent-url",
    envvar="AGENT_URL",
    default="http://localhost:8081",
    help="Agent service URL",
)
@click.option(
    "--config-url",
    envvar="CONFIG_SERVICE_URL",
    default="http://localhost:8080",
    help="Config service URL",
)
@click.option(
    "--token",
    envvar="TEAM_TOKEN",
    default=None,
    help="Team token (or set TEAM_TOKEN env var)",
)
def main(
    agent: str, list_agents: bool, agent_url: str, config_url: str, token: Optional[str]
):
    """IncidentFox AI SRE - Interactive Terminal"""

    # Get team token
    team_token = token or os.getenv("TEAM_TOKEN", "")
    if not team_token:
        console.print("[red]❌ TEAM_TOKEN not set[/red]")
        console.print("[yellow]Set TEAM_TOKEN in .env or pass --token[/yellow]")
        sys.exit(1)

    # Initialize clients
    client = AgentClient(base_url=agent_url, team_token=team_token)
    config_client = ConfigServiceClient(base_url=config_url, team_token=team_token)

    # Check health
    if not client.check_health():
        console.print(f"[red]❌ Cannot connect to agent at {agent_url}[/red]")
        console.print("[yellow]Run 'make start' to start services[/yellow]")
        sys.exit(1)

    if list_agents:
        display_agents(client)
        return

    # Show welcome banner
    console.print(
        Panel.fit(
            "[bold blue]IncidentFox AI SRE[/bold blue] - Local Edition\n\n"
            f"Entry Agent: [green]{agent}[/green]\n"
            f"Connected to: [cyan]{agent_url}[/cyan]\n\n"
            "The planner agent orchestrates investigations by delegating to\n"
            "specialized sub-agents: K8s, AWS, Metrics, Coding, Investigation.\n\n"
            "Type [yellow]help[/yellow] for commands, [yellow]quit[/yellow] to exit.",
            title="🦊 IncidentFox",
        )
    )
    console.print()

    # Run REPL
    asyncio.run(run_repl(client, config_client, agent))


def display_session_stats(session_state: SessionState, agent_name: str):
    """Display session statistics."""
    table = Table(title="Session Statistics", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    # Session info
    session_mins = session_state.session_duration / 60
    table.add_row("Current Agent", agent_name)
    table.add_row("Session Duration", f"{session_mins:.1f} min")
    table.add_row("", "")

    # Query stats
    table.add_row("Total Queries", str(session_state.total_queries))
    table.add_row("Total Tool Calls", str(session_state.total_tool_calls))
    table.add_row("Total Agent Time", f"{session_state.total_duration:.1f}s")

    if session_state.total_queries > 0:
        avg_duration = session_state.total_duration / session_state.total_queries
        avg_tools = session_state.total_tool_calls / session_state.total_queries
        table.add_row("", "")
        table.add_row("Avg Duration/Query", f"{avg_duration:.1f}s")
        table.add_row("Avg Tools/Query", f"{avg_tools:.1f}")

    console.print(table)

    # Show recent queries
    if session_state.queries:
        console.print("\n[cyan]Recent Queries:[/cyan]")
        for i, q in enumerate(session_state.queries[-5:], 1):
            query_preview = q.query[:50] + "..." if len(q.query) > 50 else q.query
            console.print(
                f"  {i}. [dim]{q.timestamp.strftime('%H:%M:%S')}[/dim] "
                f"{query_preview} [dim]({q.duration_seconds:.1f}s, {q.tool_calls} tools)[/dim]"
            )


async def export_session(session_state: SessionState, agent_name: str, args: str):
    """Export session conversation to file."""
    if not session_state.queries:
        console.print("[yellow]No conversation to export.[/yellow]")
        return

    # Parse arguments
    parts = args.split() if args else []
    export_format = "markdown"
    filename = None

    for part in parts:
        if part.lower() in ("json", "md", "markdown"):
            export_format = "json" if part.lower() == "json" else "markdown"
        else:
            filename = part

    # Generate default filename if not provided
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = "json" if export_format == "json" else "md"
        filename = f"incidentfox_session_{timestamp}.{ext}"

    # Build export content
    if export_format == "json":
        export_data = {
            "agent": agent_name,
            "session_start": session_state.start_time.isoformat(),
            "export_time": datetime.now().isoformat(),
            "stats": {
                "total_queries": session_state.total_queries,
                "total_tool_calls": session_state.total_tool_calls,
                "total_duration_seconds": session_state.total_duration,
            },
            "conversation": [
                {
                    "timestamp": q.timestamp.isoformat(),
                    "query": q.query,
                    "response": q.response,
                    "agent": q.agent,
                    "tool_calls": q.tool_calls,
                    "duration_seconds": q.duration_seconds,
                }
                for q in session_state.queries
            ],
        }
        content = json.dumps(export_data, indent=2)
    else:
        # Markdown format
        lines = [
            "# IncidentFox Session Export",
            "",
            f"**Agent:** {agent_name}",
            f"**Session Start:** {session_state.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Statistics",
            "",
            f"- Queries: {session_state.total_queries}",
            f"- Tool Calls: {session_state.total_tool_calls}",
            f"- Total Duration: {session_state.total_duration:.1f}s",
            "",
            "## Conversation",
            "",
        ]

        for i, q in enumerate(session_state.queries, 1):
            lines.extend(
                [
                    f"### Query {i}",
                    "",
                    f"**Time:** {q.timestamp.strftime('%H:%M:%S')} | "
                    f"**Duration:** {q.duration_seconds:.1f}s | "
                    f"**Tools:** {q.tool_calls}",
                    "",
                    "**User:**",
                    "```",
                    q.query,
                    "```",
                    "",
                    "**Response:**",
                    "",
                    q.response or "_No response_",
                    "",
                    "---",
                    "",
                ]
            )

        content = "\n".join(lines)

    # Write to file
    try:
        filepath = Path(filename).expanduser()
        filepath.write_text(content)
        console.print(f"[green]Session exported to:[/green] {filepath.absolute()}")
    except Exception as e:
        console.print(f"[red]Export failed:[/red] {e}")


# =============================================================================
# Agent Commands
# =============================================================================

# Known sub-agent topology (hardcoded for now, could be fetched from config)
AGENT_TOPOLOGY = {
    "planner": ["investigation", "coding_agent", "writeup_agent"],
    "investigation": [
        "k8s_agent",
        "aws_agent",
        "metrics_agent",
        "github_agent",
        "log_analysis_agent",
    ],
    "k8s_agent": [],
    "aws_agent": [],
    "metrics_agent": [],
    "github_agent": [],
    "log_analysis_agent": [],
    "coding_agent": [],
    "writeup_agent": [],
    "ci_agent": [],
}


async def handle_agents_command(
    args: str,
    client: AgentClient,
    config_client: ConfigServiceClient,
    current_agent: str,
) -> str | None:
    """
    Handle /agents command group.

    Returns new agent name if switched, None otherwise.
    """
    args = args.strip()

    # /agents (no args) - list agents
    if not args:
        display_agents_list(client, config_client, current_agent)
        return None

    # Parse subcommand
    parts = args.split(None, 1)
    subcmd = parts[0].lower()
    subargs = parts[1] if len(parts) > 1 else ""

    if subcmd == "use":
        # /agents use <name>
        if not subargs:
            console.print("[yellow]Usage: /agents use <agent_name>[/yellow]")
            return None
        new_agent = subargs.strip()
        console.print(f"[green]Switched to {new_agent} (new conversation)[/green]")
        return new_agent

    elif subcmd == "info":
        # /agents info [name]
        agent_name = subargs.strip() or current_agent
        display_agent_info(client, config_client, agent_name)
        return None

    elif subcmd == "tools":
        # /agents tools [name]
        agent_name = subargs.strip() or current_agent
        display_agent_tools(client, config_client, agent_name)
        return None

    elif subcmd == "config":
        # /agents config [name] [set <key> <value>]
        await handle_agents_config(subargs, config_client, current_agent)
        return None

    elif subcmd == "reload":
        # /agents reload - trigger config reload
        console.print("[dim]Reloading agent configuration...[/dim]")
        if client.reload_config():
            console.print("[green]Configuration reloaded successfully[/green]")
        else:
            console.print("[red]Failed to reload configuration[/red]")
        return None

    else:
        # Unknown subcommand - show help
        console.print("[cyan]Agent Commands:[/cyan]")
        console.print("  [green]/agents[/green]              List all agents")
        console.print(
            "  [green]/agents use <name>[/green]   Switch to a different agent"
        )
        console.print(
            "  [green]/agents info [name][/green]  Show agent details and topology"
        )
        console.print(
            "  [green]/agents tools [name][/green] List agent's available tools"
        )
        console.print(
            "  [green]/agents config[/green]       Show all agent configurations"
        )
        console.print(
            "  [green]/agents config <name>[/green] Show specific agent config"
        )
        console.print("  [green]/agents config <name> set <key> <value>[/green]")
        console.print("                         Update agent configuration")
        console.print(
            "  [green]/agents reload[/green]       Reload configuration from service"
        )
        return None


def display_agents_list(
    client: AgentClient,
    config_client: ConfigServiceClient,
    current_agent: str,
):
    """Display list of available agents with status."""
    agents = client.list_agents()
    agents_config = config_client.get_agents_config()

    table = Table(title="Available Agents", show_header=True)
    table.add_column("Agent", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Model", style="dim")

    for agent in agents:
        # Check if current
        status = "● active" if agent == current_agent else ""

        # Get model from config
        agent_cfg = agents_config.get(agent, {})
        model_cfg = agent_cfg.get("model", {})
        model_name = model_cfg.get("name", "") if isinstance(model_cfg, dict) else ""

        # Check if enabled
        enabled = agent_cfg.get("enabled", True)
        if not enabled:
            status = "[dim]disabled[/dim]"

        table.add_row(agent, status, model_name)

    console.print(table)
    console.print("\n[dim]Use '/agents use <name>' to switch agents[/dim]")


def display_agent_info(
    client: AgentClient,
    config_client: ConfigServiceClient,
    agent_name: str,
):
    """Display detailed agent information including topology."""
    # Get agent info from agent service
    agent_info = client.get_agent_info(agent_name)

    # Get config from config service
    agents_config = config_client.get_agents_config()
    agent_cfg = agents_config.get(agent_name, {})

    console.print(f"\n[bold cyan]Agent: {agent_name}[/bold cyan]")
    console.print()

    # Basic info
    if agent_info:
        console.print(f"[green]Name:[/green] {agent_info.get('name', agent_name)}")
        console.print(f"[green]Model:[/green] {agent_info.get('model', 'unknown')}")
        console.print(
            f"[green]Tools:[/green] {agent_info.get('tools_count', '?')} available"
        )
    else:
        console.print("[yellow]Could not fetch agent info from service[/yellow]")

    # Config details
    if agent_cfg:
        console.print()
        console.print("[cyan]Configuration:[/cyan]")
        model_cfg = agent_cfg.get("model", {})
        if isinstance(model_cfg, dict):
            if model_cfg.get("temperature"):
                console.print(f"  Temperature: {model_cfg.get('temperature')}")
            if model_cfg.get("max_tokens"):
                console.print(f"  Max Tokens: {model_cfg.get('max_tokens')}")

        if agent_cfg.get("timeout_seconds"):
            console.print(f"  Timeout: {agent_cfg.get('timeout_seconds')}s")
        if agent_cfg.get("max_turns"):
            console.print(f"  Max Turns: {agent_cfg.get('max_turns')}")

    # Sub-agent topology
    console.print()
    console.print("[cyan]Sub-agent Topology:[/cyan]")
    _print_agent_tree(agent_name, indent=0, printed=set())


def _print_agent_tree(agent_name: str, indent: int, printed: set):
    """Recursively print agent topology tree."""
    if agent_name in printed:
        console.print("  " * indent + f"└── {agent_name} [dim](circular ref)[/dim]")
        return

    printed.add(agent_name)

    prefix = "  " * indent
    if indent == 0:
        console.print(f"  {agent_name}")
    else:
        console.print(f"{prefix}├── {agent_name}")

    sub_agents = AGENT_TOPOLOGY.get(agent_name, [])
    for i, sub in enumerate(sub_agents):
        _print_agent_tree(sub, indent + 1, printed.copy())


def display_agent_tools(
    client: AgentClient, config_client: ConfigServiceClient, agent_name: str
):
    """Display tools available to a specific agent from config."""
    # Get effective config from config service
    effective_config = config_client.get_effective_config()

    if not effective_config or "error" in effective_config:
        console.print(f"[yellow]Could not fetch config: {effective_config}[/yellow]")
        return

    # Get agent config - try both agent_name and agent_name without _agent suffix
    agents = effective_config.get("agents", {})
    agent_config = agents.get(agent_name) or agents.get(
        agent_name.replace("_agent", "")
    )

    if not agent_config:
        console.print(f"[yellow]Agent '{agent_name}' not found in config[/yellow]")
        console.print(f"[dim]Available: {', '.join(agents.keys())}[/dim]")
        return

    # Extract tools info
    tools_config = agent_config.get("tools", {})
    enabled_tools = tools_config.get("enabled", [])
    disabled_tools = tools_config.get("disabled", [])
    sub_agents = agent_config.get("sub_agents", [])
    handoff_strategy = agent_config.get("handoff_strategy", "")

    # Build tools list
    table = Table(title=f"Tools for {agent_name}", show_header=True)
    table.add_column("Tool", style="cyan")
    table.add_column("Type", style="dim")
    table.add_column("Status", style="green")

    # Handle wildcard
    if "*" in enabled_tools:
        table.add_row("*", "wildcard", "[green]All tools enabled[/green]")
    else:
        # Show direct tools
        for tool in enabled_tools:
            status = "[red]disabled[/red]" if tool in disabled_tools else "✓"
            table.add_row(tool, "direct", status)

    # Show sub-agent tools if using agent-as-tool pattern
    if sub_agents and handoff_strategy == "agent_as_tool":
        for sub in sub_agents:
            tool_name = f"call_{sub}_agent"
            table.add_row(tool_name, "sub-agent", "✓")

    console.print(table)

    # Show summary
    direct_count = len(enabled_tools) if "*" not in enabled_tools else "all"
    subagent_count = len(sub_agents) if handoff_strategy == "agent_as_tool" else 0
    console.print(
        f"\n[dim]Direct tools: {direct_count}, Sub-agent tools: {subagent_count}[/dim]"
    )

    if handoff_strategy:
        console.print(f"[dim]Handoff strategy: {handoff_strategy}[/dim]")


async def handle_agents_config(
    args: str,
    config_client: ConfigServiceClient,
    current_agent: str,
):
    """Handle /agents config subcommand."""
    args = args.strip()

    # /agents config (no args) - show all
    if not args:
        agents_config = config_client.get_agents_config()
        if not agents_config:
            console.print("[yellow]No agent configurations found[/yellow]")
            return

        console.print("[cyan]Agent Configurations:[/cyan]\n")
        for agent_name, cfg in agents_config.items():
            enabled = cfg.get("enabled", True)
            status = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
            console.print(f"[bold]{agent_name}[/bold] ({status})")

            model_cfg = cfg.get("model", {})
            if isinstance(model_cfg, dict) and model_cfg:
                console.print(f"  model: {model_cfg.get('name', '')}")
                if model_cfg.get("temperature"):
                    console.print(f"  temperature: {model_cfg.get('temperature')}")

            if cfg.get("timeout_seconds"):
                console.print(f"  timeout: {cfg.get('timeout_seconds')}s")

            console.print()
        return

    # Parse: <agent_name> [set <key> <value>]
    parts = args.split(None, 1)
    agent_name = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if not rest:
        # /agents config <name> - show specific agent config
        agents_config = config_client.get_agents_config()
        agent_cfg = agents_config.get(agent_name, {})

        if not agent_cfg:
            console.print(f"[yellow]No configuration found for {agent_name}[/yellow]")
            return

        console.print(f"[cyan]Configuration for {agent_name}:[/cyan]\n")
        # Pretty print as YAML-like
        _print_config_yaml(agent_cfg, indent=0)
        return

    # Check for 'set' subcommand
    if rest.startswith("set "):
        set_args = rest[4:].strip()
        parts = set_args.split(None, 1)
        if len(parts) < 2:
            console.print(
                "[yellow]Usage: /agents config <agent> set <key> <value>[/yellow]"
            )
            console.print("[dim]Examples:[/dim]")
            console.print("  /agents config planner set model.temperature 0.5")
            console.print("  /agents config k8s_agent set timeout_seconds 120")
            console.print("  /agents config planner set enabled false")
            return

        key = parts[0]
        value = parts[1]

        # Parse value (bool, int, float, string)
        parsed_value = _parse_config_value(value)

        # Build config patch
        config_patch = _build_nested_dict(key, parsed_value)

        console.print(f"[dim]Updating {agent_name}.{key} = {parsed_value}[/dim]")

        result = config_client.update_agent_config(
            agent_name, config_patch, f"CLI: set {key}={value}"
        )

        if result.get("success"):
            console.print(f"[green]✓ Updated {agent_name} configuration[/green]")
            console.print(
                "[dim]Use '/agents reload' to apply changes to running agents[/dim]"
            )
        else:
            console.print(f"[red]Failed to update config: {result.get('error')}[/red]")
    else:
        console.print(f"[yellow]Unknown subcommand: {rest}[/yellow]")
        console.print(
            "[dim]Use '/agents config <name> set <key> <value>' to update[/dim]"
        )


def _print_config_yaml(config: dict, indent: int):
    """Print config dict in YAML-like format."""
    prefix = "  " * indent
    for key, value in config.items():
        if isinstance(value, dict):
            console.print(f"{prefix}[cyan]{key}:[/cyan]")
            _print_config_yaml(value, indent + 1)
        elif isinstance(value, list):
            console.print(f"{prefix}[cyan]{key}:[/cyan]")
            for item in value:
                console.print(f"{prefix}  - {item}")
        else:
            console.print(f"{prefix}[cyan]{key}:[/cyan] {value}")


def _parse_config_value(value: str):
    """Parse a config value string to appropriate type."""
    # Boolean
    if value.lower() in ("true", "yes", "on"):
        return True
    if value.lower() in ("false", "no", "off"):
        return False

    # Number
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        pass

    # String (remove quotes if present)
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    return value


def _build_nested_dict(key: str, value) -> dict:
    """Build nested dict from dot-notation key."""
    parts = key.split(".")
    result = {}
    current = result

    for i, part in enumerate(parts[:-1]):
        current[part] = {}
        current = current[part]

    current[parts[-1]] = value
    return result


async def run_repl(
    client: AgentClient, config_client: ConfigServiceClient, agent_name: str
):
    """Main REPL loop."""
    history_file = os.path.expanduser("~/.incidentfox_history")
    session = PromptSession(history=FileHistory(history_file))

    # Track conversation across prompts for follow-up questions
    session_response_id: str | None = None

    # Track session statistics and conversation history
    session_state = SessionState()

    while True:
        try:
            # Show conversation indicator in prompt
            prompt_indicator = (
                "incidentfox" + (" (follow-up)" if session_response_id else "") + "> "
            )
            prompt = await session.prompt_async(prompt_indicator)
            prompt = prompt.strip()

            if not prompt:
                continue

            # Built-in commands
            cmd = prompt.lower()

            # Shell escape: run bash commands with ! prefix
            if prompt.startswith("!"):
                shell_cmd = prompt[1:].strip()
                if shell_cmd:
                    try:
                        console.print(f"[dim]$ {shell_cmd}[/dim]")
                        result = subprocess.run(
                            shell_cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            cwd=os.getcwd(),
                        )
                        if result.stdout:
                            console.print(result.stdout.rstrip())
                        if result.stderr:
                            console.print(f"[red]{result.stderr.rstrip()}[/red]")
                        if result.returncode != 0:
                            console.print(
                                f"[yellow]Exit code: {result.returncode}[/yellow]"
                            )
                    except Exception as e:
                        console.print(f"[red]Error running command: {e}[/red]")
                else:
                    console.print("[yellow]Usage: !<command> (e.g., !ls -la)[/yellow]")
                continue

            # Basic commands: work with or without slash
            if cmd in ("quit", "exit", "q", "/quit", "/exit", "/q"):
                console.print("[dim]Goodbye![/dim]")
                break

            if cmd in ("help", "/help"):
                display_help()
                continue

            # /agents command group
            if cmd == "/agents" or cmd.startswith("/agents "):
                args = prompt[7:].strip() if len(prompt) > 7 else ""
                result = await handle_agents_command(
                    args, client, config_client, agent_name
                )
                if result:  # Returns new agent name if switched
                    agent_name = result
                    session_response_id = None
                continue

            if cmd == "/clear":
                console.clear()
                continue

            if cmd == "/new":
                session_response_id = None
                session_state.clear()
                console.print("[green]Started new conversation[/green]")
                continue

            if cmd.startswith("/config "):
                integration = prompt[8:].strip().lower()
                await configure_integration(client, session, integration)
                continue

            if cmd == "/config":
                await show_config_status(client)
                continue

            # Handle /context commands
            if cmd.startswith("/context"):
                await handle_context_command(cmd.lstrip("/"), session)
                continue

            # Session stats command
            if cmd == "/tokens" or cmd == "/stats":
                display_session_stats(session_state, agent_name)
                continue

            # Export command
            if cmd == "/export" or cmd.startswith("/export "):
                export_args = prompt[7:].strip() if len(prompt) > 7 else ""
                await export_session(session_state, agent_name, export_args)
                continue

            # RAG commands: knowledge base operations
            if cmd == "/rag" or cmd.startswith("/rag "):
                rag_args = prompt[4:].strip() if len(prompt) > 4 else ""

                # /rag (no args) - show help
                if not rag_args:
                    console.print("[cyan]RAG Commands:[/cyan]")
                    console.print(
                        "  [green]/rag search <query>[/green] Search knowledge base (raw results)"
                    )
                    console.print(
                        "  [green]/rag answer <query>[/green] Get synthesized answer from knowledge base"
                    )
                    console.print(
                        "  [green]/rag trees[/green]         List available knowledge trees"
                    )
                    console.print(
                        "  [green]/rag add <text>[/green]    Add text to knowledge base"
                    )
                    console.print(
                        "  [green]/rag upload <file>[/green]  Upload file to knowledge base"
                    )
                    console.print("")
                    console.print(
                        "[dim]Example: /rag search How do I debug OOMKilled pods?[/dim]"
                    )
                    console.print(f"[dim]RAPTOR URL: {RAPTOR_URL}[/dim]")
                    continue

                # rag trees - list available trees
                if rag_args == "trees":
                    await rag_list_trees()
                    continue

                # rag search <query> - direct search without agent
                if rag_args.startswith("search "):
                    query = rag_args[7:].strip()
                    if query:
                        await rag_search_direct(query)
                    else:
                        console.print("[yellow]Usage: /rag search <query>[/yellow]")
                    continue

                # rag answer <query> - get synthesized answer directly
                if rag_args.startswith("answer "):
                    query = rag_args[7:].strip()
                    if query:
                        await rag_answer_direct(query)
                    else:
                        console.print("[yellow]Usage: /rag answer <query>[/yellow]")
                    continue

                # rag add <content> - add text content
                if rag_args.startswith("add "):
                    content = rag_args[4:].strip()
                    if content:
                        await rag_add_content(content)
                    else:
                        console.print("[yellow]Usage: rag add <text content>[/yellow]")
                    continue

                # rag upload <file> - upload file
                if rag_args.startswith("upload "):
                    file_path = rag_args[7:].strip()
                    # Handle quoted paths
                    if file_path.startswith('"') and file_path.endswith('"'):
                        file_path = file_path[1:-1]
                    elif file_path.startswith("'") and file_path.endswith("'"):
                        file_path = file_path[1:-1]
                    if file_path:
                        await rag_upload_file(file_path)
                    else:
                        console.print("[yellow]Usage: rag upload <file_path>[/yellow]")
                    continue

                # Unknown subcommand
                subcommand = rag_args.split()[0] if rag_args else ""
                console.print(f"[yellow]Unknown RAG command: {subcommand}[/yellow]")
                console.print("[dim]Use /rag for available commands[/dim]")
                continue

            # Image command: /image <path> [prompt]
            if cmd.startswith("/image "):
                image_args = prompt[7:].strip()
                # Split into path and optional prompt
                # Handle quoted paths
                if image_args.startswith('"'):
                    end_quote = image_args.find('"', 1)
                    if end_quote > 0:
                        img_path = image_args[1:end_quote]
                        img_prompt = image_args[end_quote + 1 :].strip()
                    else:
                        img_path = image_args
                        img_prompt = ""
                elif image_args.startswith("'"):
                    end_quote = image_args.find("'", 1)
                    if end_quote > 0:
                        img_path = image_args[1:end_quote]
                        img_prompt = image_args[end_quote + 1 :].strip()
                    else:
                        img_path = image_args
                        img_prompt = ""
                else:
                    # Try to split on first space after path
                    parts = image_args.split(" ", 1)
                    img_path = parts[0]
                    img_prompt = parts[1] if len(parts) > 1 else ""

                path = is_image_path(img_path)
                if not path:
                    console.print(f"[red]Image not found: {img_path}[/red]")
                    continue

                # Build message with image
                message = build_image_message(path, img_prompt)
                w, h = get_image_size(path)
                size_info = f" ({w}x{h})" if w and h else ""
                console.print(f"[green]Sending image:[/green] {path.name}{size_info}")
                console.print()
                result = await run_with_streaming(
                    client,
                    agent_name,
                    message,
                    session,
                    previous_response_id=session_response_id,
                )
                if result.response_id:
                    session_response_id = result.response_id
                if result.success:
                    query_text = (
                        f"[image: {path.name}] {img_prompt}"
                        if img_prompt
                        else f"[image: {path.name}]"
                    )
                    session_state.add_query(
                        query_text,
                        result.output or "",
                        agent_name,
                        result.tool_calls,
                        result.duration_seconds,
                    )
                console.print()
                continue

            # Voice command: record and transcribe
            if cmd == "/voice":
                recorder = get_voice_recorder()
                if not recorder.is_available():
                    missing = recorder.get_missing_deps()
                    console.print("[red]Voice recording not available.[/red]")
                    if missing:
                        console.print(
                            f"[yellow]Install missing dependencies: pip install {' '.join(missing)}[/yellow]"
                        )
                    if not os.getenv("OPENAI_API_KEY"):
                        console.print(
                            "[yellow]Set OPENAI_API_KEY for Whisper transcription[/yellow]"
                        )
                    continue

                result = await handle_voice_recording(
                    client,
                    agent_name,
                    session,
                    session_response_id,
                    recorder,
                    session_state,
                )
                if result.response_id:
                    session_response_id = result.response_id
                continue

            # Check if input is a dropped image file path
            image_path = is_image_path(prompt)
            if image_path:
                # User dropped/pasted an image path
                console.print(f"[cyan]Detected image:[/cyan] {image_path.name}")
                img_prompt = await session.prompt_async(
                    "Add a prompt (or press Enter to analyze): "
                )
                img_prompt = img_prompt.strip()

                message = build_image_message(image_path, img_prompt)
                w, h = get_image_size(image_path)
                size_info = f" ({w}x{h})" if w and h else ""
                console.print(f"[green]Sending image{size_info}...[/green]")
                console.print()
                result = await run_with_streaming(
                    client,
                    agent_name,
                    message,
                    session,
                    previous_response_id=session_response_id,
                )
                if result.response_id:
                    session_response_id = result.response_id
                if result.success:
                    query_text = (
                        f"[image: {image_path.name}] {img_prompt}"
                        if img_prompt
                        else f"[image: {image_path.name}]"
                    )
                    session_state.add_query(
                        query_text,
                        result.output or "",
                        agent_name,
                        result.tool_calls,
                        result.duration_seconds,
                    )
                console.print()
                continue

            # Gather local context for the request
            local_context = gather_local_context()

            # Run investigation with streaming, passing previous response_id for follow-ups
            console.print()
            result = await run_with_streaming(
                client,
                agent_name,
                prompt,
                session,
                previous_response_id=session_response_id,
                local_context=local_context,
            )
            # Update session_response_id for next follow-up
            if result.response_id:
                session_response_id = result.response_id
            # Track query in session state
            if result.success:
                session_state.add_query(
                    prompt,
                    result.output or "",
                    agent_name,
                    result.tool_calls,
                    result.duration_seconds,
                )
            console.print()

        except KeyboardInterrupt:
            console.print("\n[dim]Use 'quit' to exit[/dim]")
        except EOFError:
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


@dataclass
class StreamResult:
    """Result from a streaming agent run."""

    response_id: str | None = None
    output: str | None = None
    duration_seconds: float = 0.0
    tool_calls: int = 0
    success: bool = False


async def run_with_streaming(
    client: AgentClient,
    agent_name: str,
    message: str,
    session=None,
    previous_response_id: str | None = None,
    local_context: dict | None = None,
) -> StreamResult:
    """
    Run agent with SSE streaming and display events in real-time.

    Shows execution trace like Claude Code/Cursor, including nested sub-agent calls.
    Handles human input requests by prompting the user and resuming the conversation.

    Args:
        client: Agent client instance
        agent_name: Name of agent to run
        message: User message/query
        session: Prompt session for user input
        previous_response_id: Optional response ID for resumption (continues from previous state)
        local_context: Optional local environment context (k8s, git, aws, key_context)

    Returns:
        The last_response_id from the agent run, for chaining follow-up queries
    """
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text

    tool_calls = []
    final_result = None
    # Track nested agent depth for indentation
    agent_stack = [agent_name]
    # Track config issues encountered during the run
    config_issues = []
    # Track response_id for potential resumption
    current_conversation_id = previous_response_id
    # Track if we need human input
    pending_human_input = None

    def get_indent(depth: int = None) -> str:
        """Get indentation based on agent nesting depth."""
        if depth is None:
            depth = len(agent_stack) - 1
        return "  " * (depth + 1)

    def check_for_config_required(output_preview: str) -> dict | None:
        """Check if tool output indicates config is required."""
        if not output_preview:
            return None
        # Check if this looks like a config_required response
        if (
            '"config_required": true' not in output_preview
            and '"config_required":true' not in output_preview
        ):
            return None

        try:
            # Try to parse as complete JSON first
            data = json.loads(output_preview)
            if data.get("config_required"):
                return data
        except json.JSONDecodeError:
            # JSON is truncated - use regex to extract key fields
            import re

            integration_match = re.search(r'"integration":\s*"([^"]+)"', output_preview)
            tool_match = re.search(r'"tool":\s*"([^"]+)"', output_preview)
            if integration_match:
                return {
                    "config_required": True,
                    "integration": integration_match.group(1),
                    "tool": tool_match.group(1) if tool_match else "unknown",
                }
        except Exception:
            pass
        return None

    def check_for_human_input_required(output_preview: str) -> dict | None:
        """Check if tool output indicates human input is required."""
        if not output_preview:
            return None
        if (
            '"human_input_required": true' not in output_preview
            and '"human_input_required":true' not in output_preview
        ):
            return None

        try:
            data = json.loads(output_preview)
            if data.get("human_input_required"):
                return data
        except json.JSONDecodeError:
            # Try regex extraction for truncated JSON
            import re

            question_match = re.search(r'"question":\s*"([^"]+)"', output_preview)
            if question_match:
                return {
                    "human_input_required": True,
                    "question": question_match.group(1),
                    "response_type": "text",
                }
        except Exception:
            pass
        return None

    try:
        # Initial status
        if current_conversation_id:
            console.print(
                f"[dim]Resuming {agent_name} (conversation continues)...[/dim]"
            )
        else:
            console.print(f"[dim]Starting {agent_name}...[/dim]")

        async for event in client.run_agent_stream(
            agent_name,
            message,
            previous_response_id=current_conversation_id,
            local_context=local_context,
        ):
            event_type = event.get("event_type", "unknown")
            depth = event.get("depth", 0)
            indent = get_indent(depth)

            if event_type == "agent_started":
                console.print(
                    f"[green]{indent}Agent started[/green] [dim]({event.get('correlation_id', '')[:8]})[/dim]"
                )

            elif event_type == "subagent_started":
                # Sub-agent started - show nesting
                subagent_name = event.get("agent", "unknown")
                parent = event.get("parent_agent", "")
                agent_stack.append(subagent_name)
                console.print(
                    f"[magenta]{indent}▶ {subagent_name}[/magenta] [dim](delegated from {parent})[/dim]"
                )

            elif event_type == "subagent_completed":
                # Sub-agent completed
                subagent_name = event.get("agent", "unknown")
                success = event.get("success", True)
                if agent_stack and agent_stack[-1] == subagent_name:
                    agent_stack.pop()
                if success:
                    console.print(f"[green]{indent}◀ {subagent_name} done[/green]")
                else:
                    error = event.get("error", "")
                    console.print(
                        f"[red]{indent}◀ {subagent_name} failed:[/red] {error[:50]}"
                    )

            elif event_type == "tool_started":
                tool_name = event.get("tool", "unknown")
                tool_input = event.get("input", {})
                input_preview = event.get("input_preview", "")
                seq = event.get("sequence", 0)
                agent = event.get("agent", "")

                # Format input preview with proper truncation
                if not input_preview and tool_input:
                    if isinstance(tool_input, dict):
                        # Show first few key=value pairs with ellipsis
                        def truncate(v, max_len=40):
                            s = repr(v)
                            return s[:max_len] + "..." if len(s) > max_len else s

                        pairs = [
                            f"{k}={truncate(v)}"
                            for k, v in list(tool_input.items())[:2]
                        ]
                        input_preview = ", ".join(pairs)
                    else:
                        s = str(tool_input)
                        input_preview = s[:50] + "..." if len(s) > 50 else s

                # Truncate overall preview to avoid very long lines
                if input_preview:
                    if len(input_preview) > 80:
                        input_preview = input_preview[:80] + "..."
                    input_preview = f"({input_preview})"

                # Show which agent is calling the tool
                agent_prefix = (
                    f"[dim]{agent}:[/dim] " if agent and agent != agent_name else ""
                )
                console.print(
                    f"[yellow]{indent}→ {agent_prefix}[/yellow][cyan]{tool_name}[/cyan]{input_preview}"
                )
                tool_calls.append({"tool": tool_name, "seq": seq, "agent": agent})

            elif event_type == "tool_completed":
                seq = event.get("sequence", 0)
                output_preview = event.get("output_preview", "")

                # Check if tool output indicates config is required
                config_data = check_for_config_required(output_preview)
                if config_data:
                    # Track this config issue
                    integration = config_data.get("integration", "unknown")
                    if integration not in [c.get("integration") for c in config_issues]:
                        config_issues.append(config_data)
                    # Show user-friendly message
                    console.print(
                        f"[yellow]{indent}⚠ {integration.upper()} not configured[/yellow]"
                    )
                else:
                    # Check if tool output indicates human input is required
                    human_input_data = check_for_human_input_required(output_preview)
                    if human_input_data:
                        pending_human_input = human_input_data
                        console.print(f"[cyan]{indent}⏸ Agent needs your input[/cyan]")
                    else:
                        # Show brief output preview
                        if output_preview and len(output_preview) > 80:
                            output_preview = output_preview[:80] + "..."
                        console.print(
                            f"[green]{indent}✓[/green] [dim]{output_preview if output_preview else ''}[/dim]"
                        )

            elif event_type == "human_input_required":
                # Direct human input request event (from SSE)
                pending_human_input = event
                console.print(f"[cyan]{indent}⏸ Agent needs your input[/cyan]")

            elif event_type == "message":
                content = event.get("content_preview", "")
                if content:
                    console.print(f"[blue]{indent}Message:[/blue] {content[:100]}")

            elif event_type == "agent_handoff":
                new_agent = event.get("new_agent", "unknown")
                console.print(f"[magenta]{indent}→ Handoff to {new_agent}[/magenta]")

            elif event_type == "agent_completed":
                final_result = event
                success = event.get("success", False)
                duration = event.get("duration_seconds", 0)
                tc_count = event.get("tool_calls_count", len(tool_calls))
                # Capture last_response_id for follow-up queries (chains without pre-created conversations)
                current_conversation_id = (
                    event.get("last_response_id") or current_conversation_id
                )

                if success:
                    console.print(
                        f"[green]{indent}Completed[/green] in {duration:.1f}s ({tc_count} tool calls)"
                    )
                else:
                    error = event.get("error", "Unknown error")
                    console.print(f"[red]{indent}Failed:[/red] {error}")

            elif event_type == "error":
                error = event.get("error", "Unknown error")
                console.print(f"[red]Error: {error}[/red]")
                return StreamResult()

        # Handle config issues FIRST (before human input) - CLI handles configuration automatically
        if config_issues:
            console.print()
            should_retry = await display_config_issues(config_issues, session, client)
            if should_retry:
                # Retry with conversation_id to resume from where we left off
                if current_conversation_id:
                    console.print(
                        "\n[dim]Resuming your query with new configuration (previous work preserved)...[/dim]\n"
                    )
                else:
                    console.print(
                        "\n[dim]Retrying your query with new configuration...[/dim]\n"
                    )
                return await run_with_streaming(
                    client,
                    agent_name,
                    message,
                    session,
                    previous_response_id=current_conversation_id,
                    local_context=local_context,
                )

        # Handle human input request (only if no config issues took priority)
        if pending_human_input and session:
            console.print()
            human_response = await handle_human_input_request(
                pending_human_input, session
            )
            if human_response:
                # Resume the conversation with the human's response
                console.print("\n[dim]Resuming with your input...[/dim]\n")
                return await run_with_streaming(
                    client,
                    agent_name,
                    human_response,
                    session,
                    previous_response_id=current_conversation_id,
                    local_context=local_context,
                )

        # Display final output
        output_text = None
        if final_result:
            console.print()
            output_text = final_result.get("output")
            if output_text:
                display_result({"output": output_text, "success": True})
            elif not final_result.get("success"):
                display_error(final_result)

        # Return StreamResult with stats for tracking
        return StreamResult(
            response_id=current_conversation_id,
            output=output_text,
            duration_seconds=duration if final_result else 0.0,
            tool_calls=tc_count if final_result else len(tool_calls),
            success=final_result.get("success", False) if final_result else False,
        )

    except Exception as e:
        console.print(f"[red]Stream error: {e}[/red]")
        return StreamResult()


async def handle_human_input_request(request: dict, session) -> str | None:
    """
    Handle a human input request from the agent.

    Displays the question and prompts the user for input based on the response type.

    Args:
        request: The human input request data containing question, context, etc.
        session: Prompt session for user input

    Returns:
        The user's response, or None if cancelled
    """
    question = request.get("question", "The agent needs your input")
    context = request.get("context")
    action_required = request.get("action_required")
    response_type = request.get("response_type", "text")
    choices = request.get("choices", [])

    # Display the request
    console.print(
        Panel.fit(
            f"[bold cyan]{question}[/bold cyan]",
            title="🤖 Agent Request",
            border_style="cyan",
        )
    )

    # Show context if provided
    if context:
        console.print(f"\n[dim]Context:[/dim] {context}")

    # Show action required if provided
    if action_required:
        console.print(f"\n[yellow]Action needed:[/yellow] {action_required}")

    console.print()

    # Get response based on type
    try:
        if response_type == "yes_no":
            response = await session.prompt_async("Your answer [Y/n]: ")
            response = response.strip().lower()
            if response in ("", "y", "yes"):
                return "yes"
            elif response in ("n", "no"):
                return "no"
            else:
                return response  # Pass through other responses

        elif response_type == "choice" and choices:
            console.print("[dim]Options:[/dim]")
            for i, choice in enumerate(choices, 1):
                console.print(f"  {i}. {choice}")
            console.print()
            response = await session.prompt_async("Your choice (number or text): ")
            response = response.strip()
            # Handle numeric selection
            try:
                idx = int(response) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
            except ValueError:
                pass
            return response  # Return as-is if not a number

        elif response_type == "action_done":
            response = await session.prompt_async(
                "Type 'done' when ready (or 'skip' to continue without): "
            )
            response = response.strip().lower()
            if response == "skip":
                return "User chose to skip this action and continue without it."
            elif response in ("done", "ready", "ok", "yes", ""):
                return "done"
            else:
                return response

        else:  # Default text response
            response = await session.prompt_async("Your response: ")
            return response.strip() if response.strip() else None

    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        return None


async def handle_voice_recording(
    client: AgentClient,
    agent_name: str,
    session,
    session_response_id: str | None,
    recorder,
    session_state: SessionState | None = None,
) -> StreamResult:
    """
    Handle voice recording and transcription.

    Records audio from the microphone, transcribes using Whisper,
    and sends the result to the agent.

    Args:
        client: Agent client instance
        agent_name: Current agent name
        session: Prompt session for user input
        session_response_id: Current conversation ID
        recorder: VoiceRecorder instance
        session_state: Optional session state for tracking

    Returns:
        StreamResult from the agent run
    """
    console.print(
        Panel.fit(
            "[bold cyan]Voice Recording[/bold cyan]\n\n"
            "Press [yellow]Enter[/yellow] to start recording.\n"
            "Press [yellow]Enter[/yellow] again to stop and transcribe.\n"
            "Press [yellow]Ctrl+C[/yellow] to cancel.",
            title="🎤 Voice Mode",
            border_style="cyan",
        )
    )

    try:
        # Wait for user to press Enter to start
        await session.prompt_async("[dim]Press Enter to start recording...[/dim] ")

        # Start recording
        console.print("[red]● Recording...[/red] (Press Enter to stop)")

        # Record in a thread with stop event
        stop_event = threading.Event()
        audio_chunks = []

        def record_audio():
            import numpy as np

            try:
                import sounddevice as sd
            except ImportError:
                return

            def callback(indata, frames, time, status):
                if not stop_event.is_set():
                    audio_chunks.append(indata.copy())

            with sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                callback=callback,
            ):
                stop_event.wait(timeout=60.0)  # Max 60 seconds

        # Start recording thread
        record_thread = threading.Thread(target=record_audio)
        record_thread.start()

        # Wait for Enter to stop
        await session.prompt_async("")
        stop_event.set()
        record_thread.join(timeout=2.0)

        if not audio_chunks:
            console.print("[yellow]No audio recorded.[/yellow]")
            return StreamResult(response_id=session_response_id)

        console.print("[dim]Transcribing...[/dim]")

        # Combine and transcribe
        import numpy as np

        audio_data = np.concatenate(audio_chunks)
        transcript = await recorder.transcribe_audio(audio_data)

        if not transcript:
            console.print("[yellow]Could not transcribe audio.[/yellow]")
            return StreamResult(response_id=session_response_id)

        # Show transcript and confirm
        console.print(f"\n[green]Transcript:[/green] {transcript}")
        confirm = await session.prompt_async("\nSend this? [Y/n/edit]: ")
        confirm = confirm.strip().lower()

        if confirm in ("n", "no", "cancel"):
            console.print("[dim]Cancelled.[/dim]")
            return StreamResult(response_id=session_response_id)

        if confirm in ("e", "edit"):
            transcript = await session.prompt_async(
                "Edit message: ", default=transcript
            )
            transcript = transcript.strip()
            if not transcript:
                console.print("[dim]Cancelled.[/dim]")
                return StreamResult(response_id=session_response_id)

        # Send to agent
        console.print()
        result = await run_with_streaming(
            client,
            agent_name,
            transcript,
            session,
            previous_response_id=session_response_id,
        )
        # Track in session state if provided
        if session_state and result.success:
            session_state.add_query(
                f"[voice] {transcript}",
                result.output or "",
                agent_name,
                result.tool_calls,
                result.duration_seconds,
            )
        console.print()
        return result

    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        return session_response_id


async def display_config_issues(
    config_issues: list[dict], session=None, client=None
) -> bool:
    """
    Display configuration issues encountered during the run.

    Shows what integrations need to be configured and offers to configure them.

    Returns:
        True if configuration was successful and query should be retried
    """
    # Get unique integrations
    integrations = list(
        {issue.get("integration", "unknown") for issue in config_issues}
    )

    console.print(
        Panel.fit(
            "[bold yellow]Configuration Required[/bold yellow]\n\n"
            "Some integrations are not configured. The agent worked around these\n"
            "limitations, but you can enable them now for full functionality.",
            title="⚠ Missing Configuration",
            border_style="yellow",
        )
    )

    for issue in config_issues:
        integration = issue.get("integration", "unknown").upper()
        missing = issue.get("missing_config", [])

        console.print(f"\n[bold cyan]{integration}[/bold cyan]")

        if missing:
            console.print("[dim]Missing:[/dim]")
            for item in missing:
                console.print(f"  [red]•[/red] {item}")

    # Offer to configure if we have a session
    if session and len(integrations) > 0:
        console.print()
        if len(integrations) == 1:
            integration = integrations[0]
            response = await session.prompt_async(
                f"Configure {integration} now? [Y/n]: "
            )
            if response.lower() in ("", "y", "yes"):
                success = await configure_integration(client, session, integration)
                return success
        else:
            console.print(f"[dim]Unconfigured: {', '.join(integrations)}[/dim]")
            response = await session.prompt_async(
                "Configure which integration? (or press Enter to skip): "
            )
            if response.strip():
                success = await configure_integration(client, session, response.strip())
                return success
    else:
        console.print()
        console.print(
            "[dim]Type 'config <integration>' to configure (e.g., 'config kubernetes')[/dim]"
        )

    return False


def display_result(result: dict):
    """Display successful agent result."""
    output = result.get("output", "No output")
    duration = result.get("duration")

    # Try to render as markdown
    try:
        if isinstance(output, dict):
            import json

            output = json.dumps(output, indent=2)
        console.print(Markdown(str(output)))
    except Exception:
        console.print(output)

    if duration:
        console.print(f"\n[dim]Completed in {duration:.1f}s[/dim]")


def display_error(result: dict):
    """Display error result."""
    error = result.get("error", "Unknown error")
    console.print(f"[red]❌ Error: {error}[/red]")


def display_agents(client: AgentClient):
    """Display available agents."""
    agents = client.list_agents()

    table = Table(title="Available Agents")
    table.add_column("Agent", style="cyan")
    table.add_column("Description")

    descriptions = {
        "planner": "Entry point - orchestrates sub-agents (recommended)",
        "investigation_agent": "Full toolkit - autonomous investigation",
        "k8s_agent": "Kubernetes specialist - pods, logs, events",
        "aws_agent": "AWS specialist - EC2, Lambda, RDS, CloudWatch",
        "metrics_agent": "Performance analysis - anomaly detection",
        "coding_agent": "Code analysis - GitHub, git operations",
        "ci_agent": "CI/CD - GitHub Actions, pipelines",
    }

    for a in agents:
        desc = descriptions.get(a, "")
        table.add_row(a, desc)

    console.print(table)


def display_help():
    """Display help message."""
    help_text = """
## Commands

| Command | Description |
|---------|-------------|
| `!<cmd>` | Run a shell command (e.g., `!ls -la`, `!kubectl get pods`) |
| `help` | Show this help |
| `/config` | Show integration config status |
| `/config <name>` | Configure an integration (e.g., `/config kubernetes`) |
| `/context` | Show local context (K8s, Git, AWS, key_context.txt) |
| `/context edit` | Edit key_context.txt (team knowledge, common issues) |
| `/clear` | Clear screen |
| `/new` | Start a new conversation |
| `quit` | Exit CLI |

## Agent Management

| Command | Description |
|---------|-------------|
| `/agents` | List all agents with status |
| `/agents use <name>` | Switch to a different agent |
| `/agents info [name]` | Show agent details and sub-agent topology |
| `/agents tools [name]` | List tools available to an agent |
| `/agents config` | Show all agent configurations |
| `/agents config <name>` | Show specific agent configuration |
| `/agents config <name> set <key> <value>` | Update agent config |
| `/agents reload` | Reload configuration from config service |

**Config Examples**:
- `/agents config planner set model.temperature 0.5`
- `/agents config k8s_agent set timeout_seconds 180`
- `/agents config planner set enabled false`

## Knowledge Base (RAG)

| Command | Description |
|---------|-------------|
| `/rag` | Show RAG command help |
| `/rag <query>` | Search & answer via agent (AI-synthesized) |
| `/rag search <query>` | Search directly (raw results) |
| `/rag trees` | List available knowledge trees |
| `/rag add <text>` | Add text content to knowledge base |
| `/rag upload <file>` | Upload file to knowledge base |

**Note**: Requires RAPTOR service running (`make start-raptor`)

## Multimodal Input

| Command | Description |
|---------|-------------|
| `/voice` | Record voice and transcribe (requires sounddevice, openai) |
| `/image <path>` | Send an image for analysis |
| `/image <path> <prompt>` | Send an image with a custom prompt |
| *drag & drop* | Drop an image file into the terminal to analyze it |

**Voice Recording**: Press Enter to start, Enter again to stop. Requires:
- `pip install sounddevice soundfile openai`
- `OPENAI_API_KEY` environment variable

**Image Support**: Drag/drop image files or use `/image /path/to/file.png`.
Supports: PNG, JPG, JPEG, GIF, WebP, BMP

## Session Management

| Command | Description |
|---------|-------------|
| `/tokens` | Show session statistics (queries, tool calls, duration) |
| `/stats` | Alias for `/tokens` |
| `/export` | Export conversation to markdown file |
| `/export json` | Export conversation to JSON file |
| `/export <file>` | Export to specific filename |

## How It Works

The **planner** agent is the entry point. It analyzes your query and delegates
to specialized sub-agents:

- **K8s Agent** - Kubernetes issues (pods, logs, events, deployments)
- **AWS Agent** - AWS resources (EC2, Lambda, RDS, CloudWatch)
- **Metrics Agent** - Performance analysis and anomaly detection
- **Coding Agent** - Code review, GitHub operations
- **Investigation Agent** - Full autonomous investigation with all tools

## Example Prompts

```
Check if there are any k8s pods crashing
```
```
Check if there's any grafana metric anomaly
```
```
What GitHub PRs were merged in the last 24 hours?
```
"""
    console.print(Markdown(help_text))


# All supported integrations and their required env vars
INTEGRATIONS = {
    # Core
    "kubernetes": {
        "name": "Kubernetes",
        "required": [],  # Special handling - checks K8S_ENABLED + kubeconfig
        "optional": ["K8S_ENABLED"],
        "check": "k8s",
    },
    "aws": {
        "name": "AWS",
        "required": [],  # Special handling - checks credentials
        "optional": ["AWS_REGION", "AWS_ACCESS_KEY_ID"],
        "check": "aws",
    },
    # Code & Version Control
    "github": {
        "name": "GitHub",
        "required": ["GITHUB_TOKEN"],
        "env_hint": "GITHUB_TOKEN=ghp_...",
    },
    "gitlab": {
        "name": "GitLab",
        "required": ["GITLAB_TOKEN"],
        "optional": ["GITLAB_URL"],
        "env_hint": "GITLAB_TOKEN=glpat-...",
    },
    "sourcegraph": {
        "name": "Sourcegraph",
        "required": ["SOURCEGRAPH_TOKEN", "SOURCEGRAPH_URL"],
        "env_hint": "SOURCEGRAPH_TOKEN=...",
    },
    # Communication
    "slack": {
        "name": "Slack",
        "required": ["SLACK_BOT_TOKEN"],
        "optional": ["SLACK_APP_TOKEN"],
        "env_hint": "SLACK_BOT_TOKEN=xoxb-...",
    },
    "msteams": {
        "name": "MS Teams",
        "required": ["MSTEAMS_WEBHOOK_URL"],
        "env_hint": "MSTEAMS_WEBHOOK_URL=https://...",
    },
    # Observability
    "datadog": {
        "name": "Datadog",
        "required": ["DATADOG_API_KEY"],
        "optional": ["DATADOG_APP_KEY"],
        "env_hint": "DATADOG_API_KEY=...",
    },
    "grafana": {
        "name": "Grafana",
        "required": ["GRAFANA_URL", "GRAFANA_API_KEY"],
        "env_hint": "GRAFANA_URL=https://...",
    },
    "newrelic": {
        "name": "New Relic",
        "required": ["NEWRELIC_API_KEY"],
        "env_hint": "NEWRELIC_API_KEY=...",
    },
    "coralogix": {
        "name": "Coralogix",
        "required": ["CORALOGIX_API_KEY"],
        "env_hint": "CORALOGIX_API_KEY=...",
    },
    "splunk": {
        "name": "Splunk",
        "required": ["SPLUNK_HOST", "SPLUNK_TOKEN"],
        "env_hint": "SPLUNK_HOST=...",
    },
    "elasticsearch": {
        "name": "Elasticsearch",
        "required": ["ELASTICSEARCH_URL"],
        "optional": ["ELASTICSEARCH_USERNAME", "ELASTICSEARCH_PASSWORD"],
        "env_hint": "ELASTICSEARCH_URL=https://...",
    },
    "sentry": {
        "name": "Sentry",
        "required": ["SENTRY_AUTH_TOKEN"],
        "optional": ["SENTRY_ORGANIZATION", "SENTRY_PROJECT"],
        "env_hint": "SENTRY_AUTH_TOKEN=...",
    },
    # Ticketing & Incidents
    "jira": {
        "name": "Jira",
        "required": ["JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"],
        "env_hint": "JIRA_URL=https://...",
    },
    "linear": {
        "name": "Linear",
        "required": ["LINEAR_API_KEY"],
        "env_hint": "LINEAR_API_KEY=lin_api_...",
    },
    "pagerduty": {
        "name": "PagerDuty",
        "required": ["PAGERDUTY_API_KEY"],
        "env_hint": "PAGERDUTY_API_KEY=...",
    },
    # Documentation
    "confluence": {
        "name": "Confluence",
        "required": ["CONFLUENCE_URL", "CONFLUENCE_USERNAME", "CONFLUENCE_API_TOKEN"],
        "env_hint": "CONFLUENCE_URL=https://...",
    },
    "notion": {
        "name": "Notion",
        "required": ["NOTION_API_KEY"],
        "env_hint": "NOTION_API_KEY=secret_...",
    },
    # Data
    "bigquery": {
        "name": "BigQuery",
        "required": ["BIGQUERY_PROJECT_ID"],
        "optional": ["BIGQUERY_DATASET"],
        "env_hint": "BIGQUERY_PROJECT_ID=...",
    },
    "postgres": {
        "name": "PostgreSQL",
        "required": ["POSTGRES_TOOLS_URL"],
        "env_hint": "POSTGRES_TOOLS_URL=postgresql://...",
    },
    "snowflake": {
        "name": "Snowflake",
        "required": ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"],
        "env_hint": "SNOWFLAKE_ACCOUNT=...",
    },
    # Knowledge Base
    "raptor": {
        "name": "RAPTOR (RAG)",
        "required": ["RAPTOR_URL"],
        "optional": ["RAPTOR_DEFAULT_TREE"],
        "env_hint": "RAPTOR_URL=http://localhost:8000",
    },
    # Search
    "tavily": {
        "name": "Tavily (Web Search)",
        "required": ["TAVILY_API_KEY"],
        "env_hint": "TAVILY_API_KEY=tvly-...",
    },
}


async def show_config_status(client: AgentClient):
    """Show status of all integration configurations from .env."""
    table = Table(title="Integration Configuration Status (.env)")
    table.add_column("Integration", style="cyan")
    table.add_column("Status")
    table.add_column("Notes")

    configured_count = 0

    for int_id, int_config in INTEGRATIONS.items():
        name = int_config["name"]

        # Special handling for certain integrations
        if int_config.get("check") == "k8s":
            status, notes = _check_k8s_config()
        elif int_config.get("check") == "aws":
            status, notes = _check_aws_config()
        else:
            status, notes = _check_env_config(int_config)

        if "✓" in status:
            configured_count += 1

        table.add_row(name, status, notes)

    console.print(table)
    console.print(
        f"\n[dim]{configured_count}/{len(INTEGRATIONS)} integrations configured[/dim]"
    )
    console.print(
        "[dim]Use '/config <name>' to configure (e.g., '/config github')[/dim]"
    )


def _check_k8s_config() -> tuple[str, str]:
    """Check Kubernetes configuration status."""
    k8s_enabled = os.getenv("K8S_ENABLED", "false").lower() == "true"
    kubeconfig = Path.home() / ".kube" / "config"

    if k8s_enabled and kubeconfig.exists():
        return "[green]✓ Configured[/green]", "K8S_ENABLED + kubeconfig"
    elif kubeconfig.exists():
        return "[yellow]⚠ Disabled[/yellow]", "Set K8S_ENABLED=true"
    else:
        return "[dim]○ Not configured[/dim]", "No kubeconfig"


def _check_aws_config() -> tuple[str, str]:
    """Check AWS configuration status."""
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    has_env_creds = os.getenv("AWS_ACCESS_KEY_ID")
    has_file_creds = os.path.exists(os.path.expanduser("~/.aws/credentials"))

    if region and (has_env_creds or has_file_creds):
        return "[green]✓ Configured[/green]", f"Region: {region}"
    elif has_env_creds or has_file_creds:
        return "[yellow]⚠ Partial[/yellow]", "Set AWS_REGION"
    else:
        return "[dim]○ Not configured[/dim]", "No credentials"


def _check_env_config(int_config: dict) -> tuple[str, str]:
    """Check if required env vars are set for an integration."""
    required = int_config.get("required", [])
    optional = int_config.get("optional", [])
    env_hint = int_config.get("env_hint", "")

    if not required:
        return "[dim]○ Optional[/dim]", ""

    # Check which required vars are set
    set_vars = [v for v in required if os.getenv(v)]
    missing_vars = [v for v in required if not os.getenv(v)]

    if len(set_vars) == len(required):
        # All required vars set
        notes = ", ".join(set_vars)
        if len(notes) > 30:
            notes = f"{len(set_vars)} vars set"
        return "[green]✓ Configured[/green]", notes
    elif set_vars:
        # Partial
        return "[yellow]⚠ Partial[/yellow]", f"Missing: {missing_vars[0]}"
    else:
        # Not configured
        hint = env_hint.split("=")[0] if env_hint else required[0]
        return "[dim]○ Not configured[/dim]", f"Set {hint}"


def get_env_file_path() -> str:
    """Get the path to the .env file."""
    # Look for .env in current directory or local/ directory
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.getcwd(), "local", ".env"),
        os.path.expanduser("~/.incidentfox/.env"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    # Default to local/.env if none found
    return os.path.join(os.getcwd(), "local", ".env")


def read_env_file(path: str) -> dict[str, str]:
    """Read .env file into a dictionary."""
    env_vars = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    # Remove quotes if present
                    value = value.strip().strip('"').strip("'")
                    env_vars[key.strip()] = value
    return env_vars


def write_env_file(path: str, env_vars: dict[str, str], preserve_comments: bool = True):
    """Write environment variables to .env file, preserving comments and order."""
    lines = []
    existing_keys = set()

    # Read existing file to preserve comments and order
    if os.path.exists(path) and preserve_comments:
        with open(path) as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in env_vars:
                        # Update existing value
                        lines.append(f"{key}={env_vars[key]}\n")
                        existing_keys.add(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

    # Add new keys at the end
    for key, value in env_vars.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}\n")

    # Ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w") as f:
        f.writelines(lines)


def update_env_var(key: str, value: str) -> bool:
    """Update a single environment variable in .env file."""
    try:
        env_path = get_env_file_path()
        env_vars = read_env_file(env_path)
        env_vars[key] = value
        write_env_file(env_path, env_vars)
        # Also update current process environment
        os.environ[key] = value
        return True
    except Exception as e:
        console.print(f"[red]Failed to update .env: {e}[/red]")
        return False


def _find_local_dir() -> str | None:
    """Find the local directory containing docker-compose.yml.

    Searches in order of preference:
    1. INCIDENTFOX_LOCAL_DIR environment variable
    2. ./local (relative to cwd)
    3. . (cwd itself)
    4. Relative to __file__ (fallback for development)

    Returns the path if found, None otherwise.
    """
    # Check environment variable first
    env_dir = os.getenv("INCIDENTFOX_LOCAL_DIR")
    if env_dir and os.path.exists(os.path.join(env_dir, "docker-compose.yml")):
        return env_dir

    # Check common locations relative to cwd
    candidates = [
        os.path.join(os.getcwd(), "local"),
        os.getcwd(),
        # Fallback: relative to this file (works in development)
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ]

    for candidate in candidates:
        if os.path.exists(os.path.join(candidate, "docker-compose.yml")):
            return candidate

    return None


async def restart_agent_service() -> bool:
    """Recreate agent container to apply new config.

    Returns:
        True if restart was successful, False otherwise.
    """
    console.print("\n[dim]Recreating agent service to apply new config...[/dim]")
    try:
        import subprocess

        local_dir = _find_local_dir()
        if not local_dir:
            console.print(
                "[yellow]Could not find docker-compose.yml in expected locations[/yellow]"
            )
            console.print(
                "[dim]Searched: ./local, ., and relative to CLI installation[/dim]"
            )
            console.print(
                "[dim]Set INCIDENTFOX_LOCAL_DIR to specify the correct path[/dim]"
            )
            raise FileNotFoundError("docker-compose.yml not found")

        # Check if dev compose file exists (mounts local source code)
        dev_compose = os.path.join(local_dir, "docker-compose.dev.yml")
        if os.path.exists(dev_compose):
            # Use dev compose to mount local source code
            cmd = [
                "docker-compose",
                "-f",
                "docker-compose.yml",
                "-f",
                "docker-compose.dev.yml",
                "up",
                "-d",
                "--force-recreate",
                "agent",
            ]
        else:
            # Standard compose (pre-built image)
            cmd = ["docker-compose", "up", "-d", "--force-recreate", "agent"]

        # Must use 'up -d --force-recreate' to reload .env file
        # docker-compose restart does NOT reload env vars
        result = subprocess.run(
            cmd,
            cwd=local_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            console.print("[green]✓ Agent service recreated with new config![/green]")
            console.print("[dim]Waiting for service to be ready...[/dim]")
            import asyncio

            await asyncio.sleep(5)
            return True
        else:
            console.print(f"[yellow]Could not recreate: {result.stderr}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Could not recreate: {e}[/yellow]")

    console.print("\n[yellow]Please recreate the agent manually:[/yellow]")
    console.print(
        "  [cyan]cd local && docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate agent[/cyan]"
    )
    return False


async def configure_integration(client: AgentClient, session, integration: str) -> bool:
    """Interactive configuration for an integration.

    Returns:
        True if configuration was successful
    """
    integration = integration.lower()

    # Map aliases
    aliases = {"k8s": "kubernetes"}
    integration = aliases.get(integration, integration)

    # Check if integration exists
    if integration not in INTEGRATIONS:
        console.print(f"[red]Unknown integration: {integration}[/red]")
        available = ", ".join(sorted(INTEGRATIONS.keys()))
        console.print(f"[dim]Available: {available}[/dim]")
        return False

    # Special handlers for complex integrations
    if integration == "kubernetes":
        return await configure_kubernetes(session)
    elif integration == "aws":
        return await configure_aws(session)
    elif integration == "github":
        return await configure_github(session)
    elif integration == "slack":
        return await configure_slack(session)
    else:
        # Generic handler for integrations that need env vars
        return await configure_generic_integration(session, integration)


async def configure_kubernetes(session) -> bool:
    """Interactive Kubernetes configuration - auto-enables if kubeconfig exists.

    Returns:
        True if configuration was successful
    """
    from pathlib import Path

    console.print(
        Panel.fit(
            "[bold cyan]Kubernetes Configuration[/bold cyan]",
            title="🔧 Configure Kubernetes",
        )
    )

    kubeconfig = Path.home() / ".kube" / "config"
    k8s_enabled = os.getenv("K8S_ENABLED", "false").lower() == "true"

    if kubeconfig.exists():
        console.print(f"[green]✓[/green] Found kubeconfig at {kubeconfig}")

        # Read current context
        try:
            import yaml

            with open(kubeconfig) as f:
                kc = yaml.safe_load(f)
                current = kc.get("current-context", "unknown")
                contexts = [c["name"] for c in kc.get("contexts", [])]
                console.print(
                    f"[green]✓[/green] Current context: [cyan]{current}[/cyan]"
                )
                if len(contexts) > 1:
                    console.print(f"[dim]  Available: {', '.join(contexts)}[/dim]")
        except Exception:
            pass

        if not k8s_enabled:
            # Auto-enable K8s
            console.print("\n[yellow]K8S_ENABLED is currently 'false'[/yellow]")
            response = await session.prompt_async(
                "Enable Kubernetes integration? [Y/n]: "
            )
            if response.lower() in ("", "y", "yes"):
                if update_env_var("K8S_ENABLED", "true"):
                    console.print("[green]✓ K8S_ENABLED=true saved to .env[/green]")
                    restart_success = await restart_agent_service()
                    if restart_success:
                        console.print(
                            "\n[green]✓ Kubernetes is now configured![/green]"
                        )
                        return True
                    else:
                        console.print(
                            "\n[yellow]Config saved but service restart failed.[/yellow]"
                        )
                        console.print(
                            "[yellow]Please restart manually, then retry your query.[/yellow]"
                        )
                        return False
                else:
                    console.print("[red]Failed to update .env file[/red]")
                    return False
            else:
                console.print("[dim]Skipped.[/dim]")
                return False
        else:
            console.print("\n[green]✓ Kubernetes is fully configured![/green]")
            return True  # Already configured
    else:
        console.print(f"[red]✗[/red] No kubeconfig found at {kubeconfig}")
        console.print("\n[yellow]To set up Kubernetes:[/yellow]")
        console.print("  1. If you have kubectl configured elsewhere:")
        console.print("     [cyan]cp /path/to/kubeconfig ~/.kube/config[/cyan]")
        console.print("  2. Or connect to a cluster:")
        console.print("     [cyan]kubectl config set-cluster ...[/cyan]")
        console.print("\nThen run [cyan]config kubernetes[/cyan] again.")
        return False


async def configure_aws(session) -> bool:
    """Interactive AWS configuration - prompts for region and credentials.

    Returns:
        True if configuration was successful
    """
    console.print(
        Panel.fit(
            "[bold cyan]AWS Configuration[/bold cyan]",
            title="🔧 Configure AWS",
        )
    )

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    has_creds = os.getenv("AWS_ACCESS_KEY_ID") or os.path.exists(
        os.path.expanduser("~/.aws/credentials")
    )
    changes_made = False

    # Check credentials
    if has_creds:
        console.print("[green]✓[/green] AWS credentials found")
    else:
        console.print("[red]✗[/red] No AWS credentials found")
        console.print("\n[yellow]Do you want to configure AWS credentials?[/yellow]")
        response = await session.prompt_async(
            "Enter AWS Access Key ID (or press Enter to skip): "
        )
        if response.strip():
            access_key = response.strip()
            secret_key = await session.prompt_async("Enter AWS Secret Access Key: ")
            if secret_key.strip():
                update_env_var("AWS_ACCESS_KEY_ID", access_key)
                update_env_var("AWS_SECRET_ACCESS_KEY", secret_key.strip())
                console.print("[green]✓ AWS credentials saved to .env[/green]")
                changes_made = True
                has_creds = True

    # Check region
    if region:
        console.print(f"[green]✓[/green] AWS_REGION: [cyan]{region}[/cyan]")
    else:
        console.print("\n[yellow]AWS_REGION not set[/yellow]")
        response = await session.prompt_async(
            "Enter AWS region (e.g., us-west-2, us-east-1): "
        )
        if response.strip():
            update_env_var("AWS_REGION", response.strip())
            console.print(
                f"[green]✓ AWS_REGION={response.strip()} saved to .env[/green]"
            )
            changes_made = True
            region = response.strip()

    if changes_made:
        restart_success = await restart_agent_service()
        if restart_success:
            console.print("\n[green]✓ AWS is now configured![/green]")
            return True
        else:
            console.print("\n[yellow]Config saved but service restart failed.[/yellow]")
            console.print(
                "[yellow]Please restart manually, then retry your query.[/yellow]"
            )
            return False
    elif has_creds and region:
        console.print("\n[green]✓ AWS is fully configured![/green]")
        return True

    return False


async def configure_github(session) -> bool:
    """Interactive GitHub configuration - prompts for token.

    Returns:
        True if configuration was successful
    """
    console.print(
        Panel.fit(
            "[bold cyan]GitHub Configuration[/bold cyan]",
            title="🔧 Configure GitHub",
        )
    )

    token = os.getenv("GITHUB_TOKEN")
    if token:
        # Show masked token
        masked = token[:4] + "..." + token[-4:] if len(token) > 8 else "***"
        console.print(f"[green]✓[/green] GITHUB_TOKEN is set ({masked})")
        response = await session.prompt_async("Update token? [y/N]: ")
        if response.lower() not in ("y", "yes"):
            console.print("\n[green]✓ GitHub is configured![/green]")
            return True  # Already configured

    if not token:
        console.print("[yellow]GITHUB_TOKEN not set[/yellow]")
        console.print("\n[dim]To get a token:[/dim]")
        console.print("  1. Go to [cyan]https://github.com/settings/tokens[/cyan]")
        console.print("  2. Create a token with 'repo' and 'read:org' scopes")

    console.print()
    new_token = await session.prompt_async("Paste your GitHub token (ghp_...): ")
    if new_token.strip():
        should_save = False
        if new_token.strip().startswith("ghp_") or new_token.strip().startswith(
            "github_"
        ):
            should_save = True
        else:
            console.print(
                "[yellow]Token doesn't look like a GitHub token (should start with ghp_ or github_)[/yellow]"
            )
            confirm = await session.prompt_async("Save anyway? [y/N]: ")
            if confirm.lower() in ("y", "yes"):
                should_save = True

        if should_save:
            update_env_var("GITHUB_TOKEN", new_token.strip())
            console.print("[green]✓ GITHUB_TOKEN saved to .env[/green]")
            restart_success = await restart_agent_service()
            if restart_success:
                console.print("\n[green]✓ GitHub is now configured![/green]")
                return True
            else:
                console.print(
                    "\n[yellow]Config saved but service restart failed.[/yellow]"
                )
                console.print(
                    "[yellow]Please restart manually, then retry your query.[/yellow]"
                )
                return False
    else:
        console.print("[dim]Skipped.[/dim]")

    return False


async def configure_slack(session) -> bool:
    """Interactive Slack configuration - prompts for token.

    Returns:
        True if configuration was successful
    """
    console.print(
        Panel.fit(
            "[bold cyan]Slack Configuration[/bold cyan]",
            title="🔧 Configure Slack",
        )
    )

    token = os.getenv("SLACK_BOT_TOKEN")
    if token:
        console.print("[green]✓[/green] SLACK_BOT_TOKEN is set")
        response = await session.prompt_async("Update token? [y/N]: ")
        if response.lower() not in ("y", "yes"):
            console.print("\n[green]✓ Slack is configured![/green]")
            return True  # Already configured

    if not token:
        console.print("[dim]SLACK_BOT_TOKEN not set (optional integration)[/dim]")
        console.print("\n[dim]To get a token:[/dim]")
        console.print("  1. Create app at [cyan]https://api.slack.com/apps[/cyan]")
        console.print("  2. Add scopes: channels:history, channels:read, chat:write")
        console.print("  3. Install to workspace and copy Bot Token")

    console.print()
    new_token = await session.prompt_async("Paste your Slack Bot Token (xoxb-...): ")
    if new_token.strip():
        should_save = False
        if new_token.strip().startswith("xoxb-"):
            should_save = True
        else:
            console.print(
                "[yellow]Token doesn't look like a Slack bot token (should start with xoxb-)[/yellow]"
            )
            confirm = await session.prompt_async("Save anyway? [y/N]: ")
            if confirm.lower() in ("y", "yes"):
                should_save = True

        if should_save:
            update_env_var("SLACK_BOT_TOKEN", new_token.strip())
            console.print("[green]✓ SLACK_BOT_TOKEN saved to .env[/green]")
            restart_success = await restart_agent_service()
            if restart_success:
                console.print("\n[green]✓ Slack is now configured![/green]")
                return True
            else:
                console.print(
                    "\n[yellow]Config saved but service restart failed.[/yellow]"
                )
                console.print(
                    "[yellow]Please restart manually, then retry your query.[/yellow]"
                )
                return False
    else:
        console.print("[dim]Skipped.[/dim]")

    return False


async def configure_generic_integration(session, integration: str) -> bool:
    """Generic configuration for integrations that need env vars.

    Returns:
        True if configuration was successful
    """
    int_config = INTEGRATIONS.get(integration)
    if not int_config:
        console.print(f"[red]Unknown integration: {integration}[/red]")
        return False

    name = int_config["name"]
    required = int_config.get("required", [])
    optional = int_config.get("optional", [])
    env_hint = int_config.get("env_hint", "")

    console.print(
        Panel.fit(
            f"[bold cyan]{name} Configuration[/bold cyan]",
            title=f"🔧 Configure {name}",
        )
    )

    if not required:
        console.print(f"[dim]{name} has no required configuration.[/dim]")
        return True

    changes_made = False
    all_set = True

    # Check and configure required variables
    for var in required:
        current = os.getenv(var)
        if current:
            # Show masked value
            if (
                "token" in var.lower()
                or "key" in var.lower()
                or "password" in var.lower()
            ):
                masked = (
                    current[:4] + "..." + current[-4:] if len(current) > 8 else "***"
                )
                console.print(f"[green]✓[/green] {var} is set ({masked})")
            else:
                console.print(f"[green]✓[/green] {var} = {current}")
        else:
            all_set = False
            console.print(f"[yellow]○[/yellow] {var} not set")

    if all_set:
        response = await session.prompt_async("Update configuration? [y/N]: ")
        if response.lower() not in ("y", "yes"):
            console.print(f"\n[green]✓ {name} is configured![/green]")
            return True

    # Get hint for how values should look
    if env_hint and not all_set:
        console.print(f"\n[dim]Format hint: {env_hint}[/dim]")

    console.print()

    # Prompt for each required variable
    for var in required:
        current = os.getenv(var)
        prompt_text = f"Enter {var}"
        if current:
            prompt_text += " (press Enter to keep current)"
        prompt_text += ": "

        value = await session.prompt_async(prompt_text)
        value = value.strip()

        if value:
            update_env_var(var, value)
            console.print(f"[green]✓[/green] {var} saved to .env")
            changes_made = True
        elif not current:
            console.print(f"[yellow]⚠[/yellow] {var} skipped (still required)")

    # Optionally configure optional variables
    if optional and changes_made:
        console.print(f"\n[dim]Optional variables: {', '.join(optional)}[/dim]")
        response = await session.prompt_async("Configure optional variables? [y/N]: ")
        if response.lower() in ("y", "yes"):
            for var in optional:
                current = os.getenv(var)
                prompt_text = f"Enter {var}"
                if current:
                    prompt_text += f" (current: {current})"
                prompt_text += ": "

                value = await session.prompt_async(prompt_text)
                value = value.strip()
                if value:
                    update_env_var(var, value)
                    console.print(f"[green]✓[/green] {var} saved to .env")

    if changes_made:
        restart_success = await restart_agent_service()
        if restart_success:
            console.print(f"\n[green]✓ {name} is now configured![/green]")
            return True
        else:
            console.print("\n[yellow]Config saved but service restart failed.[/yellow]")
            console.print(
                "[yellow]Please restart manually, then retry your query.[/yellow]"
            )
            return False
    else:
        console.print("[dim]No changes made.[/dim]")
        return False


if __name__ == "__main__":
    main()
