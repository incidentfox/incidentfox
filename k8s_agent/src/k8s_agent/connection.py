"""SSE connection to IncidentFox Gateway."""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import structlog
from httpx_sse import aconnect_sse

from .config import get_settings
from .executor import K8sExecutor

logger = structlog.get_logger(__name__)

# Health file for liveness/readiness probes
HEALTH_FILE = Path("/tmp/healthy")


class GatewayConnection:
    """Manages SSE connection to IncidentFox K8s Gateway."""

    def __init__(self, executor: K8sExecutor):
        """
        Initialize gateway connection.

        Args:
            executor: K8s executor for running commands
        """
        self.executor = executor
        self.settings = get_settings()
        self._reconnect_delay = self.settings.initial_reconnect_delay
        self._running = False

    async def start(self):
        """Start the connection loop with automatic reconnection."""
        self._running = True
        logger.info(
            "starting_gateway_connection",
            gateway_url=self.settings.gateway_url,
            cluster_name=self.settings.cluster_name,
        )

        while self._running:
            try:
                await self._connect()
                # Reset reconnect delay on successful connection
                self._reconnect_delay = self.settings.initial_reconnect_delay
            except Exception as e:
                logger.error(
                    "connection_error",
                    error=str(e),
                    reconnect_delay=self._reconnect_delay,
                )

                if self._running:
                    # Wait before reconnecting with exponential backoff
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * self.settings.reconnect_multiplier,
                        self.settings.max_reconnect_delay,
                    )

    async def stop(self):
        """Stop the connection loop."""
        logger.info("stopping_gateway_connection")
        self._running = False
        self._remove_health_file()

    def _create_health_file(self):
        """Create health file for liveness/readiness probes."""
        try:
            HEALTH_FILE.touch()
        except Exception as e:
            logger.warning("failed_to_create_health_file", error=str(e))

    def _remove_health_file(self):
        """Remove health file."""
        try:
            HEALTH_FILE.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("failed_to_remove_health_file", error=str(e))

    async def _connect(self):
        """Establish SSE connection to gateway."""
        # Get cluster info for registration
        cluster_info = self.executor.get_cluster_info()

        # Build query params for registration
        params = {
            "agent_version": self.settings.agent_version,
            "kubernetes_version": cluster_info.get("kubernetes_version"),
            "node_count": cluster_info.get("node_count"),
            "namespace_count": cluster_info.get("namespace_count"),
        }
        # Remove None values
        params = {k: str(v) for k, v in params.items() if v is not None}

        # Build URL with query params
        url = f"{self.settings.gateway_url}/agent/connect"

        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "User-Agent": f"incidentfox-k8s-agent/{self.settings.agent_version}",
        }

        logger.info("connecting_to_gateway", url=url)

        async with httpx.AsyncClient(timeout=None) as client:
            async with aconnect_sse(
                client, "GET", url, params=params, headers=headers
            ) as event_source:
                logger.info("connected_to_gateway")

                async for event in event_source.aiter_sse():
                    await self._handle_event(event.event, event.data, event.id)

    async def _handle_event(
        self,
        event_type: str,
        data: str,
        event_id: Optional[str] = None,
    ):
        """
        Handle an SSE event from the gateway.

        Args:
            event_type: Type of event (connected, command, heartbeat)
            data: JSON data payload
            event_id: Optional event ID
        """
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("invalid_event_data", event_type=event_type, data=data)
            return

        if event_type == "connected":
            logger.info(
                "gateway_connected",
                cluster_id=payload.get("cluster_id"),
                message=payload.get("message"),
            )
            self._create_health_file()

        elif event_type == "command":
            await self._handle_command(payload)

        elif event_type == "heartbeat":
            logger.debug("heartbeat_received", timestamp=payload.get("timestamp"))

        else:
            logger.warning("unknown_event_type", event_type=event_type)

    async def _handle_command(self, payload: Dict[str, Any]):
        """
        Handle a command from the gateway.

        Args:
            payload: Command payload with request_id, command, params
        """
        request_id = payload.get("request_id")
        command = payload.get("command")
        params = payload.get("params", {})

        logger.info(
            "command_received",
            request_id=request_id,
            command=command,
        )

        # Execute the command
        try:
            result = await self.executor.execute(command, params)
            await self._send_response(
                request_id=request_id,
                ok=True,
                result=result,
            )
            logger.info(
                "command_completed",
                request_id=request_id,
                command=command,
            )
        except Exception as e:
            logger.error(
                "command_failed",
                request_id=request_id,
                command=command,
                error=str(e),
            )
            await self._send_response(
                request_id=request_id,
                ok=False,
                error=str(e),
            )

    async def _send_response(
        self,
        request_id: str,
        ok: bool,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        """
        Send command response to gateway.

        Args:
            request_id: ID of the request being responded to
            ok: Whether the command succeeded
            result: Command result (if ok)
            error: Error message (if not ok)
        """
        url = f"{self.settings.gateway_url}/agent/response/{request_id}"

        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

        body = {
            "request_id": request_id,
            "ok": ok,
        }
        if ok:
            body["result"] = result
        else:
            body["error"] = error

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers, json=body)
                if response.status_code != 200:
                    logger.error(
                        "response_send_failed",
                        request_id=request_id,
                        status_code=response.status_code,
                        response=response.text[:200],
                    )
        except Exception as e:
            logger.error(
                "response_send_error",
                request_id=request_id,
                error=str(e),
            )
