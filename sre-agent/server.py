#!/usr/bin/env python3
"""
IncidentFox Investigation Server

Server that manages investigations in isolated K8s sandboxes.
Uses Pattern 3: Hybrid Sessions - ephemeral sandboxes hydrated with history.

Streams structured SSE events for slack-bot consumption.

File Proxy Pattern:
- Slack bot sends file metadata (URL + auth) instead of base64 content
- Server generates download tokens and stores the mapping
- Sandbox downloads from /proxy/files/{token} endpoint
- Server injects auth and streams from Slack to sandbox
- This keeps credentials out of the sandbox (security best practice)
"""

import asyncio
import logging
import os
import re
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Optional

import httpx
from auth import generate_sandbox_jwt
from dotenv import load_dotenv
from events import error_event
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sandbox_manager import (
    SandboxExecutionError,
    SandboxInfo,
    SandboxInterruptError,
    SandboxManager,
)

logger = logging.getLogger(__name__)

load_dotenv()

# Initialize SandboxManager
# Production: Use ECR/GCR image from env var
# Development: Use local image
image = os.getenv("SANDBOX_IMAGE", "incidentfox-agent:latest")
namespace = os.getenv("SANDBOX_NAMESPACE", "default")
sandbox_manager = SandboxManager(namespace=namespace, image=image)
print(f"✅ SandboxManager initialized (namespace={namespace}, image={image})")

# Concurrency limit for investigations — prevents pod OOM under burst load.
# Requests beyond this limit wait (backpressure) instead of all crashing.
MAX_CONCURRENT_INVESTIGATIONS = int(os.getenv("MAX_CONCURRENT_INVESTIGATIONS", "8"))
_investigation_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INVESTIGATIONS)

# Service-to-service auth for /investigate and /interrupt.
# In production, set via K8s Secret (shared between slack-bot, orchestrator, and sre-agent).
# If unset, auth is disabled (local dev with `make dev`).
INVESTIGATE_AUTH_TOKEN = os.getenv("INVESTIGATE_AUTH_TOKEN", "")
if INVESTIGATE_AUTH_TOKEN:
    print("🔒 /investigate auth enabled (INVESTIGATE_AUTH_TOKEN is set)")
else:
    print(
        "⚠️  /investigate auth disabled (INVESTIGATE_AUTH_TOKEN not set — local dev only)"
    )


def require_service_auth(request: Request) -> None:
    """Verify service-to-service auth token on /investigate and /interrupt.

    In production, only slack-bot and orchestrator should call these endpoints.
    The token prevents any compromised pod from forging tenant context
    and hijacking credential-proxy.

    Skipped when INVESTIGATE_AUTH_TOKEN is not configured (local dev).
    """
    if not INVESTIGATE_AUTH_TOKEN:
        return

    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = auth_header.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, INVESTIGATE_AUTH_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid service token")


# File proxy: token -> download info mapping
# Tokens expire after 1 hour to prevent stale downloads
_file_download_tokens: Dict[str, dict] = {}
_FILE_TOKEN_TTL_SECONDS = 3600  # 1 hour

# Session store: thread_id -> {jwt, jwt_expiry, tenant_id, team_id}
# JWTs are reused across sandbox recreations for the same session
_sessions: Dict[str, dict] = {}
_SESSION_JWT_TTL_HOURS = 24  # JWT valid for 24h (spans multiple sandbox lifetimes)
_SESSION_JWT_REUSE_THRESHOLD_MINUTES = 30  # Reuse JWT if >30 min remaining


def _cleanup_expired_sessions():
    """Remove sessions whose JWTs have expired."""
    now = datetime.now(timezone.utc)
    expired = [
        tid
        for tid, session in _sessions.items()
        if session.get("jwt_expiry") and session["jwt_expiry"] <= now
    ]
    for tid in expired:
        del _sessions[tid]


def get_or_create_session_jwt(
    thread_id: str, tenant_id: str, team_id: str
) -> tuple[str, datetime]:
    """Get existing JWT if still valid, or create new one.

    This enables session continuity across sandbox recreations. A user's
    session can span multiple sandbox lifetimes without generating new JWTs.

    Args:
        thread_id: Investigation thread ID (session key)
        tenant_id: Organization/tenant ID
        team_id: Team node ID

    Returns:
        Tuple of (jwt_token, jwt_expiry)
    """
    # Periodically clean up expired sessions to prevent unbounded growth
    _cleanup_expired_sessions()

    session = _sessions.get(thread_id)
    now = datetime.now(timezone.utc)

    # Check if existing JWT is still valid with enough remaining time
    if session:
        jwt_expiry = session.get("jwt_expiry")
        if jwt_expiry and jwt_expiry > now + timedelta(
            minutes=_SESSION_JWT_REUSE_THRESHOLD_MINUTES
        ):
            print(
                f"♻️  Reusing existing JWT for thread {thread_id} "
                f"(expires in {int((jwt_expiry - now).total_seconds() / 60)} min)"
            )
            return session["jwt"], jwt_expiry

    # Generate new JWT
    sandbox_name = f"investigation-{thread_id}"
    jwt_token = generate_sandbox_jwt(
        tenant_id=tenant_id,
        team_id=team_id,
        sandbox_name=sandbox_name,
        thread_id=thread_id,
        ttl_hours=_SESSION_JWT_TTL_HOURS,
    )
    jwt_expiry = now + timedelta(hours=_SESSION_JWT_TTL_HOURS)

    # Store in session
    _sessions[thread_id] = {
        "jwt": jwt_token,
        "jwt_expiry": jwt_expiry,
        "tenant_id": tenant_id,
        "team_id": team_id,
    }
    print(
        f"🔑 Generated new JWT for thread {thread_id} (expires in {_SESSION_JWT_TTL_HOURS}h)"
    )

    return jwt_token, jwt_expiry


def start_liveness_server(port: int = 8081):
    """Start a dedicated liveness health server on a separate thread.

    This is isolated from the main FastAPI event loop so it always responds,
    even when the main server is under heavy load. Kubernetes liveness probe
    should target this port. Readiness probe should target the main server
    (port 8000) since readiness reflects actual ability to serve traffic.
    """

    class LivenessHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            pass  # Suppress access logs — this fires every 10s

    server = HTTPServer(("0.0.0.0", port), LivenessHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"✅ Liveness health server started on port {port}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start dedicated liveness health server on startup."""
    health_port = int(os.getenv("HEALTH_SERVER_PORT", "8081"))
    start_liveness_server(health_port)
    yield


app = FastAPI(
    title="IncidentFox Investigation Server",
    description="AI SRE agent for incident investigation",
    version="0.2.0",
    lifespan=lifespan,
)


class ImageData(BaseModel):
    type: str = "base64"  # Currently only base64 supported
    media_type: str = Field(..., max_length=128)
    data: str = Field(..., max_length=20_000_000)  # ~15MB decoded
    filename: Optional[str] = Field(None, max_length=255)


class FileAttachment(BaseModel):
    """
    File attachment metadata for proxy-based download.

    Instead of sending large files as base64, slack-bot sends metadata.
    The server generates download tokens and the sandbox downloads via proxy.
    """

    filename: str = Field(..., max_length=255)
    size: int = Field(..., ge=0, le=100_000_000)  # Max 100MB
    media_type: str = Field(..., max_length=128)
    download_url: str = Field(..., max_length=2048)
    auth_header: str = Field(..., max_length=1024)


class InvestigateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=500_000)
    thread_id: Optional[str] = Field(None, max_length=128)
    tenant_id: Optional[str] = Field(None, max_length=128)
    team_id: Optional[str] = Field(None, max_length=128)
    team_token: Optional[str] = Field(None, max_length=512)
    images: Optional[List[ImageData]] = Field(None, max_length=10)
    file_attachments: Optional[List[FileAttachment]] = Field(None, max_length=20)


class InterruptRequest(BaseModel):
    thread_id: str  # Required for interrupt (must have existing session)


class InvestigateResponse(BaseModel):
    thread_id: str
    status: str


class AnswerRequest(BaseModel):
    thread_id: str
    answers: dict


_ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "files.slack.com",
        "files-origin.slack.com",
    }
)


def _validate_download_url(url: str) -> None:
    """Validate download URL to prevent SSRF against internal services."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Missing hostname in download URL")
    # Block private/internal IPs
    import ipaddress

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError(f"Download URL targets private IP: {host}")
    except ValueError as e:
        if "private" in str(e) or "loopback" in str(e) or "link_local" in str(e):
            raise
        # Not an IP — it's a hostname, check allowlist
    if host not in _ALLOWED_DOWNLOAD_HOSTS:
        # Allow env override for additional hosts (e.g., Google Drive, Teams)
        extra = os.getenv("ALLOWED_DOWNLOAD_HOSTS", "")
        extra_hosts = frozenset(
            h.strip().lower() for h in extra.split(",") if h.strip()
        )
        if host not in extra_hosts:
            raise ValueError(
                f"Download host '{host}' not in allowlist. "
                f"Allowed: {', '.join(sorted(_ALLOWED_DOWNLOAD_HOSTS | extra_hosts))}"
            )


def _create_file_download_token(
    download_url: str, auth_header: str, filename: str, size: int
) -> str:
    """
    Create a secure download token for file proxy.

    Args:
        download_url: The actual URL to download from (e.g., Slack's url_private)
        auth_header: Authorization header value (e.g., "Bearer xoxb-...")
        filename: Original filename
        size: File size in bytes

    Returns:
        Secure token that can be used to download via /proxy/files/{token}
    """
    _validate_download_url(download_url)
    token = secrets.token_urlsafe(32)
    _file_download_tokens[token] = {
        "download_url": download_url,
        "auth_header": auth_header,
        "filename": filename,
        "size": size,
        "created_at": time.time(),
    }
    return token


def _cleanup_expired_tokens():
    """Remove expired download tokens."""
    current_time = time.time()
    expired = [
        token
        for token, info in _file_download_tokens.items()
        if current_time - info["created_at"] > _FILE_TOKEN_TTL_SECONDS
    ]
    for token in expired:
        del _file_download_tokens[token]


def _get_proxy_base_url() -> str:
    """
    Get the base URL for file proxy that sandbox can access.

    In K8s production: http://incidentfox-server-svc.<namespace>.svc.cluster.local:8000
    Local dev (Kind): http://host.docker.internal:8000 (sandbox reaches host via Docker network)
    """
    # Check if we have an explicit proxy URL configured
    proxy_url = os.getenv("FILE_PROXY_URL")
    if proxy_url:
        return proxy_url

    # Check if we're in local dev mode (ROUTER_LOCAL_PORT is set by dev.sh)
    if os.getenv("ROUTER_LOCAL_PORT"):
        # Local dev with Kind - sandbox can reach host via host.docker.internal
        return "http://host.docker.internal:8000"

    # In K8s cluster (production)
    server_namespace = os.getenv("SERVER_NAMESPACE", "incidentfox-prod")
    return f"http://incidentfox-server-svc.{server_namespace}.svc.cluster.local:8000"


@app.get("/health")
async def health():
    """Health check."""
    # Cleanup expired tokens periodically
    _cleanup_expired_tokens()
    return {"status": "ok", "active_download_tokens": len(_file_download_tokens)}


@app.get("/warmpool/status")
async def warmpool_status():
    """
    Get warm pool status.

    Returns information about the warm pool including:
    - Desired pool size
    - Available warm pods
    - Pending pods

    Only available when USE_WARM_POOL=true.
    """
    use_warm_pool = os.getenv("USE_WARM_POOL", "false").lower() == "true"

    if not use_warm_pool:
        return {
            "enabled": False,
            "message": "Warm pool is disabled. Set USE_WARM_POOL=true to enable.",
        }

    try:
        status = sandbox_manager.get_warm_pool_status()
        return {
            "enabled": True,
            **status,
        }
    except Exception as e:
        return {
            "enabled": True,
            "error": str(e),
        }


@app.get("/metrics/sandbox-demand")
async def sandbox_demand_metric():
    """Returns desired warm pool size for the CronJob autoscaler.

    The autoscaler CronJob polls this endpoint every minute and patches
    SandboxWarmPool replicas to match the returned value.
    Value = active_claims + buffer, clamped to [min, max] by the CronJob.

    Security: Internal-only (ClusterIP Service, not exposed via ingress).
    No auth required — same trust boundary as K8s health probes.
    """
    active_claims = sandbox_manager.count_active_claims()
    try:
        buffer = int(os.getenv("WARMPOOL_BUFFER", "3"))
        if buffer < 0:
            buffer = 3
    except ValueError:
        buffer = 3
    return {"value": active_claims + buffer}


@app.get("/proxy/files/{token}")
async def proxy_file_download(token: str):
    """
    File proxy endpoint - streams files from external sources (e.g., Slack).

    This endpoint allows sandboxes to download files without having access to
    the actual credentials. The server injects auth and streams the response.

    Security:
    - Tokens are single-use (deleted after successful download)
    - Tokens expire after 1 hour
    - Credentials never reach the sandbox
    """
    # Cleanup expired tokens
    _cleanup_expired_tokens()

    # Check if token exists
    if token not in _file_download_tokens:
        raise HTTPException(
            status_code=404, detail="Download token not found or expired"
        )

    token_info = _file_download_tokens[token]
    download_url = token_info["download_url"]
    auth_header = token_info["auth_header"]
    filename = token_info["filename"]

    print(f"📥 [PROXY] Downloading file: {filename} from {download_url[:50]}...")

    async def stream_file():
        """Stream file from source to sandbox."""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(300.0), follow_redirects=False
            ) as client:
                async with client.stream(
                    "GET", download_url, headers={"Authorization": auth_header}
                ) as response:
                    if response.status_code != 200:
                        raise HTTPException(
                            status_code=response.status_code,
                            detail=f"Failed to download from source: {response.status_code}",
                        )

                    bytes_streamed = 0
                    async for chunk in response.aiter_bytes(
                        chunk_size=65536
                    ):  # 64KB chunks
                        bytes_streamed += len(chunk)
                        yield chunk

                    print(
                        f"✅ [PROXY] Completed streaming {filename}: {bytes_streamed} bytes"
                    )

        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504, detail="Timeout downloading file from source"
            )
        except Exception as e:
            print(f"❌ [PROXY] Error streaming {filename}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Error downloading file: {str(e)}"
            )

    # Delete token after starting download (single-use)
    # Note: We delete before streaming completes to prevent replay attacks
    # If download fails, user needs to re-request the file
    del _file_download_tokens[token]

    # Sanitize filename: strip path components, remove dangerous characters
    safe_filename = os.path.basename(filename)
    safe_filename = safe_filename.replace("\x00", "").replace('"', "").replace("\\", "")
    safe_filename = re.sub(r"[^\w\.\-\(\) ]", "_", safe_filename)
    if not safe_filename:
        safe_filename = "download"

    return StreamingResponse(
        stream_file(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
        },
    )


def create_investigation_stream(
    sandbox_manager: SandboxManager,
    sandbox_info: SandboxInfo,
    thread_id: str,
    prompt: str,
    is_new: bool,
    images: Optional[List[dict]] = None,
    file_downloads: Optional[List[dict]] = None,
):
    """
    Create a streaming SSE generator for investigation execution.

    Args:
        sandbox_manager: The sandbox manager instance
        sandbox_info: Info about the sandbox to execute in
        thread_id: The investigation thread ID
        prompt: The user's prompt
        is_new: Whether this is a new sandbox (True) or reused (False)
        images: Optional list of image data dicts (type, media_type, data, filename)
        file_downloads: Optional list of file download info for sandbox to fetch via proxy
                       Each dict has: {token, filename, size, proxy_url}
    """

    def stream():
        # Don't emit sandbox status to Slack - it's an implementation detail
        # The actual agent thoughts will come from the sandbox

        try:
            print(f"🔄 [STREAM] Calling execute_in_sandbox for thread {thread_id}")
            if images:
                print(f"📷 [STREAM] Sending {len(images)} image(s) to sandbox")
            if file_downloads:
                print(
                    f"📎 [STREAM] Sending {len(file_downloads)} file download(s) to sandbox"
                )
            # Execute in sandbox (streaming SSE)
            response = sandbox_manager.execute_in_sandbox(
                sandbox_info, prompt, images, file_downloads
            )
            print(
                f"✅ [STREAM] Got response object (status={response.status_code}), starting to stream for thread {thread_id}"
            )
            print(f"🔍 [STREAM] Response headers: {dict(response.headers)}")

            # Pass through SSE events from sandbox as-is
            # The sandbox_server now returns SSE format
            line_count = 0
            last_event_type = None
            try:
                for line in response.iter_lines(decode_unicode=True):
                    if line:
                        line_count += 1
                        # Track the last event type we saw
                        if '"type":' in line:
                            if '"result"' in line:
                                last_event_type = "result"
                            elif '"error"' in line:
                                last_event_type = "error"
                        # Pass through SSE data lines directly
                        yield line + "\n"
                        # SSE requires blank line after data
                        if line.startswith("data:"):
                            yield "\n"
                print(
                    f"✅ [STREAM] Completed streaming {line_count} lines for thread {thread_id}"
                )
            except Exception as stream_err:
                # If we already got a result/error event, the stream ending is okay
                if last_event_type in ("result", "error") and line_count > 0:
                    print(
                        f"⚠️ [STREAM] Stream ended after {last_event_type} event ({line_count} lines) - this is okay"
                    )
                else:
                    # Re-raise if we haven't sent a complete response yet
                    raise stream_err
        except SandboxExecutionError as e:
            print(
                f"❌ [STREAM ERROR] SandboxExecutionError for thread {thread_id}: {e}"
            )
            yield error_event(thread_id, str(e), recoverable=False).to_sse()
        except Exception as e:
            print(
                f"❌ [STREAM ERROR] Unexpected error for thread {thread_id}: {type(e).__name__}: {e}"
            )
            yield error_event(
                thread_id, f"Unexpected error: {str(e)}", recoverable=False
            ).to_sse()

    return stream


@app.post("/investigate", dependencies=[Depends(require_service_auth)])
async def investigate(request: InvestigateRequest, raw_request: Request):
    """
    Run investigation and stream results.

    Architecture (Hybrid Sessions - Pattern 3):
    - If thread_id provided and sandbox alive: reuse for follow-up
    - If thread_id provided but sandbox dead: new sandbox + hydrate history (TODO)
    - If no thread_id: new sandbox, new investigation

    Each sandbox provides isolated filesystem for Claude Code tools.

    Concurrency: Limited by _investigation_semaphore. Requests beyond the limit
    wait (backpressure) instead of overloading the pod and crashing.
    """
    require_service_auth(raw_request)

    print(
        f"🔵 [INVESTIGATE] Request received: thread_id={request.thread_id}, prompt={request.prompt[:50]}..."
    )

    # Acquire semaphore — excess requests wait here instead of crashing the pod
    async with _investigation_semaphore:
        return await _investigate_inner(request)


async def _investigate_inner(request: InvestigateRequest):
    """Inner investigation logic, called under semaphore."""

    # Note: ANTHROPIC_API_KEY check removed - in multi-tenant mode, credentials
    # flow through credential-resolver → sandbox via Envoy sidecar.
    # The server doesn't need the API key directly.

    # Generate thread_id if not provided
    thread_id = request.thread_id or f"thread-{uuid.uuid4().hex[:8]}"

    # Extract tenant context (defaults for local dev)
    tenant_id = request.tenant_id or os.getenv("DEFAULT_TENANT_ID", "local")
    team_id = request.team_id or os.getenv("DEFAULT_TEAM_ID", "local")
    team_token = request.team_token  # For config-driven agents (may be None)

    # Create/reuse sandbox
    sandbox_info = sandbox_manager.get_sandbox(thread_id)

    if not sandbox_info:
        # Get or create session JWT (reuses existing if still valid)
        jwt_token, _ = get_or_create_session_jwt(thread_id, tenant_id, team_id)

        # Check if warm pool is enabled
        use_warm_pool = os.getenv("USE_WARM_POOL", "false").lower() == "true"

        # Sandbox TTL — configurable via env var (default: 120 minutes = 2 hours)
        try:
            ttl_minutes = int(os.getenv("SANDBOX_TTL_MINUTES", "120"))
            if not (1 <= ttl_minutes <= 1440):
                ttl_minutes = 120
        except ValueError:
            ttl_minutes = 120
        ttl_hours = ttl_minutes / 60

        # Create new sandbox with session JWT
        print(
            f"🔧 Creating sandbox for thread {thread_id} (tenant={tenant_id}, team={team_id}, warm_pool={use_warm_pool})"
        )
        provision_start = time.time()
        try:
            if use_warm_pool:
                # Use warm pool for instant provisioning (<2 seconds)
                # Falls back to direct creation if warm pool unavailable
                # Run in thread pool to avoid blocking the event loop
                # (sandbox_manager uses requests + time.sleep internally)
                sandbox_info = await asyncio.to_thread(
                    sandbox_manager.create_sandbox_from_pool,
                    thread_id,
                    tenant_id=tenant_id,
                    team_id=team_id,
                    ttl_hours=ttl_hours,
                    jwt_token=jwt_token,
                    team_token=team_token,
                )
                provision_ms = (time.time() - provision_start) * 1000
                # Warm pool method already waits for ready and injects JWT
                print(
                    f"✅ Sandbox {sandbox_info.name} is ready (from warm pool, {provision_ms:.0f}ms total)"
                )
            else:
                # Direct creation (traditional path)
                # Run in thread pool to avoid blocking the event loop
                sandbox_info = await asyncio.to_thread(
                    sandbox_manager.create_sandbox,
                    thread_id,
                    tenant_id=tenant_id,
                    team_id=team_id,
                    ttl_hours=ttl_hours,
                    jwt_token=jwt_token,
                    team_token=team_token,
                )

                # Wait for sandbox to be ready
                print(f"⏳ Waiting for sandbox {sandbox_info.name} to be ready...")
                ready = await asyncio.to_thread(
                    sandbox_manager.wait_for_ready, thread_id, 120
                )
                if not ready:
                    raise HTTPException(
                        status_code=500, detail="Sandbox failed to become ready"
                    )

                provision_ms = (time.time() - provision_start) * 1000
                print(
                    f"✅ Sandbox {sandbox_info.name} is ready (direct creation, {provision_ms:.0f}ms total)"
                )

        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to create sandbox: {e}"
            )

        is_new = True
    else:
        # Reuse existing sandbox (follow-up)
        print(f"♻️  Reusing sandbox {sandbox_info.name} for follow-up")
        is_new = False

        # Reset idle timeout — extend sandbox lifetime on activity
        try:
            ttl_minutes = int(os.getenv("SANDBOX_TTL_MINUTES", "120"))
        except (ValueError, TypeError):
            ttl_minutes = 120
        sandbox_manager.reset_sandbox_ttl(thread_id, ttl_hours=ttl_minutes / 60)

    # Convert images to dict format if provided
    images_list = None
    if request.images:
        images_list = [img.model_dump() for img in request.images]
        print(f"📷 [INVESTIGATE] Processing {len(images_list)} image(s)")

    # Process file attachments: create download tokens for each
    file_downloads = None
    if request.file_attachments:
        proxy_base_url = _get_proxy_base_url()
        file_downloads = []
        for att in request.file_attachments:
            # Create secure download token
            token = _create_file_download_token(
                download_url=att.download_url,
                auth_header=att.auth_header,
                filename=att.filename,
                size=att.size,
            )
            file_downloads.append(
                {
                    "token": token,
                    "filename": att.filename,
                    "size": att.size,
                    "media_type": att.media_type,
                    "proxy_url": f"{proxy_base_url}/proxy/files/{token}",
                }
            )
            print(
                f"📎 [INVESTIGATE] Created download token for {att.filename} ({att.size} bytes)"
            )
        print(f"📎 [INVESTIGATE] Total {len(file_downloads)} file download(s) prepared")

    stream = create_investigation_stream(
        sandbox_manager,
        sandbox_info,
        thread_id,
        request.prompt,
        is_new,
        images_list,
        file_downloads,
    )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "X-Thread-ID": thread_id,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.post("/interrupt", dependencies=[Depends(require_service_auth)])
async def interrupt(request: InterruptRequest, raw_request: Request):
    """
    Interrupt current execution and stop.

    This endpoint allows users to stop a long-running task mid-execution.
    After interrupt, new messages should be sent via the normal /investigate endpoint.

    Requirements:
    - thread_id must exist (must have an active session)
    - The sandbox must still be alive

    The interrupt is graceful - it uses the Claude SDK's interrupt() API
    to stop the current task without killing the sandbox.

    Note: This follows Cursor's UX - interrupt just stops, new messages
    are queued separately.
    """
    require_service_auth(raw_request)

    print(f"🔴 [INTERRUPT] Request received: thread_id={request.thread_id}")

    # Check if sandbox exists
    sandbox_info = sandbox_manager.get_sandbox(request.thread_id)

    if not sandbox_info:
        raise HTTPException(
            status_code=404,
            detail=f"No active sandbox found for thread {request.thread_id}. "
            "Cannot interrupt a non-existent session.",
        )

    print(f"🛑 Interrupting sandbox {sandbox_info.name} for thread {request.thread_id}")

    def stream():
        # Don't emit status to Slack - actual interrupt events come from sandbox
        try:
            # Interrupt (no new prompt) - returns streaming SSE response
            response = sandbox_manager.interrupt_sandbox(sandbox_info)

            # Pass through SSE events from sandbox
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    yield line + "\n"
                    if line.startswith("data:"):
                        yield "\n"
        except SandboxInterruptError as e:
            yield error_event(request.thread_id, str(e), recoverable=False).to_sse()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "X-Thread-ID": request.thread_id,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/answer", dependencies=[Depends(require_service_auth)])
async def answer_question(request: AnswerRequest):
    """
    Receive answer to AskUserQuestion from Slack bot.
    Forwards the answer to the sandbox where the agent is waiting.
    """
    thread_id = request.thread_id
    answers = request.answers

    if not thread_id or not answers:
        raise HTTPException(400, "Missing thread_id or answers")

    logger.info(f"📬 [ANSWER] Received answer for thread {thread_id}: {answers}")

    # Get sandbox info
    sandbox_info = sandbox_manager.get_sandbox(thread_id)
    if not sandbox_info:
        raise HTTPException(404, f"No sandbox found for {thread_id}")

    # Forward answer to the sandbox
    try:
        response = sandbox_manager.send_answer_to_sandbox(sandbox_info, answers)
        logger.info(f"✅ [ANSWER] Forwarded to sandbox: {response}")
        return {"status": "ok", "thread_id": thread_id}
    except SandboxExecutionError as e:
        error_msg = str(e)
        logger.error(f"❌ [ANSWER] Failed to forward to sandbox: {error_msg}")

        # Check for specific error cases
        if "No pending question" in error_msg or "400" in error_msg:
            raise HTTPException(
                400,
                "No pending question - the agent may have timed out waiting for your response",
            )
        elif "No active session" in error_msg or "404" in error_msg:
            raise HTTPException(404, "No active session for this investigation")
        else:
            raise HTTPException(500, f"Failed to forward answer: {error_msg}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
