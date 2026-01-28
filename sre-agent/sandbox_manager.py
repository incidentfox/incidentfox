"""
Kubernetes Sandbox Manager

Manages isolated sandboxes for investigations using K8s agent-sandbox.
Follows the agent-sandbox pattern with FastAPI servers running on port 8888.
"""

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests
from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException


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


class SandboxManager:
    """Manage investigation sandboxes in Kubernetes."""

    def __init__(
        self, namespace: str = "default", image: str = "incidentfox-agent:latest"
    ):
        """
        Initialize sandbox manager.

        Args:
            namespace: Kubernetes namespace for sandboxes
            image: Docker image to use for sandboxes (defaults to local image,
                   use ECR URI for production: xxx.dkr.ecr.region.amazonaws.com/incidentfox-agent:latest)
        """
        self.namespace = namespace
        self.image = image
        self._load_k8s_config()
        self.custom_api = client.CustomObjectsApi()
        self.core_api = client.CoreV1Api()

    def _load_k8s_config(self):
        """Load Kubernetes configuration."""
        try:
            # Try in-cluster config first (when running in K8s)
            k8s_config.load_incluster_config()
        except:
            # Fall back to local kubeconfig (development)
            k8s_config.load_kube_config()

    def create_sandbox(self, thread_id: str, ttl_hours: int = 2) -> SandboxInfo:
        """
        Create a new sandbox for an investigation.

        The sandbox runs a FastAPI server on port 8888 that accepts /execute requests.

        Args:
            thread_id: Unique identifier for the investigation thread
            ttl_hours: Hours until automatic cleanup (default: 2, balances resource usage and follow-up window)

        Returns:
            SandboxInfo with details about the created sandbox
        """
        sandbox_name = f"investigation-{thread_id}"

        # Calculate shutdown time (TTL-based cleanup)
        shutdown_time = (datetime.utcnow() + timedelta(hours=ttl_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        sandbox_manifest = {
            "apiVersion": "agents.x-k8s.io/v1alpha1",
            "kind": "Sandbox",
            "metadata": {
                "name": sandbox_name,
                "namespace": self.namespace,
                "labels": {
                    "app": "incidentfox",
                    "thread-id": thread_id,
                    "managed-by": "incidentfox-server",
                },
            },
            "spec": {
                "podTemplate": {
                    "metadata": {
                        "labels": {
                            "app": "incidentfox-agent",
                            "thread-id": thread_id,
                        }
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "agent",
                                "image": self.image,
                                "imagePullPolicy": (
                                    "Always"
                                    if "ecr" in self.image or "gcr" in self.image
                                    else "IfNotPresent"
                                ),
                                # FastAPI server runs automatically via CMD in Dockerfile
                                "ports": [{"containerPort": 8888, "name": "sandbox"}],
                                "env": [
                                    # Core
                                    {
                                        "name": "ANTHROPIC_API_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "anthropic-api-key",
                                            }
                                        },
                                    },
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
                                    # Observability
                                    {
                                        "name": "CORALOGIX_API_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "coralogix-api-key",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "CORALOGIX_DOMAIN",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "coralogix-domain",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "DATADOG_API_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "datadog-api-key",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "DATADOG_APP_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "datadog-app-key",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "DATADOG_SITE",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "datadog-site",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "PROMETHEUS_URL",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "prometheus-url",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "ALERTMANAGER_URL",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "alertmanager-url",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "GRAFANA_URL",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "grafana-url",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "GRAFANA_API_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "grafana-api-key",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "SENTRY_AUTH_TOKEN",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "sentry-auth-token",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "SENTRY_ORGANIZATION",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "sentry-organization",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "SENTRY_PROJECT",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "sentry-project",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    # Logging backends
                                    {
                                        "name": "ELASTICSEARCH_URL",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "elasticsearch-url",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "ELASTICSEARCH_INDEX",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "elasticsearch-index",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "LOKI_URL",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "loki-url",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "SPLUNK_HOST",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "splunk-host",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "SPLUNK_TOKEN",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "splunk-token",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "SPLUNK_PORT",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "splunk-port",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    # Collaboration
                                    {
                                        "name": "GITHUB_TOKEN",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "github-token",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "GITHUB_APP_ID",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "github-app-id",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "GITHUB_PRIVATE_KEY_B64",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "github-private-key-b64",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "GITHUB_WEBHOOK_SECRET",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "github-webhook-secret",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "GITHUB_INSTALLATION_ID",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "github-installation-id",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "GITHUB_REPOSITORY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "github-repository",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "SLACK_BOT_TOKEN",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "slack-bot-token",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "SLACK_DEFAULT_CHANNEL",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "slack-default-channel",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "PAGERDUTY_API_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "pagerduty-api-key",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    # AWS
                                    {
                                        "name": "AWS_ACCESS_KEY_ID",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "aws-access-key-id",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "AWS_SECRET_ACCESS_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "aws-secret-access-key",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "AWS_REGION",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "aws-region",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    # Advanced features
                                    {
                                        "name": "DATABASE_URL",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "database-url",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "SERVICE_CATALOG_PATH",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "service-catalog-path",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "HISTORY_DB_PATH",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "history-db-path",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    {
                                        "name": "REMEDIATION_LOG_PATH",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "incidentfox-secrets",
                                                "key": "remediation-log-path",
                                                "optional": True,
                                            }
                                        },
                                    },
                                    # Kubernetes context (use pre-configured kubeconfig for incidentfox-demo cluster)
                                    {
                                        "name": "KUBECONFIG",
                                        "value": "/home/agent/.kube/config",
                                    },
                                    # Dynamic values
                                    {"name": "THREAD_ID", "value": thread_id},
                                    {"name": "SANDBOX_NAME", "value": sandbox_name},
                                    {"name": "NAMESPACE", "value": self.namespace},
                                ],
                                "resources": {
                                    "requests": {
                                        "memory": "512Mi",
                                        "cpu": "100m",  # Low: agents are I/O-bound (Claude API calls)
                                        "ephemeral-storage": "2Gi",
                                    },
                                    "limits": {
                                        "memory": "2Gi",
                                        "cpu": "2000m",  # High: allows bursts for git/file ops
                                        "ephemeral-storage": "10Gi",  # Large for file attachments
                                    },
                                },
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "runAsNonRoot": True,
                                    "runAsUser": 1000,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                            }
                        ]
                    },
                },
                # Automatic cleanup after TTL
                "lifecycle": {
                    "shutdownTime": shutdown_time,
                    "shutdownPolicy": "Delete",
                },
                "replicas": 1,
            },
        }

        # Add gVisor runtime for production (optional for local dev)
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
            )
        except ApiException as e:
            raise Exception(f"Failed to create sandbox: {e}")

    def get_sandbox(self, thread_id: str) -> Optional[SandboxInfo]:
        """Get sandbox info for a thread. Returns info if sandbox exists."""
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
        """Delete a sandbox and clean up port-forward."""
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

    def wait_for_ready(self, thread_id: str, timeout: int = 120) -> bool:
        """
        Wait for sandbox pod to be ready and FastAPI server to be responding.

        Args:
            thread_id: Investigation thread ID
            timeout: Max wait time in seconds

        Returns:
            True if ready, False if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Get pods for this sandbox
                pods = self.core_api.list_namespaced_pod(
                    namespace=self.namespace, label_selector=f"thread-id={thread_id}"
                )

                if not pods.items:
                    time.sleep(2)
                    continue

                pod = pods.items[0]

                # Check if pod is ready
                if pod.status.phase == "Running":
                    for condition in pod.status.conditions or []:
                        if condition.type == "Ready" and condition.status == "True":
                            # Pod is ready, now check if FastAPI server is responding
                            # We'll verify this when we actually try to execute
                            return True

            except ApiException:
                pass

            time.sleep(2)

        return False

    def get_router_url(self) -> str:
        """
        Get the Router URL for sandbox communication.

        Returns http://sandbox-router-svc.<namespace>.svc.cluster.local:8080 for in-cluster,
        or http://localhost:8080 if ROUTER_LOCAL_PORT env var is set for development.
        """
        local_port = os.getenv("ROUTER_LOCAL_PORT")
        if local_port:
            return f"http://localhost:{local_port}"
        # Router is deployed in incidentfox-prod namespace, sandboxes in default
        router_namespace = os.getenv("ROUTER_NAMESPACE", "incidentfox-prod")
        return f"http://sandbox-router-svc.{router_namespace}.svc.cluster.local:8080"

    def execute_in_sandbox(
        self,
        sandbox_info: SandboxInfo,
        prompt: str,
        images: list = None,
        file_downloads: list = None,
    ) -> requests.Response:
        """
        Execute an investigation in the sandbox via the Sandbox Router (streaming).

        This returns a streaming response that yields chunks as they arrive,
        enabling real-time display of agent output.

        Args:
            sandbox_info: Sandbox information
            prompt: Investigation prompt
            images: Optional list of image dicts (type, media_type, data, filename)
            file_downloads: Optional list of file download info for sandbox to fetch via proxy
                           Each dict has: {token, filename, size, media_type, proxy_url}

        Returns:
            requests.Response object with stream=True

        Raises:
            SandboxExecutionError: If the request to the sandbox fails
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

        if file_downloads:
            payload["file_downloads"] = file_downloads

        try:
            response = requests.post(
                f"{router_url}/execute",
                headers=headers,
                json=payload,
                stream=True,
                timeout=300,  # 5 minute timeout
            )
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            raise SandboxExecutionError(
                f"Failed to execute in sandbox via Router: {e}"
            ) from e

    def interrupt_sandbox(self, sandbox_info: SandboxInfo) -> requests.Response:
        """
        Interrupt the current execution in the sandbox (streaming).

        This allows users to stop a long-running task mid-execution.
        After interrupt, new messages should be sent via the normal /investigate endpoint.

        The Router uses the same headers as execute_in_sandbox but calls the
        /interrupt endpoint instead.

        Args:
            sandbox_info: Sandbox information

        Returns:
            requests.Response object (streaming)

        Raises:
            SandboxInterruptError: If the interrupt request fails

        Note: This follows Cursor's UX - interrupt just stops, new messages
        are queued separately.
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
                timeout=300,  # 5 minute timeout
            )
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            raise SandboxInterruptError(
                f"Failed to interrupt sandbox via Router: {e}"
            ) from e

    def send_answer_to_sandbox(self, sandbox_info: SandboxInfo, answers: dict) -> dict:
        """
        Send answer to AskUserQuestion to the sandbox via the Router.

        Args:
            sandbox_info: Sandbox information
            answers: User's answers to the questions

        Returns:
            Response from sandbox

        Raises:
            SandboxExecutionError: If the request fails
        """
        router_url = self.get_router_url()

        headers = {
            "X-Sandbox-ID": sandbox_info.name,
            "X-Sandbox-Port": "8888",
            "X-Sandbox-Namespace": self.namespace,
        }

        payload = {"thread_id": sandbox_info.thread_id, "answers": answers}

        try:
            response = requests.post(
                f"{router_url}/answer", headers=headers, json=payload, timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise SandboxExecutionError(
                f"Failed to send answer to sandbox via Router: {e}"
            ) from e
