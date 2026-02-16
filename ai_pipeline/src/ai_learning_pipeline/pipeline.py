"""
Self-Learning Pipeline orchestrator.

Coordinates all pipeline tasks based on team configuration.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import httpx


def _log(event: str, **fields) -> None:
    """Structured logging."""
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-learning-pipeline",
        "module": "pipeline",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


@dataclass
class PipelineConfig:
    """Configuration for the pipeline run."""

    # Ingestion settings
    ingestion_enabled: bool = False
    ingestion_sources: Dict[str, Any] = None

    # Teaching settings
    teaching_enabled: bool = True
    auto_approve_threshold: float = 0.8

    # Maintenance settings
    maintenance_enabled: bool = False
    decay_enabled: bool = True
    rebalance_enabled: bool = True
    gap_detection_enabled: bool = True


class SelfLearningPipeline:
    """
    Main orchestrator for the Self-Learning System.

    Coordinates:
    - Knowledge ingestion from configured sources
    - Processing of agent-taught knowledge
    - Maintenance tasks (decay, rebalancing, gap detection)
    """

    def __init__(self, org_id: str, team_node_id: str):
        self.org_id = org_id
        self.team_node_id = team_node_id
        self.config: Optional[PipelineConfig] = None
        self._config_client: Optional[httpx.AsyncClient] = None
        self._raptor_client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize pipeline and load configuration."""
        config_url = os.getenv("CONFIG_SERVICE_URL", "http://config-service:8080")
        raptor_url = os.getenv("RAPTOR_URL", "http://knowledge-base:8000")

        self._config_client = httpx.AsyncClient(
            base_url=config_url,
            timeout=30.0,
        )
        self._raptor_client = httpx.AsyncClient(
            base_url=raptor_url,
            timeout=60.0,
        )

        # Load team configuration
        await self._load_config()

        _log(
            "pipeline_initialized",
            org_id=self.org_id,
            team_node_id=self.team_node_id,
            ingestion_enabled=self.config.ingestion_enabled,
            teaching_enabled=self.config.teaching_enabled,
            maintenance_enabled=self.config.maintenance_enabled,
        )

    async def _load_config(self) -> None:
        """Load team configuration from config service."""
        try:
            # Get effective config via team-facing /me endpoint
            response = await self._config_client.get(
                "/api/v1/config/me",
                headers={
                    "X-Org-Id": self.org_id,
                    "X-Team-Node-Id": self.team_node_id,
                },
            )
            response.raise_for_status()
            data = response.json().get("effective_config", {})

            # Extract self_learning config
            sl_config = data.get("self_learning", {})
            ingestion = sl_config.get("ingestion", {})
            teaching = sl_config.get("teaching", {})
            maintenance = sl_config.get("maintenance", {})

            self.config = PipelineConfig(
                ingestion_enabled=sl_config.get("enabled", False)
                and ingestion.get("enabled", False),
                ingestion_sources=ingestion.get("sources", {}),
                teaching_enabled=sl_config.get("enabled", False)
                and teaching.get("enabled", True),
                auto_approve_threshold=teaching.get("auto_approve_threshold", 0.8),
                maintenance_enabled=sl_config.get("enabled", False)
                and maintenance.get("enabled", False),
                decay_enabled=maintenance.get("decay_enabled", True),
                rebalance_enabled=maintenance.get("rebalance_enabled", True),
                gap_detection_enabled=maintenance.get("gap_detection_enabled", True),
            )

        except Exception as e:
            _log("config_load_failed", error=str(e))
            # Use defaults
            self.config = PipelineConfig()

    async def run_scheduled_tasks(self) -> Dict[str, Any]:
        """Run all scheduled tasks based on configuration."""
        results = {}

        # 1. Knowledge Ingestion
        if self.config.ingestion_enabled:
            try:
                from .tasks.ingestion import KnowledgeIngestionTask

                task = KnowledgeIngestionTask(
                    org_id=self.org_id,
                    team_node_id=self.team_node_id,
                    config_client=self._config_client,
                    raptor_client=self._raptor_client,
                    sources_config=self.config.ingestion_sources,
                )
                await task.initialize()
                results["ingestion"] = await task.run()
            except Exception as e:
                _log("ingestion_task_failed", error=str(e))
                results["ingestion"] = {"error": str(e)}
        else:
            results["ingestion"] = {"skipped": True, "reason": "disabled"}

        # 2. Teaching Processing
        if self.config.teaching_enabled:
            try:
                from .tasks.teaching import TeachingProcessorTask

                task = TeachingProcessorTask(
                    org_id=self.org_id,
                    team_node_id=self.team_node_id,
                    config_client=self._config_client,
                    raptor_client=self._raptor_client,
                    teaching_config={
                        "auto_approve_threshold": self.config.auto_approve_threshold,
                    },
                )
                await task.initialize()
                results["teaching"] = await task.run()
            except Exception as e:
                _log("teaching_task_failed", error=str(e))
                results["teaching"] = {"error": str(e)}
        else:
            results["teaching"] = {"skipped": True, "reason": "disabled"}

        # 3. Maintenance Tasks
        if self.config.maintenance_enabled:
            try:
                from .tasks.maintenance import MaintenanceTask

                task = MaintenanceTask(
                    org_id=self.org_id,
                    team_node_id=self.team_node_id,
                    raptor_client=self._raptor_client,
                    maintenance_config={
                        "decay_enabled": self.config.decay_enabled,
                        "rebalance_enabled": self.config.rebalance_enabled,
                        "gap_detection_enabled": self.config.gap_detection_enabled,
                    },
                )
                await task.initialize()
                results["maintenance"] = await task.run()
            except Exception as e:
                _log("maintenance_task_failed", error=str(e))
                results["maintenance"] = {"error": str(e)}
        else:
            results["maintenance"] = {"skipped": True, "reason": "disabled"}

        return results

    async def close(self) -> None:
        """Clean up resources."""
        if self._config_client:
            await self._config_client.aclose()
        if self._raptor_client:
            await self._raptor_client.aclose()
