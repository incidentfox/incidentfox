"""
A2A Protocol Client

Implements JSON-RPC 2.0 client for communicating with remote A2A agents.

Protocol Reference: https://a2a-protocol.org/
"""

import logging
import uuid
from typing import Any

import httpx

from .auth import A2AAuth, NoAuth, create_auth_from_config

logger = logging.getLogger(__name__)


class A2AClient:
    """
    Client for communicating with remote A2A agents using JSON-RPC 2.0.

    Example:
        client = A2AClient(
            url="https://example.com/a2a",
            auth=BearerAuth("token"),
        )
        result = await client.send_task("Investigate high error rate")
    """

    def __init__(
        self,
        url: str,
        auth: A2AAuth | None = None,
        timeout: float = 300.0,  # 5 minutes default
        agent_name: str | None = None,
    ):
        """
        Initialize A2A client.

        Args:
            url: A2A endpoint URL (e.g., https://example.com/a2a)
            auth: Authentication handler
            timeout: Request timeout in seconds
            agent_name: Optional agent name for logging
        """
        self.url = url
        self.auth = auth or NoAuth()
        self.timeout = timeout
        self.agent_name = agent_name or url

    async def send_jsonrpc_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Send a JSON-RPC 2.0 request to the remote agent.

        Args:
            method: JSON-RPC method name (e.g., "tasks/send")
            params: Method parameters

        Returns:
            JSON-RPC result

        Raises:
            A2AError: If the request fails or returns an error
        """
        request_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id,
        }

        headers = {
            "Content-Type": "application/json",
        }
        query_params = {}

        # Apply authentication
        self.auth.apply_auth(headers, query_params)

        logger.debug("A2A request to %s: method=%s", self.agent_name, method)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.url,
                    json=payload,
                    headers=headers,
                    params=query_params,
                )

                response.raise_for_status()
                result = response.json()

                # Check for JSON-RPC error
                if "error" in result:
                    error = result["error"]
                    logger.error(
                        "A2A JSON-RPC error from %s: code=%s, message=%s",
                        self.agent_name, error.get("code"), error.get("message"),
                    )
                    raise A2AError(
                        f"A2A error: {error.get('message')}",
                        error_code=error.get("code"),
                    )

                logger.info("A2A request success: agent=%s, method=%s", self.agent_name, method)
                return result.get("result", {})

        except httpx.HTTPError as e:
            logger.error("A2A HTTP error from %s: %s", self.agent_name, e)
            raise A2AError(f"HTTP error calling A2A agent: {e}") from e
        except Exception as e:
            logger.error("A2A request failed for %s: %s", self.agent_name, e)
            raise A2AError(f"Failed to call A2A agent: {e}") from e

    async def get_agent_card(self) -> dict[str, Any]:
        """
        Get the agent's capabilities card.

        Returns:
            Agent card with name, description, capabilities, etc.
        """
        return await self.send_jsonrpc_request("agent/authenticatedExtendedCard")

    async def send_task(
        self,
        message: str,
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a task to the remote agent.

        Args:
            message: Natural language message/task
            task_id: Optional task ID (generated if not provided)
            session_id: Optional session ID for context

        Returns:
            Task response with id, status, message, artifacts
        """
        task_id = task_id or f"task-{uuid.uuid4()}"

        params = {
            "id": task_id,
            "message": {
                "role": "user",
                "parts": [{"text": message}],
            },
        }

        if session_id:
            params["sessionId"] = session_id

        return await self.send_jsonrpc_request("tasks/send", params)

    async def get_task_status(self, task_id: str) -> dict[str, Any]:
        """
        Get the status of a previously sent task.

        Args:
            task_id: Task ID

        Returns:
            Task status with id, status, message, artifacts
        """
        return await self.send_jsonrpc_request("tasks/get", {"id": task_id})

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        """
        Cancel a running task.

        Args:
            task_id: Task ID

        Returns:
            Updated task status
        """
        return await self.send_jsonrpc_request("tasks/cancel", {"id": task_id})


class A2AError(Exception):
    """Exception raised for A2A protocol errors."""

    def __init__(self, message: str, error_code: int | None = None):
        super().__init__(message)
        self.error_code = error_code


def create_a2a_client_from_config(agent_config: dict[str, Any]) -> A2AClient:
    """
    Create an A2A client from agent configuration.

    Args:
        agent_config: Remote agent configuration

    Returns:
        A2AClient instance

    Example config:
        {
            "id": "openai_assistant",
            "name": "OpenAI Assistant",
            "type": "a2a",
            "url": "https://api.example.com/a2a",
            "auth": {
                "type": "bearer",
                "token": "sk-abc123"
            },
            "timeout": 300
        }
    """
    url = agent_config["url"]
    auth_config = agent_config.get("auth", {})
    auth = create_auth_from_config(auth_config)
    timeout = agent_config.get("timeout", 300.0)
    agent_name = agent_config.get("name", agent_config.get("id"))

    return A2AClient(
        url=url,
        auth=auth,
        timeout=timeout,
        agent_name=agent_name,
    )
