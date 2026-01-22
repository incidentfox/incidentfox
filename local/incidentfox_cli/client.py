"""HTTP client for IncidentFox Agent API."""

import json
from typing import Any, AsyncGenerator, Dict, List

import httpx


class AgentClient:
    """Client for IncidentFox Agent API."""

    def __init__(self, base_url: str, team_token: str):
        """
        Initialize agent client.

        Args:
            base_url: Agent service URL (e.g., http://localhost:8081)
            team_token: Team authentication token
        """
        self.base_url = base_url.rstrip("/")
        self.team_token = team_token
        self.timeout = httpx.Timeout(600.0)  # 10 minute timeout for investigations

    def _headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        return {
            "Authorization": f"Bearer {self.team_token}",
            "Content-Type": "application/json",
            "X-IncidentFox-Team-Token": self.team_token,
        }

    def check_health(self) -> bool:
        """
        Check if agent service is healthy.

        Returns:
            True if healthy, False otherwise
        """
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    def list_agents(self) -> List[str]:
        """
        List available agents.

        Returns:
            List of agent names
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self.base_url}/agents", headers=self._headers())
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("agents", [])
        except Exception:
            pass

        # Fallback to known agents if API doesn't support listing
        return [
            "planner",
            "investigation_agent",
            "k8s_agent",
            "aws_agent",
            "metrics_agent",
            "coding_agent",
            "ci_agent",
        ]

    async def run_agent(
        self,
        agent_name: str,
        message: str,
        local_context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Run an agent with a message.

        Args:
            agent_name: Name of agent to run (e.g., "planner")
            message: User message/query
            local_context: Optional local environment context (k8s, git, aws, key_context)

        Returns:
            Dict with success, output/error, duration, agent
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/agents/{agent_name}/run",
                    headers=self._headers(),
                    json={
                        "message": message,
                        "context": {
                            "local_context": local_context or {},
                        },
                        "max_turns": 20,
                        "timeout": 600,
                    },
                )

                if resp.status_code == 200:
                    data = resp.json()
                    # Handle different response formats
                    output = (
                        data.get("output")
                        or data.get("final_output")
                        or data.get("result", {}).get("output")
                        or data.get("result", {}).get("final_output")
                        or "Investigation complete."
                    )
                    return {
                        "success": True,
                        "output": output,
                        "duration": data.get("duration_seconds")
                        or data.get("duration"),
                        "agent": agent_name,
                        "tool_calls": data.get("tool_calls_count"),
                    }
                else:
                    error_detail = resp.text[:500]
                    try:
                        error_json = resp.json()
                        error_detail = error_json.get("detail", error_detail)
                    except Exception:
                        pass
                    return {
                        "success": False,
                        "error": f"HTTP {resp.status_code}: {error_detail}",
                        "agent": agent_name,
                    }

            except httpx.TimeoutException:
                return {
                    "success": False,
                    "error": "Investigation timed out after 10 minutes",
                    "agent": agent_name,
                }
            except httpx.ConnectError:
                return {
                    "success": False,
                    "error": f"Cannot connect to agent at {self.base_url}",
                    "agent": agent_name,
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "agent": agent_name,
                }

    async def run_agent_stream(
        self,
        agent_name: str,
        message: str,
        previous_response_id: str | None = None,
        local_context: Dict[str, Any] | None = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run an agent with SSE streaming.

        Yields events as the agent executes:
        - agent_started: Agent execution has begun
        - tool_started: A tool call is starting
        - tool_completed: A tool call has finished
        - agent_completed: Final result (includes success, output, duration, last_response_id)

        Args:
            agent_name: Name of agent to run (e.g., "planner")
            message: User message/query
            previous_response_id: Optional response ID for chaining (continues conversation without pre-creating)
            local_context: Optional local environment context (k8s, git, aws, key_context)

        Yields:
            Dict with event_type and event data
        """
        url = f"{self.base_url}/agents/{agent_name}/run/stream"

        # Build request body with local context
        request_body = {
            "message": message,
            "context": {
                "local_context": local_context or {},
            },
            "max_turns": 20,
            "timeout": 600,
        }
        # Include previous_response_id if provided (for chaining follow-up queries)
        if previous_response_id:
            request_body["previous_response_id"] = previous_response_id

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream(
                    "POST",
                    url,
                    headers=self._headers(),
                    json=request_body,
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        yield {
                            "event_type": "error",
                            "error": f"HTTP {response.status_code}: {error_text.decode()[:500]}",
                        }
                        return

                    # Parse SSE events
                    event_type = None
                    data_buffer = []

                    async for line in response.aiter_lines():
                        line = line.strip()

                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                        elif line.startswith("data:"):
                            data_buffer.append(line[5:].strip())
                        elif line == "" and event_type and data_buffer:
                            # End of event - parse and yield
                            try:
                                data_str = "".join(data_buffer)
                                data = json.loads(data_str)
                                yield {
                                    "event_type": event_type,
                                    **data,
                                }
                            except json.JSONDecodeError:
                                yield {
                                    "event_type": event_type,
                                    "raw_data": "".join(data_buffer),
                                }
                            # Reset for next event
                            event_type = None
                            data_buffer = []

            except httpx.TimeoutException:
                yield {
                    "event_type": "error",
                    "error": "Connection timed out",
                }
            except httpx.ConnectError:
                yield {
                    "event_type": "error",
                    "error": f"Cannot connect to agent at {self.base_url}",
                }
            except Exception as e:
                yield {
                    "event_type": "error",
                    "error": str(e),
                }

    def get_config(self) -> Dict[str, Any]:
        """
        Get current team configuration.

        Returns:
            Team configuration dict
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.base_url}/api/v1/config", headers=self._headers()
                )
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass
        return {}

    def get_agent_info(self, agent_name: str) -> Dict[str, Any] | None:
        """
        Get information about a specific agent.

        Args:
            agent_name: Name of the agent

        Returns:
            Dict with agent info (name, model, tools_count) or None if not found
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.base_url}/agents/{agent_name}",
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass
        return None

    def get_tools_catalog(self) -> List[Dict[str, Any]]:
        """
        Get the complete tools catalog.

        Returns:
            List of tool definitions
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.base_url}/api/v1/tools/catalog",
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("tools", [])
        except Exception:
            pass
        return []

    def reload_config(self) -> bool:
        """
        Trigger agent to reload configuration.

        Returns:
            True if successful
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/v1/config/reload",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False


class ConfigServiceClient:
    """Client for IncidentFox Config Service API."""

    def __init__(self, base_url: str, team_token: str):
        """
        Initialize config service client.

        Args:
            base_url: Config service URL (e.g., http://localhost:8080)
            team_token: Team authentication token
        """
        self.base_url = base_url.rstrip("/")
        self.team_token = team_token
        self.timeout = httpx.Timeout(30.0)

    def _headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        return {
            "Authorization": f"Bearer {self.team_token}",
            "Content-Type": "application/json",
        }

    def check_health(self) -> bool:
        """Check if config service is healthy."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    def get_effective_config(self) -> Dict[str, Any] | None:
        """
        Get effective (merged) team configuration.

        Returns:
            Merged configuration dict or None on error
        """
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.base_url}/api/v1/config/me/effective",
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    return resp.json()
                else:
                    return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def get_raw_config(self) -> Dict[str, Any] | None:
        """
        Get raw team configuration (without inheritance).

        Returns:
            Raw configuration dict or None on error
        """
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.base_url}/api/v1/config/me/raw",
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    return resp.json()
                else:
                    return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def update_config(
        self, config_patch: Dict[str, Any], reason: str = "Updated via CLI"
    ) -> Dict[str, Any]:
        """
        Update team configuration (deep merge).

        Args:
            config_patch: Configuration patch to apply
            reason: Reason for the change (for audit)

        Returns:
            Updated configuration or error dict
        """
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.patch(
                    f"{self.base_url}/api/v1/config/me",
                    headers=self._headers(),
                    json={"config": config_patch, "reason": reason},
                )
                if resp.status_code == 200:
                    return {"success": True, "config": resp.json()}
                else:
                    error_detail = resp.text[:500]
                    try:
                        error_json = resp.json()
                        error_detail = error_json.get("detail", error_detail)
                    except Exception:
                        pass
                    return {
                        "success": False,
                        "error": f"HTTP {resp.status_code}: {error_detail}",
                    }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_agents_config(self) -> Dict[str, Any]:
        """
        Get agent configurations from effective config.

        Returns:
            Dict of agent_name -> agent_config
        """
        config = self.get_effective_config()
        if config and "error" not in config:
            return config.get("config", {}).get("agents", {})
        return {}

    def update_agent_config(
        self, agent_name: str, config_patch: Dict[str, Any], reason: str | None = None
    ) -> Dict[str, Any]:
        """
        Update a specific agent's configuration.

        Args:
            agent_name: Name of the agent to update
            config_patch: Configuration patch for the agent
            reason: Reason for the change

        Returns:
            Result dict with success status
        """
        full_patch = {"agents": {agent_name: config_patch}}
        return self.update_config(
            full_patch, reason or f"Updated {agent_name} config via CLI"
        )

    # =========================================================================
    # MCP Server Management
    # =========================================================================

    def get_mcp_servers(self) -> Dict[str, Any]:
        """
        Get all configured MCP servers from effective config.

        Returns:
            Dict of mcp_id -> mcp_config
        """
        config = self.get_effective_config()
        if config and "error" not in config:
            return config.get("config", {}).get("mcp_servers", {})
        return {}

    def add_mcp_server(
        self,
        mcp_id: str,
        command: str,
        args: List[str],
        env_vars: Dict[str, str] | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> Dict[str, Any]:
        """
        Add a new MCP server configuration.

        Args:
            mcp_id: Unique identifier for the MCP (e.g., "github-mcp")
            command: Command to run (e.g., "npx", "uvx")
            args: Command arguments
            env_vars: Environment variables (supports ${var} substitution)
            name: Display name
            description: Description

        Returns:
            Result dict with success status
        """
        mcp_config: Dict[str, Any] = {
            "enabled": True,
            "command": command,
            "args": args,
            "env_vars": env_vars or {},
            "enabled_tools": ["*"],  # Enable all tools by default
        }
        if name:
            mcp_config["name"] = name
        if description:
            mcp_config["description"] = description

        patch = {"mcp_servers": {mcp_id: mcp_config}}
        return self.update_config(patch, f"Added MCP '{mcp_id}' via CLI")

    def update_mcp_server(
        self, mcp_id: str, mcp_patch: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update an existing MCP server configuration.

        Args:
            mcp_id: MCP server identifier
            mcp_patch: Configuration updates

        Returns:
            Result dict with success status
        """
        patch = {"mcp_servers": {mcp_id: mcp_patch}}
        return self.update_config(patch, f"Updated MCP '{mcp_id}' via CLI")

    def enable_mcp(self, mcp_id: str) -> Dict[str, Any]:
        """Enable an MCP server."""
        return self.update_mcp_server(mcp_id, {"enabled": True})

    def disable_mcp(self, mcp_id: str) -> Dict[str, Any]:
        """Disable an MCP server."""
        return self.update_mcp_server(mcp_id, {"enabled": False})

    def delete_mcp(self, mcp_id: str) -> Dict[str, Any]:
        """
        Delete an MCP server by setting it to null (removes from team config).

        Note: This only removes the team-level override. If the MCP is defined
        at org level, it will still be inherited.
        """
        patch = {"mcp_servers": {mcp_id: None}}
        return self.update_config(patch, f"Deleted MCP '{mcp_id}' via CLI")

    def preview_mcp(
        self,
        name: str,
        command: str,
        args: List[str],
        env_vars: Dict[str, str] | None = None,
    ) -> Dict[str, Any]:
        """
        Preview an MCP server before adding (discovers available tools).

        Args:
            name: Display name for the MCP
            command: Command to run
            args: Command arguments
            env_vars: Environment variables

        Returns:
            Dict with success, tools list, tool_count, or error
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/v1/team/mcp-servers/preview",
                    headers=self._headers(),
                    json={
                        "name": name,
                        "command": command,
                        "args": args,
                        "env_vars": env_vars or {},
                    },
                )
                if resp.status_code == 200:
                    return resp.json()
                else:
                    error_detail = resp.text[:500]
                    try:
                        error_json = resp.json()
                        error_detail = error_json.get("detail", error_detail)
                    except Exception:
                        pass
                    return {
                        "success": False,
                        "error": f"HTTP {resp.status_code}: {error_detail}",
                    }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # A2A Remote Agent Management
    # =========================================================================

    def get_remote_agents(self) -> Dict[str, Any]:
        """
        Get all configured remote A2A agents from effective config.

        Returns:
            Dict of agent_id -> agent_config
        """
        config = self.get_effective_config()
        if config and "error" not in config:
            return config.get("config", {}).get("remote_agents", {})
        return {}

    def add_remote_agent(
        self,
        agent_id: str,
        name: str,
        url: str,
        auth_type: str = "none",
        auth_config: Dict[str, Any] | None = None,
        description: str | None = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Add a new remote A2A agent.

        Args:
            agent_id: Unique identifier (e.g., "security-scanner")
            name: Display name
            url: A2A endpoint URL
            auth_type: Authentication type ("none", "bearer", "apikey", "oauth2")
            auth_config: Authentication configuration (token, api_key, etc.)
            description: Agent description
            timeout: Request timeout in seconds

        Returns:
            Result dict with success status
        """
        agent_config: Dict[str, Any] = {
            "name": name,
            "type": "a2a",
            "url": url,
            "auth": {"type": auth_type, **(auth_config or {})},
            "timeout": timeout,
            "enabled": True,
        }
        if description:
            agent_config["description"] = description

        patch = {"remote_agents": {agent_id: agent_config}}
        return self.update_config(patch, f"Added remote agent '{agent_id}' via CLI")

    def update_remote_agent(
        self, agent_id: str, agent_patch: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update an existing remote agent configuration.

        Args:
            agent_id: Remote agent identifier
            agent_patch: Configuration updates

        Returns:
            Result dict with success status
        """
        patch = {"remote_agents": {agent_id: agent_patch}}
        return self.update_config(patch, f"Updated remote agent '{agent_id}' via CLI")

    def enable_remote_agent(self, agent_id: str) -> Dict[str, Any]:
        """Enable a remote agent."""
        return self.update_remote_agent(agent_id, {"enabled": True})

    def disable_remote_agent(self, agent_id: str) -> Dict[str, Any]:
        """Disable a remote agent."""
        return self.update_remote_agent(agent_id, {"enabled": False})

    def delete_remote_agent(self, agent_id: str) -> Dict[str, Any]:
        """
        Delete a remote agent by setting it to null.

        Note: This only removes the team-level config.
        """
        patch = {"remote_agents": {agent_id: None}}
        return self.update_config(patch, f"Deleted remote agent '{agent_id}' via CLI")

    def test_remote_agent(
        self, url: str, auth_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Test connection to a remote A2A agent.

        Args:
            url: A2A endpoint URL
            auth_config: Authentication configuration

        Returns:
            Dict with success, message, and optionally agentInfo
        """
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/a2a/test",
                    headers=self._headers(),
                    json={"url": url, "auth": auth_config},
                )
                if resp.status_code == 200:
                    return resp.json()
                else:
                    return {
                        "success": False,
                        "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
                    }
        except Exception as e:
            return {"success": False, "message": str(e)}
