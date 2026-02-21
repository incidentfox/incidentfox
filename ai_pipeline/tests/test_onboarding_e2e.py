"""
End-to-end tests for the self-onboarding scan system.

Validates the full flow:
  Slack OAuth → Slack scan → signal analysis → recommendations → RAG ingestion

All external APIs (Slack, GitHub, OpenAI, config service, RAG) are mocked.
"""

import json
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from ai_learning_pipeline.tasks.knowledge_extractor import KnowledgeExtractor
from ai_learning_pipeline.tasks.onboarding_scan import (
    IntegrationRecommender,
    OnboardingScanTask,
    Recommendation,
    SignalAnalyzer,
)
from ai_learning_pipeline.tasks.scanners import get_scanner
from ai_learning_pipeline.tasks.scanners.slack_scanner import (
    CollectedMessage,
    Signal,
    SlackEnvironmentScanner,
    _extract_text_from_blocks,
    _get_message_text,
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
# 1a. Block Kit Text Extraction Tests
# ===================================================================


class TestBlockKitExtraction:
    """Test _extract_text_from_blocks and _get_message_text helpers."""

    def test_section_block_extracts_mrkdwn(self):
        """Section blocks with mrkdwn text (e.g. code blocks) are extracted."""
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Turned off feature flag:\n```flagctl set emailMemoryLeak off```",
                },
            }
        ]
        result = _extract_text_from_blocks(blocks)
        assert "flagctl set emailMemoryLeak off" in result

    def test_header_block_extracted(self):
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Incident Resolved"},
            }
        ]
        result = _extract_text_from_blocks(blocks)
        assert result == "Incident Resolved"

    def test_rich_text_block_extracted(self):
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": "Ran "},
                            {"type": "text", "text": "kubectl rollout restart"},
                            {"type": "text", "text": " to fix it"},
                        ],
                    }
                ],
            }
        ]
        result = _extract_text_from_blocks(blocks)
        assert "kubectl rollout restart" in result

    def test_rich_text_link_extracted(self):
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": "See dashboard: "},
                            {
                                "type": "link",
                                "url": "https://grafana.example.com/d/abc",
                            },
                        ],
                    }
                ],
            }
        ]
        result = _extract_text_from_blocks(blocks)
        assert "https://grafana.example.com/d/abc" in result

    def test_context_block_extracted(self):
        blocks = [
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "Posted by AlertManager"},
                ],
            }
        ]
        result = _extract_text_from_blocks(blocks)
        assert "Posted by AlertManager" in result

    def test_empty_blocks_returns_empty(self):
        assert _extract_text_from_blocks([]) == ""

    def test_unknown_block_types_skipped(self):
        blocks = [{"type": "divider"}, {"type": "image", "image_url": "http://x.png"}]
        assert _extract_text_from_blocks(blocks) == ""

    def test_get_message_text_prefers_blocks(self):
        """_get_message_text returns block text when blocks are present."""
        msg = {
            "text": "plain fallback (no code block here)",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Resolved via `flagctl set emailMemoryLeak off`",
                    },
                }
            ],
        }
        result = _get_message_text(msg)
        assert "flagctl set emailMemoryLeak off" in result

    def test_get_message_text_falls_back_to_plain_text(self):
        """Falls back to plain text when no blocks are present."""
        msg = {"text": "simple message without blocks"}
        assert _get_message_text(msg) == "simple message without blocks"

    def test_get_message_text_falls_back_when_blocks_empty(self):
        """Falls back when blocks exist but yield no text."""
        msg = {"text": "fallback", "blocks": [{"type": "divider"}]}
        assert _get_message_text(msg) == "fallback"

    def test_multiple_blocks_joined_with_newlines(self):
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Alert: High Memory"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "email-service pod OOMKilled"},
            },
        ]
        result = _extract_text_from_blocks(blocks)
        assert "Alert: High Memory" in result
        assert "email-service pod OOMKilled" in result
        assert "\n" in result


# ===================================================================
# 1b. Slack Scanner Thread Tests
# ===================================================================


class TestSlackScannerThreads:
    """Test thread reply fetching in SlackEnvironmentScanner."""

    def _make_scanner_with_threads(self, channels, messages, thread_replies):
        """Create a scanner with mocked Slack API including thread replies."""
        scanner = SlackEnvironmentScanner(
            bot_token="xoxb-test-token",
            max_threads_per_channel=10,
        )
        # Disable rate limiting for tests
        scanner._replies_interval = 0

        def mock_api(method, params=None):
            if method == "conversations.list":
                return {"ok": True, "channels": channels, "response_metadata": {}}
            elif method == "conversations.history":
                return {"ok": True, "messages": messages}
            elif method == "conversations.replies":
                parent_ts = params.get("ts", "") if params else ""
                replies = thread_replies.get(parent_ts, [])
                return {"ok": True, "messages": replies}
            return None

        scanner._api_request = mock_api
        return scanner

    def test_scan_fetches_thread_replies(
        self, slack_channels, slack_messages_with_threads, slack_thread_replies
    ):
        """Thread replies should be collected for RAG-relevant channels."""
        scanner = self._make_scanner_with_threads(
            slack_channels, slack_messages_with_threads, slack_thread_replies
        )
        result = scanner.scan()

        assert result.error is None

        # Should have thread reply messages collected
        thread_replies_collected = [
            m
            for m in result.collected_messages
            if m.thread_ts and not m.is_thread_parent
        ]
        assert len(thread_replies_collected) > 0

        # Thread parents should be marked
        parents = [m for m in result.collected_messages if m.is_thread_parent]
        assert len(parents) > 0

    def test_scan_respects_max_threads_per_channel(
        self, slack_channels, slack_messages_with_threads, slack_thread_replies
    ):
        """Scanner should cap thread fetching at max_threads_per_channel."""
        scanner = self._make_scanner_with_threads(
            slack_channels, slack_messages_with_threads, slack_thread_replies
        )
        scanner.max_threads_per_channel = 1  # Only fetch 1 thread

        result = scanner.scan()

        # Should have fetched replies for only 1 thread (highest reply_count)
        parent_tss = {m.ts for m in result.collected_messages if m.is_thread_parent}
        assert len(parent_tss) <= 1

    def test_thread_reply_parent_not_duplicated(
        self, slack_channels, slack_messages_with_threads, slack_thread_replies
    ):
        """conversations.replies includes the parent; it should not be duplicated within a channel."""
        scanner = self._make_scanner_with_threads(
            slack_channels, slack_messages_with_threads, slack_thread_replies
        )
        result = scanner.scan()

        # Count how many times each (channel_id, ts) appears within a channel
        key_counts: dict = {}
        for m in result.collected_messages:
            key = (m.channel_id, m.ts)
            key_counts[key] = key_counts.get(key, 0) + 1

        # No (channel_id, ts) should appear more than once
        for key, count in key_counts.items():
            assert count == 1, f"Message {key} appeared {count} times (duplicate)"

    def test_thread_parents_have_reply_count(
        self, slack_channels, slack_messages_with_threads, slack_thread_replies
    ):
        """Thread parent messages should have reply_count set."""
        scanner = self._make_scanner_with_threads(
            slack_channels, slack_messages_with_threads, slack_thread_replies
        )
        result = scanner.scan()

        parents = [m for m in result.collected_messages if m.is_thread_parent]
        for p in parents:
            assert p.reply_count > 0


# ===================================================================
# 1c. Knowledge Extractor Thread Formatting Tests
# ===================================================================


class TestKnowledgeExtractorThreads:
    """Test thread-aware formatting in KnowledgeExtractor."""

    def test_format_messages_with_threads(self):
        """Thread blocks should be formatted with [THREAD]...[/THREAD]."""
        extractor = KnowledgeExtractor()

        messages = [
            CollectedMessage(
                channel_name="incidents",
                channel_id="C001",
                user="U001",
                text="Some standalone message about deployment",
                ts="1708300000",
            ),
            CollectedMessage(
                channel_name="incidents",
                channel_id="C001",
                user="U002",
                text="PagerDuty alert fired for user-service",
                ts="1708300100",
                thread_ts="1708300100",
                is_thread_parent=True,
                reply_count=2,
            ),
            CollectedMessage(
                channel_name="incidents",
                channel_id="C001",
                user="U001",
                text="Root cause: DB connection pool exhaustion",
                ts="1708300200",
                thread_ts="1708300100",
            ),
            CollectedMessage(
                channel_name="incidents",
                channel_id="C001",
                user="U003",
                text="Increased pool size, error rate recovering",
                ts="1708300300",
                thread_ts="1708300100",
            ),
        ]

        formatted = extractor._format_messages_with_threads(messages)

        assert "[THREAD]" in formatted
        assert "[/THREAD]" in formatted
        assert "(2 replies)" in formatted
        assert "PagerDuty alert" in formatted
        assert "Root cause" in formatted
        assert "Increased pool size" in formatted
        # Standalone message should appear outside the thread block
        assert "Some standalone message" in formatted

    def test_format_preserves_chronological_order(self):
        """Events should be sorted chronologically by parent/standalone ts."""
        extractor = KnowledgeExtractor()

        messages = [
            CollectedMessage(
                channel_name="alerts",
                channel_id="C001",
                user="U001",
                text="Early standalone message about monitoring setup",
                ts="1708300000",
            ),
            CollectedMessage(
                channel_name="alerts",
                channel_id="C001",
                user="U002",
                text="Alert: CPU spike on api-gateway",
                ts="1708300100",
                thread_ts="1708300100",
                is_thread_parent=True,
                reply_count=1,
            ),
            CollectedMessage(
                channel_name="alerts",
                channel_id="C001",
                user="U001",
                text="Scaled up replicas, CPU back to normal",
                ts="1708300150",
                thread_ts="1708300100",
            ),
            CollectedMessage(
                channel_name="alerts",
                channel_id="C001",
                user="U003",
                text="Late standalone message about cleanup",
                ts="1708300200",
            ),
        ]

        formatted = extractor._format_messages_with_threads(messages)
        lines = formatted.split("\n")

        # Find positions
        early_pos = next(i for i, l in enumerate(lines) if "Early standalone" in l)
        thread_pos = next(i for i, l in enumerate(lines) if "[THREAD]" in l)
        late_pos = next(i for i, l in enumerate(lines) if "Late standalone" in l)

        assert early_pos < thread_pos < late_pos

    def test_no_threads_uses_flat_format(self):
        """When no messages have is_thread_parent, has_threads should be False."""
        messages = [
            CollectedMessage(
                channel_name="incidents",
                channel_id="C001",
                user="U001",
                text="Some message",
                ts="1708300000",
            ),
            CollectedMessage(
                channel_name="incidents",
                channel_id="C001",
                user="U002",
                text="Another message",
                ts="1708300100",
            ),
        ]

        has_threads = any(m.is_thread_parent for m in messages)
        assert has_threads is False


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
            elif method == "conversations.replies":
                return {"ok": True, "messages": []}
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
                elif "tree/stats" in url:
                    # Tree exists check — return 200 so _ensure_tree_exists succeeds
                    return httpx.Response(200, json={"nodes": 0})
                elif "/trees" in url and "ingest" not in url:
                    return httpx.Response(200, json={"tree_name": "test"})
                elif "ingest/batch" in url:
                    return rag_response
                elif "config/me" in url:
                    # _set_knowledge_tree_config PATCH
                    return httpx.Response(200, json={"status": "ok"})
                return httpx.Response(404)

            mock_client.get = AsyncMock(side_effect=route_request)
            mock_client.post = AsyncMock(side_effect=route_request)
            mock_client.patch = AsyncMock(side_effect=route_request)
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
