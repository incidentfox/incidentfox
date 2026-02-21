"""Shared test fixtures for AI Learning Pipeline tests."""

from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

# --- Slack API mock data ---


@pytest.fixture
def slack_channels() -> List[Dict[str, Any]]:
    """Mock Slack conversations.list response."""
    return [
        {
            "id": "C001",
            "name": "incidents",
            "topic": {"value": "Active incident channel"},
            "purpose": {"value": "Post incidents here"},
            "num_members": 50,
        },
        {
            "id": "C002",
            "name": "sre-alerts",
            "topic": {"value": "Automated alerts from monitoring"},
            "purpose": {"value": ""},
            "num_members": 30,
        },
        {
            "id": "C003",
            "name": "general",
            "topic": {"value": "Company general chat"},
            "purpose": {"value": ""},
            "num_members": 200,
        },
        {
            "id": "C004",
            "name": "deploy-notifications",
            "topic": {"value": "Deployment updates"},
            "purpose": {"value": ""},
            "num_members": 40,
        },
    ]


@pytest.fixture
def slack_messages() -> List[Dict[str, Any]]:
    """Mock Slack conversations.history messages with tool signals."""
    now = datetime.utcnow()
    base_ts = now.timestamp()
    return [
        {
            "user": "U001",
            "text": "Check the Grafana dashboard for payment-service latency: <https://grafana.company.com/d/abc123|payment dashboard>",
            "ts": str(base_ts - 100),
        },
        {
            "user": "U002",
            "text": "PagerDuty alert fired for high error rate on user-service",
            "ts": str(base_ts - 200),
        },
        {
            "user": "U001",
            "text": "I pushed a fix, check the PR at github.com/acme/user-service/pull/42",
            "ts": str(base_ts - 300),
        },
        {
            "user": "U003",
            "text": "Sentry is showing a spike in 500 errors from the payment endpoint",
            "ts": str(base_ts - 400),
        },
        {
            "user": "U002",
            "text": "Looking at Datadog APM traces, the db queries are slow",
            "ts": str(base_ts - 500),
        },
        {
            "user": "U001",
            "text": "Updated the runbook in Confluence for this failure mode",
            "ts": str(base_ts - 600),
        },
        {
            "user": "U003",
            "text": "Short msg",  # < 20 chars, should be skipped for RAG
            "ts": str(base_ts - 700),
        },
    ]


# Fixed base timestamp for thread fixtures (avoids drift between fixtures)
_THREAD_BASE_TS = 1700000000.0


@pytest.fixture
def slack_messages_with_threads() -> List[Dict[str, Any]]:
    """Mock Slack messages where some have reply_count (threaded)."""
    return [
        {
            "user": "U001",
            "text": "Check the Grafana dashboard for payment-service latency: <https://grafana.company.com/d/abc123|payment dashboard>",
            "ts": str(_THREAD_BASE_TS - 100),
        },
        {
            "user": "U002",
            "text": "PagerDuty alert fired for high error rate on user-service",
            "ts": str(_THREAD_BASE_TS - 200),
            "reply_count": 3,
            "thread_ts": str(_THREAD_BASE_TS - 200),
        },
        {
            "user": "U003",
            "text": "Sentry is showing a spike in 500 errors from the payment endpoint",
            "ts": str(_THREAD_BASE_TS - 400),
            "reply_count": 2,
            "thread_ts": str(_THREAD_BASE_TS - 400),
        },
        {
            "user": "U002",
            "text": "Looking at Datadog APM traces, the db queries are slow",
            "ts": str(_THREAD_BASE_TS - 500),
        },
        {
            "user": "U001",
            "text": "Updated the runbook in Confluence for this failure mode",
            "ts": str(_THREAD_BASE_TS - 600),
        },
    ]


@pytest.fixture
def slack_thread_replies() -> Dict[str, List[Dict[str, Any]]]:
    """Mock conversations.replies responses keyed by parent ts."""
    return {
        str(_THREAD_BASE_TS - 200): [
            # Parent message (always first in conversations.replies)
            {
                "user": "U002",
                "text": "PagerDuty alert fired for high error rate on user-service",
                "ts": str(_THREAD_BASE_TS - 200),
                "thread_ts": str(_THREAD_BASE_TS - 200),
            },
            {
                "user": "U001",
                "text": "Looking at Grafana, latency spiked at 14:30 UTC. DB connection pool looks saturated.",
                "ts": str(_THREAD_BASE_TS - 190),
                "thread_ts": str(_THREAD_BASE_TS - 200),
            },
            {
                "user": "U003",
                "text": "Root cause: connection pool exhaustion in the PostgreSQL layer. user-service was opening new connections on every request.",
                "ts": str(_THREAD_BASE_TS - 180),
                "thread_ts": str(_THREAD_BASE_TS - 200),
            },
            {
                "user": "U001",
                "text": "Increased pool size from 10 to 50, error rate recovering. Will deploy a proper fix with connection reuse tomorrow.",
                "ts": str(_THREAD_BASE_TS - 170),
                "thread_ts": str(_THREAD_BASE_TS - 200),
            },
        ],
        str(_THREAD_BASE_TS - 400): [
            {
                "user": "U003",
                "text": "Sentry is showing a spike in 500 errors from the payment endpoint",
                "ts": str(_THREAD_BASE_TS - 400),
                "thread_ts": str(_THREAD_BASE_TS - 400),
            },
            {
                "user": "U001",
                "text": "Checked the payment-service logs, it's a timeout to the Stripe API. Their status page shows degraded.",
                "ts": str(_THREAD_BASE_TS - 390),
                "thread_ts": str(_THREAD_BASE_TS - 400),
            },
            {
                "user": "U003",
                "text": "Added circuit breaker config, retries with backoff. Stripe recovered, errors cleared.",
                "ts": str(_THREAD_BASE_TS - 380),
                "thread_ts": str(_THREAD_BASE_TS - 400),
            },
        ],
    }


# --- GitHub API mock data ---


@pytest.fixture
def github_repos() -> List[Dict[str, Any]]:
    """Mock GitHub repos list."""
    return [
        {"name": "payment-service", "full_name": "acme/payment-service"},
        {"name": "user-service", "full_name": "acme/user-service"},
        {"name": "infra", "full_name": "acme/infra"},
    ]


@pytest.fixture
def github_file_contents() -> Dict[str, str]:
    """Mock GitHub file contents keyed by path."""
    return {
        "payment-service/README.md": "# Payment Service\nHandles payment processing via Stripe API.\n\n## Running\n```\ndocker-compose up\n```",
        "payment-service/Dockerfile": 'FROM python:3.11-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .\nCMD ["uvicorn", "main:app"]\n',
        "payment-service/requirements.txt": "fastapi==0.104.0\nuvicorn==0.24.0\npsycopg2-binary==2.9.9\nredis==5.0.1\nstripe==7.0.0\n",
        "user-service/README.md": "# User Service\nManages user accounts and authentication.\n",
        "user-service/Dockerfile": 'FROM golang:1.21-alpine\nWORKDIR /app\nCOPY go.mod go.sum ./\nRUN go mod download\nCOPY . .\nRUN go build -o server .\nCMD ["./server"]\n',
        "user-service/go.mod": "module github.com/acme/user-service\n\ngo 1.21\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n\tgorm.io/gorm v1.25.5\n)\n",
        "infra/k8s/deployment.yaml": "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: payment-service\nspec:\n  replicas: 3\n  template:\n    spec:\n      containers:\n      - name: payment-service\n        image: acme/payment-service:latest\n        ports:\n        - containerPort: 8080\n",
    }


# --- OpenAI mock ---


@pytest.fixture
def mock_openai_response():
    """Factory for mock OpenAI chat completion responses."""

    def _make(content: str):
        mock_choice = MagicMock()
        mock_choice.message.content = content
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    return _make
