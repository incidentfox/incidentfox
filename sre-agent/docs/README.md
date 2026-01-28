# SRE Agent - Overview

**Claude SDK-based agent for interactive incident investigation.**

---

## What is SRE Agent?

A separate agent system using Claude's Agent SDK (not OpenAI Agents SDK) that runs investigations in isolated Kubernetes sandboxes.

**Key Differences from Main Agent**:

| Feature | SRE Agent (Claude SDK) | Main Agent (OpenAI SDK) |
|---------|------------------------|-------------------------|
| **Execution** | Isolated K8s sandboxes | Shared pod |
| **Interaction** | Interactive (supports interrupt) | Automated workflows |
| **Tools** | Built-in only (Read, Edit, Bash, Grep, Glob) | 100+ custom tools + MCPs |
| **Use Case** | Exploratory debugging | Automated operations |
| **State** | Persistent filesystem (2 hours) | Stateless |

---

## When to Use SRE Agent vs Main Agent?

**Use SRE Agent for**:
- Interactive code investigation (user guides exploration)
- Debugging unknown issues (need to pivot/interrupt)
- Pair programming sessions
- Learning/exploring codebases

**Use Main Agent for**:
- Automated incident response (PagerDuty → investigate → remediate)
- Scheduled operations (CI/CD bots, health reports)
- Multi-agent workflows (planner delegates to sub-agents)
- Operations requiring integrations (Slack, GitHub, Datadog, etc.)

See: `/sre-agent/docs/SDK_COMPARISON.md` for detailed comparison.

---

## Architecture

```
External Request
    ↓ POST /investigate
sre-agent/server.py (Investigation Server)
    ↓ creates/reuses K8s Sandbox
sandbox_manager.py
    ↓ sends to Router
Sandbox Router (routes by X-Sandbox-ID header)
    ↓ HTTP POST to sandbox pod's port 8888
Sandbox Pod (investigation-thread-abc)
    ├── sandbox_server.py (FastAPI on port 8888)
    ├── agent.py (InteractiveAgentSession)
    └── ClaudeSDKClient (maintains conversation)
```

See: `/sre-agent/docs/SANDBOX_ARCHITECTURE.md`

---

## Interrupt/Resume Support

**Key Feature**: Can interrupt mid-execution and resume.

```bash
# Start investigation
curl -X POST http://sre-agent:8000/investigate \
  -d '{"prompt": "Debug slow API", "thread_id": "thread-abc"}'

# Interrupt (user changes mind)
curl -X POST http://sre-agent:8000/interrupt \
  -d '{"thread_id": "thread-abc"}'

# Resume with refined request
curl -X POST http://sre-agent:8000/investigate \
  -d '{"prompt": "Focus on database queries", "thread_id": "thread-abc"}'
```

Conversation history and filesystem state preserved.

See: `/sre-agent/docs/INTERRUPT_RESUME.md` (to be created based on AGENT_SDK_REVIEW.md content)

---

## Key Files

| File | Purpose |
|------|---------|
| `server.py` | External API (POST /investigate, /interrupt) |
| `sandbox_manager.py` | K8s Sandbox lifecycle management |
| `sandbox_server.py` | FastAPI server running in sandbox pod |
| `agent.py` | InteractiveAgentSession (Claude SDK wrapper) |

---

## Deployment

See: `/sre-agent/README.md` for Docker build and K8s deployment.

---

## Known Issues

See: `/sre-agent/docs/KNOWN_ISSUES.md`

---

## Related Documentation

- `/sre-agent/docs/SANDBOX_ARCHITECTURE.md` - Sandbox isolation details
- `/sre-agent/docs/SDK_COMPARISON.md` - Claude SDK vs OpenAI SDK
- `/sre-agent/docs/KNOWN_ISSUES.md` - Limitations
- `/sre-agent/docs/UPSTREAM_CONTRIBUTION.md` - Contributing to Claude SDK
