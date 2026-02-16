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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from .scanners.slack_scanner import (
    CollectedMessage,
    ScanResult,
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
    ):
        self.org_id = org_id
        self.team_node_id = team_node_id

        self.config_service_url = os.getenv(
            "CONFIG_SERVICE_URL", "http://config-service:8080"
        )
        self.rag_url = os.getenv("RAPTOR_URL", "http://knowledge-base:8000")

        self.analyzer = SignalAnalyzer()
        self.recommender = IntegrationRecommender(self.config_service_url)

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

        # 1. Scan Slack
        scanner = SlackEnvironmentScanner(bot_token=slack_bot_token)
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

        # 2. Run integration-specific data ingestion
        scanner_method = self._get_integration_scanner(integration_id)
        if scanner_method:
            try:
                ingest_result = await scanner_method(integration_config or {})
                result["ingestion"] = ingest_result
            except Exception as e:
                _log(
                    "integration_scanner_failed",
                    integration_id=integration_id,
                    error=str(e),
                )
                result["ingestion"] = {"error": str(e)}
        else:
            _log(
                "no_scanner_for_integration",
                integration_id=integration_id,
            )
            result["ingestion"] = {"status": "no_scanner_available"}

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

    def _get_integration_scanner(self, integration_id: str):
        """Return the scanner method for a given integration, or None."""
        scanners = {
            "github": self._scan_github,
            "confluence": self._scan_confluence,
        }
        return scanners.get(integration_id)

    async def _scan_github(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scan a connected GitHub integration for operational knowledge.

        Discovers repos, READMEs, runbooks, and incident-related docs
        and ingests them into RAG.
        """
        # GitHub integration uses the GitHub App — repos are auto-discovered.
        # We look for operational docs: runbooks, postmortems, READMEs.
        github_org = config.get("account_login") or config.get("org")
        if not github_org:
            return {"status": "no_org_configured"}

        documents = []

        # Fetch repos via config service (which proxies GitHub App auth)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.config_service_url}/api/v1/internal/github"
                    f"/repos?org_id={self.org_id}",
                    headers={
                        "X-Internal-Service": "ai_pipeline",
                        "Content-Type": "application/json",
                    },
                )

                if response.status_code != 200:
                    return {
                        "status": "failed_to_list_repos",
                        "code": response.status_code,
                    }

                repos = response.json()
                if not isinstance(repos, list):
                    repos = repos.get("repositories", [])

        except Exception as e:
            return {"status": "repos_fetch_error", "error": str(e)}

        # For each repo, try to fetch operational docs
        ops_paths = [
            "README.md",
            "docs/runbook.md",
            "docs/runbooks/",
            "runbook.md",
            "RUNBOOK.md",
            "docs/oncall.md",
            "docs/incident-response.md",
        ]

        for repo in repos[:20]:  # Cap at 20 repos
            repo_name = repo.get("full_name") or repo.get("name", "")
            if not repo_name:
                continue

            for doc_path in ops_paths:
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.get(
                            f"{self.config_service_url}/api/v1/internal/github"
                            f"/file?org_id={self.org_id}"
                            f"&repo={repo_name}&path={doc_path}",
                            headers={
                                "X-Internal-Service": "ai_pipeline",
                                "Content-Type": "application/json",
                            },
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            content = data.get("content", "")
                            if content and len(content) >= 50:
                                documents.append(
                                    {
                                        "content": content,
                                        "source_url": f"github://{repo_name}/{doc_path}",
                                        "content_type": "markdown",
                                        "metadata": {
                                            "repo": repo_name,
                                            "path": doc_path,
                                            "org_id": self.org_id,
                                            "source": "integration_scan",
                                        },
                                    }
                                )
                except Exception:
                    continue  # Best-effort per file

        if not documents:
            return {"status": "no_docs_found", "repos_scanned": len(repos)}

        return await self._ingest_documents(documents, tree=f"github_{self.org_id}")

    async def _scan_confluence(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scan a connected Confluence integration for operational knowledge.

        Discovers runbook/incident spaces and ingests pages into RAG.
        """
        base_url = config.get("base_url") or config.get("url", "")
        if not base_url:
            return {"status": "no_url_configured"}

        # Search for ops-relevant pages via config service proxy
        search_queries = [
            "runbook",
            "incident response",
            "on-call",
            "postmortem",
            "architecture",
        ]

        documents = []
        for query in search_queries:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(
                        f"{self.config_service_url}/api/v1/internal/confluence"
                        f"/search?org_id={self.org_id}&query={query}&limit=10",
                        headers={
                            "X-Internal-Service": "ai_pipeline",
                            "Content-Type": "application/json",
                        },
                    )
                    if resp.status_code == 200:
                        pages = resp.json()
                        if not isinstance(pages, list):
                            pages = pages.get("results", [])

                        for page in pages:
                            content = page.get("body", "") or page.get("content", "")
                            title = page.get("title", "Untitled")
                            page_url = page.get("url", "")

                            if content and len(content) >= 50:
                                documents.append(
                                    {
                                        "content": content,
                                        "source_url": page_url
                                        or f"confluence://{title}",
                                        "content_type": "markdown",
                                        "metadata": {
                                            "title": title,
                                            "org_id": self.org_id,
                                            "source": "integration_scan",
                                            "search_query": query,
                                        },
                                    }
                                )
            except Exception:
                continue  # Best-effort per query

        if not documents:
            return {"status": "no_pages_found"}

        return await self._ingest_documents(documents, tree=f"confluence_{self.org_id}")

    async def _ingest_documents(
        self, documents: List[Dict], tree: str
    ) -> Dict[str, Any]:
        """Ingest a list of documents into RAG via /ingest/batch."""
        payload = {
            "documents": documents,
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

        Groups messages by channel, formats them as documents following the
        existing SlackSource format ([TIMESTAMP] USER: TEXT), and POSTs to
        the Ultimate RAG /ingest/batch endpoint.
        """
        if not messages:
            return {"documents_sent": 0}

        # Group messages by channel
        by_channel: Dict[str, List[CollectedMessage]] = defaultdict(list)
        for msg in messages:
            by_channel[msg.channel_name].append(msg)

        documents = []
        for channel_name, ch_messages in by_channel.items():
            # Sort by timestamp
            ch_messages.sort(key=lambda m: m.ts)

            # Format messages following existing SlackSource convention
            lines = []
            participants: set = set()
            for msg in ch_messages:
                ts_float = float(msg.ts) if msg.ts else 0
                ts_str = (
                    datetime.fromtimestamp(ts_float).strftime("%Y-%m-%d %H:%M")
                    if ts_float
                    else "unknown"
                )
                lines.append(f"[{ts_str}] {msg.user}: {msg.text}")
                participants.add(msg.user)

            content = "\n".join(lines)

            # Skip very short documents
            if len(content) < 100:
                continue

            documents.append(
                {
                    "content": content,
                    "source_url": f"slack://#{channel_name}",
                    "content_type": "slack_thread",
                    "metadata": {
                        "channel": channel_name,
                        "message_count": len(ch_messages),
                        "participants": list(participants),
                        "org_id": self.org_id,
                        "source": "onboarding_scan",
                    },
                }
            )

        if not documents:
            return {"documents_sent": 0}

        # POST to Ultimate RAG /ingest/batch
        payload = {
            "documents": documents,
            "tree": f"slack_{self.org_id}",
            "build_hierarchy": False,  # Fast ingest, hierarchy built later by cronjob
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
                        "rag_ingestion_completed",
                        documents_sent=len(documents),
                        chunks_created=data.get("chunks_created", 0),
                    )
                    return {
                        "documents_sent": len(documents),
                        "chunks_created": data.get("chunks_created", 0),
                        "nodes_created": data.get("nodes_created", 0),
                    }
                else:
                    _log(
                        "rag_ingestion_failed",
                        status=response.status_code,
                        body=response.text[:200],
                    )
                    return {
                        "documents_sent": len(documents),
                        "error": f"HTTP {response.status_code}",
                    }

        except Exception as e:
            _log("rag_ingestion_error", error=str(e))
            return {"documents_sent": len(documents), "error": str(e)}

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
