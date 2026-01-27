"""
Knowledge Ingestion Task.

Ingests knowledge from configured sources:
- Confluence
- Google Docs
- GitHub repositories
- Grafana dashboards
- Incident history
- Slack channels
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx


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


class KnowledgeIngestionTask:
    """
    Ingests knowledge from external sources into the knowledge base.

    Uses extractors from knowledge_base/ingestion/ to pull content,
    then sends to ultimate_rag for processing and storage.
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

    async def initialize(self) -> None:
        """Initialize the task."""
        if not self._config_client:
            config_url = os.getenv("CONFIG_SERVICE_URL", "http://config-service:8080")
            self._config_client = httpx.AsyncClient(base_url=config_url, timeout=30.0)

        if not self._raptor_client:
            raptor_url = os.getenv("RAPTOR_URL", "http://knowledge-base:8000")
            self._raptor_client = httpx.AsyncClient(base_url=raptor_url, timeout=60.0)

        self._initialized = True
        _log("ingestion_task_initialized", org_id=self.org_id, team_node_id=self.team_node_id)

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
                results["sources_processed"].append({"source": "confluence", **source_result})
                results["documents_processed"] += source_result.get("documents", 0)
                results["chunks_created"] += source_result.get("chunks", 0)
            except Exception as e:
                _log("confluence_ingestion_failed", error=str(e))
                results["errors"].append({"source": "confluence", "error": str(e)})

        if self.sources_config.get("github_enabled"):
            try:
                source_result = await self._ingest_github()
                results["sources_processed"].append({"source": "github", **source_result})
                results["documents_processed"] += source_result.get("documents", 0)
                results["chunks_created"] += source_result.get("chunks", 0)
            except Exception as e:
                _log("github_ingestion_failed", error=str(e))
                results["errors"].append({"source": "github", "error": str(e)})

        if self.sources_config.get("incidents_enabled", True):
            try:
                source_result = await self._ingest_incidents()
                results["sources_processed"].append({"source": "incidents", **source_result})
                results["documents_processed"] += source_result.get("documents", 0)
                results["chunks_created"] += source_result.get("chunks", 0)
            except Exception as e:
                _log("incidents_ingestion_failed", error=str(e))
                results["errors"].append({"source": "incidents", "error": str(e)})

        if self.sources_config.get("grafana_enabled"):
            try:
                source_result = await self._ingest_grafana()
                results["sources_processed"].append({"source": "grafana", **source_result})
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
        """Ingest past incidents and postmortems."""
        lookback_days = self.sources_config.get("incidents_lookback_days", 90)
        _log("incidents_ingestion_started", lookback_days=lookback_days)

        documents = 0
        chunks = 0

        try:
            # Fetch incidents from config service (where they're stored)
            # This is a placeholder - real implementation would query incidents
            response = await self._config_client.get(
                f"/api/v1/orgs/{self.org_id}/teams/{self.team_node_id}/incidents",
                params={"days": lookback_days},
            )

            if response.status_code == 200:
                incidents = response.json().get("incidents", [])

                for incident in incidents:
                    # Send to knowledge base for ingestion
                    content = self._format_incident(incident)
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

        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise

        return {"documents": documents, "chunks": chunks, "status": "completed"}

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
