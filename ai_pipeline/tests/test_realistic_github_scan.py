"""
Realistic GitHub scanner tests using actual file contents from
the incidentfox/aws-playground repository.

This repo is a microservices monorepo (OpenTelemetry Demo fork) with:
- 28 services across Go, Python, Java, Node.js, C#, Rust, Ruby, C++, PHP
- Terraform (EKS, VPC, Secrets Manager, KMS)
- Helm charts with AWS-specific values
- Docker Compose for local dev
- GitHub Actions CI
- Kafka-based async messaging layer

Tests validate the GitHub scanner produces meaningful architecture maps
and ops docs from this real-world codebase.
"""

import base64
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from ai_learning_pipeline.tasks.scanners import get_scanner
from ai_learning_pipeline.tasks.scanners.github_scanner import (
    _collect_infra_signals,
    _format_architecture_document,
    _format_repo_summaries,
    _scan_ops_docs,
)

# ===================================================================
# Real file contents from incidentfox/aws-playground
# ===================================================================

# This is a monorepo — everything is in one repo, services live under src/
REPO_NAME = "aws-playground"
REPO_FULL_NAME = "incidentfox/aws-playground"
GITHUB_ORG = "incidentfox"

REAL_FILES: Dict[str, str] = {
    # --- Root README ---
    "README.md": """# OpenTelemetry Astronomy Shop Demo

This repository contains the OpenTelemetry Astronomy Shop, a microservice-based
distributed system intended to illustrate the implementation of OpenTelemetry in
a near real-world environment.

### IncidentFox Lab Setup

This fork includes IncidentFox-specific configurations for AI SRE agent development:

- [IncidentFox Documentation](./incidentfox/README.md) - Complete setup guide
- [Local Setup](./incidentfox/docs/local-setup.md) - Run locally with Docker or Kubernetes
- [Agent Integration](./incidentfox/docs/agent-integration.md) - Connect your AI agent
- [Incident Scenarios](./incidentfox/docs/incident-scenarios.md) - Trigger test incidents
""",
    # --- Checkout service (Go) ---
    "src/checkout/Dockerfile": """FROM golang:1.24-bookworm AS builder
WORKDIR /usr/src/app/
COPY ./src/checkout/go.mod go.mod
COPY ./src/checkout/go.sum go.sum
RUN go mod download
COPY ./src/checkout/genproto/oteldemo/ genproto/oteldemo/
COPY ./src/checkout/kafka/ kafka/
COPY ./src/checkout/money/ money/
COPY ./src/checkout/main.go main.go
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags "-s -w" -o checkout main.go

FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /usr/src/app/
COPY --from=builder /usr/src/app/checkout/ ./
EXPOSE ${CHECKOUT_PORT}
ENTRYPOINT [ "./checkout" ]
""",
    "src/checkout/go.mod": """module github.com/open-telemetry/opentelemetry-demo/src/checkout

go 1.24.2

require (
\tgithub.com/IBM/sarama v1.46.3
\tgithub.com/google/uuid v1.6.0
\tgo.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc v0.64.0
\tgo.opentelemetry.io/otel v1.39.0
\tgoogle.golang.org/grpc v1.77.0
\tgoogle.golang.org/protobuf v1.36.11
)
""",
    # --- Payment service (Node.js) ---
    "src/payment/Dockerfile": """FROM docker.io/library/node:22-slim AS builder
WORKDIR /usr/src/app/
COPY ./src/payment/package.json package.json
COPY ./src/payment/package-lock.json package-lock.json
RUN npm ci --omit=dev

FROM gcr.io/distroless/nodejs22-debian12:nonroot
WORKDIR /usr/src/app/
COPY --from=builder /usr/src/app/node_modules/ node_modules/
COPY ./pb/demo.proto demo.proto
COPY ./src/payment/charge.js charge.js
COPY ./src/payment/index.js index.js
EXPOSE ${PAYMENT_PORT}
CMD ["--require=./opentelemetry.js", "index.js"]
""",
    "src/payment/package.json": """{
  "name": "payment",
  "description": "Payment Service",
  "main": "index.js",
  "dependencies": {
    "@grpc/grpc-js": "1.12.6",
    "@grpc/proto-loader": "0.8.0",
    "@opentelemetry/api": "1.9.0",
    "@opentelemetry/auto-instrumentations-node": "0.67.2",
    "@opentelemetry/sdk-node": "0.208.0",
    "simple-card-validator": "1.1.0",
    "uuid": "13.0.0"
  }
}
""",
    # --- Recommendation service (Python) ---
    "src/recommendation/Dockerfile": """FROM docker.io/library/python:3.12-alpine3.22 AS build-venv
RUN apk update && apk add gcc g++ linux-headers
COPY ./src/recommendation/requirements.txt requirements.txt
RUN python -m venv venv && venv/bin/pip install --no-cache-dir -r requirements.txt
RUN venv/bin/opentelemetry-bootstrap -a install

FROM docker.io/library/python:3.12-alpine3.22
COPY --from=build-venv /venv/ /venv/
WORKDIR /app
COPY ./src/recommendation/recommendation_server.py recommendation_server.py
EXPOSE ${RECOMMENDATION_PORT}
ENTRYPOINT [ "/venv/bin/opentelemetry-instrument", "/venv/bin/python", "recommendation_server.py" ]
""",
    "src/recommendation/requirements.txt": """grpcio-health-checking==1.71.0
opentelemetry-distro==0.60b1
opentelemetry-exporter-otlp-proto-grpc==1.39.1
psutil==7.0.0
python-dotenv==1.2.1
python-json-logger==4.0.0
""",
    # --- Docker Compose (truncated, key services) ---
    "docker-compose.yml": """services:
  accounting:
    image: ${IMAGE_NAME}:${DEMO_VERSION}-accounting
    container_name: accounting
    environment:
      - KAFKA_ADDR
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://${OTEL_COLLECTOR_HOST}:${OTEL_COLLECTOR_PORT_HTTP}
      - OTEL_SERVICE_NAME=accounting
      - DB_CONNECTION_STRING=Host=${POSTGRES_HOST};Username=otelu;Password=otelp;Database=${POSTGRES_DB}
    depends_on:
      otel-collector:
        condition: service_started
      kafka:
        condition: service_healthy

  checkout:
    image: ${IMAGE_NAME}:${DEMO_VERSION}-checkout
    container_name: checkout
    environment:
      - CHECKOUT_PORT
      - KAFKA_ADDR
      - OTEL_SERVICE_NAME=checkout
    depends_on:
      - kafka
      - otel-collector

  payment:
    image: ${IMAGE_NAME}:${DEMO_VERSION}-payment
    container_name: payment
    environment:
      - PAYMENT_PORT
      - OTEL_SERVICE_NAME=payment
    depends_on:
      - otel-collector

  frontend:
    image: ${IMAGE_NAME}:${DEMO_VERSION}-frontend
    container_name: frontend
    environment:
      - FRONTEND_PORT
      - FRONTEND_ADDR
      - OTEL_SERVICE_NAME=frontend

  kafka:
    image: ${IMAGE_NAME}:${DEMO_VERSION}-kafka
    container_name: kafka
    environment:
      - KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:9092
    healthcheck:
      test: nc -z kafka 9092

  postgres:
    image: postgres:16
    container_name: postgres
    environment:
      - POSTGRES_USER=otelu
      - POSTGRES_PASSWORD=otelp
      - POSTGRES_DB=${POSTGRES_DB}

  prometheus:
    image: quay.io/prometheus/prometheus:v3.4.1
    container_name: prometheus
    volumes:
      - ./src/prometheus/prometheus-config.yaml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana:11.6.0
    container_name: grafana
    volumes:
      - ./src/grafana/grafana.ini:/etc/grafana/grafana.ini
      - ./src/grafana/provisioning/:/etc/grafana/provisioning/

  jaeger:
    image: jaegertracing/all-in-one:1.68
    container_name: jaeger

  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.127.0
    container_name: otel-collector
""",
    # --- Terraform ---
    "incidentfox/terraform/main.tf": """provider "aws" {
  region = var.region
  default_tags {
    tags = merge(var.tags, {
      Environment = var.environment
      Project     = "incidentfox"
      ManagedBy   = "terraform"
    })
  }
}

resource "aws_kms_key" "ebs" {
  description             = "KMS key for EBS volume encryption (SOC2 compliance)"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

module "vpc" {
  source             = "./modules/vpc"
  cluster_name       = var.cluster_name
  vpc_cidr           = var.vpc_cidr
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
}

module "eks" {
  source              = "./modules/eks"
  cluster_name        = var.cluster_name
  cluster_version     = var.cluster_version
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  kms_key_arn         = aws_kms_key.ebs.arn
}

module "irsa" {
  source       = "./modules/irsa"
  cluster_name = var.cluster_name
  oidc_issuer  = module.eks.oidc_issuer
}
""",
    # --- Helm values ---
    "incidentfox/helm/values-aws.yaml": """global:
  region: us-west-2
  environment: lab

ingress:
  enabled: true
  className: alb
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip

persistence:
  enabled: true
  storageClassName: gp3

prometheus:
  server:
    persistentVolume:
      enabled: true
      storageClass: gp3
      size: 50Gi

grafana:
  persistence:
    enabled: true
    storageClassName: gp3
    size: 10Gi
  admin:
    existingSecret: grafana-credentials

postgresql:
  auth:
    existingSecret: postgres-credentials
""",
    # --- CI workflow ---
    ".github/workflows/telemetry-agent.yml": """name: IncidentFox Telemetry Agent

on:
  pull_request:
    types: [opened, reopened]

permissions:
  contents: read

jobs:
  suggest:
    name: Analyze PR for new services
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      contents: read
    steps:
      - name: Find new services in PR
        uses: actions/github-script@v8
""",
    # --- Kubernetes manifest ---
    "kubernetes/opentelemetry-demo.yaml": """apiVersion: v1
kind: Namespace
metadata:
  name: otel-demo
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-demo
  namespace: otel-demo
spec:
  replicas: 1
""",
    # --- Service dependencies doc (ops doc) ---
    "incidentfox/docs/service-dependencies.md": """# OpenTelemetry Demo - Service Dependencies

## Architecture Overview

Frontend Layer:
- Frontend (Next.js) <-> Frontend Proxy (Envoy) <-> Load Generator

Application Layer:
- Product Catalog (Go)
- Ad Service (Java)
- Recommendation (Python)
- Checkout (Go) -> Payment (Node.js), Shipping (Rust), Email (Ruby), Currency (C++)
- Cart (DotNet) -> Quote (PHP)

Async/Messaging Layer:
- Kafka (Message Queue)
- Accounting (DotNet) consumer
- Fraud Detection (Kotlin) consumer

Observability Layer:
- OpenTelemetry Collector -> Prometheus, Grafana, Jaeger
""",
}

# Repos list as returned by GitHub API for a monorepo org
MONOREPO_REPOS = [
    {"name": "aws-playground", "full_name": "incidentfox/aws-playground"},
]

# For multi-repo orgs (simulate additional repos)
MULTI_REPO_LIST = [
    {"name": "aws-playground", "full_name": "incidentfox/aws-playground"},
    {"name": "incidentfox", "full_name": "incidentfox/incidentfox"},
    {"name": "docs", "full_name": "incidentfox/docs"},
]


# ===================================================================
# Helpers
# ===================================================================


def _encode_file(content: str) -> Dict[str, Any]:
    """Create a GitHub API file response."""
    return {
        "content": base64.b64encode(content.encode()).decode(),
        "size": len(content),
    }


def _make_github_api_mock(
    repos: List[Dict],
    files: Dict[str, str],
    org: str = GITHUB_ORG,
):
    """Create a _github_api mock that serves real file contents."""

    def mock_api(
        path: str,
        token: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        # List repos
        if f"/orgs/{org}/repos" in path:
            return repos
        if f"/users/{org}/repos" in path:
            return repos

        # File contents
        if "/contents/" in path:
            parts = path.split("/contents/")
            if len(parts) == 2:
                file_path = parts[1]
                content = files.get(file_path)
                if content:
                    return _encode_file(content)
            return None

        return None

    return mock_api


# ===================================================================
# 1. Infra Signal Collection from Real Files
# ===================================================================


class TestInfraSignalCollection:
    """Test that _collect_infra_signals correctly picks up real infra files."""

    def test_collects_dockerfiles_and_deps(self):
        """Should find Dockerfile, docker-compose, go.mod, package.json, requirements.txt."""
        mock_api = _make_github_api_mock(MONOREPO_REPOS, REAL_FILES)

        with patch(
            "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
            side_effect=mock_api,
        ):
            signals = _collect_infra_signals(
                token="ghp_test",
                repos=MONOREPO_REPOS,
                github_org=GITHUB_ORG,
            )

        assert REPO_FULL_NAME in signals
        found_files = signals[REPO_FULL_NAME]

        # Root-level infra files should be found
        assert "docker-compose.yml" in found_files
        assert "Dockerfile" not in found_files  # no root Dockerfile

    def test_signal_content_is_truncated(self):
        """Large files should be truncated to 10K chars."""
        huge_content = "x" * 20_000
        files = {"docker-compose.yml": huge_content}
        mock_api = _make_github_api_mock(MONOREPO_REPOS, files)

        with patch(
            "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
            side_effect=mock_api,
        ):
            signals = _collect_infra_signals(
                token="ghp_test", repos=MONOREPO_REPOS, github_org=GITHUB_ORG
            )

        content = signals[REPO_FULL_NAME]["docker-compose.yml"]
        assert len(content) <= 10_000

    def test_skips_tiny_files(self):
        """Files with < 10 chars should be skipped."""
        files = {"docker-compose.yml": "tiny"}
        mock_api = _make_github_api_mock(MONOREPO_REPOS, files)

        with patch(
            "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
            side_effect=mock_api,
        ):
            signals = _collect_infra_signals(
                token="ghp_test", repos=MONOREPO_REPOS, github_org=GITHUB_ORG
            )

        # Repo should not appear (or be empty) since file was too small
        if REPO_FULL_NAME in signals:
            assert "docker-compose.yml" not in signals[REPO_FULL_NAME]


# ===================================================================
# 2. Ops Docs Discovery from Real Files
# ===================================================================


class TestOpsDocsDiscovery:
    """Test that _scan_ops_docs correctly finds operational documents."""

    def test_finds_readme(self):
        """Should find root README.md."""
        mock_api = _make_github_api_mock(MONOREPO_REPOS, REAL_FILES)

        with patch(
            "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
            side_effect=mock_api,
        ):
            docs = _scan_ops_docs(
                token="ghp_test",
                repos=MONOREPO_REPOS,
                github_org=GITHUB_ORG,
                org_id="org-123",
            )

        readme_docs = [d for d in docs if "README.md" in d.source_url]
        assert len(readme_docs) >= 1
        # Should contain IncidentFox-specific content
        assert any("IncidentFox" in d.content for d in readme_docs)

    def test_readme_is_markdown_type(self):
        """Ops docs should have content_type=markdown."""
        mock_api = _make_github_api_mock(MONOREPO_REPOS, REAL_FILES)

        with patch(
            "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
            side_effect=mock_api,
        ):
            docs = _scan_ops_docs(
                token="ghp_test",
                repos=MONOREPO_REPOS,
                github_org=GITHUB_ORG,
                org_id="org-123",
            )

        for doc in docs:
            assert doc.content_type == "markdown"

    def test_skips_short_docs(self):
        """Docs shorter than 50 chars should be skipped."""
        files = {"README.md": "# Hi\nShort."}
        mock_api = _make_github_api_mock(MONOREPO_REPOS, files)

        with patch(
            "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
            side_effect=mock_api,
        ):
            docs = _scan_ops_docs(
                token="ghp_test",
                repos=MONOREPO_REPOS,
                github_org=GITHUB_ORG,
                org_id="org-123",
            )

        assert len(docs) == 0

    def test_metadata_includes_repo_and_org(self):
        """Each doc should have correct metadata."""
        mock_api = _make_github_api_mock(MONOREPO_REPOS, REAL_FILES)

        with patch(
            "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
            side_effect=mock_api,
        ):
            docs = _scan_ops_docs(
                token="ghp_test",
                repos=MONOREPO_REPOS,
                github_org=GITHUB_ORG,
                org_id="org-123",
            )

        for doc in docs:
            assert doc.metadata["org_id"] == "org-123"
            assert doc.metadata["repo"] == REPO_FULL_NAME
            assert doc.metadata["source"] == "integration_scan"


# ===================================================================
# 3. Repo Summaries Formatting
# ===================================================================


class TestRepoSummaryFormatting:
    """Test _format_repo_summaries produces correct LLM context."""

    def test_formats_multiple_files(self):
        """Should create a readable text block with file headers."""
        repo_signals = {
            REPO_FULL_NAME: {
                "docker-compose.yml": REAL_FILES["docker-compose.yml"],
                "src/checkout/go.mod": REAL_FILES["src/checkout/go.mod"],
            }
        }

        summary = _format_repo_summaries(repo_signals)

        assert f"### Repository: {REPO_FULL_NAME}" in summary
        assert "**docker-compose.yml**" in summary
        assert "**src/checkout/go.mod**" in summary
        assert "kafka" in summary.lower()  # from docker-compose
        assert "sarama" in summary  # from go.mod (Kafka client)

    def test_formats_multi_repo(self):
        """Should separate repos with dividers."""
        repo_signals = {
            "incidentfox/aws-playground": {
                "docker-compose.yml": "services:\n  web: {}"
            },
            "incidentfox/incidentfox": {"Dockerfile": "FROM python:3.11"},
        }

        summary = _format_repo_summaries(repo_signals)

        assert "### Repository: incidentfox/aws-playground" in summary
        assert "### Repository: incidentfox/incidentfox" in summary
        assert "---" in summary  # divider between repos


# ===================================================================
# 4. Architecture Document Formatting
# ===================================================================


class TestArchitectureDocFormatting:
    """Test _format_architecture_document produces correct output."""

    def _make_real_architecture(self) -> Dict[str, Any]:
        """Architecture JSON that an LLM would produce from aws-playground."""
        return {
            "services": [
                {
                    "name": "checkout",
                    "repo": "incidentfox/aws-playground",
                    "language": "Go",
                    "framework": "gRPC",
                    "dependencies": [
                        "Kafka",
                        "Payment",
                        "Shipping",
                        "Email",
                        "Currency",
                    ],
                    "deployment": "Kubernetes/Docker",
                    "description": "Handles checkout flow, publishes order events to Kafka",
                },
                {
                    "name": "payment",
                    "repo": "incidentfox/aws-playground",
                    "language": "Node.js",
                    "framework": "gRPC",
                    "dependencies": [],
                    "deployment": "Kubernetes/Docker",
                    "description": "Processes credit card payments via gRPC",
                },
                {
                    "name": "recommendation",
                    "repo": "incidentfox/aws-playground",
                    "language": "Python",
                    "framework": "gRPC",
                    "dependencies": ["Product Catalog"],
                    "deployment": "Kubernetes/Docker",
                    "description": "Provides product recommendations based on catalog",
                },
                {
                    "name": "accounting",
                    "repo": "incidentfox/aws-playground",
                    "language": "C#/.NET",
                    "framework": "",
                    "dependencies": ["Kafka", "PostgreSQL"],
                    "deployment": "Kubernetes/Docker",
                    "description": "Kafka consumer that records transactions to PostgreSQL",
                },
                {
                    "name": "frontend",
                    "repo": "incidentfox/aws-playground",
                    "language": "TypeScript",
                    "framework": "Next.js",
                    "dependencies": ["Frontend Proxy"],
                    "deployment": "Kubernetes/Docker",
                    "description": "Web storefront for the astronomy shop",
                },
            ],
            "infrastructure": {
                "orchestration": "Kubernetes (EKS)",
                "ci_cd": "GitHub Actions",
                "cloud_provider": "AWS",
                "databases": ["PostgreSQL"],
                "message_queues": ["Kafka"],
                "monitoring": [
                    "Prometheus",
                    "Grafana",
                    "Jaeger",
                    "OpenTelemetry Collector",
                ],
            },
            "service_dependencies": [
                {"from": "checkout", "to": "Kafka", "type": "async/message"},
                {"from": "checkout", "to": "payment", "type": "gRPC"},
                {"from": "checkout", "to": "shipping", "type": "gRPC"},
                {"from": "accounting", "to": "Kafka", "type": "async/consumer"},
                {"from": "accounting", "to": "PostgreSQL", "type": "database"},
                {"from": "frontend", "to": "frontend-proxy", "type": "HTTP"},
            ],
            "key_observations": [
                "Polyglot microservices: Go, Python, Node.js, Java, C#, Rust, Ruby, C++, PHP",
                "Event-driven architecture using Kafka for order processing",
                "Full OpenTelemetry instrumentation across all services",
                "AWS deployment with EKS, ALB ingress, EBS gp3, Secrets Manager",
                "SOC2-compliant infrastructure with KMS encryption and IRSA",
            ],
        }

    def test_format_includes_all_services(self):
        arch = self._make_real_architecture()
        doc = _format_architecture_document(arch, GITHUB_ORG)

        assert f"# Architecture Map: {GITHUB_ORG}" in doc
        assert "## Services" in doc
        assert "### checkout" in doc
        assert "### payment" in doc
        assert "### recommendation" in doc
        assert "### accounting" in doc

    def test_format_includes_tech_stack(self):
        arch = self._make_real_architecture()
        doc = _format_architecture_document(arch, GITHUB_ORG)

        assert "Go" in doc
        assert "Node.js" in doc
        assert "Python" in doc
        assert "gRPC" in doc

    def test_format_includes_infrastructure(self):
        arch = self._make_real_architecture()
        doc = _format_architecture_document(arch, GITHUB_ORG)

        assert "## Infrastructure" in doc
        assert "Kubernetes" in doc
        assert "AWS" in doc
        assert "Kafka" in doc
        assert "Prometheus" in doc

    def test_format_includes_dependencies(self):
        arch = self._make_real_architecture()
        doc = _format_architecture_document(arch, GITHUB_ORG)

        assert "## Service Dependencies" in doc
        assert "checkout" in doc
        assert "Kafka" in doc
        assert "gRPC" in doc

    def test_format_includes_observations(self):
        arch = self._make_real_architecture()
        doc = _format_architecture_document(arch, GITHUB_ORG)

        assert "## Key Observations" in doc
        assert "Polyglot" in doc or "polyglot" in doc
        assert "SOC2" in doc or "EKS" in doc


# ===================================================================
# 5. Full GitHub Scanner Integration (Mocked API + LLM)
# ===================================================================


class TestFullGitHubScanRealistic:
    """Full scan of the aws-playground repo with mocked APIs."""

    @pytest.mark.asyncio
    async def test_scan_produces_ops_docs_and_arch_map(self, mock_openai_response):
        """
        Full scan should produce:
        1. At least one ops doc (README.md)
        2. An architecture map generated by LLM from real infra files
        """
        arch_json = json.dumps(
            {
                "services": [
                    {
                        "name": "checkout",
                        "repo": REPO_FULL_NAME,
                        "language": "Go",
                        "framework": "gRPC",
                        "dependencies": ["Kafka"],
                        "deployment": "Kubernetes",
                        "description": "Handles checkout flow",
                    },
                    {
                        "name": "payment",
                        "repo": REPO_FULL_NAME,
                        "language": "Node.js",
                        "framework": "gRPC",
                        "dependencies": [],
                        "deployment": "Kubernetes",
                        "description": "Processes payments",
                    },
                ],
                "infrastructure": {
                    "orchestration": "Kubernetes (EKS)",
                    "cloud_provider": "AWS",
                    "databases": ["PostgreSQL"],
                    "message_queues": ["Kafka"],
                    "monitoring": ["Prometheus", "Grafana", "Jaeger"],
                },
                "service_dependencies": [
                    {"from": "checkout", "to": "Kafka", "type": "async"},
                    {"from": "checkout", "to": "payment", "type": "gRPC"},
                ],
                "key_observations": [
                    "Polyglot microservices architecture",
                    "Event-driven with Kafka",
                ],
            }
        )

        mock_api = _make_github_api_mock(MONOREPO_REPOS, REAL_FILES)

        with (
            patch(
                "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
                side_effect=mock_api,
            ),
            patch("openai.AsyncOpenAI") as mock_oai_cls,
        ):
            mock_client = AsyncMock()
            mock_client.chat.completions.create.return_value = mock_openai_response(
                arch_json
            )
            mock_oai_cls.return_value = mock_client

            scanner_fn = get_scanner("github")
            docs = await scanner_fn(
                credentials={"api_key": "ghp_test123"},
                config={"account_login": GITHUB_ORG},
                org_id="org-123",
            )

        # Should have both ops docs and architecture map
        assert len(docs) >= 2

        # Check ops docs
        md_docs = [d for d in docs if d.content_type == "markdown"]
        assert len(md_docs) >= 1
        assert any("IncidentFox" in d.content for d in md_docs)

        # Check architecture map
        arch_docs = [
            d for d in docs if d.metadata.get("document_type") == "architecture_map"
        ]
        assert len(arch_docs) == 1
        arch_doc = arch_docs[0]

        assert arch_doc.content_type == "text"
        assert "checkout" in arch_doc.content
        assert "payment" in arch_doc.content
        assert "Kafka" in arch_doc.content
        assert f"github://{GITHUB_ORG}/architecture-map" == arch_doc.source_url

        # Metadata should include raw architecture
        raw_arch = arch_doc.metadata.get("raw_architecture", {})
        assert len(raw_arch.get("services", [])) == 2
        assert "repos_analyzed" in arch_doc.metadata

    @pytest.mark.asyncio
    async def test_llm_receives_real_infra_context(self, mock_openai_response):
        """The LLM prompt should contain actual infra file contents."""
        captured_prompt = None

        async def capture_create(**kwargs):
            nonlocal captured_prompt
            messages = kwargs.get("messages", [])
            if messages:
                captured_prompt = messages[0]["content"]
            return mock_openai_response(
                json.dumps(
                    {
                        "services": [],
                        "infrastructure": {},
                        "service_dependencies": [],
                        "key_observations": [],
                    }
                )
            )

        mock_api = _make_github_api_mock(MONOREPO_REPOS, REAL_FILES)

        with (
            patch(
                "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
                side_effect=mock_api,
            ),
            patch("openai.AsyncOpenAI") as mock_oai_cls,
        ):
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=capture_create)
            mock_oai_cls.return_value = mock_client

            scanner_fn = get_scanner("github")
            await scanner_fn(
                credentials={"api_key": "ghp_test"},
                config={"account_login": GITHUB_ORG},
                org_id="org-123",
            )

        assert captured_prompt is not None
        # LLM should see docker-compose content
        assert "kafka" in captured_prompt.lower()
        # LLM should see the repo name
        assert REPO_FULL_NAME in captured_prompt

    @pytest.mark.asyncio
    async def test_scan_handles_llm_failure_gracefully(self):
        """If LLM fails, should still return ops docs."""
        mock_api = _make_github_api_mock(MONOREPO_REPOS, REAL_FILES)

        with (
            patch(
                "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
                side_effect=mock_api,
            ),
            patch("openai.AsyncOpenAI") as mock_oai_cls,
        ):
            mock_client = AsyncMock()
            mock_client.chat.completions.create.side_effect = Exception(
                "OpenAI rate limit"
            )
            mock_oai_cls.return_value = mock_client

            scanner_fn = get_scanner("github")
            docs = await scanner_fn(
                credentials={"api_key": "ghp_test"},
                config={"account_login": GITHUB_ORG},
                org_id="org-123",
            )

        # Should still have ops docs even if LLM failed
        md_docs = [d for d in docs if d.content_type == "markdown"]
        assert len(md_docs) >= 1

        # Should NOT have architecture map
        arch_docs = [
            d for d in docs if d.metadata.get("document_type") == "architecture_map"
        ]
        assert len(arch_docs) == 0


# ===================================================================
# 6. Full Onboarding E2E with Realistic Slack + GitHub
# ===================================================================


class TestRealisticOnboardingE2E:
    """
    Simulate a team that uses the aws-playground environment:
    - Slack messages mention Grafana, Prometheus, Jaeger, PagerDuty
    - After initial scan recommends Grafana + PagerDuty
    - Team configures GitHub → scanner finds real infra files
    """

    @pytest.mark.asyncio
    async def test_slack_scan_detects_otel_stack(self):
        """
        Slack messages from a team running the otel demo should
        produce signals for Grafana, Prometheus, Jaeger.
        """
        from ai_learning_pipeline.tasks.scanners.slack_scanner import (
            SlackEnvironmentScanner,
        )

        channels = [
            {
                "id": "C001",
                "name": "incidents",
                "topic": {"value": "Active incidents"},
                "purpose": {"value": ""},
                "num_members": 25,
            },
            {
                "id": "C002",
                "name": "sre-platform",
                "topic": {"value": "SRE platform discussion"},
                "purpose": {"value": ""},
                "num_members": 15,
            },
        ]

        now_ts = str(datetime.utcnow().timestamp())
        messages = [
            {
                "user": "U001",
                "text": "The checkout-service latency spiked. Check the Grafana dashboard at <https://grafana.lab.incidentfox.com/d/sre-overview|SRE Overview>",
                "ts": now_ts,
            },
            {
                "user": "U002",
                "text": "PagerDuty alert fired for high error rate on payment service",
                "ts": now_ts,
            },
            {
                "user": "U001",
                "text": "Looking at Jaeger traces, the checkout -> payment gRPC call has p99 > 2s",
                "ts": now_ts,
            },
            {
                "user": "U003",
                "text": "Prometheus alertmanager triggered pod-restart alert for recommendation-service",
                "ts": now_ts,
            },
            {
                "user": "U002",
                "text": "I checked the Datadog APM traces but we should migrate to our self-hosted Jaeger",
                "ts": now_ts,
            },
            {
                "user": "U001",
                "text": "PR merged: github.com/incidentfox/aws-playground/pull/42 - fixes the Kafka consumer lag",
                "ts": now_ts,
            },
            {
                "user": "U003",
                "text": "Updated the runbook in Confluence for Kafka lag scenarios",
                "ts": now_ts,
            },
        ]

        scanner = SlackEnvironmentScanner(bot_token="xoxb-test")

        def mock_api(method, params=None):
            if method == "conversations.list":
                return {"ok": True, "channels": channels, "response_metadata": {}}
            elif method == "conversations.history":
                return {"ok": True, "messages": messages}
            elif method == "conversations.replies":
                return {"ok": True, "messages": []}
            return None

        scanner._api_request = mock_api
        result = scanner.scan()

        assert result.error is None
        integration_ids = {s.integration_id for s in result.signals}

        # Should detect the OTel stack tools
        assert "grafana" in integration_ids
        assert "pagerduty" in integration_ids
        assert "jaeger" in integration_ids
        assert "prometheus" in integration_ids
        assert "github" in integration_ids
        assert "confluence" in integration_ids

        # Grafana URL should produce high-confidence signal
        url_signals = [
            s
            for s in result.signals
            if s.signal_type == "url" and s.integration_id == "grafana"
        ]
        assert len(url_signals) >= 1
        assert url_signals[0].confidence >= 0.9

    @pytest.mark.asyncio
    async def test_github_integration_scan_with_real_files(self, mock_openai_response):
        """
        After team connects GitHub, integration scan should:
        1. Fetch credentials from config service
        2. Run GitHub scanner with real aws-playground files
        3. Ingest docs into RAG
        """
        from ai_learning_pipeline.tasks.onboarding_scan import OnboardingScanTask

        task = OnboardingScanTask(org_id="org-incidentfox", team_node_id="default")

        # Mock config service responses
        creds_response = httpx.Response(
            200,
            json={
                "integration_id": "github",
                "status": "connected",
                "config": {"api_key": "ghp_real_token"},
            },
        )
        config_response = httpx.Response(
            200,
            json={
                "integrations": {
                    "github": {"account_login": GITHUB_ORG},
                    "slack": {"bot_token": "xoxb-test"},
                }
            },
        )
        rag_response = httpx.Response(
            200, json={"chunks_created": 12, "nodes_created": 12}
        )

        # Architecture map from LLM
        arch_json = json.dumps(
            {
                "services": [
                    {
                        "name": "checkout",
                        "language": "Go",
                        "dependencies": ["Kafka"],
                        "description": "Checkout flow",
                    },
                    {
                        "name": "payment",
                        "language": "Node.js",
                        "dependencies": [],
                        "description": "Payment processing",
                    },
                    {
                        "name": "recommendation",
                        "language": "Python",
                        "dependencies": ["Product Catalog"],
                        "description": "Product recommendations",
                    },
                ],
                "infrastructure": {
                    "orchestration": "Kubernetes (EKS)",
                    "cloud_provider": "AWS",
                    "databases": ["PostgreSQL"],
                    "message_queues": ["Kafka"],
                    "monitoring": ["Prometheus", "Grafana", "Jaeger"],
                },
                "service_dependencies": [
                    {"from": "checkout", "to": "Kafka", "type": "async"},
                ],
                "key_observations": [
                    "Polyglot architecture with 10+ services",
                ],
            }
        )

        mock_github = _make_github_api_mock(MONOREPO_REPOS, REAL_FILES)

        with (
            patch(
                "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
                side_effect=mock_github,
            ),
            patch("openai.AsyncOpenAI") as mock_oai_cls,
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_oai_client = AsyncMock()
            mock_oai_client.chat.completions.create.return_value = mock_openai_response(
                arch_json
            )
            mock_oai_cls.return_value = mock_oai_client

            mock_client = AsyncMock()

            async def route_request(*args, **kwargs):
                url = str(args[0]) if args else str(kwargs.get("url", ""))
                if "/credentials/" in url:
                    return creds_response
                elif "config/effective" in url:
                    return config_response
                elif "tree/stats" in url:
                    return httpx.Response(200, json={"nodes": 0})
                elif "/trees" in url and "ingest" not in url:
                    return httpx.Response(200, json={"tree_name": "test"})
                elif "ingest/batch" in url:
                    return rag_response
                elif "config/me" in url:
                    return httpx.Response(200, json={"status": "ok"})
                return httpx.Response(404)

            mock_client.get = AsyncMock(side_effect=route_request)
            mock_client.post = AsyncMock(side_effect=route_request)
            mock_client.patch = AsyncMock(side_effect=route_request)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            result = await task.run_integration_scan(integration_id="github")

        # Scan should succeed
        assert result["trigger"] == "integration"
        assert result["integration_id"] == "github"
        assert result["ingestion"]["status"] == "ingested"

        # Should have ingested multiple documents (ops docs + architecture map)
        assert result["ingestion"]["documents_sent"] >= 2

        # Verify RAG ingest was called with correct payload
        post_calls = mock_client.post.call_args_list
        ingest_calls = [c for c in post_calls if "ingest/batch" in str(c)]
        assert len(ingest_calls) >= 1

        # Extract the payload sent to RAG
        ingest_call = ingest_calls[0]
        ingest_payload = ingest_call.kwargs.get("json") or ingest_call[1].get("json")
        doc_contents = [d["content"] for d in ingest_payload["documents"]]

        # Should contain README content
        assert any("IncidentFox" in c for c in doc_contents)
        # Should contain architecture map
        assert any("checkout" in c.lower() for c in doc_contents)

        # Tree should be scoped to integration + org
        assert ingest_payload["tree"] == "github_org-incidentfox_default"
