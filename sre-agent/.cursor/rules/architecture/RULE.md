---
description: "Core architecture patterns and critical implementation details"
globs:
  - "server.py"
  - "sandbox_server.py"
  - "sandbox_manager.py"
  - "agent.py"
alwaysApply: true
---

# SRE Agent Architecture

## Sandbox Isolation Pattern

**One sandbox per thread** - Each investigation thread (`thread_id`) gets its own isolated K8s pod:
- Isolated filesystem for Claude Code tools
- Persistent ClaudeSDKClient session
- Independent execution environment
- Automatic cleanup via TTL

## Communication Flow

```
User/Slack → Main Server → Sandbox Router → Sandbox Pod → ClaudeSDKClient → Claude
   (HTTP)    server.py    (HTTP via svc)   sandbox_server.py    (SDK)
```

### Why This Architecture?
1. **Isolation** - Each investigation can't affect others
2. **Safety** - Code execution contained in K8s pod
3. **Persistence** - Sessions survive interrupts
4. **Scalability** - Multiple concurrent investigations

## Critical: StreamingResponse Race Condition

**ALWAYS** create session BEFORE StreamingResponse in `sandbox_server.py`:

```python
# ✅ CORRECT - Session created before StreamingResponse
@app.post("/execute")
async def execute(request: ExecuteRequest):
    thread_id = request.thread_id or os.getenv("THREAD_ID", "default")
    
    # CRITICAL: Get session BEFORE StreamingResponse
    session = await get_or_create_session(thread_id)
    
    async def stream():
        async for chunk in session.execute(request.prompt):
            yield chunk
    
    return StreamingResponse(stream(), media_type="text/plain")


# ❌ WRONG - Session created inside stream (race condition)
@app.post("/execute")
async def execute(request: ExecuteRequest):
    async def stream():
        session = await get_or_create_session(thread_id)  # TOO LATE!
        async for chunk in session.execute(request.prompt):
            yield chunk
    
    return StreamingResponse(stream(), media_type="text/plain")
```

**Why?** FastAPI sends response headers before the stream function executes. If session creation is inside the stream, concurrent requests can create duplicate sessions, causing hangs and undefined behavior.

## Session Management After Interrupts

Claude Agent SDK sessions **automatically handle post-interrupt state**:

```python
# ✅ CORRECT - Session continues after interrupt
session.interrupt()  # Stop current execution
# ... later ...
session.execute("new prompt")  # Works! No recreation needed


# ❌ WRONG - Don't recreate session after interrupt
if session._was_interrupted:
    session = InteractiveAgentSession(thread_id)  # UNNECESSARY!
    await session.start()
```

The SDK handles this internally. Recreating causes issues.

## Streaming Results Pattern

Return `StreamingResponse` immediately for good UX:

```python
# ✅ CORRECT - Immediate response (current implementation)
sandbox_info = sandbox_manager.create_sandbox(thread_id)
# Wait for sandbox to be ready BEFORE streaming
if not sandbox_manager.wait_for_ready(thread_id, timeout=120):
    raise HTTPException(status_code=500, detail="Sandbox failed")

return StreamingResponse(stream(), media_type="text/plain")


# ❌ WRONG - Don't wait inside the stream (investigated, rejected)
return StreamingResponse(stream(), media_type="text/plain")
# Then wait inside stream function

# Why rejected: Adds complexity for marginal gain
# Current approach: 2-5s delay is acceptable UX
```

**Current Timing:**
- Sandbox becomes "Ready": ~2 seconds
- First output to user: ~4-5 seconds
- This is **acceptable UX**, no need to over-engineer

## Error Handling Pattern

Use specific exceptions, not "fake" responses:

```python
# ✅ CORRECT
class SandboxExecutionError(Exception):
    pass

def execute_in_sandbox(sandbox_info, prompt):
    response = router_request(...)
    if not response.ok:
        raise SandboxExecutionError(f"Failed: {response.status_code}")
    return response


# ❌ WRONG
def execute_in_sandbox(sandbox_info, prompt):
    response = router_request(...)
    if not response.ok:
        # Don't fake a Response object!
        return MockResponse(status_code=500, text="Error")
    return response
```

## Timeout Handling

Interrupted requests eventually timeout (industry standard):

```python
# In agent.py
async def execute(self, prompt: str):
    timeout_seconds = int(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))
    async with asyncio.timeout(timeout_seconds):
        async for chunk in self.client.receive_response():
            yield chunk
```

**Why?** After `interrupt()`, the agent stops but the HTTP request doesn't know. Timeout ensures the connection eventually closes. This is standard practice (ChatGPT, Claude web, etc.).

**User doesn't care** - They can send new messages immediately after interrupt. The hanging old request doesn't block them.

## Sandbox Lifecycle

```python
# Creation
sandbox_info = sandbox_manager.create_sandbox(thread_id)

# Wait for ready (Pod Running + Service exists)
if not sandbox_manager.wait_for_ready(thread_id, timeout=120):
    raise HTTPException(...)

# Execute (via Router)
response = sandbox_manager.execute_in_sandbox(sandbox_info, prompt)

# Interrupt (optional)
sandbox_manager.interrupt_sandbox(sandbox_info)

# Auto-cleanup via TTL (configured in Sandbox CR)
# No manual cleanup needed
```

## State Management

Track session state in `InteractiveAgentSession`:

```python
class InteractiveAgentSession:
    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.client = None
        self.is_running: bool = False      # Currently executing?
        self._was_interrupted: bool = False  # Was interrupted?
    
    async def execute(self, prompt: str):
        self.is_running = True
        self._was_interrupted = False
        # ... execute ...
        self.is_running = False
    
    async def interrupt(self):
        self._was_interrupted = True
        self.is_running = False
        await self.client.interrupt()
```

## Observability with Laminar

Initialize **once globally**, not per-session:

```python
# ✅ CORRECT - Global initialization
from lmnr import Laminar

if os.getenv("LMNR_PROJECT_API_KEY"):
    Laminar.initialize(project_api_key=os.getenv("LMNR_PROJECT_API_KEY"))

# Then use @observe() decorator
@observe()
async def execute(self, prompt: str):
    # ...
```

**Why?** Multiple ClaudeSDKClient instances try to start their own proxy servers if Laminar isn't initialized globally. This causes "Server is already running" errors.

## When to Simplify vs. When to Add Complexity

**Simplify when:**
- Dead code exists (remove it!)
- Complex solution for simple problem
- Marginal UX improvement requires significant complexity
- "Nice to have" feature with maintenance burden

**Examples we simplified:**
- Removed `run_agent()` (dead code)
- Removed session recreation logic after interrupt (SDK handles it)
- Simplified `make test-prod` from 21 lines to 9 lines
- Removed CORS middleware (no web UI)

**Add complexity when:**
- Solves real production issue
- Required for isolation/safety
- Industry standard pattern
- Critical for correctness

**Examples we kept:**
- Sandbox isolation (safety)
- Interrupt timeout handling (standard practice)
- Multi-platform builds (prevents prod failures)
- Session lock in sandbox_server (prevents race conditions)

