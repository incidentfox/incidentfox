"""
Sandbox Infrastructure for Unified Agent.

Provides gVisor-based Kubernetes sandboxes for secure agent execution:
- Per-investigation isolated pods
- JWT-based credential injection via Envoy sidecar
- Automatic cleanup via TTL
- Multi-tenant support

Components:
- auth: JWT generation for sandbox identity
- manager: K8s Sandbox CRD management
- server: FastAPI runtime inside sandbox (port 8888)
"""

from .auth import generate_sandbox_jwt, verify_sandbox_jwt
from .manager import SandboxExecutionError, SandboxInfo, SandboxManager

__all__ = [
    "generate_sandbox_jwt",
    "verify_sandbox_jwt",
    "SandboxManager",
    "SandboxInfo",
    "SandboxExecutionError",
]
