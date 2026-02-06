"""
Kubernetes Sandbox Manager.

Manages isolated sandboxes for investigations using K8s agent-sandbox CRD.
Each sandbox is a per-investigation pod with:
- gVisor runtime isolation (optional)
- Envoy sidecar for credential injection
- JWT-based authentication
- Automatic TTL cleanup

Architecture:
┌─────────────────────────────────────────────────────────────┐
│ Sandbox Pod                                                 │
│                                                             │
│  ┌─────────────────────┐    ┌─────────────────────┐        │
│  │ Agent Container     │    │ Envoy Sidecar       │        │
│  │ (port 8888)         │    │ (port 8001)         │        │
│  │                     │    │                     │        │
│  │ - FastAPI server    │───▶│ - ext_authz         │───▶ credential-resolver
│  │ - LLM provider      │    │ - JWT header        │
│  │ - Tools             │    │ - Credential inject │
│  └─────────────────────┘    └─────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests

from .auth import generate_sandbox_jwt

logger = logging.getLogger(__name__)


class SandboxExecutionError(Exception):
    """Raised when sandbox execution fails."""

    pass


class SandboxInterruptError(Exception):
    """Raised when sandbox interrupt fails."""

    pass


@dataclass
class SandboxInfo:
    """Information about a running sandbox."""

    name: str
    thread_id: str
    created_at: datetime
    namespace: str = "default"
    jwt_token: Optional[str] = None


def fetch_configured_integrations(
    jwt_token: str,
    tenant_id: str,
    team_id: str,
) -> str:
    """
    Fetch configured integrations from credential-resolver.

    This is called when creating a sandbox to inject integration metadata
    into the sandbox environment. The agent can then know what integrations
    are available without making runtime API calls.

    Args:
        jwt_token: JWT for authentication
        tenant_id: Tenant ID
        team_id: Team ID

    Returns:
        JSON string of integration metadata (non-sensitive)
    """
    cred_resolver_ns = os.getenv("CREDENTIAL_RESOLVER_NAMESPACE", "incidentfox-prod")

    # In local dev, use port-forwarded URL
    local_port = os.getenv("CREDENTIAL_RESOLVER_LOCAL_PORT")
    if local_port:
        url = f"http://localhost:{local_port}/api/integrations"
    else:
        url = f"http://credential-resolver-svc.{cred_resolver_ns}.svc.cluster.local:8002/api/integrations"

    headers = {
        "Accept": "application/json",
        "X-Sandbox-JWT": jwt_token,
        "X-Tenant-Id": tenant_id,
        "X-Team-Id": team_id,
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        return json.dumps(data.get("integrations", []))
    except Exception as e:
        logger.warning(f"Failed to fetch integrations: {e}")
        return "[]"


class SandboxManager:
    """
    Manage investigation sandboxes in Kubernetes.

    Creates and manages K8s Sandbox CRDs with:
    - Per-sandbox JWT tokens for authentication
    - Per-sandbox Envoy ConfigMaps with JWT embedded
    - Automatic cleanup via shutdownTime
    - Communication via sandbox-router
    """

    def __init__(
        self,
        namespace: str = "default",
        image: Optional[str] = None,
    ):
        """
        Initialize sandbox manager.

        Args:
            namespace: Kubernetes namespace for sandboxes
            image: Docker image to use for sandboxes.
                   Defaults to UNIFIED_AGENT_IMAGE env var or 'unified-agent:latest'
        """
        self.namespace = namespace
        self.image = image or os.getenv("UNIFIED_AGENT_IMAGE", "unified-agent:latest")
        self._k8s_loaded = False
        self.custom_api = None
        self.core_api = None

    def _ensure_k8s_client(self):
        """Lazy load Kubernetes client."""
        if self._k8s_loaded:
            return

        try:
            from kubernetes import client
            from kubernetes import config as k8s_config

            try:
                k8s_config.load_incluster_config()
            except Exception:
                k8s_config.load_kube_config()

            self.custom_api = client.CustomObjectsApi()
            self.core_api = client.CoreV1Api()
            self._k8s_loaded = True

        except ImportError:
            raise RuntimeError("kubernetes package not installed")

    def _create_envoy_configmap(
        self,
        sandbox_name: str,
        jwt_token: str,
    ) -> str:
        """
        Create a per-sandbox ConfigMap with JWT embedded in Envoy config.

        Each sandbox gets its own ConfigMap with the JWT as a static header.
        This ensures credential-resolver can cryptographically verify the
        sandbox identity and prevent credential theft via spoofed headers.

        Args:
            sandbox_name: Name of the sandbox
            jwt_token: JWT token to embed

        Returns:
            Name of the created ConfigMap
        """
        from kubernetes import client
        from kubernetes.client.rest import ApiException

        self._ensure_k8s_client()
        configmap_name = f"envoy-config-{sandbox_name}"
        cred_resolver_ns = os.getenv(
            "CREDENTIAL_RESOLVER_NAMESPACE", "incidentfox-prod"
        )

        # Envoy configuration with JWT embedded
        envoy_config = f"""# Envoy proxy configuration for credential injection
# Per-sandbox config with embedded JWT for authentication
# Generated by SandboxManager

admin:
  address:
    socket_address:
      address: 127.0.0.1
      port_value: 9901

static_resources:
  listeners:
  - name: http_proxy
    address:
      socket_address:
        address: 0.0.0.0
        port_value: 8001
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: credential_proxy
          codec_type: AUTO

          http_protocol_options:
            allow_absolute_url: true

          route_config:
            name: proxy_routes
            virtual_hosts:
            - name: localhost_proxy
              domains:
              - "localhost:8001"
              - "127.0.0.1:8001"
              - "localhost"
              routes:
              # Anthropic API
              - match:
                  prefix: "/v1/"
                route:
                  cluster: anthropic
                  auto_host_rewrite: true
              # Coralogix API
              - match:
                  prefix: "/api/v1/dataprime/"
                route:
                  cluster: coralogix_us2
                  auto_host_rewrite: true

            - name: anthropic
              domains:
              - "api.anthropic.com"
              - "api.anthropic.com:443"
              routes:
              - match:
                  prefix: "/"
                route:
                  cluster: anthropic
                  auto_host_rewrite: true

          http_filters:
          - name: envoy.filters.http.ext_authz
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz
              transport_api_version: V3
              http_service:
                server_uri:
                  uri: http://credential-resolver-svc.{cred_resolver_ns}.svc.cluster.local:8002/check
                  cluster: ext_authz
                  timeout: 2s
                authorization_request:
                  headers_to_add:
                  - key: "x-sandbox-jwt"
                    value: "{jwt_token}"
                  - key: "x-original-host"
                    value: "%REQ(:authority)%"
                authorization_response:
                  allowed_upstream_headers:
                    patterns:
                    - exact: "authorization"
                    - exact: "x-api-key"
              failure_mode_allow: false

          - name: envoy.filters.http.router
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router

  clusters:
  - name: ext_authz
    type: STRICT_DNS
    lb_policy: ROUND_ROBIN
    load_assignment:
      cluster_name: ext_authz
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: credential-resolver-svc.{cred_resolver_ns}.svc.cluster.local
                port_value: 8002

  - name: anthropic
    type: LOGICAL_DNS
    dns_lookup_family: V4_ONLY
    lb_policy: ROUND_ROBIN
    load_assignment:
      cluster_name: anthropic
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: api.anthropic.com
                port_value: 443
    transport_socket:
      name: envoy.transport_sockets.tls
      typed_config:
        "@type": type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext
        sni: api.anthropic.com

  - name: coralogix_us2
    type: LOGICAL_DNS
    dns_lookup_family: V4_ONLY
    lb_policy: ROUND_ROBIN
    load_assignment:
      cluster_name: coralogix_us2
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: api.us2.coralogix.com
                port_value: 443
    transport_socket:
      name: envoy.transport_sockets.tls
      typed_config:
        "@type": type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext
        sni: api.us2.coralogix.com
"""

        configmap = client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=client.V1ObjectMeta(
                name=configmap_name,
                namespace=self.namespace,
                labels={
                    "app": "incidentfox",
                    "component": "envoy-config",
                    "sandbox": sandbox_name,
                },
            ),
            data={"envoy.yaml": envoy_config},
        )

        try:
            self.core_api.create_namespaced_config_map(
                namespace=self.namespace, body=configmap
            )
        except ApiException as e:
            if e.status == 409:
                self.core_api.replace_namespaced_config_map(
                    name=configmap_name, namespace=self.namespace, body=configmap
                )
            else:
                raise

        return configmap_name

    def _delete_envoy_configmap(self, sandbox_name: str):
        """Delete the per-sandbox Envoy ConfigMap."""
        from kubernetes.client.rest import ApiException

        configmap_name = f"envoy-config-{sandbox_name}"
        try:
            self.core_api.delete_namespaced_config_map(
                name=configmap_name, namespace=self.namespace
            )
        except ApiException as e:
            if e.status != 404:
                raise

    def _build_container_env(
        self,
        tenant_id: str,
        team_id: str,
        thread_id: str,
        sandbox_name: str,
        jwt_token: str,
        team_token: Optional[str],
        llm_model: Optional[str],
        configured_integrations: str,
    ) -> list:
        """
        Build environment variables for the agent container.

        Supports:
        - Multi-tenant context (tenant_id, team_id)
        - Config-driven agents (TEAM_TOKEN)
        - Multi-LLM support (LLM_MODEL, API keys from secrets)
        - Envoy proxy routing (ANTHROPIC_BASE_URL)
        """
        cred_resolver_ns = os.getenv(
            "CREDENTIAL_RESOLVER_NAMESPACE", "incidentfox-prod"
        )

        env = [
            # Tenant context
            {"name": "INCIDENTFOX_TENANT_ID", "value": tenant_id},
            {"name": "INCIDENTFOX_TEAM_ID", "value": team_id},
            # Session identifiers
            {"name": "THREAD_ID", "value": thread_id},
            {"name": "SANDBOX_NAME", "value": sandbox_name},
            {"name": "NAMESPACE", "value": self.namespace},
            # Sandbox JWT for credential-resolver auth
            {"name": "SANDBOX_JWT", "value": jwt_token},
            # Envoy proxy: route Anthropic API through sidecar
            {"name": "ANTHROPIC_BASE_URL", "value": "http://localhost:8001"},
            # Placeholder key - proxy injects real key
            {
                "name": "ANTHROPIC_API_KEY",
                "value": "sk-ant-placeholder-proxy-will-inject",
            },
            # Configured integrations metadata (non-sensitive)
            {"name": "CONFIGURED_INTEGRATIONS", "value": configured_integrations},
            # Integration proxy URLs (credential-resolver handles auth)
            {"name": "CORALOGIX_BASE_URL", "value": "http://localhost:8001"},
            {
                "name": "CONFLUENCE_BASE_URL",
                "value": f"http://credential-resolver-svc.{cred_resolver_ns}.svc.cluster.local:8002/confluence",
            },
            {
                "name": "GRAFANA_BASE_URL",
                "value": f"http://credential-resolver-svc.{cred_resolver_ns}.svc.cluster.local:8002/grafana",
            },
            {
                "name": "GITHUB_BASE_URL",
                "value": f"http://credential-resolver-svc.{cred_resolver_ns}.svc.cluster.local:8002/github",
            },
            {
                "name": "DATADOG_BASE_URL",
                "value": f"http://credential-resolver-svc.{cred_resolver_ns}.svc.cluster.local:8002/datadog",
            },
            # Kubeconfig for K8s tools
            {"name": "KUBECONFIG", "value": "/home/agent/.kube/config"},
        ]

        # Config-driven agents: TEAM_TOKEN enables loading config from Config Service
        if team_token:
            env.append({"name": "TEAM_TOKEN", "value": team_token})

        # LLM model override
        if llm_model:
            env.append({"name": "LLM_MODEL", "value": llm_model})
        else:
            # Try to get from environment or K8s secret
            env.append(
                {
                    "name": "LLM_MODEL",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": "incidentfox-secrets",
                            "key": "llm-model",
                            "optional": True,
                        }
                    },
                }
            )

        # Multi-LLM API keys (from K8s secrets)
        env.extend(
            [
                {
                    "name": "GEMINI_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": "incidentfox-secrets",
                            "key": "gemini-api-key",
                            "optional": True,
                        }
                    },
                },
                {
                    "name": "OPENAI_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": "incidentfox-secrets",
                            "key": "openai-api-key",
                            "optional": True,
                        }
                    },
                },
                # Laminar observability (optional)
                {
                    "name": "LMNR_PROJECT_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": "incidentfox-secrets",
                            "key": "laminar-api-key",
                            "optional": True,
                        }
                    },
                },
                # Langfuse observability (optional)
                {
                    "name": "LANGFUSE_PUBLIC_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": "incidentfox-langfuse",
                            "key": "LANGFUSE_PUBLIC_KEY",
                            "optional": True,
                        }
                    },
                },
                {
                    "name": "LANGFUSE_SECRET_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": "incidentfox-langfuse",
                            "key": "LANGFUSE_SECRET_KEY",
                            "optional": True,
                        }
                    },
                },
                {
                    "name": "LANGFUSE_HOST",
                    "value": os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com"),
                },
            ]
        )

        return env

    def create_sandbox(
        self,
        thread_id: str,
        tenant_id: str = "local",
        team_id: str = "local",
        ttl_hours: int = 2,
        jwt_token: Optional[str] = None,
        team_token: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> SandboxInfo:
        """
        Create a new sandbox for an investigation.

        The sandbox runs a FastAPI server on port 8888 that accepts /execute requests.
        Credentials are injected via Envoy sidecar ext_authz, not directly.

        Args:
            thread_id: Unique identifier for the investigation thread
            tenant_id: Organization/tenant ID for credential lookup
            team_id: Team node ID for credential lookup
            ttl_hours: Hours until automatic cleanup (default: 2)
            jwt_token: Pre-generated JWT for session reuse
            team_token: Team token for Config Service auth (enables config-driven agents)
            llm_model: LLM model to use (e.g., 'anthropic/claude-sonnet-4-20250514')

        Returns:
            SandboxInfo with details about the created sandbox
        """
        self._ensure_k8s_client()
        from kubernetes.client.rest import ApiException

        sandbox_name = f"investigation-{thread_id}"
        shutdown_time = (datetime.utcnow() + timedelta(hours=ttl_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        # Generate JWT if not provided
        if jwt_token is None:
            jwt_token = generate_sandbox_jwt(
                tenant_id=tenant_id,
                team_id=team_id,
                sandbox_name=sandbox_name,
                thread_id=thread_id,
                ttl_hours=ttl_hours + 1,
            )

        cred_resolver_ns = os.getenv(
            "CREDENTIAL_RESOLVER_NAMESPACE", "incidentfox-prod"
        )

        # Fetch configured integrations
        configured_integrations = fetch_configured_integrations(
            jwt_token, tenant_id, team_id
        )

        # Create per-sandbox ConfigMap
        envoy_configmap_name = self._create_envoy_configmap(sandbox_name, jwt_token)

        # Build sandbox manifest
        sandbox_manifest = {
            "apiVersion": "agents.x-k8s.io/v1alpha1",
            "kind": "Sandbox",
            "metadata": {
                "name": sandbox_name,
                "namespace": self.namespace,
                "labels": {
                    "app": "incidentfox",
                    "thread-id": thread_id,
                    "managed-by": "unified-agent",
                },
            },
            "spec": {
                "podTemplate": {
                    "metadata": {
                        "labels": {
                            "app": "incidentfox-sandbox",  # Different from incidentfox-agent to avoid service routing
                            "thread-id": thread_id,
                        }
                    },
                    "spec": {
                        "containers": [
                            # Main agent container
                            {
                                "name": "agent",
                                "image": self.image,
                                "imagePullPolicy": (
                                    "Always"
                                    if "ecr" in self.image or "gcr" in self.image
                                    else "IfNotPresent"
                                ),
                                "ports": [{"containerPort": 8888, "name": "sandbox"}],
                                "env": self._build_container_env(
                                    tenant_id=tenant_id,
                                    team_id=team_id,
                                    thread_id=thread_id,
                                    sandbox_name=sandbox_name,
                                    jwt_token=jwt_token,
                                    team_token=team_token,
                                    llm_model=llm_model,
                                    configured_integrations=configured_integrations,
                                ),
                                "resources": {
                                    "requests": {
                                        "memory": "512Mi",
                                        "cpu": "100m",
                                        "ephemeral-storage": "2Gi",
                                    },
                                    "limits": {
                                        "memory": "2Gi",
                                        "cpu": "2000m",
                                        "ephemeral-storage": "10Gi",
                                    },
                                },
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "runAsNonRoot": True,
                                    "runAsUser": 1000,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                            },
                            # Envoy sidecar
                            {
                                "name": "envoy",
                                "image": "envoyproxy/envoy:v1.28-latest",
                                "args": [
                                    "--config-path",
                                    "/etc/envoy/envoy.yaml",
                                    "--log-level",
                                    "warn",
                                ],
                                "ports": [{"containerPort": 8001, "name": "proxy"}],
                                "volumeMounts": [
                                    {
                                        "name": "envoy-config",
                                        "mountPath": "/etc/envoy",
                                        "readOnly": True,
                                    }
                                ],
                                "resources": {
                                    "requests": {"cpu": "50m", "memory": "64Mi"},
                                    "limits": {"cpu": "200m", "memory": "128Mi"},
                                },
                                "securityContext": {
                                    "runAsNonRoot": True,
                                    "runAsUser": 1000,
                                    "allowPrivilegeEscalation": False,
                                },
                            },
                        ],
                        "volumes": [
                            {
                                "name": "envoy-config",
                                "configMap": {"name": envoy_configmap_name},
                            }
                        ],
                    },
                },
                "shutdownTime": shutdown_time,
                "replicas": 1,
            },
        }

        # Add gVisor runtime if enabled
        if os.getenv("USE_GVISOR", "false").lower() == "true":
            sandbox_manifest["spec"]["podTemplate"]["spec"][
                "runtimeClassName"
            ] = "gvisor"

        try:
            self.custom_api.create_namespaced_custom_object(
                group="agents.x-k8s.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="sandboxes",
                body=sandbox_manifest,
            )

            return SandboxInfo(
                name=sandbox_name,
                thread_id=thread_id,
                created_at=datetime.utcnow(),
                namespace=self.namespace,
                jwt_token=jwt_token,
            )
        except ApiException as e:
            raise SandboxExecutionError(f"Failed to create sandbox: {e}")

    def get_sandbox(self, thread_id: str) -> Optional[SandboxInfo]:
        """Get sandbox info for a thread."""
        self._ensure_k8s_client()
        from kubernetes.client.rest import ApiException

        sandbox_name = f"investigation-{thread_id}"

        try:
            sandbox = self.custom_api.get_namespaced_custom_object(
                group="agents.x-k8s.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="sandboxes",
                name=sandbox_name,
            )

            created = sandbox.get("metadata", {}).get("creationTimestamp")
            return SandboxInfo(
                name=sandbox_name,
                thread_id=thread_id,
                created_at=(
                    datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if created
                    else datetime.utcnow()
                ),
                namespace=self.namespace,
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def delete_sandbox(self, thread_id: str):
        """Delete a sandbox and clean up resources."""
        self._ensure_k8s_client()
        from kubernetes.client.rest import ApiException

        sandbox_name = f"investigation-{thread_id}"

        try:
            self.custom_api.delete_namespaced_custom_object(
                group="agents.x-k8s.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="sandboxes",
                name=sandbox_name,
            )
        except ApiException as e:
            if e.status != 404:
                raise

        self._delete_envoy_configmap(sandbox_name)

    def wait_for_ready(self, thread_id: str, timeout: int = 120) -> bool:
        """
        Wait for sandbox pod to be ready.

        Args:
            thread_id: Investigation thread ID
            timeout: Max wait time in seconds

        Returns:
            True if ready, False if timeout
        """
        self._ensure_k8s_client()
        start_time = time.time()
        sandbox_name = f"investigation-{thread_id}"

        while time.time() - start_time < timeout:
            try:
                pods = self.core_api.list_namespaced_pod(
                    namespace=self.namespace,
                    label_selector=f"thread-id={thread_id}",
                )

                if pods.items:
                    pod = pods.items[0]
                    if pod.status.phase == "Running":
                        for condition in pod.status.conditions or []:
                            if condition.type == "Ready" and condition.status == "True":
                                # Verify FastAPI server is responding
                                try:
                                    router_url = self.get_router_url()
                                    response = requests.get(
                                        f"{router_url}/health",
                                        headers={
                                            "X-Sandbox-ID": sandbox_name,
                                            "X-Sandbox-Port": "8888",
                                            "X-Sandbox-Namespace": self.namespace,
                                        },
                                        timeout=5,
                                    )
                                    if response.status_code == 200:
                                        time.sleep(0.5)
                                        return True
                                except requests.RequestException:
                                    pass
            except Exception:
                pass

            time.sleep(2)

        return False

    def get_router_url(self) -> str:
        """Get the Router URL for sandbox communication."""
        local_port = os.getenv("ROUTER_LOCAL_PORT")
        if local_port:
            return f"http://localhost:{local_port}"
        router_namespace = os.getenv("ROUTER_NAMESPACE", "incidentfox-prod")
        return f"http://sandbox-router-svc.{router_namespace}.svc.cluster.local:8080"

    def execute_in_sandbox(
        self,
        sandbox_info: SandboxInfo,
        prompt: str,
        images: Optional[list] = None,
    ) -> requests.Response:
        """
        Execute an investigation in the sandbox via Router (streaming).

        Args:
            sandbox_info: Sandbox information
            prompt: Investigation prompt
            images: Optional list of image dicts

        Returns:
            Streaming requests.Response

        Raises:
            SandboxExecutionError: If execution fails
        """
        router_url = self.get_router_url()

        headers = {
            "X-Sandbox-ID": sandbox_info.name,
            "X-Sandbox-Port": "8888",
            "X-Sandbox-Namespace": self.namespace,
        }

        payload = {"prompt": prompt, "thread_id": sandbox_info.thread_id}
        if images:
            payload["images"] = images

        try:
            response = requests.post(
                f"{router_url}/execute",
                headers=headers,
                json=payload,
                stream=True,
                timeout=(30, None),
            )
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            raise SandboxExecutionError(f"Failed to execute in sandbox: {e}")

    def interrupt_sandbox(self, sandbox_info: SandboxInfo) -> requests.Response:
        """
        Interrupt the current execution in the sandbox.

        Args:
            sandbox_info: Sandbox information

        Returns:
            Streaming requests.Response

        Raises:
            SandboxInterruptError: If interrupt fails
        """
        router_url = self.get_router_url()

        headers = {
            "X-Sandbox-ID": sandbox_info.name,
            "X-Sandbox-Port": "8888",
            "X-Sandbox-Namespace": self.namespace,
        }

        payload = {"thread_id": sandbox_info.thread_id}

        try:
            response = requests.post(
                f"{router_url}/interrupt",
                headers=headers,
                json=payload,
                stream=True,
                timeout=(30, None),
            )
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            raise SandboxInterruptError(f"Failed to interrupt sandbox: {e}")
