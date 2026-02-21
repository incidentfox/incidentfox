#!/usr/bin/env python3
"""
IncidentFox AI SRE Agent

Provides InteractiveAgentSession for persistent LLM sessions with interrupt support.
Used by sandbox_server.py for production deployments.

Architecture (Skills + Scripts + Subagents):
- Skills: Progressive disclosure of knowledge in .claude/skills/
- Scripts: API integrations executed via Bash (output only in context)
- Subagents: Context isolation for deep-dive work (log-analyst, k8s-debugger, remediator)

No MCP tools - all integrations use skills with scripts for:
- Minimal context bloat (skill metadata ~100 tokens, loaded on-demand)
- Progressive disclosure (syntax/methodology loaded when needed)
- Clean main context (subagent output stays isolated)

LLM Provider:
- Claude SDK: Production-tested, full feature support
- Multi-LLM support: Handled via credential-proxy which routes to different providers
  (Claude, Gemini, OpenAI) based on configuration

Observability:
- Configurable backend via OBSERVABILITY_BACKEND env var: "laminar", "langfuse", or "none"
- Laminar: Sessions grouped by thread_id, metadata for filtering, outcome tags
- Langfuse: Trace/span/generation tracking with Claude SDK callback integration
- Backend selection is a deployment config (Helm values), not per-tenant
"""

import base64
import mimetypes
import os
import re
from pathlib import Path
from typing import AsyncIterator

# Claude SDK imports
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
)
from dotenv import load_dotenv
from events import (
    StreamEvent,
    error_event,
    result_event,
    thought_event,
    tool_end_event,
    tool_start_event,
)

# Max image size to embed (5MB)
MAX_IMAGE_SIZE = 5 * 1024 * 1024

# Max file size to share (1GB - Slack limit for all plans)
MAX_FILE_SIZE = 1 * 1024 * 1024 * 1024  # 1 GB

# Max number of files to share per message (Slack best practice)
MAX_FILES_PER_MESSAGE = 10


def _extract_images_from_text(text: str) -> tuple[str, list]:
    """
    Extract local image references from markdown text.

    Finds markdown image syntax: ![alt](path)
    where path is a local file (starts with ./, /, /workspace/, or attachments/)

    Args:
        text: Markdown text that may contain image references

    Returns:
        Tuple of (text_with_placeholders, images_list)
        - text stays the same (slack-bot will replace based on path)
        - images_list: [{path, data (base64), media_type, alt}, ...]
    """
    # Match markdown images: ![alt text](path)
    # Path must look local (not http/https)
    pattern = r"!\[([^\]]*)\]\(([^)]+)\)"

    images = []

    for match in re.finditer(pattern, text):
        alt = match.group(1)
        path_str = match.group(2)

        # Skip external URLs
        if path_str.startswith(("http://", "https://", "data:")):
            continue

        # Resolve path — always relative to /workspace
        # Reject absolute paths that don't start with /workspace
        workspace = Path("/workspace")
        if path_str.startswith("./"):
            full_path = workspace / path_str[2:]
        elif path_str.startswith("/workspace/"):
            full_path = Path(path_str)
        elif path_str.startswith("/"):
            # Reject other absolute paths (e.g. /var/run/secrets)
            print(f"⚠️ [IMAGE] Rejecting absolute path: {path_str}")
            continue
        else:
            full_path = workspace / path_str

        # Security: resolve symlinks and verify path is within /workspace
        try:
            resolved = full_path.resolve(strict=False)
            # Use Path containment check (not string prefix) to prevent
            # bypass via paths like /workspacefoo
            if (
                workspace.resolve() not in resolved.parents
                and resolved != workspace.resolve()
            ):
                print(f"⚠️ [IMAGE] Skipping path outside workspace: {path_str}")
                continue
        except Exception:
            continue

        # Check if file exists and is an image
        if not resolved.exists():
            print(f"⚠️ [IMAGE] File not found: {path_str}")
            continue

        # Check size
        file_size = resolved.stat().st_size
        if file_size > MAX_IMAGE_SIZE:
            print(
                f"⚠️ [IMAGE] File too large ({file_size} bytes > {MAX_IMAGE_SIZE}): {path_str}"
            )
            continue

        # Determine media type
        media_type, _ = mimetypes.guess_type(str(resolved))
        if not media_type or not media_type.startswith("image/"):
            print(f"⚠️ [IMAGE] Not an image type ({media_type}): {path_str}")
            continue

        # Read and encode
        try:
            image_data = resolved.read_bytes()
            base64_data = base64.b64encode(image_data).decode("utf-8")

            images.append(
                {
                    "path": path_str,  # Original path from markdown
                    "data": base64_data,
                    "media_type": media_type,
                    "alt": alt or resolved.name,
                }
            )
            print(
                f"✅ [IMAGE] Extracted: {path_str} ({len(image_data)} bytes, {media_type})"
            )

        except Exception as e:
            print(f"⚠️ [IMAGE] Failed to read {path_str}: {e}")
            continue

    return text, images


def _extract_files_from_text(text: str) -> tuple[str, list]:
    """
    Extract local file references from markdown text.

    Finds markdown link syntax: [description](path)
    where path is a local file (NOT an image, NOT a URL)

    Args:
        text: Markdown text that may contain file references

    Returns:
        Tuple of (text, files_list)
        - text stays the same (slack-bot will replace based on path)
        - files_list: [{path, data (base64), media_type, filename, description}, ...]
    """
    # Match markdown links: [text](path)
    # But NOT images which start with !
    # We use negative lookbehind to exclude ![...](...)
    pattern = r"(?<!!)\[([^\]]+)\]\(([^)]+)\)"

    files = []

    # Find all matches first for debugging
    all_matches = list(re.finditer(pattern, text))
    if all_matches:
        print(f"📎 [FILE] Found {len(all_matches)} potential file link(s) in text")
        for m in all_matches:
            print(f"   - [{m.group(1)}]({m.group(2)})")

    # Image extensions to skip (handled by _extract_images_from_text)
    image_extensions = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".bmp",
        ".ico",
    }

    for match in re.finditer(pattern, text):
        description = match.group(1)
        path_str = match.group(2)

        # Skip external URLs
        if path_str.startswith(("http://", "https://", "mailto:", "tel:", "data:")):
            continue

        # Skip anchor links
        if path_str.startswith("#"):
            continue

        # Resolve path — always relative to /workspace
        # Reject absolute paths that don't start with /workspace
        workspace = Path("/workspace")
        if path_str.startswith("./"):
            full_path = workspace / path_str[2:]
        elif path_str.startswith("/workspace/"):
            full_path = Path(path_str)
        elif path_str.startswith("/"):
            # Reject other absolute paths (e.g. /var/run/secrets, /tmp/sandbox-jwt)
            print(f"⚠️ [FILE] Rejecting absolute path: {path_str}")
            continue
        elif path_str.startswith("attachments/"):
            full_path = workspace / path_str
        else:
            full_path = workspace / path_str

        # Security: resolve symlinks and verify path is within /workspace
        try:
            resolved = full_path.resolve(strict=False)
            # Use Path containment check (not string prefix) to prevent
            # bypass via paths like /workspacefoo
            if (
                workspace.resolve() not in resolved.parents
                and resolved != workspace.resolve()
            ):
                print(f"⚠️ [FILE] Skipping path outside workspace: {path_str}")
                continue
        except Exception:
            continue

        # Check if file exists
        if not resolved.exists():
            print(f"⚠️ [FILE] File not found: {path_str} (resolved to: {resolved})")
            continue

        # Skip directories
        if resolved.is_dir():
            print(f"⚠️ [FILE] Skipping directory: {path_str}")
            continue

        # Skip images (handled separately)
        if resolved.suffix.lower() in image_extensions:
            continue

        # Check size
        file_size = resolved.stat().st_size
        if file_size > MAX_FILE_SIZE:
            print(
                f"⚠️ [FILE] File too large ({file_size} bytes > {MAX_FILE_SIZE}): {path_str}"
            )
            continue

        # Check if we've hit the limit
        if len(files) >= MAX_FILES_PER_MESSAGE:
            print(
                f"⚠️ [FILE] Max files limit reached ({MAX_FILES_PER_MESSAGE}), skipping: {path_str}"
            )
            continue

        # Determine media type
        media_type, _ = mimetypes.guess_type(str(resolved))
        if not media_type:
            media_type = "application/octet-stream"

        # Read and encode
        try:
            file_data = resolved.read_bytes()
            base64_data = base64.b64encode(file_data).decode("utf-8")

            files.append(
                {
                    "path": path_str,  # Original path from markdown
                    "data": base64_data,
                    "media_type": media_type,
                    "filename": resolved.name,
                    "description": description,
                    "size": file_size,
                }
            )
            print(f"✅ [FILE] Extracted: {path_str} ({file_size} bytes, {media_type})")

        except Exception as e:
            print(f"⚠️ [FILE] Failed to read {path_str}: {e}")
            continue

    return text, files


load_dotenv()

# ---------------------------------------------------------------------------
# Observability backend initialization
# ---------------------------------------------------------------------------
# Configured via OBSERVABILITY_BACKEND env var: "laminar" | "langfuse" | "none"
# Falls back to auto-detection for backward compatibility:
#   - LMNR_PROJECT_API_KEY set → laminar
#   - LANGFUSE_PUBLIC_KEY set  → langfuse
#   - neither                  → none
# ---------------------------------------------------------------------------
_observability_backend = "none"
_observability_initialized = False

# Laminar helpers (lazy-imported)
_Laminar = None
_observe = None

# Langfuse helpers (lazy-imported)
_langfuse_client = None


def _detect_observability_backend() -> str:
    """Detect which observability backend to use."""
    backend = os.getenv("OBSERVABILITY_BACKEND", "").lower().strip()
    if backend in ("laminar", "langfuse", "none"):
        return backend
    # Auto-detect from available credentials
    if os.getenv("LMNR_PROJECT_API_KEY"):
        return "laminar"
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        return "langfuse"
    return "none"


def init_observability() -> None:
    """Initialize the configured observability backend. Call once at process startup."""
    global _observability_backend, _observability_initialized
    global _Laminar, _observe, _langfuse_client

    if _observability_initialized:
        return

    _observability_backend = _detect_observability_backend()

    if _observability_backend == "laminar":
        try:
            from lmnr import Laminar, observe

            _Laminar = Laminar
            _observe = observe
            Laminar.initialize()
            _observability_initialized = True
            print("[OBSERVABILITY] Laminar initialized (key present)")
        except Exception as e:
            print(f"[OBSERVABILITY] Laminar init failed: {e}")
            _observability_backend = "none"

    elif _observability_backend == "langfuse":
        try:
            from langfuse import Langfuse

            _langfuse_client = Langfuse(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com"),
            )
            _observability_initialized = True
            print(
                f"[OBSERVABILITY] Langfuse initialized (host: {os.getenv('LANGFUSE_HOST', 'https://us.cloud.langfuse.com')})"
            )
        except Exception as e:
            print(f"[OBSERVABILITY] Langfuse init failed: {e}")
            _observability_backend = "none"

    else:
        print("[OBSERVABILITY] No backend configured")
        _observability_initialized = True


def observability_set_session(thread_id: str, metadata: dict | None = None) -> None:
    """Set session/trace context for the current thread."""
    if _observability_backend == "laminar" and _Laminar:
        _Laminar.set_trace_session_id(thread_id)
        if metadata:
            _Laminar.set_trace_metadata(metadata)
    elif _observability_backend == "langfuse" and _langfuse_client:
        # Langfuse session context is set per-trace at creation time
        pass


def observability_set_tags(tags: list[str]) -> None:
    """Set outcome tags on the current span."""
    if _observability_backend == "laminar" and _Laminar:
        _Laminar.set_span_tags(tags)


def observability_observe():
    """Decorator for tracing a function. Returns identity decorator if backend doesn't support it."""
    if _observability_backend == "laminar" and _observe:
        return _observe()

    # No-op decorator
    def identity(fn):
        return fn

    return identity


# Initialize at import time
init_observability()


def get_environment() -> str:
    """Detect if running in local/dev or production."""
    # Check for explicit env var
    env = os.getenv("ENVIRONMENT")
    if env:
        return env.lower()

    # Auto-detect: Check for K8s namespace
    namespace = os.getenv("SANDBOX_NAMESPACE", os.getenv("NAMESPACE", "default"))
    if namespace == "incidentfox-prod":
        return "production"
    elif os.getenv("KUBERNETES_SERVICE_HOST"):
        return "staging"  # In K8s but not prod namespace
    else:
        return "local"


class InteractiveAgentSession:
    """
    Manages a persistent ClaudeSDKClient session that supports interrupts.

    Follows Claude SDK best practices:
    - Use connect()/disconnect() for session lifecycle
    - Use query() then receive_response() for each turn
    - Session maintains conversation context across multiple turns

    Each sandbox maintains one session per thread_id.
    """

    # Default tools when no team config overrides
    DEFAULT_TOOLS = [
        "Skill",
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Glob",
        "Grep",
        "WebSearch",
        "WebFetch",
        "AskUserQuestion",
        "Task",
    ]

    def __init__(self, thread_id: str, team_config=None):
        self.thread_id = thread_id
        self.team_config = team_config

        self.client: ClaudeSDKClient | None = None
        self.is_running: bool = False
        self._was_interrupted: bool = False
        self._pending_tool_ends: list = []  # Queue of tool_end events to emit
        self._tool_parent_map: dict = (
            {}
        )  # Map tool_use_id -> parent_tool_use_id for subagent tracking

        # Hook to capture tool outputs - queues tool_end event when tool completes
        async def capture_tool_output(input_data, tool_use_id, context):
            import logging

            logger = logging.getLogger(__name__)

            if input_data["hook_event_name"] == "PostToolUse":
                tool_name = input_data.get("tool_name", "Unknown")
                tool_response = input_data.get("tool_response", "")
                response_preview = (
                    str(tool_response)[:200] if tool_response else "(empty)"
                )
                logger.info(
                    f"[Hook] PostToolUse: tool={tool_name}, id={tool_use_id}, output_preview={response_preview}"
                )

                # Look up parent_tool_use_id from our tracking map
                parent_tool_use_id = self._tool_parent_map.get(tool_use_id)

                # Truncate large outputs to avoid buffer issues (SDK has 1MB limit)
                MAX_OUTPUT_LEN = 50000  # 50KB - plenty for display, safe for buffers
                output_str = str(tool_response) if tool_response else None
                if output_str and len(output_str) > MAX_OUTPUT_LEN:
                    output_str = (
                        output_str[:MAX_OUTPUT_LEN]
                        + f"... [truncated, {len(str(tool_response))} total chars]"
                    )

                # Queue tool_end event with tool_use_id and parent for proper matching
                self._pending_tool_ends.append(
                    {
                        "name": tool_name,
                        "tool_use_id": tool_use_id,
                        "parent_tool_use_id": parent_tool_use_id,
                        "output": output_str,
                    }
                )

                # Clean up the mapping
                self._tool_parent_map.pop(tool_use_id, None)
            return {}

        # Callback for tool permission requests (handles AskUserQuestion)
        async def can_use_tool_handler(tool_name: str, input_data: dict, context):
            """Handle tool permission requests, including AskUserQuestion."""
            if tool_name == "AskUserQuestion":
                import asyncio
                import logging

                from claude_agent_sdk.types import (
                    PermissionResultAllow,
                    PermissionResultDeny,
                )

                logger = logging.getLogger(__name__)
                questions = input_data.get("questions", [])
                logger.info(
                    f"[AskUserQuestion] Agent asked {len(questions)} question(s)"
                )

                # Store event on session instance (sandbox-local state)
                event = asyncio.Event()
                self._pending_answer_event = event
                self._pending_answer = None

                logger.info("[AskUserQuestion] Waiting up to 60s for answer...")

                # Wait up to 60 seconds for user response
                try:
                    await asyncio.wait_for(event.wait(), timeout=60.0)
                    answer = self._pending_answer

                    # Cleanup
                    delattr(self, "_pending_answer_event")
                    delattr(self, "_pending_answer")

                    logger.info(f"[AskUserQuestion] Received answer: {answer}")
                    return PermissionResultAllow(
                        updated_input={"questions": questions, "answers": answer}
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "[AskUserQuestion] Timeout - continuing without answer"
                    )

                    # Emit timeout event so Slack can update the UI
                    from events import question_timeout_event

                    if hasattr(self, "_pending_events"):
                        self._pending_events.append(
                            question_timeout_event(self.thread_id)
                        )

                    # Cleanup
                    if hasattr(self, "_pending_answer_event"):
                        delattr(self, "_pending_answer_event")
                    if hasattr(self, "_pending_answer"):
                        delattr(self, "_pending_answer")

                    return PermissionResultDeny(
                        message="User did not respond. Continue without this information."
                    )

            # Auto-approve other tools
            from claude_agent_sdk.types import PermissionResultAllow

            return PermissionResultAllow(updated_input=input_data)

        # Import AgentDefinition for subagent configuration
        from claude_agent_sdk import AgentDefinition

        subagents = {}

        # Build options for streaming input mode
        # Determine working directory based on mode
        # - Sandbox mode: Use /app (each sandbox is isolated, has .claude/ skills)
        # - Simple mode: Use per-thread workspace for session persistence
        if os.path.exists("/workspace"):
            # Sandbox mode - use canonical /app directory where .claude/ lives
            cwd = "/app"
        else:
            # Simple mode - use per-thread workspace for multi-turn conversations
            thread_workspace = f"/tmp/sessions/{self.thread_id}"
            os.makedirs(thread_workspace, exist_ok=True)

            # Copy .claude/ skills to thread workspace if it doesn't exist yet
            import shutil

            thread_claude_dir = os.path.join(thread_workspace, ".claude")
            if not os.path.exists(thread_claude_dir):
                source_claude_dir = "/app/.claude"
                if os.path.exists(source_claude_dir):
                    shutil.copytree(source_claude_dir, thread_claude_dir)

            cwd = thread_workspace

        # --- Dynamic config from team config service ---
        system_prompt = None
        root_config = None
        if self.team_config:
            from config import get_root_agent_config

            root_config = get_root_agent_config(self.team_config)

            # Set system prompt directly (Method 4 from SDK docs)
            if root_config and root_config.prompt.system:
                system_prompt = root_config.prompt.system
                print(
                    f"📝 [AGENT] System prompt ({len(system_prompt)} chars) "
                    f"from root agent '{root_config.name}'"
                )

            # Build subagents from config
            root_name = root_config.name if root_config else None

            # Register all enabled subagents
            for name, agent_cfg in self.team_config.agents.items():
                if name == root_name:
                    continue  # Skip root agent

                if not agent_cfg.enabled or not agent_cfg.prompt.system:
                    continue

                # Create AgentDefinition
                # All agents registered flat at root level
                subagents[name] = AgentDefinition(
                    description=agent_cfg.prompt.prefix or f"{name} specialist",
                    prompt=agent_cfg.prompt.system,
                    tools=(
                        agent_cfg.tools.enabled
                        if agent_cfg.tools.enabled != ["*"]
                        else None
                    ),
                )

            print(
                f"🤖 [AGENT] Registered {len(subagents)} subagents: "
                f"{', '.join(subagents.keys())}"
            )

        # Resolve allowed tools from config or defaults
        allowed_tools = self.DEFAULT_TOOLS
        if root_config:
            tc = root_config.tools
            if "*" in tc.enabled:
                allowed_tools = [t for t in self.DEFAULT_TOOLS if t not in tc.disabled]
            else:
                allowed_tools = tc.enabled

        options_kwargs = dict(
            cwd=cwd,
            allowed_tools=allowed_tools,
            permission_mode="acceptEdits",
            can_use_tool=can_use_tool_handler,
            include_partial_messages=True,  # Needed to get parent_tool_use_id for subagent tracking
            setting_sources=["user", "project"],  # Loads .claude/skills/
            agents=subagents,
            hooks={"PostToolUse": [HookMatcher(hooks=[capture_tool_output])]},
        )

        # Apply model settings and execution limits from root agent config
        if root_config:
            # Apply max_turns to prevent infinite loops
            if root_config.max_turns:
                options_kwargs["max_turns"] = root_config.max_turns
                print(f"🔧 [AGENT] Max turns: {root_config.max_turns}")

            # Apply model settings globally via environment variables
            # credential-proxy forwards these to LiteLLM (llm_proxy.py lines 460-470)
            # Note: These apply to all subagents (Claude SDK limitation)
            if root_config.model.temperature is not None:
                os.environ["LLM_TEMPERATURE"] = str(root_config.model.temperature)
                print(f"🔧 [AGENT] Temperature: {root_config.model.temperature}")

            if root_config.model.max_tokens is not None:
                os.environ["LLM_MAX_TOKENS"] = str(root_config.model.max_tokens)
                print(f"🔧 [AGENT] Max tokens: {root_config.model.max_tokens}")

            if root_config.model.top_p is not None:
                os.environ["LLM_TOP_P"] = str(root_config.model.top_p)
                print(f"🔧 [AGENT] Top-p: {root_config.model.top_p}")

        if system_prompt:
            # Method 3: Append custom prompt to claude_code preset
            # Preserves built-in tool instructions, safety, and env context
            options_kwargs["system_prompt"] = {
                "type": "preset",
                "preset": "claude_code",
                "append": system_prompt,
            }

        self.options = ClaudeAgentOptions(**options_kwargs)

    async def start(self):
        """Initialize the Claude client session for streaming input mode."""
        if self.client is None:
            # Don't use async with here - we need to keep the client alive
            # across multiple execute() calls. We'll manage lifecycle manually.
            self.client = ClaudeSDKClient(options=self.options)
            # Manually enter the async context manager
            await self.client.__aenter__()

            # Set up observability session context
            metadata = {
                "environment": get_environment(),
                "thread_id": self.thread_id,
            }
            if os.getenv("SANDBOX_NAME"):
                metadata["sandbox_name"] = os.getenv("SANDBOX_NAME")
            observability_set_session(self.thread_id, metadata)

    async def cleanup(self):
        """Clean up the client session. Alias for close()."""
        await self.close()

    @observability_observe()
    async def execute(
        self, prompt: str, images: list = None
    ) -> AsyncIterator[StreamEvent]:
        """
        Execute a query and stream structured events.

        Follows SDK pattern: query() sends the message, then receive_response()
        iterates over the response until complete. This blocks until the full
        response is received, which is the correct behavior per SDK docs.

        Args:
            prompt: User prompt to send to Claude
            images: Optional list of image dicts with {type, media_type, data, filename}

        Yields:
            StreamEvent objects for each agent action
        """
        import asyncio

        if self.client is None:
            raise RuntimeError("Session not started. Call start() first.")

        if self.is_running:
            raise RuntimeError(
                "Session already executing. Wait for current execution to complete."
            )

        self.is_running = True
        self._was_interrupted = False
        self._pending_tool_ends = []  # Reset pending tool ends
        self._pending_events = []  # For timeout events, etc.
        self._tool_parent_map = {}  # Reset subagent tracking
        success = False
        error_occurred = False
        final_text = ""  # Accumulate text for final result

        # Timeout for receive_response (10 minutes for complex investigations)
        # This prevents hanging forever if interrupted from another request
        # Configurable via AGENT_TIMEOUT_SECONDS env var
        RESPONSE_TIMEOUT = int(
            os.getenv("AGENT_TIMEOUT_SECONDS", "600")
        )  # 10 min default

        try:
            # Build message - can be simple string or multimodal content
            # Always use generator pattern for consistency (even for simple text)
            # This is the recommended SDK pattern per the streaming input docs
            async def message_generator():
                if images:
                    # Multimodal message: text + images
                    content = [{"type": "text", "text": prompt}]
                    for img in images:
                        content.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": img["media_type"],
                                    "data": img["data"],
                                },
                            }
                        )
                    print(
                        f"📷 [AGENT] Sending multimodal message with {len(images)} image(s)"
                    )
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": content},
                    }
                else:
                    # Simple text message - still use generator pattern
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": prompt},
                    }

            print(f"🔍 [DEBUG] Calling client.query() for thread {self.thread_id}")
            await self.client.query(message_generator())
            print(f"✅ [DEBUG] client.query() completed for thread {self.thread_id}")

            # Receive response with timeout
            try:
                print(
                    f"🔍 [DEBUG] Starting receive_response() with timeout {RESPONSE_TIMEOUT}s for thread {self.thread_id}"
                )
                message_count = 0
                async with asyncio.timeout(RESPONSE_TIMEOUT):
                    async for message in self.client.receive_response():
                        message_count += 1
                        print(
                            f"🔍 [DEBUG] Received message #{message_count}: {type(message).__name__} for thread {self.thread_id}"
                        )
                        # Get parent_tool_use_id if this message is from a subagent
                        parent_tool_use_id = getattr(
                            message, "parent_tool_use_id", None
                        )

                        # Emit any pending tool_end events (from PostToolUse hooks)
                        while self._pending_tool_ends:
                            pending = self._pending_tool_ends.pop(0)
                            yield tool_end_event(
                                self.thread_id,
                                pending["name"],
                                success=True,
                                output=pending.get("output"),
                                tool_use_id=pending.get("tool_use_id"),
                                parent_tool_use_id=pending.get("parent_tool_use_id"),
                            )

                        # Emit any pending events (timeout events, etc.)
                        while self._pending_events:
                            yield self._pending_events.pop(0)

                        if isinstance(message, AssistantMessage):
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    # Emit thought event for text
                                    yield thought_event(
                                        self.thread_id,
                                        block.text,
                                        parent_tool_use_id=parent_tool_use_id,
                                    )
                                    # Add separator between text blocks for proper spacing
                                    if final_text:
                                        final_text += "\n\n"
                                    final_text += block.text
                                elif hasattr(block, "name"):
                                    # Extract tool input and ID
                                    tool_input = {}
                                    if hasattr(block, "input"):
                                        tool_input = (
                                            block.input
                                            if isinstance(block.input, dict)
                                            else {}
                                        )

                                    tool_use_id = getattr(block, "id", None)

                                    # Track parent_tool_use_id for this tool (used by PostToolUse hook)
                                    if tool_use_id and parent_tool_use_id:
                                        self._tool_parent_map[tool_use_id] = (
                                            parent_tool_use_id
                                        )

                                    # Emit tool_start event with tool_use_id and parent context
                                    yield tool_start_event(
                                        self.thread_id,
                                        block.name,
                                        tool_input,
                                        tool_use_id=tool_use_id,
                                        parent_tool_use_id=parent_tool_use_id,
                                    )

                                    # If AskUserQuestion, emit special question event
                                    if block.name == "AskUserQuestion":
                                        from events import question_event

                                        questions = tool_input.get("questions", [])
                                        yield question_event(self.thread_id, questions)
                        elif isinstance(message, ResultMessage):
                            # Emit any remaining pending tool_end events
                            while self._pending_tool_ends:
                                pending = self._pending_tool_ends.pop(0)
                                yield tool_end_event(
                                    self.thread_id,
                                    pending["name"],
                                    success=True,
                                    output=pending.get("output"),
                                    tool_use_id=pending.get("tool_use_id"),
                                )

                            # Extract any local images referenced in the final text
                            result_text, extracted_images = _extract_images_from_text(
                                final_text
                            )
                            if extracted_images:
                                print(
                                    f"📷 [AGENT] Extracted {len(extracted_images)} image(s) from result"
                                )

                            # Extract any local files referenced in the final text
                            _, extracted_files = _extract_files_from_text(final_text)
                            if extracted_files:
                                print(
                                    f"📎 [AGENT] Extracted {len(extracted_files)} file(s) from result"
                                )

                            # Emit result event with images and files
                            success = message.subtype == "success"
                            yield result_event(
                                self.thread_id,
                                result_text,
                                success=success,
                                subtype=message.subtype,
                                images=extracted_images if extracted_images else None,
                                files=extracted_files if extracted_files else None,
                            )
                print(
                    f"✅ [DEBUG] receive_response() completed. Total messages: {message_count} for thread {self.thread_id}"
                )
            except asyncio.TimeoutError:
                print(
                    f"❌ [DEBUG] receive_response() TIMEOUT after {RESPONSE_TIMEOUT}s, messages received: {message_count} for thread {self.thread_id}"
                )
                yield error_event(
                    self.thread_id,
                    "Response exceeded maximum time limit",
                    recoverable=False,
                )
                error_occurred = True

        except Exception as e:
            error_occurred = True
            observability_set_tags(["error", "exception"])
            import traceback

            error_msg = str(e)
            print(f"❌ [AGENT] Exception during execute: {error_msg}")
            traceback.print_exc()

            # Provide user-friendly messages for known issues; default to generic
            if "buffer size" in error_msg.lower() or "1048576" in error_msg:
                error_msg = "Subagent produced too much output (SDK buffer limit). Try a simpler task."
            elif "decode" in error_msg.lower() and "json" in error_msg.lower():
                error_msg = (
                    "SDK JSON parsing error. The response was too large or malformed."
                )
            elif "rate" in error_msg.lower() and "limit" in error_msg.lower():
                error_msg = (
                    "API rate limit reached. Please wait a moment and try again."
                )
            else:
                # Don't leak internal details (file paths, DB strings, SDK state)
                error_msg = "An internal error occurred during the investigation."

            yield error_event(self.thread_id, error_msg, recoverable=False)
            # Don't re-raise - let the error event be sent cleanly
        finally:
            self.is_running = False
            # Add outcome tags
            if success:
                observability_set_tags(["success"])
            elif not error_occurred:
                observability_set_tags(["incomplete"])

    async def interrupt(self) -> AsyncIterator[StreamEvent]:
        """
        Interrupt current execution and stop.

        This sends an interrupt signal to Claude to stop the current task.
        After interrupt, the session is ready for new messages.

        Note: This does NOT automatically execute a new prompt. New messages
        should be sent separately via execute(). This matches Cursor's UX where
        interrupt just stops, and new messages are sent normally.

        Important: Claude SDK's interrupt() doesn't kill running bash subprocesses,
        so long-running scripts may continue in the background. This is a known
        limitation of the SDK.

        KNOWN ISSUE: If an execute() is running in a separate async context (e.g.,
        different HTTP request), its receive_response() may hang and not properly
        terminate. The interrupted task will stop in Claude, but the HTTP streaming
        response may not close immediately. This is a limitation of having separate
        HTTP requests for execute and interrupt.

        Yields:
            StreamEvent objects for interrupt status
        """
        if self.client is None:
            raise RuntimeError("Session not started. Call start() first.")

        try:
            yield thought_event(self.thread_id, "Interrupting current task...")
            await self.client.interrupt()
            self._was_interrupted = True
            self.is_running = False
            yield result_event(
                self.thread_id,
                "Task interrupted. Send a new message to continue.",
                success=True,
                subtype="interrupted",
            )
        except Exception as e:
            print(f"❌ [AGENT] Interrupt failed: {str(e)}")
            yield error_event(
                self.thread_id, "Interrupt failed. Please try again.", recoverable=False
            )
            raise

    async def close(self):
        """Clean up the client session."""
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass  # Ignore cleanup errors
            self.client = None

    async def provide_answer(self, answers: dict) -> None:
        """Provide answer to pending AskUserQuestion."""
        if (
            hasattr(self, "_pending_answer_event")
            and self._pending_answer_event is not None
        ):
            self._pending_answer = answers
            self._pending_answer_event.set()


def create_agent_session(thread_id: str, team_config=None):
    """
    Factory function to create agent session.

    Returns InteractiveAgentSession (Claude SDK).
    Multi-LLM support is handled via the credential-proxy which translates
    requests to different providers (Claude, Gemini, OpenAI) based on routing.

    Args:
        thread_id: Unique identifier for the session
        team_config: Optional TeamConfig from config_service

    Returns:
        InteractiveAgentSession
    """
    print("🔄 [AGENT] Using Claude SDK with credential-proxy for multi-LLM support")
    return InteractiveAgentSession(thread_id, team_config)
