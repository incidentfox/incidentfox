"""
End-to-end tests for the self-onboarding scan system.

Validates the full flow:
  Slack OAuth → Slack scan → signal analysis → recommendations → RAG ingestion

All external APIs (Slack, GitHub, OpenAI, config service, RAG) are mocked.
"""

import json
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from ai_learning_pipeline.tasks.onboarding_scan import (
    AnalysisResult,
    IntegrationRecommender,
    OnboardingScanTask,
    Recommendation,
    SignalAnalyzer,
)
from ai_learning_pipeline.tasks.scanners import Document, get_scanner
from ai_learning_pipeline.tasks.scanners.slack_scanner import (
    CollectedMessage,
    ScanResult,
    Signal,
    SlackEnvironmentScanner,
)

# ===================================================================
# 1. Slack Scanner Tests
# ===================================================================


class TestSlackScanner:
    """Test that SlackEnvironmentScanner correctly extracts signals and messages."""

    def _make_scanner(self, channels, messages):
        """Create a scanner with mocked Slack API."""
        scanner = SlackEnvironmentScanner(bot_token="xoxb-test-token")

        # Mock the API request method
        def mock_api(method, params=None):
            if method == "conversations.list":
                return {"ok": True, "channels": channels, "response_metadata": {}}
            elif method == "conversations.history":
                return {"ok": True, "messages": messages}
            return None

        scanner._api_request = mock_api
        return scanner

    def test_scan_extracts_signals(self, slack_channels, slack_messages):
        scanner = self._make_scanner(slack_channels, slack_messages)
        result = scanner.scan()

        assert result.error is None
        assert result.channels_scanned > 0
        assert result.messages_scanned > 0
        assert len(result.signals) > 0

        # Should find grafana, pagerduty, github, sentry, datadog, confluence
        integration_ids = {s.integration_id for s in result.signals}
        assert "grafana" in integration_ids, f"Expected grafana in {integration_ids}"
        assert "pagerduty" in integration_ids
        assert "github" in integration_ids

    def test_scan_collects_messages_for_rag(self, slack_channels, slack_messages):
        scanner = self._make_scanner(slack_channels, slack_messages)
        result = scanner.scan()

        # Should collect messages from incident/ops channels (not #general)
        assert len(result.collected_messages) > 0

        channels_collected = {m.channel_name for m in result.collected_messages}
        # "incidents" and "sre-alerts" match RELEVANT_CHANNEL_PATTERNS
        assert "incidents" in channels_collected or "sre-alerts" in channels_collected
        # "general" should NOT be collected for RAG
        assert "general" not in channels_collected

    def test_scan_skips_short_messages_for_rag(self, slack_channels, slack_messages):
        scanner = self._make_scanner(slack_channels, slack_messages)
        result = scanner.scan()

        # Messages with len < 20 should not be collected
        for msg in result.collected_messages:
            assert len(msg.text) >= 20

    def test_scan_deduplicates_signals(self, slack_channels, slack_messages):
        scanner = self._make_scanner(slack_channels, slack_messages)
        result = scanner.scan()

        # After dedup, should have at most one signal per integration+type combo
        keys = set()
        for s in result.signals:
            key = f"{s.integration_id}:{s.signal_type}"
            assert key not in keys, f"Duplicate signal: {key}"
            keys.add(key)

    def test_scan_handles_empty_workspace(self):
        scanner = self._make_scanner(channels=[], messages=[])
        result = scanner.scan()

        assert result.error == "Could not list channels"
        assert result.channels_scanned == 0
        assert len(result.signals) == 0

    def test_url_signals_have_high_confidence(self, slack_channels, slack_messages):
        scanner = self._make_scanner(slack_channels, slack_messages)
        result = scanner.scan()

        url_signals = [s for s in result.signals if s.signal_type == "url"]
        for s in url_signals:
            assert s.confidence >= 0.9


# ===================================================================
# 2. Signal Analyzer Tests
# ===================================================================


class TestSignalAnalyzer:
    """Test LLM-based and heuristic signal analysis."""

    def _make_signals(self) -> List[Signal]:
        return [
            Signal(
                signal_type="url",
                integration_id="grafana",
                context="Check grafana.company.com/d/abc",
                confidence=0.9,
                source="slack:#incidents",
                metadata={"occurrence_count": 15},
            ),
            Signal(
                signal_type="tool_mention",
                integration_id="grafana",
                context="Look at the Grafana dashboard",
                confidence=0.7,
                source="slack:#sre-alerts",
                metadata={"occurrence_count": 8},
            ),
            Signal(
                signal_type="tool_mention",
                integration_id="pagerduty",
                context="PagerDuty alert fired",
                confidence=0.7,
                source="slack:#incidents",
                metadata={"occurrence_count": 12},
            ),
            Signal(
                signal_type="tool_mention",
                integration_id="sentry",
                context="Sentry error spike",
                confidence=0.7,
                source="slack:#incidents",
                metadata={"occurrence_count": 5},
            ),
        ]

    @pytest.mark.asyncio
    async def test_heuristic_analysis_when_llm_unavailable(self):
        """When OpenAI is unavailable, heuristic fallback should work."""
        analyzer = SignalAnalyzer(model="gpt-4o-mini")
        signals = self._make_signals()

        # Patch OpenAI to raise an error
        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create.side_effect = Exception(
                "API unavailable"
            )
            mock_cls.return_value = mock_client

            result = await analyzer.analyze(
                signals=signals,
                existing_integrations=["slack"],
            )

        assert len(result.recommendations) > 0
        # Grafana should be top recommendation (most signals + URL)
        assert result.recommendations[0].integration_id == "grafana"
        assert result.recommendations[0].priority == "high"

    @pytest.mark.asyncio
    async def test_heuristic_skips_existing_integrations(self):
        analyzer = SignalAnalyzer()
        signals = self._make_signals()

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create.side_effect = Exception("nope")
            mock_cls.return_value = mock_client

            result = await analyzer.analyze(
                signals=signals,
                existing_integrations=["slack", "grafana"],
            )

        integration_ids = {r.integration_id for r in result.recommendations}
        assert "grafana" not in integration_ids  # Already connected
        assert "pagerduty" in integration_ids

    @pytest.mark.asyncio
    async def test_analyze_returns_empty_for_no_signals(self):
        analyzer = SignalAnalyzer()
        result = await analyzer.analyze(signals=[], existing_integrations=["slack"])
        assert result.recommendations == []

    @pytest.mark.asyncio
    async def test_llm_analysis_parses_json_response(self, mock_openai_response):
        analyzer = SignalAnalyzer()
        signals = self._make_signals()

        llm_response = json.dumps(
            {
                "recommendations": [
                    {
                        "integration_id": "grafana",
                        "priority": "high",
                        "confidence": 0.95,
                        "reasoning": "23 Grafana URL shares found",
                        "evidence_quotes": ["Check the Grafana dashboard"],
                    }
                ]
            }
        )

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create.return_value = mock_openai_response(
                llm_response
            )
            mock_cls.return_value = mock_client

            result = await analyzer.analyze(
                signals=signals,
                existing_integrations=["slack"],
            )

        assert len(result.recommendations) == 1
        assert result.recommendations[0].integration_id == "grafana"
        assert result.recommendations[0].confidence == 0.95


# ===================================================================
# 3. Integration Recommender Tests
# ===================================================================


class TestIntegrationRecommender:
    """Test that recommendations are correctly submitted as PendingConfigChange."""

    @pytest.mark.asyncio
    async def test_submit_creates_pending_changes(self):
        recommender = IntegrationRecommender("http://config-service:8080")
        recs = [
            Recommendation(
                integration_id="grafana",
                priority="high",
                confidence=0.92,
                reasoning="Found 23 Grafana mentions",
                evidence_quotes=["Check the Grafana dashboard"],
            ),
        ]

        # Mock the HTTP call
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            change_ids = await recommender.submit_recommendations(
                org_id="slack-T123",
                team_node_id="default",
                recommendations=recs,
            )

        assert len(change_ids) == 1
        # Verify the POST payload
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["change_type"] == "integration_recommendation"
        assert payload["proposed_value"]["integration_id"] == "grafana"
        assert payload["proposed_value"]["confidence"] == 0.92


# ===================================================================
# 4. Scanner Registry Tests
# ===================================================================


class TestScannerRegistry:
    """Test that scanner registration and lookup works."""

    def test_github_scanner_registered(self):
        scanner = get_scanner("github")
        assert scanner is not None
        assert callable(scanner)

    def test_confluence_scanner_registered(self):
        scanner = get_scanner("confluence")
        assert scanner is not None

    def test_unknown_scanner_returns_none(self):
        scanner = get_scanner("notion")
        assert scanner is None


# ===================================================================
# 5. GitHub Scanner Tests
# ===================================================================


class TestGitHubScanner:
    """Test GitHub scanning including architecture map generation."""

    @pytest.mark.asyncio
    async def test_scan_fetches_docs_and_architecture(
        self, github_repos, github_file_contents, mock_openai_response
    ):
        """Full GitHub scan: ops docs + architecture map."""

        # Mock GitHub API
        def mock_github_api(path, token, params=None):
            if "/orgs/" in path and "/repos" in path:
                return github_repos
            if "/contents/" in path:
                # Extract repo and file path
                # path format: /repos/acme/payment-service/contents/README.md
                parts = path.split("/contents/")
                if len(parts) == 2:
                    repo_parts = parts[0].replace("/repos/", "").split("/")
                    repo_name = repo_parts[-1]
                    file_path = parts[1]
                    key = f"{repo_name}/{file_path}"
                    content = github_file_contents.get(key)
                    if content:
                        import base64

                        return {
                            "content": base64.b64encode(content.encode()).decode(),
                            "size": len(content),
                        }
                return None
            return None

        arch_response = json.dumps(
            {
                "services": [
                    {
                        "name": "payment-service",
                        "repo": "acme/payment-service",
                        "language": "Python",
                        "framework": "FastAPI",
                        "dependencies": ["PostgreSQL", "Redis", "Stripe"],
                        "deployment": "Kubernetes",
                        "description": "Handles payment processing",
                    },
                    {
                        "name": "user-service",
                        "repo": "acme/user-service",
                        "language": "Go",
                        "framework": "Gin",
                        "dependencies": ["PostgreSQL"],
                        "deployment": "Kubernetes",
                        "description": "Manages user accounts",
                    },
                ],
                "infrastructure": {
                    "orchestration": "Kubernetes",
                    "ci_cd": "GitHub Actions",
                    "databases": ["PostgreSQL", "Redis"],
                },
                "service_dependencies": [
                    {"from": "payment-service", "to": "PostgreSQL", "type": "database"},
                ],
                "key_observations": [
                    "Multi-repo setup with separate services",
                ],
            }
        )

        with (
            patch(
                "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
                side_effect=mock_github_api,
            ),
            patch("openai.AsyncOpenAI") as mock_oai_cls,
        ):
            mock_client = AsyncMock()
            mock_client.chat.completions.create.return_value = mock_openai_response(
                arch_response
            )
            mock_oai_cls.return_value = mock_client

            scanner_fn = get_scanner("github")
            docs = await scanner_fn(
                credentials={"api_key": "ghp_test123"},
                config={"account_login": "acme"},
                org_id="org-123",
            )

        # Should have ops docs + architecture map
        assert len(docs) >= 1

        # Check for architecture map document
        arch_docs = [
            d for d in docs if d.metadata.get("document_type") == "architecture_map"
        ]
        assert len(arch_docs) == 1
        arch = arch_docs[0]
        assert "payment-service" in arch.content
        assert "Python" in arch.content or "FastAPI" in arch.content
        assert arch.content_type == "text"

        # Check for ops docs
        md_docs = [d for d in docs if d.content_type == "markdown"]
        assert len(md_docs) >= 1

    @pytest.mark.asyncio
    async def test_scan_returns_empty_without_token(self):
        scanner_fn = get_scanner("github")
        docs = await scanner_fn(
            credentials={},
            config={"account_login": "acme"},
            org_id="org-123",
        )
        assert docs == []


# ===================================================================
# 6. Full E2E: Initial Scan Flow
# ===================================================================


class TestOnboardingScanE2E:
    """
    End-to-end test of the initial onboarding scan.

    Mocks: Slack API, OpenAI, config service, RAG service.
    Validates: signals extracted → recommendations created → messages ingested to RAG.
    """

    @pytest.mark.asyncio
    async def test_full_initial_scan_flow(
        self, slack_channels, slack_messages, mock_openai_response
    ):
        task = OnboardingScanTask(
            org_id="slack-T123",
            team_node_id="default",
        )

        # --- Mock Slack API ---
        def mock_slack_api(method, params=None):
            if method == "conversations.list":
                return {"ok": True, "channels": slack_channels, "response_metadata": {}}
            elif method == "conversations.history":
                return {"ok": True, "messages": slack_messages}
            return None

        # --- Mock OpenAI (for SignalAnalyzer) ---
        llm_recs = json.dumps(
            {
                "recommendations": [
                    {
                        "integration_id": "grafana",
                        "priority": "high",
                        "confidence": 0.92,
                        "reasoning": "Found Grafana URLs and mentions",
                        "evidence_quotes": ["Check grafana.company.com"],
                    },
                    {
                        "integration_id": "pagerduty",
                        "priority": "medium",
                        "confidence": 0.7,
                        "reasoning": "Multiple PagerDuty alert mentions",
                        "evidence_quotes": ["PagerDuty alert fired"],
                    },
                ]
            }
        )

        # --- Mock config service (get existing integrations) ---
        config_response = httpx.Response(
            200,
            json={"integrations": {"slack": {"bot_token": "xoxb-test"}}},
        )

        # --- Mock config service (create pending changes) ---
        pending_change_response = httpx.Response(200, json={"id": "rec_abc123"})

        # --- Mock RAG service (ingest) ---
        rag_response = httpx.Response(
            200, json={"chunks_created": 5, "nodes_created": 5}
        )

        # --- Patch everything ---
        with (
            patch.object(
                SlackEnvironmentScanner, "_api_request", side_effect=mock_slack_api
            ),
            patch("openai.AsyncOpenAI") as mock_oai,
            patch("httpx.AsyncClient") as mock_http,
        ):
            # OpenAI mock
            mock_oai_client = AsyncMock()
            mock_oai_client.chat.completions.create.return_value = mock_openai_response(
                llm_recs
            )
            mock_oai.return_value = mock_oai_client

            # httpx mock — route by URL
            mock_client = AsyncMock()

            async def route_request(*args, **kwargs):
                url = str(args[0]) if args else str(kwargs.get("url", ""))
                if "config/effective" in url:
                    return config_response
                elif "pending-changes" in url:
                    return pending_change_response
                elif "ingest/batch" in url:
                    return rag_response
                return httpx.Response(404)

            mock_client.get = AsyncMock(side_effect=route_request)
            mock_client.post = AsyncMock(side_effect=route_request)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            # --- Run the scan ---
            result = await task.run_initial_scan(slack_bot_token="xoxb-test-token")

        # --- Assertions ---
        assert result["trigger"] == "initial"
        assert result.get("error") is None

        # 1. Signals were found
        assert result["signals_found"] > 0
        assert result["channels_scanned"] > 0

        # 2. Recommendations were created
        assert len(result.get("recommendations", [])) > 0
        rec_ids = {r["integration_id"] for r in result["recommendations"]}
        assert "grafana" in rec_ids

        # 3. Pending changes were submitted to config service
        assert len(result.get("recommendations_created", [])) > 0

        # 4. RAG ingestion happened
        rag_result = result.get("rag_ingestion", {})
        assert rag_result.get("documents_sent", 0) > 0

    @pytest.mark.asyncio
    async def test_initial_scan_handles_empty_workspace(self):
        """Scan should handle a workspace with no channels gracefully."""
        task = OnboardingScanTask(
            org_id="slack-T123",
            team_node_id="default",
        )

        def mock_slack_api(method, params=None):
            if method == "conversations.list":
                return {"ok": True, "channels": [], "response_metadata": {}}
            return None

        with patch.object(
            SlackEnvironmentScanner, "_api_request", side_effect=mock_slack_api
        ):
            result = await task.run_initial_scan(slack_bot_token="xoxb-test")

        assert result.get("error") == "Could not list channels"
        assert result.get("recommendations") is None or result["recommendations"] == []


# ===================================================================
# 7. Integration Scan Flow
# ===================================================================


class TestIntegrationScanE2E:
    """Test the post-integration-save scan flow."""

    @pytest.mark.asyncio
    async def test_integration_scan_fetches_credentials_and_runs_scanner(
        self, github_repos, github_file_contents, mock_openai_response
    ):
        task = OnboardingScanTask(
            org_id="slack-T123",
            team_node_id="default",
        )

        # Mock credentials endpoint
        creds_response = httpx.Response(
            200,
            json={
                "integration_id": "github",
                "status": "connected",
                "config": {"api_key": "ghp_test"},
            },
        )

        # Mock effective config
        config_response = httpx.Response(
            200,
            json={"integrations": {"github": {"account_login": "acme"}, "slack": {}}},
        )

        # Mock RAG ingest
        rag_response = httpx.Response(
            200, json={"chunks_created": 3, "nodes_created": 3}
        )

        def mock_github_api(path, token, params=None):
            if "/orgs/" in path and "/repos" in path:
                return github_repos
            if "/contents/" in path:
                parts = path.split("/contents/")
                if len(parts) == 2:
                    repo_name = parts[0].split("/")[-1]
                    file_path = parts[1]
                    key = f"{repo_name}/{file_path}"
                    content = github_file_contents.get(key)
                    if content:
                        import base64

                        return {
                            "content": base64.b64encode(content.encode()).decode(),
                            "size": len(content),
                        }
                return None
            return None

        arch_response = json.dumps(
            {
                "services": [{"name": "payment-service", "language": "Python"}],
                "infrastructure": {},
                "service_dependencies": [],
                "key_observations": [],
            }
        )

        with (
            patch(
                "ai_learning_pipeline.tasks.scanners.github_scanner._github_api",
                side_effect=mock_github_api,
            ),
            patch("openai.AsyncOpenAI") as mock_oai_cls,
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_oai_client = AsyncMock()
            mock_oai_client.chat.completions.create.return_value = mock_openai_response(
                arch_response
            )
            mock_oai_cls.return_value = mock_oai_client

            mock_client = AsyncMock()

            async def route_request(*args, **kwargs):
                url = str(args[0]) if args else str(kwargs.get("url", ""))
                if "/credentials/" in url:
                    return creds_response
                elif "config/effective" in url:
                    return config_response
                elif "ingest/batch" in url:
                    return rag_response
                return httpx.Response(404)

            mock_client.get = AsyncMock(side_effect=route_request)
            mock_client.post = AsyncMock(side_effect=route_request)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            result = await task.run_integration_scan(integration_id="github")

        assert result["trigger"] == "integration"
        assert result["integration_id"] == "github"
        assert result.get("ingestion", {}).get("status") in (
            "ingested",
            "no_docs_found",
        )
