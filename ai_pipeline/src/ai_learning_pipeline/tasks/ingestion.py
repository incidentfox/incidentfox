"""
Knowledge Ingestion Task.

Ingests knowledge from configured sources using LLM-powered analysis:
- Confluence
- Google Docs
- GitHub repositories
- Grafana dashboards
- Incident history
- Slack channels

This task uses the IntelligentIngestionPipeline which provides:
1. Document Processing (parsing, chunking)
2. LLM-Powered Analysis (knowledge type, entities, relationships, importance)
3. Conflict Resolution (duplicate detection, supersession, merging)
4. Human Review Integration (FLAG_REVIEW to Proposed Changes)
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

# Add ultimate_rag to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../.."))


def _log(event: str, **fields) -> None:
    """Structured logging."""
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-learning-pipeline",
        "module": "tasks.ingestion",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


class APIIntegratedStorageBackend:
    """
    Storage backend that combines in-memory storage with API integration.

    Content is stored in memory (for development/testing), but pending changes
    are submitted to the config_service internal API so they appear in the
    Proposed Changes UI at /team/pending-changes.
    """

    def __init__(
        self,
        org_id: str,
        team_node_id: str,
        config_service_url: str,
    ):
        self.org_id = org_id
        self.team_node_id = team_node_id
        self.config_service_url = config_service_url.rstrip("/")

        # In-memory storage for content
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.pending_changes: Dict[str, Any] = {}
        self._node_counter = 0

    async def store_content(
        self,
        content: str,
        source: str,
        analysis: Any,
        related_node_ids: Optional[List[str]] = None,
    ) -> str:
        """Store content and return node ID."""
        self._node_counter += 1
        node_id = f"node_{self._node_counter}"

        self.nodes[node_id] = {
            "id": node_id,
            "content": content,
            "source": source,
            "analysis": analysis,
            "related_node_ids": related_node_ids or [],
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

        return node_id

    async def update_content(
        self,
        node_id: str,
        content: str,
        source: str,
        analysis: Any,
        importance_multiplier: float = 1.0,
    ) -> None:
        """Update existing content."""
        if node_id in self.nodes:
            self.nodes[node_id].update({
                "content": content,
                "source": source,
                "analysis": analysis,
                "updated_at": datetime.utcnow().isoformat(),
            })

    async def find_similar(
        self,
        content: str,
        limit: int = 5,
        threshold: float = 0.75,
    ) -> List[Dict[str, Any]]:
        """Find similar existing content using simple text overlap."""
        results = []

        content_words = set(content.lower().split())

        for node_id, node in self.nodes.items():
            node_content = node.get("content", "")
            node_words = set(node_content.lower().split())

            if not node_words:
                continue

            # Jaccard similarity
            intersection = len(content_words & node_words)
            union = len(content_words | node_words)
            similarity = intersection / union if union > 0 else 0

            if similarity >= threshold:
                results.append({
                    "id": node_id,
                    "content": node_content,
                    "source": node.get("source", "unknown"),
                    "updated_at": node.get("updated_at", "unknown"),
                    "similarity_score": similarity,
                })

        results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return results[:limit]

    async def store_pending_change(self, change: Any) -> str:
        """Store a pending change by submitting to the config_service internal API."""
        # Store locally as backup
        self.pending_changes[change.id] = change

        # Submit to config_service internal API
        try:
            url = f"{self.config_service_url}/api/v1/internal/pending-changes"

            # Build proposed_value dict for the team UI
            proposed_value = {
                "title": change.title,
                "summary": change.new_content,
                "learned_from": change.source,
                "conflict_type": change.conflict_relationship.value,
                "existing_content": change.existing_content,
                "existing_node_id": change.existing_node_id,
                "ai_reasoning": change.conflict_reasoning,
                "ai_confidence": change.confidence,
                "evidence": change.evidence,
            }

            reason = (
                f"{change.conflict_reasoning}\n\n"
                f"Conflict type: {change.conflict_relationship.value}\n"
                f"AI confidence: {change.confidence:.2f}"
            )

            payload = {
                "id": change.id,
                "org_id": self.org_id,
                "node_id": self.team_node_id,
                "change_type": "knowledge",
                "proposed_value": proposed_value,
                "previous_value": (
                    {"content": change.existing_content, "node_id": change.existing_node_id}
                    if change.existing_content else None
                ),
                "requested_by": change.proposed_by or "content_analyzer",
                "reason": reason,
                "status": "pending",
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Internal-Service": "ai_pipeline",
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

                _log(
                    "pending_change_submitted",
                    change_id=change.id,
                    api_id=data.get("id"),
                )

                return data.get("id", change.id)

        except Exception as e:
            _log(
                "pending_change_api_failed",
                change_id=change.id,
                error=str(e),
            )
            # Return local ID on API failure
            return change.id


class KnowledgeIngestionTask:
    """
    Ingests knowledge from external sources into the knowledge base.

    Uses the IntelligentIngestionPipeline for LLM-powered analysis:
    - Knowledge type classification
    - Entity extraction
    - Relationship extraction
    - Importance assessment
    - Conflict resolution
    - Human review integration
    """

    def __init__(
        self,
        org_id: str,
        team_node_id: str,
        config_client: Optional[httpx.AsyncClient] = None,
        raptor_client: Optional[httpx.AsyncClient] = None,
        sources_config: Optional[Dict[str, Any]] = None,
    ):
        self.org_id = org_id
        self.team_node_id = team_node_id
        self._config_client = config_client
        self._raptor_client = raptor_client
        self.sources_config = sources_config or {}
        self._initialized = False
        self._pipeline = None  # IntelligentIngestionPipeline

    async def initialize(self) -> None:
        """Initialize the task and pipeline."""
        if not self._config_client:
            config_url = os.getenv("CONFIG_SERVICE_URL", "http://config-service:8080")
            self._config_client = httpx.AsyncClient(base_url=config_url, timeout=30.0)

        if not self._raptor_client:
            raptor_url = os.getenv("RAPTOR_URL", "http://knowledge-base:8000")
            self._raptor_client = httpx.AsyncClient(base_url=raptor_url, timeout=60.0)

        # Initialize the intelligent ingestion pipeline
        await self._initialize_pipeline()

        self._initialized = True
        _log(
            "ingestion_task_initialized",
            org_id=self.org_id,
            team_node_id=self.team_node_id,
            pipeline_enabled=self._pipeline is not None,
        )

    async def _initialize_pipeline(self) -> None:
        """Initialize the IntelligentIngestionPipeline with LLM-powered analysis."""
        try:
            from ultimate_rag.ingestion import (
                IntelligentIngestionPipeline,
                PipelineConfig,
            )
            from ultimate_rag.ingestion.pipeline import InMemoryStorageBackend

            # Create pipeline config
            config = PipelineConfig(
                use_stepwise_analysis=False,  # Single LLM call for efficiency
                analysis_batch_size=10,
                analysis_max_concurrent=5,
                similarity_threshold=0.75,
                conflict_check_enabled=True,
                min_importance_to_store=0.2,
                min_confidence_to_auto_resolve=0.8,
                model=os.getenv("LLM_MODEL", "gpt-4o-2024-08-06"),
                temperature=0.1,
            )

            # Create storage backend with API integration for pending changes
            config_service_url = os.getenv("CONFIG_SERVICE_URL", "http://config-service:8080")
            storage = APIIntegratedStorageBackend(
                org_id=self.org_id,
                team_node_id=self.team_node_id,
                config_service_url=config_service_url,
            )

            self._pipeline = IntelligentIngestionPipeline(
                storage_backend=storage,
                config=config,
            )

            _log(
                "intelligent_pipeline_initialized",
                model=config.model,
                api_integration=True,
            )

        except ImportError as e:
            _log("pipeline_import_failed", error=str(e))
            self._pipeline = None
        except Exception as e:
            _log("pipeline_init_failed", error=str(e))
            self._pipeline = None

    async def run(self) -> Dict[str, Any]:
        """Run the ingestion task."""
        if not self._initialized:
            await self.initialize()

        results = {
            "started_at": datetime.utcnow().isoformat(),
            "documents_processed": 0,
            "chunks_created": 0,
            "sources_processed": [],
            "errors": [],
        }

        # Process each enabled source
        if self.sources_config.get("confluence_enabled"):
            try:
                source_result = await self._ingest_confluence()
                results["sources_processed"].append(
                    {"source": "confluence", **source_result}
                )
                results["documents_processed"] += source_result.get("documents", 0)
                results["chunks_created"] += source_result.get("chunks", 0)
            except Exception as e:
                _log("confluence_ingestion_failed", error=str(e))
                results["errors"].append({"source": "confluence", "error": str(e)})

        if self.sources_config.get("github_enabled"):
            try:
                source_result = await self._ingest_github()
                results["sources_processed"].append(
                    {"source": "github", **source_result}
                )
                results["documents_processed"] += source_result.get("documents", 0)
                results["chunks_created"] += source_result.get("chunks", 0)
            except Exception as e:
                _log("github_ingestion_failed", error=str(e))
                results["errors"].append({"source": "github", "error": str(e)})

        if self.sources_config.get("incidents_enabled", True):
            try:
                source_result = await self._ingest_incidents()
                results["sources_processed"].append(
                    {"source": "incidents", **source_result}
                )
                results["documents_processed"] += source_result.get("documents", 0)
                results["chunks_created"] += source_result.get("chunks", 0)
            except Exception as e:
                _log("incidents_ingestion_failed", error=str(e))
                results["errors"].append({"source": "incidents", "error": str(e)})

        if self.sources_config.get("grafana_enabled"):
            try:
                source_result = await self._ingest_grafana()
                results["sources_processed"].append(
                    {"source": "grafana", **source_result}
                )
                results["documents_processed"] += source_result.get("documents", 0)
                results["chunks_created"] += source_result.get("chunks", 0)
            except Exception as e:
                _log("grafana_ingestion_failed", error=str(e))
                results["errors"].append({"source": "grafana", "error": str(e)})

        results["completed_at"] = datetime.utcnow().isoformat()

        _log(
            "ingestion_completed",
            documents_processed=results["documents_processed"],
            chunks_created=results["chunks_created"],
            sources_count=len(results["sources_processed"]),
            errors_count=len(results["errors"]),
        )

        return results

    async def _ingest_confluence(self) -> Dict[str, Any]:
        """Ingest from Confluence spaces."""
        spaces = self.sources_config.get("confluence_spaces", [])
        _log("confluence_ingestion_started", spaces=spaces)

        # TODO: Use knowledge_base/ingestion/extractors/web.py WebExtractor
        # For now, return placeholder
        return {"documents": 0, "chunks": 0, "status": "not_implemented"}

    async def _ingest_github(self) -> Dict[str, Any]:
        """Ingest from GitHub repositories."""
        repos = self.sources_config.get("github_repos", [])
        paths = self.sources_config.get("github_paths", ["docs/", "runbooks/", "*.md"])
        _log("github_ingestion_started", repos=repos, paths=paths)

        # TODO: Use knowledge_base/ingestion/extractors/file.py or git integration
        # For now, return placeholder
        return {"documents": 0, "chunks": 0, "status": "not_implemented"}

    async def _ingest_incidents(self) -> Dict[str, Any]:
        """Ingest past incidents and postmortems using LLM-powered analysis."""
        lookback_days = self.sources_config.get("incidents_lookback_days", 90)
        _log("incidents_ingestion_started", lookback_days=lookback_days)

        documents = 0
        chunks = 0
        flagged = 0
        errors = []

        try:
            # Fetch incidents from config service (where they're stored)
            response = await self._config_client.get(
                f"/api/v1/orgs/{self.org_id}/teams/{self.team_node_id}/incidents",
                params={"days": lookback_days},
            )

            if response.status_code == 200:
                incidents = response.json().get("incidents", [])

                for incident in incidents:
                    try:
                        content = self._format_incident(incident)

                        # Use intelligent pipeline if available
                        if self._pipeline:
                            result = await self._pipeline.ingest_content(
                                content=content,
                                source=f"incident:{incident.get('id', 'unknown')}",
                                content_type="incident_report",
                                extra_metadata={
                                    "incident_id": incident.get("id"),
                                    "category": "incident",
                                    "severity": incident.get("severity"),
                                    "services_affected": incident.get("services_affected", []),
                                },
                            )

                            documents += 1
                            chunks += result.chunks_stored
                            flagged += result.chunks_flagged

                            if result.errors:
                                errors.extend(result.errors)

                            _log(
                                "incident_ingested",
                                incident_id=incident.get("id"),
                                chunks_stored=result.chunks_stored,
                                chunks_flagged=result.chunks_flagged,
                            )

                        else:
                            # Fallback to legacy API if pipeline not available
                            ingest_response = await self._raptor_client.post(
                                "/ingest",
                                json={
                                    "content": content,
                                    "metadata": {
                                        "source": "incident",
                                        "incident_id": incident.get("id"),
                                        "category": "incident",
                                    },
                                },
                            )

                            if ingest_response.status_code == 200:
                                result = ingest_response.json()
                                documents += 1
                                chunks += result.get("chunks_created", 0)

                    except Exception as e:
                        _log(
                            "incident_ingestion_error",
                            incident_id=incident.get("id"),
                            error=str(e),
                        )
                        errors.append(f"Incident {incident.get('id')}: {e}")

        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise

        return {
            "documents": documents,
            "chunks": chunks,
            "flagged_for_review": flagged,
            "errors": errors,
            "status": "completed",
        }

    async def _ingest_grafana(self) -> Dict[str, Any]:
        """Ingest Grafana dashboards and alert rules."""
        folders = self.sources_config.get("grafana_folders", [])
        _log("grafana_ingestion_started", folders=folders)

        # TODO: Integrate with Grafana API
        return {"documents": 0, "chunks": 0, "status": "not_implemented"}

    def _format_incident(self, incident: Dict[str, Any]) -> str:
        """Format an incident record for ingestion."""
        parts = []

        if incident.get("title"):
            parts.append(f"# Incident: {incident['title']}")

        if incident.get("summary"):
            parts.append(f"\n## Summary\n{incident['summary']}")

        if incident.get("symptoms"):
            parts.append(f"\n## Symptoms\n{incident['symptoms']}")

        if incident.get("root_cause"):
            parts.append(f"\n## Root Cause\n{incident['root_cause']}")

        if incident.get("resolution"):
            parts.append(f"\n## Resolution\n{incident['resolution']}")

        if incident.get("services_affected"):
            services = ", ".join(incident["services_affected"])
            parts.append(f"\n## Services Affected\n{services}")

        if incident.get("date"):
            parts.append(f"\n## Date\n{incident['date']}")

        return "\n".join(parts)
