#!/usr/bin/env python3
"""
IncidentFox AI SRE Agent

Provides InteractiveAgentSession for persistent Claude SDK sessions with interrupt support.
Used by sandbox_server.py for production deployments.

Architecture (Skills + Scripts + Subagents):
- Skills: Progressive disclosure of knowledge in .claude/skills/
- Scripts: API integrations executed via Bash (output only in context)
- Subagents: Context isolation for deep-dive work (log-analyst, k8s-debugger, remediator)

No MCP tools - all integrations use skills with scripts for:
- Minimal context bloat (skill metadata ~100 tokens, loaded on-demand)
- Progressive disclosure (syntax/methodology loaded when needed)
- Clean main context (subagent output stays isolated)

Laminar Tracing:
- Sessions: Groups multi-turn conversations by thread_id
- Metadata: Environment, thread_id, sandbox_name for filtering/debugging
- Tags: Success/error/incomplete outcome tags for analysis
"""

import base64
import mimetypes
import os
import re
from pathlib import Path
from typing import AsyncIterator, Union

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
)
from claude_agent_sdk.types import StreamEvent as SDKStreamEvent
from dotenv import load_dotenv
from events import (
    StreamEvent,
    error_event,
    result_event,
    thought_event,
    tool_end_event,
    tool_start_event,
)
from lmnr import Laminar, observe

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

        # Resolve path
        # Accept: ./path, /path, /workspace/path, attachments/path
        if path_str.startswith("./"):
            full_path = Path("/workspace") / path_str[2:]
        elif path_str.startswith("/"):
            full_path = Path(path_str)
        elif path_str.startswith("attachments/"):
            full_path = Path("/workspace") / path_str
        else:
            full_path = Path("/workspace") / path_str

        # Security: only allow paths within /workspace
        try:
            resolved = full_path.resolve()
            if not str(resolved).startswith("/workspace"):
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

        # Resolve path
        if path_str.startswith("./"):
            full_path = Path("/workspace") / path_str[2:]
        elif path_str.startswith("/"):
            full_path = Path(path_str)
        elif path_str.startswith("attachments/"):
            full_path = Path("/workspace") / path_str
        else:
            full_path = Path("/workspace") / path_str

        # Security: only allow paths within /workspace
        try:
            resolved = full_path.resolve()
            if not str(resolved).startswith("/workspace"):
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

# Initialize Laminar for tracing (if API key is set)
# Note: This should be done ONCE per process, before any ClaudeSDKClient is created
_laminar_initialized = False
if os.getenv("LMNR_PROJECT_API_KEY") and not _laminar_initialized:
    Laminar.initialize()
    _laminar_initialized = True


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

    def __init__(self, thread_id: str):
        self.thread_id = thread_id

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

        # Define specialized subagents for context isolation
        # These subagents read skills and run scripts in isolated contexts
        subagents = {
            "log-analyst": AgentDefinition(
                description="Log analysis specialist for Coralogix, Datadog, or CloudWatch. "
                "Use for analyzing logs, finding error patterns, or correlating log events. "
                "Keeps all intermediate log output in isolated context.",
                prompt="""You are a log analysis expert specializing in observability platforms.

## Your Methodology
1. Identify which backend is configured (check env vars: CORALOGIX_API_KEY, DATADOG_API_KEY, AWS_REGION)
2. Use available observability Skills to query logs and metrics

## Core Principles
- **Efficiency First**: If `get_statistics` reveals a dominant error pattern (>80%), skip signature extraction and go straight to root cause analysis.
- **Be Concise**: Do not narrate every step. Only report significant findings or when you are stuck.
- **Aggregations First**: ALWAYS get statistics before raw logs.

## Output Format
Return ONLY a structured summary:
- Error patterns found (with counts and percentages)
- Temporal correlation (when did it start, peak, trend)
- Root cause hypothesis based on log evidence
- Confidence level (high/medium/low with explanation)
- Key evidence (2-3 specific log entries that support your hypothesis)

Do NOT dump raw logs. Synthesize and summarize findings.""",
                tools=["Skill", "Read", "Bash", "Glob", "Grep"],
                model="sonnet",
            ),
            "k8s-debugger": AgentDefinition(
                description="Kubernetes debugging specialist. Use for pod crashes, CrashLoopBackOff, "
                "OOMKilled, deployment issues, resource problems, or container failures. "
                "Keeps all kubectl output in isolated context.",
                prompt="""You are a Kubernetes debugging expert.

## Your Methodology
1. ALWAYS check events BEFORE logs (events explain 80% of issues faster)
2. Use available Kubernetes Skills for debugging

## Core Principles
- Events before logs
- Use Skills for structured debugging workflows

## Common Issue Patterns
- OOMKilled → Memory limit exceeded (check resources)
- ImagePullBackOff → Image not found or auth issue
- CrashLoopBackOff → Container keeps crashing (check logs after events)
- FailedScheduling → No nodes with capacity

## Output Format
Return a structured summary:
- Pod/deployment status and recent restarts
- Key events (with timestamps)
- Resource analysis (if relevant)
- Root cause hypothesis
- Recommended action

Do NOT dump full kubectl output. Synthesize findings.""",
                tools=["Skill", "Read", "Bash", "Glob", "Grep"],
                model="sonnet",
            ),
            "remediator": AgentDefinition(
                description="Safe remediation specialist. Use when proposing or executing pod restarts, "
                "deployment scaling, or rollbacks. ALWAYS does dry-run first.",
                prompt="""You are a safe remediation specialist.

## Safety Principles
1. ALWAYS dry-run first (all scripts support --dry-run)
2. Show what will happen before executing
3. Document the action and reason

## Workflow
1. Propose the action with reasoning
2. Run with --dry-run and show output
3. Ask for confirmation before executing
4. Execute only after confirmation
5. Verify the result

## Output Format
- Action: [what you propose]
- Reason: [why this will help]
- Risk: [potential side effects]
- Dry-run output: [show what would happen]
- Status: [waiting for confirmation / executed / verified]""",
                tools=["Skill", "Read", "Bash", "Glob", "Grep"],
                model="sonnet",
            ),
        }

        self.options = ClaudeAgentOptions(
            # Point to /app where .claude/ directory lives (canonical SDK pattern)
            cwd="/app",
            # Core tools for file operations and script execution
            allowed_tools=[
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
            ],
            permission_mode="acceptEdits",
            can_use_tool=can_use_tool_handler,
            include_partial_messages=True,  # Needed to get parent_tool_use_id for subagent tracking
            # Enable skill loading from .claude/skills directories
            setting_sources=["user", "project"],
            # Register specialized subagents for context isolation
            agents=subagents,
            hooks={"PostToolUse": [HookMatcher(hooks=[capture_tool_output])]},
        )

    async def start(self):
        """Initialize the Claude client session."""
        if self.client is None:
            self.client = ClaudeSDKClient(options=self.options)
            await self.client.connect()

            # Set up Laminar tracing metadata
            environment = get_environment()
            metadata = {
                "environment": environment,
                "thread_id": self.thread_id,
            }

            if os.getenv("SANDBOX_NAME"):
                metadata["sandbox_name"] = os.getenv("SANDBOX_NAME")

            Laminar.set_trace_session_id(self.thread_id)
            Laminar.set_trace_metadata(metadata)

    @observe()
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
            if images:
                # Multimodal message: text + images
                # Build content array per Claude SDK format
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

                # SDK expects a generator for multimodal input
                async def message_generator():
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": content},
                    }

                await self.client.query(message_generator())
            else:
                # Simple text message
                await self.client.query(prompt)

            # Receive response with timeout
            try:
                async with asyncio.timeout(RESPONSE_TIMEOUT):
                    async for message in self.client.receive_response():
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
            except asyncio.TimeoutError:
                yield error_event(
                    self.thread_id,
                    "Response exceeded maximum time limit",
                    recoverable=False,
                )
                error_occurred = True

        except Exception as e:
            error_occurred = True
            Laminar.set_span_tags(["error", "exception"])
            import traceback

            error_msg = str(e)
            print(f"❌ [AGENT] Exception during execute: {error_msg}")
            traceback.print_exc()

            # Provide user-friendly messages for known SDK issues
            if "buffer size" in error_msg.lower() or "1048576" in error_msg:
                error_msg = "Subagent produced too much output (SDK buffer limit). Try a simpler task."
            elif "decode" in error_msg.lower() and "json" in error_msg.lower():
                error_msg = (
                    "SDK JSON parsing error. The response was too large or malformed."
                )

            yield error_event(self.thread_id, error_msg, recoverable=False)
            # Don't re-raise - let the error event be sent cleanly
        finally:
            self.is_running = False
            # Add outcome tags
            if success:
                Laminar.set_span_tags(["success"])
            elif not error_occurred:
                Laminar.set_span_tags(["incomplete"])

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
            yield error_event(
                self.thread_id, f"Interrupt failed: {str(e)}", recoverable=False
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
