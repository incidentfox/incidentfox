"""
Onboarding Scan Task.

Progressively scans a team's environment to:
1. Discover what tools/integrations they use (starting from Slack)
2. Generate integration recommendations via PendingConfigChange
3. Ingest discovered knowledge into the RAG system
4. Re-scan when new integrations are configured

Triggered by:
- Slack OAuth installation (initial scan)
- Integration configuration save (progressive scan)
"""

import json
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from .knowledge_extractor import KnowledgeExtractor
from .scanners import Document, get_scanner
from .scanners.slack_scanner import (
    CollectedMessage,
    Signal,
    SlackEnvironmentScanner,
)


def _log(event: str, **fields) -> None:
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-learning-pipeline",
        "module": "tasks.onboarding_scan",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


# ---------------------------------------------------------------------------
# Signal Analyzer — LLM-powered analysis of scan signals
# ---------------------------------------------------------------------------

SIGNAL_ANALYSIS_PROMPT = """You are analyzing a team's Slack workspace to recommend which monitoring and DevOps integrations they should connect to IncidentFox (an AI SRE agent platform).

Below are signals extracted from their Slack messages — tool mentions, URLs, and channel names. Each signal includes the integration it relates to, how many times it appeared, and example context.

## Signals Found
{signals_summary}

## Already Connected Integrations
{existing_integrations}

## Available Integrations (that can be connected)
{available_integrations}

## Instructions
Analyze these signals and recommend which integrations the team should connect, in priority order. For each recommendation:
- Explain WHY based on the evidence (be specific, cite message examples)
- Assign a confidence score (0.0–1.0) based on signal strength
- Assign priority: "high" (>10 mentions or URL evidence), "medium" (3-10 mentions), "low" (<3 mentions)

Only recommend integrations that are NOT already connected.
Only recommend integrations from the "Available" list.
Skip integrations with very weak signals (1-2 vague keyword matches).

Respond in JSON:
{{
  "recommendations": [
    {{
      "integration_id": "grafana",
      "priority": "high",
      "confidence": 0.92,
      "reasoning": "Found 23 Grafana URL shares and 45 mentions of dashboards across #incidents and #sre-alerts channels.",
      "evidence_quotes": [
        "Can someone check the payment-service Grafana dashboard?",
        "Latency spike visible on https://grafana.company.com/d/abc123"
      ]
    }}
  ]
}}"""

AVAILABLE_INTEGRATIONS = [
    "grafana",
    "datadog",
    "pagerduty",
    "github",
    "confluence",
    "sentry",
    "newrelic",
    "elasticsearch",
    "prometheus",
    "splunk",
    "incident_io",
    "coralogix",
    "loki",
    "jaeger",
    "opsgenie",
]

# Human-readable names for display
INTEGRATION_DISPLAY_NAMES = {
    "grafana": "Grafana",
    "datadog": "Datadog",
    "pagerduty": "PagerDuty",
    "github": "GitHub",
    "confluence": "Confluence",
    "sentry": "Sentry",
    "newrelic": "New Relic",
    "elasticsearch": "Elasticsearch",
    "prometheus": "Prometheus",
    "splunk": "Splunk",
    "incident_io": "incident.io",
    "coralogix": "Coralogix",
    "loki": "Loki",
    "jaeger": "Jaeger",
    "opsgenie": "OpsGenie",
}


@dataclass
class Recommendation:
    """A recommended integration to connect."""

    integration_id: str
    priority: str  # "high", "medium", "low"
    confidence: float
    reasoning: str
    evidence_quotes: List[str]


@dataclass
class AnalysisResult:
    """Result of LLM signal analysis."""

    recommendations: List[Recommendation]
    raw_response: Optional[str] = None


class SignalAnalyzer:
    """LLM-powered analysis of environment scan signals."""

    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model

    async def analyze(
        self,
        signals: List[Signal],
        existing_integrations: List[str],
    ) -> AnalysisResult:
        """Analyze signals and produce integration recommendations."""
        if not signals:
            return AnalysisResult(recommendations=[])

        # Group signals by integration
        grouped = self._group_signals(signals)

        # Build context for LLM
        signals_summary = self._format_signals_summary(grouped)
        available = [
            i for i in AVAILABLE_INTEGRATIONS if i not in existing_integrations
        ]

        if not available:
            _log("all_integrations_connected")
            return AnalysisResult(recommendations=[])

        prompt = SIGNAL_ANALYSIS_PROMPT.format(
            signals_summary=signals_summary,
            existing_integrations=", ".join(existing_integrations) or "None",
            available_integrations=", ".join(available),
        )

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI()
            response = await client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                max_tokens=1500,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            data = json.loads(content)

            recommendations = []
            for rec in data.get("recommendations", []):
                recommendations.append(
                    Recommendation(
                        integration_id=rec["integration_id"],
                        priority=rec.get("priority", "medium"),
                        confidence=float(rec.get("confidence", 0.5)),
                        reasoning=rec.get("reasoning", ""),
                        evidence_quotes=rec.get("evidence_quotes", []),
                    )
                )

            _log("analysis_completed", recommendations=len(recommendations))
            return AnalysisResult(recommendations=recommendations, raw_response=content)

        except Exception as e:
            _log("analysis_failed", error=str(e))
            # Fallback: heuristic recommendations based on signal counts
            return self._heuristic_analysis(grouped, existing_integrations)

    def _group_signals(self, signals: List[Signal]) -> Dict[str, List[Signal]]:
        """Group signals by integration_id."""
        grouped: Dict[str, List[Signal]] = defaultdict(list)
        for signal in signals:
            grouped[signal.integration_id].append(signal)
        return dict(grouped)

    def _format_signals_summary(self, grouped: Dict[str, List[Signal]]) -> str:
        """Format grouped signals into a readable summary for LLM."""
        lines = []
        for integration_id, sigs in sorted(
            grouped.items(), key=lambda x: len(x[1]), reverse=True
        ):
            display = INTEGRATION_DISPLAY_NAMES.get(integration_id, integration_id)
            total = sum(s.metadata.get("occurrence_count", 1) for s in sigs)
            types = set(s.signal_type for s in sigs)
            sources = set(s.source for s in sigs)

            lines.append(f"### {display} ({integration_id})")
            lines.append(f"- Total occurrences: {total}")
            lines.append(f"- Signal types: {', '.join(types)}")
            lines.append(f"- Found in: {', '.join(list(sources)[:5])}")

            # Include up to 3 example contexts
            examples = [s.context for s in sigs if s.context][:3]
            if examples:
                lines.append("- Example messages:")
                for ex in examples:
                    lines.append(f'  > "{ex[:200]}"')
            lines.append("")

        return "\n".join(lines)

    def _heuristic_analysis(
        self,
        grouped: Dict[str, List[Signal]],
        existing_integrations: List[str],
    ) -> AnalysisResult:
        """Fallback heuristic analysis when LLM is unavailable."""
        recommendations = []
        for integration_id, sigs in sorted(
            grouped.items(), key=lambda x: len(x[1]), reverse=True
        ):
            if integration_id in existing_integrations:
                continue
            if integration_id not in AVAILABLE_INTEGRATIONS:
                continue

            total = sum(s.metadata.get("occurrence_count", 1) for s in sigs)
            has_url = any(s.signal_type == "url" for s in sigs)

            if total < 2 and not has_url:
                continue

            if total >= 10 or has_url:
                priority = "high"
                confidence = min(0.95, 0.6 + total * 0.02)
            elif total >= 3:
                priority = "medium"
                confidence = 0.5 + total * 0.03
            else:
                priority = "low"
                confidence = 0.3 + total * 0.05

            display = INTEGRATION_DISPLAY_NAMES.get(integration_id, integration_id)
            recommendations.append(
                Recommendation(
                    integration_id=integration_id,
                    priority=priority,
                    confidence=round(confidence, 2),
                    reasoning=f"Found {total} mentions of {display} across Slack channels.",
                    evidence_quotes=[s.context[:200] for s in sigs[:2] if s.context],
                )
            )

        _log("heuristic_analysis_completed", recommendations=len(recommendations))
        return AnalysisResult(recommendations=recommendations)


# ---------------------------------------------------------------------------
# Integration Recommender — submits PendingConfigChange records
# ---------------------------------------------------------------------------


class IntegrationRecommender:
    """Creates PendingConfigChange records for integration recommendations."""

    def __init__(self, config_service_url: str):
        self.config_service_url = config_service_url.rstrip("/")

    async def submit_recommendations(
        self,
        org_id: str,
        team_node_id: str,
        recommendations: List[Recommendation],
    ) -> List[str]:
        """Submit recommendations as PendingConfigChange records.

        Returns list of created change IDs.
        """
        change_ids = []

        for rec in recommendations:
            change_id = await self._create_pending_change(
                org_id=org_id,
                team_node_id=team_node_id,
                recommendation=rec,
            )
            if change_id:
                change_ids.append(change_id)

        _log(
            "recommendations_submitted",
            org_id=org_id,
            count=len(change_ids),
        )
        return change_ids

    async def _create_pending_change(
        self,
        org_id: str,
        team_node_id: str,
        recommendation: Recommendation,
    ) -> Optional[str]:
        """Create a single PendingConfigChange for an integration recommendation."""
        display_name = INTEGRATION_DISPLAY_NAMES.get(
            recommendation.integration_id, recommendation.integration_id
        )
        change_id = f"rec_{uuid.uuid4().hex[:12]}"

        evidence = [
            {
                "source_type": "slack_message",
                "source_id": "",
                "quote": quote[:300],
                "link_hint": "Slack workspace",
            }
            for quote in recommendation.evidence_quotes[:5]
        ]

        proposed_value = {
            "title": f"Connect {display_name}",
            "integration_id": recommendation.integration_id,
            "integration_name": display_name,
            "recommendation": recommendation.reasoning,
            "priority": recommendation.priority,
            "confidence": recommendation.confidence,
            "evidence": evidence,
            "source": "onboarding_scan",
        }

        payload = {
            "id": change_id,
            "org_id": org_id,
            "node_id": team_node_id,
            "change_type": "integration_recommendation",
            "proposed_value": proposed_value,
            "requested_by": "onboarding_scan",
            "reason": recommendation.reasoning,
            "status": "pending",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.config_service_url}/api/v1/internal/pending-changes",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Internal-Service": "ai_pipeline",
                    },
                )

                if response.status_code == 200:
                    _log(
                        "pending_change_created",
                        change_id=change_id,
                        integration=recommendation.integration_id,
                    )
                    return change_id
                else:
                    _log(
                        "pending_change_failed",
                        status=response.status_code,
                        body=response.text[:200],
                    )
                    return None

        except Exception as e:
            _log("pending_change_error", error=str(e))
            return None


# ---------------------------------------------------------------------------
# OnboardingScanTask — main orchestrator
# ---------------------------------------------------------------------------


class OnboardingScanTask:
    """
    Orchestrates onboarding environment scans.

    Supports two trigger modes:
    - initial: Post-OAuth Slack workspace scan
    - integration: Post-integration-save scan for a specific integration
    """

    def __init__(
        self,
        org_id: str,
        team_node_id: str,
        channel_ids: Optional[List[str]] = None,
    ):
        self.org_id = org_id
        self.team_node_id = team_node_id
        self.channel_ids = channel_ids  # Team-scoped channels (None = all)

        self.config_service_url = os.getenv(
            "CONFIG_SERVICE_URL", "http://config-service:8080"
        )
        self.rag_url = os.getenv("RAPTOR_URL", "http://knowledge-base:8000")

        self.analyzer = SignalAnalyzer()
        self.recommender = IntegrationRecommender(self.config_service_url)
        self.knowledge_extractor = KnowledgeExtractor()

    async def run_initial_scan(self, slack_bot_token: str) -> Dict[str, Any]:
        """
        Run initial environment scan after Slack OAuth.

        Scans Slack workspace, analyzes signals, creates recommendations.
        """
        _log(
            "initial_scan_started",
            org_id=self.org_id,
            team_node_id=self.team_node_id,
        )

        result: Dict[str, Any] = {
            "trigger": "initial",
            "started_at": datetime.utcnow().isoformat(),
        }

        # 1. Scan Slack (scoped to team's channels if specified)
        scanner = SlackEnvironmentScanner(
            bot_token=slack_bot_token, channel_ids=self.channel_ids
        )
        scan_result = scanner.scan()

        result["channels_scanned"] = scan_result.channels_scanned
        result["messages_scanned"] = scan_result.messages_scanned
        result["signals_found"] = len(scan_result.signals)
        result["scan_duration_ms"] = scan_result.scan_duration_ms

        if scan_result.error:
            result["error"] = scan_result.error
            _log("initial_scan_error", error=scan_result.error)
            return result

        if not scan_result.signals:
            result["recommendations"] = []
            _log("initial_scan_no_signals")
            return result

        # 2. Get existing integrations
        existing = await self._get_existing_integrations()

        # 3. Analyze signals
        analysis = await self.analyzer.analyze(
            signals=scan_result.signals,
            existing_integrations=existing,
        )

        # 4. Submit recommendations
        if analysis.recommendations:
            change_ids = await self.recommender.submit_recommendations(
                org_id=self.org_id,
                team_node_id=self.team_node_id,
                recommendations=analysis.recommendations,
            )
            result["recommendations_created"] = change_ids
            result["recommendations"] = [
                {
                    "integration_id": r.integration_id,
                    "priority": r.priority,
                    "confidence": r.confidence,
                }
                for r in analysis.recommendations
            ]
        else:
            result["recommendations"] = []

        # 5. Ingest collected Slack knowledge into RAG
        if scan_result.collected_messages:
            ingest_result = await self._ingest_slack_knowledge(
                scan_result.collected_messages
            )
            result["rag_ingestion"] = ingest_result

        result["completed_at"] = datetime.utcnow().isoformat()

        _log(
            "initial_scan_completed",
            signals=len(scan_result.signals),
            recommendations=len(analysis.recommendations),
            messages_ingested=len(scan_result.collected_messages),
        )

        return result

    async def run_integration_scan(
        self,
        integration_id: str,
        integration_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run scan after a new integration is configured.

        Two responsibilities:
        1. Fetch data from the integration and ingest knowledge into RAG
        2. Re-analyze all signals — the new integration may reveal new recommendations
        """
        _log(
            "integration_scan_started",
            org_id=self.org_id,
            integration_id=integration_id,
        )

        result: Dict[str, Any] = {
            "trigger": "integration",
            "integration_id": integration_id,
            "started_at": datetime.utcnow().isoformat(),
        }

        # 1. Fetch integration config if not provided
        if not integration_config:
            integration_config = await self._get_integration_config(integration_id)

        # 2. Run integration-specific scanner (fetches credentials, calls API directly)
        try:
            ingest_result = await self._run_integration_scanner(
                integration_id, integration_config or {}
            )
            result["ingestion"] = ingest_result
        except Exception as e:
            _log(
                "integration_scanner_failed",
                integration_id=integration_id,
                error=str(e),
            )
            result["ingestion"] = {"error": str(e)}

        # 3. Re-check for new recommendations based on updated integrations
        existing = await self._get_existing_integrations()
        # If the team already has pending signals from initial scan,
        # re-analyzing could surface new recommendations now that
        # this integration is connected. For now, just log.
        _log(
            "integration_scan_recheck",
            integration_id=integration_id,
            current_integrations=existing,
        )

        result["completed_at"] = datetime.utcnow().isoformat()

        _log(
            "integration_scan_completed",
            integration_id=integration_id,
            ingestion=result.get("ingestion", {}),
        )

        return result

    async def _fetch_credentials(self, integration_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch decrypted credentials for an integration from config service.

        Uses the generic credential endpoint — no per-integration proxies needed.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.config_service_url}/api/v1/internal/credentials"
                    f"/{self.org_id}/{integration_id}",
                    headers={"X-Internal-Service": "ai_pipeline"},
                )

                if response.status_code == 200:
                    return response.json().get("config", {})
                else:
                    _log(
                        "credentials_fetch_failed",
                        integration_id=integration_id,
                        status=response.status_code,
                    )
                    return None

        except Exception as e:
            _log("credentials_fetch_error", integration_id=integration_id, error=str(e))
            return None

    async def _run_integration_scanner(
        self, integration_id: str, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Run a scanner for a specific integration.

        1. Fetch credentials from config service (one generic endpoint)
        2. Call the registered scanner (which talks to external API directly)
        3. Ingest returned documents into RAG
        """
        scanner_fn = get_scanner(integration_id)
        if not scanner_fn:
            return {"status": "no_scanner_available"}

        # Fetch decrypted credentials
        credentials = await self._fetch_credentials(integration_id)
        if not credentials:
            return {"status": "no_credentials"}

        # Run the scanner — it calls external APIs directly
        documents = await scanner_fn(
            credentials=credentials,
            config=config,
            org_id=self.org_id,
        )

        if not documents:
            return {"status": "no_docs_found"}

        # LLM extraction: transform raw docs into classified knowledge
        documents = await self._extract_knowledge_from_docs(documents, integration_id)

        # Ingest into RAG
        return await self._ingest_documents(
            documents, tree=f"{integration_id}_{self.org_id}_{self.team_node_id}"
        )

    async def _extract_knowledge_from_docs(
        self, documents: List[Document], source_type: str
    ) -> List[Document]:
        """Run LLM knowledge extraction on Document objects.

        Transforms raw documents into classified knowledge items with
        proper knowledge_type set.
        """
        knowledge_items = await self.knowledge_extractor.extract_from_documents(
            documents=documents,
            source_type=source_type,
        )

        if not knowledge_items:
            return documents

        result = []
        for item in knowledge_items:
            result.append(
                Document(
                    content=item.content,
                    source_url=item.source_url or "",
                    content_type="text",
                    knowledge_type=item.knowledge_type,
                    metadata={
                        "title": item.title,
                        "entities": [
                            {"name": e.name, "type": e.entity_type}
                            for e in item.entities
                        ],
                        "confidence": item.confidence,
                        "org_id": self.org_id,
                        "source": "integration_scan",
                        **item.metadata,
                    },
                )
            )

        _log(
            "knowledge_extracted",
            source_type=source_type,
            raw_documents=len(documents),
            extracted_items=len(result),
        )
        return result

    async def _ingest_documents(
        self, documents: List[Document], tree: str
    ) -> Dict[str, Any]:
        """Ingest a list of documents into RAG via /ingest/batch."""
        doc_dicts = []
        for doc in documents:
            meta = dict(doc.metadata) if doc.metadata else {}
            if doc.knowledge_type:
                meta["knowledge_type"] = doc.knowledge_type
            doc_dicts.append(
                {
                    "content": doc.content,
                    "source_url": doc.source_url,
                    "content_type": doc.content_type,
                    "metadata": meta,
                }
            )

        payload = {
            "documents": doc_dicts,
            "tree": tree,
            "build_hierarchy": False,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.rag_url}/ingest/batch",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code == 200:
                    data = response.json()
                    _log(
                        "documents_ingested",
                        tree=tree,
                        documents_sent=len(documents),
                        chunks_created=data.get("chunks_created", 0),
                    )
                    return {
                        "status": "ingested",
                        "documents_sent": len(documents),
                        "chunks_created": data.get("chunks_created", 0),
                        "nodes_created": data.get("nodes_created", 0),
                    }
                else:
                    return {
                        "status": "ingest_failed",
                        "documents_sent": len(documents),
                        "error": f"HTTP {response.status_code}",
                    }

        except Exception as e:
            return {
                "status": "ingest_error",
                "documents_sent": len(documents),
                "error": str(e),
            }

    async def _get_integration_config(
        self, integration_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch config for a specific integration from config service."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.config_service_url}/api/v2/orgs/{self.org_id}"
                    f"/nodes/{self.team_node_id}/config/effective",
                )

                if response.status_code != 200:
                    return None

                config = response.json()
                return config.get("integrations", {}).get(integration_id)

        except Exception as e:
            _log("get_integration_config_failed", error=str(e))
            return None

    async def _ingest_slack_knowledge(
        self, messages: List[CollectedMessage]
    ) -> Dict[str, Any]:
        """
        Ingest collected Slack messages into the RAG system.

        Uses LLM-powered KnowledgeExtractor to transform raw messages into
        classified operational knowledge items before ingesting into RAG.
        """
        if not messages:
            return {"documents_sent": 0}

        # LLM extraction: transform raw messages into knowledge items
        knowledge_items = await self.knowledge_extractor.extract_from_slack(
            messages=messages,
            org_id=self.org_id,
        )

        if not knowledge_items:
            _log(
                "slack_knowledge_extraction_empty",
                raw_messages=len(messages),
            )
            return {"documents_sent": 0, "items_extracted": 0}

        # Convert KnowledgeItems to Document objects for ingestion
        documents = []
        for item in knowledge_items:
            documents.append(
                Document(
                    content=item.content,
                    source_url=item.source_url or f"slack://{self.org_id}",
                    content_type="text",
                    knowledge_type=item.knowledge_type,
                    metadata={
                        "title": item.title,
                        "entities": [
                            {"name": e.name, "type": e.entity_type}
                            for e in item.entities
                        ],
                        "confidence": item.confidence,
                        "org_id": self.org_id,
                        "source": "onboarding_scan",
                        **item.metadata,
                    },
                )
            )

        # Ingest via existing method
        result = await self._ingest_documents(
            documents, tree=f"slack_{self.org_id}_{self.team_node_id}"
        )
        result["items_extracted"] = len(knowledge_items)
        result["raw_messages_processed"] = len(messages)

        _log(
            "slack_knowledge_ingested",
            raw_messages=len(messages),
            items_extracted=len(knowledge_items),
        )
        return result

    async def _get_existing_integrations(self) -> List[str]:
        """Fetch already-configured integrations from config service."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.config_service_url}/api/v2/orgs/{self.org_id}"
                    f"/nodes/{self.team_node_id}/config/effective",
                )

                if response.status_code != 200:
                    return ["slack"]  # Slack is always connected after OAuth

                config = response.json()
                integrations = config.get("integrations", {})

                # An integration is "configured" if it has any fields set
                configured = []
                for int_id, int_config in integrations.items():
                    if isinstance(int_config, dict) and any(
                        v for k, v in int_config.items() if k != "enabled"
                    ):
                        configured.append(int_id)

                if "slack" not in configured:
                    configured.append("slack")

                return configured

        except Exception as e:
            _log("get_integrations_failed", error=str(e))
            return ["slack"]
