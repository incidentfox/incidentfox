#!/usr/bin/env python3
"""
Local e2e test: loads team config via TEAM_TOKEN, constructs a Claude agent
with Method 3 (systemPrompt append), and runs a query.

Prerequisites:
  - kubectl port-forward -n incidentfox svc/incidentfox-config-service 18082:8080
  - ANTHROPIC_API_KEY set (or run through credential proxy)

Usage:
  .venv/bin/python3 test_e2e_local.py
"""

import asyncio
import json
import os
import sys
import time

# ── Step 0: Setup ───────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

# Ensure venv's python is on PATH so skill scripts (`python ...`) work
venv_bin = os.path.join(os.path.dirname(__file__), ".venv", "bin")
if os.path.isdir(venv_bin):
    os.environ["PATH"] = venv_bin + ":" + os.environ.get("PATH", "")

CONFIG_SERVICE_URL = os.environ.get("CONFIG_SERVICE_URL", "http://localhost:18082")
ADMIN_TOKEN = os.environ.get(
    "CONFIG_SERVICE_ADMIN_TOKEN",
    "JZzFK8FVfWnPjPgPUj8laL9H-IjbFTmq2jffvPrUfNLSYSSvUHPZpu9XRug6n8-y",
)


async def main():
    import httpx
    from claude_agent_sdk import (
        AgentDefinition,
        ClaudeAgentOptions,
    )
    from claude_agent_sdk import (
        query as claude_query,
    )

    # ── Step 1: Issue team token for otel-demo ──────────────────────────────
    print("=" * 60)
    print("Step 1: Issuing team token for incidentfox-demo/otel-demo")
    print("=" * 60)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{CONFIG_SERVICE_URL}/api/v1/admin/orgs/incidentfox-demo/teams/otel-demo/tokens",
            headers={
                "Authorization": f"Bearer {ADMIN_TOKEN}",
                "Content-Type": "application/json",
            },
            json={},
            timeout=10,
        )
        resp.raise_for_status()
        team_token = resp.json()["token"]
    print(f"  Token: {team_token[:20]}...")

    # ── Step 2: Load team config using TEAM_TOKEN (same as production) ──────
    print("\n" + "=" * 60)
    print("Step 2: Loading team config via Bearer token auth")
    print("=" * 60)
    os.environ["TEAM_TOKEN"] = team_token
    os.environ["CONFIG_SERVICE_URL"] = CONFIG_SERVICE_URL

    from config import get_root_agent_config, load_team_config

    team_config = load_team_config()
    print(f"  Agents: {len(team_config.agents)}")
    print(f"  Agent names: {list(team_config.agents.keys())}")
    print(f"  Business context: {len(team_config.business_context)} chars")
    if team_config.business_context:
        print(f"  BC preview: {team_config.business_context[:120]}...")

    # ── Step 3: Resolve root agent and build system prompt ──────────────────
    print("\n" + "=" * 60)
    print("Step 3: Resolving root agent and building config")
    print("=" * 60)
    root_config = get_root_agent_config(team_config)
    print(f"  Root agent: {root_config.name}")
    print(f"  System prompt: {len(root_config.prompt.system)} chars")
    print(f"  Prompt preview: {root_config.prompt.system[:150]}...")

    # ── Step 4: Build subagents from config ─────────────────────────────────
    print("\n" + "=" * 60)
    print("Step 4: Building subagents from config")
    print("=" * 60)
    subagents = {}
    root_name = root_config.name
    for name, agent_cfg in team_config.agents.items():
        if name == root_name or not agent_cfg.enabled:
            continue
        if agent_cfg.prompt.system:
            subagents[name] = AgentDefinition(
                description=agent_cfg.prompt.prefix or f"{name} specialist",
                prompt=agent_cfg.prompt.system,
                tools=(
                    agent_cfg.tools.enabled
                    if agent_cfg.tools.enabled != ["*"]
                    else None
                ),
            )
    print(f"  Subagents ({len(subagents)}): {list(subagents.keys())}")

    # ── Step 5: Build ClaudeAgentOptions (Method 3: append) ─────────────────
    print("\n" + "=" * 60)
    print("Step 5: Building ClaudeAgentOptions (Method 3: preset + append)")
    print("=" * 60)

    allowed_tools = [
        "Bash",
        "Read",
        "Glob",
        "Grep",
        "Skill",
    ]

    # Use cwd with .claude/skills
    cwd = os.path.dirname(__file__)

    options = ClaudeAgentOptions(
        cwd=cwd,
        allowed_tools=allowed_tools,
        permission_mode="acceptEdits",
        include_partial_messages=True,
        setting_sources=["user", "project"],
        # agents=subagents,  # Disabled: OpenAI max 128 tools
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": root_config.prompt.system,
        },
    )
    print(f"  cwd: {cwd}")
    print(f"  allowed_tools: {allowed_tools}")
    print("  system_prompt type: preset + append")
    print(f"  subagents: {len(subagents)}")

    # ── Step 6: Run a query ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Step 6: Running query")
    print("=" * 60)

    prompt = "Use the metrics-analysis skill to check Grafana dashboards and query some Prometheus metrics for our otel-demo services. List available dashboards and check error rates."

    # Timeouts
    TOTAL_TIMEOUT = int(os.environ.get("E2E_TIMEOUT", "180"))  # 3 min total
    IDLE_TIMEOUT = int(os.environ.get("E2E_IDLE_TIMEOUT", "60"))  # 60s no activity

    print(f"  Prompt: {prompt}")
    print(f"  Timeout: {TOTAL_TIMEOUT}s total, {IDLE_TIMEOUT}s idle")
    print("  Streaming...\n")

    message_count = 0
    assistant_count = 0
    tool_count = 0
    start_time = time.monotonic()
    last_activity = start_time

    try:
        async for message in claude_query(prompt=prompt, options=options):
            now = time.monotonic()
            elapsed = now - start_time
            now - last_activity
            last_activity = now
            message_count += 1
            msg_type = type(message).__name__

            # Check total timeout
            if elapsed > TOTAL_TIMEOUT:
                print(
                    f"\n  TIMEOUT: Total timeout ({TOTAL_TIMEOUT}s) exceeded after {message_count} events"
                )
                break

            if msg_type == "AssistantMessage":
                assistant_count += 1
                content = getattr(message, "content", None) or getattr(
                    message, "message", {}
                )
                if hasattr(content, "content"):
                    content = content.content
                if isinstance(content, list):
                    for block in content:
                        if hasattr(block, "text") and block.text:
                            print(f"  [{elapsed:.0f}s] [ASSISTANT] {block.text[:500]}")
                        elif hasattr(block, "name"):
                            tool_count += 1
                            inp = json.dumps(getattr(block, "input", {}))[:100]
                            print(
                                f"  [{elapsed:.0f}s] [TOOL_USE] {block.name}({inp}...)"
                            )
                else:
                    print(f"  [{elapsed:.0f}s] [ASSISTANT] {str(content)[:300]}")
            elif msg_type == "ResultMessage":
                text = (
                    getattr(message, "text", "")
                    or getattr(message, "content", "")
                    or ""
                )
                print(f"\n  [{elapsed:.0f}s] [RESULT] {str(text)[:500]}")
            elif msg_type == "SystemMessage":
                subtype = getattr(message, "subtype", "")
                print(f"  [{elapsed:.0f}s] [SYSTEM:{subtype}]")
            elif msg_type == "StreamEvent":
                pass  # Skip stream events (too noisy)
            else:
                pass  # Skip unknown types

    except asyncio.CancelledError:
        print("\n  Query cancelled.")
    except Exception as e:
        print(f"\n  ERROR: {type(e).__name__}: {e}")

    total_elapsed = time.monotonic() - start_time
    print(f"\n  Total events: {message_count}")
    print(f"  Assistant turns: {assistant_count}")
    print(f"  Tool uses: {tool_count}")
    print(f"  Wall time: {total_elapsed:.1f}s")
    print("\n" + "=" * 60)
    print("E2E test complete!")
    print("=" * 60)


if __name__ == "__main__":
    hard_timeout = int(os.environ.get("E2E_TIMEOUT", "180")) + 30  # grace period

    async def run_with_timeout():
        try:
            await asyncio.wait_for(main(), timeout=hard_timeout)
        except asyncio.TimeoutError:
            print(f"\n  HARD TIMEOUT: Process killed after {hard_timeout}s")
            sys.exit(1)

    asyncio.run(run_with_timeout())
