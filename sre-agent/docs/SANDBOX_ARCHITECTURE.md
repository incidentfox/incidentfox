# SRE Agent - Sandbox Architecture

Isolated Kubernetes sandboxes for safe agent execution.

---

## Overview

Each investigation runs in an ephemeral K8s pod created via the `agent-sandbox` CRD.

**Benefits**:
- **Isolation**: One sandbox per investigation thread
- **Safety**: Can run arbitrary bash commands without affecting other investigations
- **Persistence**: Filesystem state maintained for follow-up questions (2 hour TTL)
- **Security**: gVisor runtime, non-root execution, dropped capabilities

---

## Sandbox Lifecycle

```
1. Client: POST /investigate with thread_id="thread-abc"
2. SandboxManager checks if sandbox exists for thread_id
3. If not exists:
   - Create Sandbox CR: investigation-thread-abc
   - Wait for pod to be Ready (120s timeout)
4. Send request to sandbox via Router
5. Sandbox executes, streams response
6. After 2 hours: Sandbox auto-deletes (TTL)
```

---

## Sandbox Manifest

```yaml
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: investigation-thread-abc
  labels:
    thread-id: thread-abc
spec:
  podTemplate:
    spec:
      containers:
      - name: agent
        image: incidentfox-agent:latest
        ports:
        - containerPort: 8888  # FastAPI server
        securityContext:
          runAsNonRoot: true
          runAsUser: 1000
          allowPrivilegeEscalation: false
          capabilities:
            drop: ["ALL"]
        resources:
          requests:
            cpu: "100m"
            memory: "512Mi"
          limits:
            cpu: "2000m"  # Bursts for git/file ops
            memory: "2Gi"
      runtimeClassName: gvisor  # Optional kernel isolation
  lifecycle:
    shutdownTime: "2026-01-12T14:00:00Z"  # 2 hours from creation
    shutdownPolicy: Delete
  replicas: 1
```

---

## Security Layers

### 1. Linux Security Context

```yaml
securityContext:
  runAsNonRoot: true          # Can't run as root
  runAsUser: 1000             # UID 1000
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]              # No special capabilities
```

### 2. gVisor Runtime (Optional)

```yaml
runtimeClassName: gvisor
```

**What is gVisor?**
- User-space kernel that intercepts syscalls
- Prevents container escapes
- Runs between container and host kernel

**Enable gVisor**:
```bash
export USE_GVISOR=true
```

### 3. Resource Limits

```yaml
resources:
  limits:
    memory: "2Gi"
    cpu: "2000m"
    ephemeral-storage: "5Gi"
```

Prevents DoS attacks from runaway processes.

---

## Sandbox Router

**Problem**: Sandboxes have ephemeral pod names (investigation-thread-abc-xyz12)

**Solution**: Sandbox Router routes requests by `X-Sandbox-ID` header.

```python
# sandbox_manager.py
headers = {
    "X-Sandbox-ID": "investigation-thread-abc",
    "X-Sandbox-Port": "8888",
    "X-Sandbox-Namespace": "default"
}

response = requests.post(
    f"{router_url}/execute",
    headers=headers,
    json={"prompt": prompt}
)
```

**Router URL**:
- In-cluster: `http://sandbox-router-svc.incidentfox-prod.svc.cluster.local:8080`
- Local dev: `http://localhost:8080` (via port-forward)

---

## TTL-Based Cleanup

**Problem**: Sandboxes use resources, can't keep forever

**Solution**: Automatic cleanup after 2 hours

```python
shutdown_time = (datetime.utcnow() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
```

**Why 2 hours?**
- Long enough for follow-up questions
- Short enough to avoid resource waste
- Most investigations complete in < 30 minutes

---

## Filesystem Persistence

**Within 2-hour window**:
```bash
# First request: Clone repo
curl POST /investigate -d '{"prompt": "Clone github.com/foo/bar"}'
# Files created at /tmp/repo/

# Follow-up (same thread_id): Files still there!
curl POST /investigate -d '{"prompt": "Read /tmp/repo/README.md"}'
```

**After 2 hours**: Sandbox deleted, filesystem gone.

---

## Conversation History Storage

**Where is conversation history stored?**

In-memory in the sandbox pod's Python process:

```python
# sandbox_server.py
_sessions: Dict[str, InteractiveAgentSession] = {}

def get_or_create_session(thread_id: str):
    if thread_id not in _sessions:
        session = InteractiveAgentSession(thread_id)
        await session.start()  # Creates ClaudeSDKClient
        _sessions[thread_id] = session
    return _sessions[thread_id]
```

**Trade-off**: If pod restarts, conversation history lost (but filesystem also lost, so acceptable).

---

## Resource Usage

Typical investigation:
- **CPU**: 100m baseline, bursts to 500m during git/grep operations
- **Memory**: 512Mi baseline, peaks to 1Gi for large file operations
- **Disk**: 100MB-1GB (git repos, log files)

---

## Monitoring

### Check sandboxes:

```bash
kubectl get sandboxes -n default
```

### Check sandbox pods:

```bash
kubectl get pods -n default -l managed-by=incidentfox-server
```

### View sandbox logs:

```bash
kubectl logs -n default investigation-thread-abc-<pod-hash>
```

---

## Development Mode

For local testing without K8s:

1. Run sandbox_server.py directly (no sandbox isolation)
2. Use in-process InteractiveAgentSession

See: `/sre-agent/README.md`

---

## Related Documentation

- `/sre-agent/docs/README.md` - SRE Agent overview
- `/sre-agent/docs/SDK_COMPARISON.md` - Why sandboxes vs shared pod
- `/sre-agent/docs/KNOWN_ISSUES.md` - Sandbox limitations
