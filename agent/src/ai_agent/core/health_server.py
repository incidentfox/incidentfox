"""
Dedicated health server for Kubernetes liveness and readiness probes.

This server runs in a separate thread from the main Sanic application,
ensuring health checks remain responsive even when the main event loop
is blocked by long-running operations (e.g., OpenAI API calls).

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                      Agent Process                          │
    │  ┌──────────────────────┐    ┌───────────────────────────┐ │
    │  │   Health Server      │    │     Main Sanic Server     │ │
    │  │   (Port 8081)        │    │     (Port 8080)           │ │
    │  │   Runs in thread     │◄───│   Updates heartbeat at:   │ │
    │  │                      │    │   - Request boundaries    │ │
    │  │   /livez → 200 OK    │    │   - After tool calls      │ │
    │  │   /readyz → checks   │    │   - After LLM responses   │ │
    │  │     heartbeat        │    │                           │ │
    │  └──────────────────────┘    └───────────────────────────┘ │
    └─────────────────────────────────────────────────────────────┘

Endpoints:
    /livez  - Liveness probe: Always returns 200 if process is alive.
              Use for K8s liveness probe.

    /readyz - Readiness probe: Returns 200 if heartbeat is recent,
              503 if heartbeat is stale. Use for K8s readiness probe.

Usage:
    from ai_agent.core.health_server import start_health_server, update_heartbeat

    # Start during app initialization
    start_health_server(port=8081)

    # Update heartbeat during agent execution
    update_heartbeat()  # Call at safe points in agent loop
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from .logging import get_logger

logger = get_logger(__name__)

# Global heartbeat state (thread-safe via GIL for simple reads/writes)
_heartbeat_state = {
    "last_update": time.time(),
    "status": "starting",
    "current_operation": None,
    "run_id": None,
}
_heartbeat_lock = threading.Lock()

# Configuration
_HEARTBEAT_STALE_THRESHOLD_SECONDS = 300  # 5 minutes - agent runs can be long


def update_heartbeat(
    status: str = "active",
    operation: str | None = None,
    run_id: str | None = None,
) -> None:
    """
    Update the heartbeat timestamp and optional status.

    Call this at safe points during agent execution:
    - After each tool call completes
    - After each LLM response received
    - At request boundaries (start/end)
    - Periodically in long-running operations

    Args:
        status: Current status (active, processing, idle)
        operation: Description of current operation
        run_id: Current agent run ID
    """
    global _heartbeat_state
    with _heartbeat_lock:
        _heartbeat_state = {
            "last_update": time.time(),
            "status": status,
            "current_operation": operation,
            "run_id": run_id,
        }


def get_heartbeat_state() -> dict:
    """Get current heartbeat state (thread-safe copy)."""
    with _heartbeat_lock:
        return _heartbeat_state.copy()


def is_heartbeat_healthy(threshold_seconds: float | None = None) -> bool:
    """
    Check if heartbeat is recent enough to be considered healthy.

    Args:
        threshold_seconds: Override default staleness threshold

    Returns:
        True if heartbeat is recent, False if stale
    """
    threshold = threshold_seconds or _HEARTBEAT_STALE_THRESHOLD_SECONDS
    state = get_heartbeat_state()
    age = time.time() - state["last_update"]
    return age < threshold


class HealthRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health check endpoints."""

    # Suppress default logging
    def log_message(self, format: str, *args) -> None:
        # Only log non-200 responses or errors
        if len(args) >= 2 and args[1] != "200":
            logger.debug("health_server_request", status=args[1], path=args[0])

    def _send_json_response(self, data: dict, status: int = 200) -> None:
        """Send a JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/livez":
            self._handle_livez()
        elif self.path == "/readyz":
            self._handle_readyz()
        elif self.path == "/healthz":
            # Alias for readyz for backwards compatibility
            self._handle_readyz()
        else:
            self._send_json_response({"error": "Not found"}, status=404)

    def _handle_livez(self) -> None:
        """
        Liveness probe handler.

        Always returns 200 if the process is alive.
        Kubernetes will restart the pod if this fails.
        """
        self._send_json_response(
            {
                "status": "alive",
                "timestamp": time.time(),
            }
        )

    def _handle_readyz(self) -> None:
        """
        Readiness probe handler.

        Returns 200 if heartbeat is recent, 503 if stale.
        Kubernetes will stop routing traffic if this fails.
        """
        state = get_heartbeat_state()
        age = time.time() - state["last_update"]
        is_healthy = age < _HEARTBEAT_STALE_THRESHOLD_SECONDS

        response_data = {
            "status": "ready" if is_healthy else "not_ready",
            "heartbeat_age_seconds": round(age, 2),
            "heartbeat_status": state["status"],
            "current_operation": state["current_operation"],
            "run_id": state["run_id"],
            "threshold_seconds": _HEARTBEAT_STALE_THRESHOLD_SECONDS,
        }

        if is_healthy:
            self._send_json_response(response_data)
        else:
            logger.warning(
                "health_server_heartbeat_stale",
                age_seconds=age,
                threshold_seconds=_HEARTBEAT_STALE_THRESHOLD_SECONDS,
                last_status=state["status"],
                last_operation=state["current_operation"],
            )
            self._send_json_response(response_data, status=503)


class HealthServer:
    """
    Dedicated health server running in a separate thread.

    This ensures health probes remain responsive even when the main
    application is busy with long-running operations.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8081):
        self.host = host
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def start(self) -> None:
        """Start the health server in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("health_server_already_running")
            return

        def run_server():
            try:
                self._server = HTTPServer(
                    (self.host, self.port),
                    HealthRequestHandler,
                )
                logger.info(
                    "health_server_started",
                    host=self.host,
                    port=self.port,
                    endpoints=["/livez", "/readyz", "/healthz"],
                )
                self._started.set()
                self._server.serve_forever()
            except Exception as e:
                logger.error("health_server_error", error=str(e), exc_info=True)
                self._started.set()  # Unblock waiters even on error

        self._thread = threading.Thread(
            target=run_server,
            name="HealthServer",
            daemon=True,  # Thread will exit when main process exits
        )
        self._thread.start()

        # Wait for server to start (up to 5 seconds)
        if not self._started.wait(timeout=5.0):
            logger.error("health_server_start_timeout")

    def stop(self) -> None:
        """Stop the health server."""
        if self._server:
            logger.info("health_server_stopping")
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._started.clear()

    def is_running(self) -> bool:
        """Check if the health server is running."""
        return self._thread is not None and self._thread.is_alive()


# Global singleton instance
_health_server: HealthServer | None = None


def start_health_server(host: str = "0.0.0.0", port: int = 8081) -> HealthServer:
    """
    Start the global health server singleton.

    Args:
        host: Host to bind to (default: 0.0.0.0)
        port: Port to listen on (default: 8081)

    Returns:
        HealthServer instance
    """
    global _health_server
    if _health_server is None:
        _health_server = HealthServer(host=host, port=port)
    _health_server.start()
    # Initialize heartbeat to healthy state
    update_heartbeat(status="idle")
    return _health_server


def stop_health_server() -> None:
    """Stop the global health server singleton."""
    global _health_server
    if _health_server:
        _health_server.stop()
        _health_server = None


def get_health_server() -> HealthServer | None:
    """Get the global health server instance."""
    return _health_server
