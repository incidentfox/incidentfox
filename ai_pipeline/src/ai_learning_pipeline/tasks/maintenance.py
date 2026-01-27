"""
Knowledge Base Maintenance Task.

Performs maintenance operations on the knowledge base:
- Tree health monitoring
- Knowledge decay (reduce weight of stale knowledge)
- Tree rebalancing
- Gap detection
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
        "module": "tasks.maintenance",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


class MaintenanceTask:
    """
    Performs maintenance operations on the knowledge base.

    Operations:
    - Tree health check: Verify tree integrity and statistics
    - Knowledge decay: Reduce relevance of stale knowledge
    - Tree rebalancing: Optimize tree structure for query performance
    - Gap detection: Identify areas needing more knowledge
    """

    def __init__(
        self,
        org_id: str,
        team_node_id: str,
        raptor_client: Optional[httpx.AsyncClient] = None,
        maintenance_config: Optional[Dict[str, Any]] = None,
    ):
        self.org_id = org_id
        self.team_node_id = team_node_id
        self._raptor_client = raptor_client
        self.maintenance_config = maintenance_config or {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the task."""
        if not self._raptor_client:
            raptor_url = os.getenv("RAPTOR_URL", "http://knowledge-base:8000")
            self._raptor_client = httpx.AsyncClient(base_url=raptor_url, timeout=120.0)

        self._initialized = True
        _log(
            "maintenance_task_initialized",
            org_id=self.org_id,
            team_node_id=self.team_node_id,
        )

    async def run(self) -> Dict[str, Any]:
        """Run the maintenance task."""
        if not self._initialized:
            await self.initialize()

        results = {
            "started_at": datetime.utcnow().isoformat(),
            "operations": [],
            "errors": [],
        }

        # Run enabled maintenance operations
        if self.maintenance_config.get("decay_enabled", True):
            try:
                decay_result = await self._run_decay()
                results["operations"].append({"operation": "decay", **decay_result})
            except Exception as e:
                _log("decay_operation_failed", error=str(e))
                results["errors"].append({"operation": "decay", "error": str(e)})

        if self.maintenance_config.get("rebalance_enabled", True):
            try:
                rebalance_result = await self._run_rebalance()
                results["operations"].append(
                    {"operation": "rebalance", **rebalance_result}
                )
            except Exception as e:
                _log("rebalance_operation_failed", error=str(e))
                results["errors"].append({"operation": "rebalance", "error": str(e)})

        if self.maintenance_config.get("gap_detection_enabled", True):
            try:
                gap_result = await self._run_gap_detection()
                results["operations"].append(
                    {"operation": "gap_detection", **gap_result}
                )
            except Exception as e:
                _log("gap_detection_failed", error=str(e))
                results["errors"].append(
                    {"operation": "gap_detection", "error": str(e)}
                )

        # Always run health check
        try:
            health_result = await self._run_health_check()
            results["operations"].append({"operation": "health_check", **health_result})
        except Exception as e:
            _log("health_check_failed", error=str(e))
            results["errors"].append({"operation": "health_check", "error": str(e)})

        results["completed_at"] = datetime.utcnow().isoformat()

        _log(
            "maintenance_completed",
            operations_count=len(results["operations"]),
            errors_count=len(results["errors"]),
        )

        return results

    async def _run_decay(self) -> Dict[str, Any]:
        """Apply knowledge decay to reduce relevance of stale nodes."""
        half_life_days = self.maintenance_config.get("decay_half_life_days", 180)
        _log("decay_started", half_life_days=half_life_days)

        try:
            response = await self._raptor_client.post(
                "/maintenance/decay",
                json={
                    "half_life_days": half_life_days,
                    "min_weight": 0.1,  # Don't decay below this threshold
                },
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "status": "completed",
                    "nodes_updated": result.get("nodes_updated", 0),
                    "avg_decay_applied": result.get("avg_decay", 0),
                }
            else:
                return {"status": "failed", "error": f"Status {response.status_code}"}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Endpoint not implemented yet
                return {"status": "not_implemented"}
            raise

    async def _run_rebalance(self) -> Dict[str, Any]:
        """Rebalance tree structure for optimal query performance."""
        _log("rebalance_started")

        try:
            response = await self._raptor_client.post(
                "/maintenance/rebalance",
                json={
                    "target_cluster_size": 10,
                    "max_tree_depth": 5,
                },
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "status": "completed",
                    "nodes_moved": result.get("nodes_moved", 0),
                    "clusters_merged": result.get("clusters_merged", 0),
                    "clusters_split": result.get("clusters_split", 0),
                }
            else:
                return {"status": "failed", "error": f"Status {response.status_code}"}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"status": "not_implemented"}
            raise

    async def _run_gap_detection(self) -> Dict[str, Any]:
        """Detect knowledge gaps by analyzing query patterns and coverage."""
        _log("gap_detection_started")

        try:
            response = await self._raptor_client.post(
                "/maintenance/detect-gaps",
                json={
                    "analyze_query_logs": True,
                    "min_query_count": 5,  # Only flag gaps seen in 5+ queries
                },
            )

            if response.status_code == 200:
                result = response.json()
                gaps = result.get("gaps", [])
                return {
                    "status": "completed",
                    "gaps_found": len(gaps),
                    "top_gaps": gaps[:10],  # Return top 10 gaps
                }
            else:
                return {"status": "failed", "error": f"Status {response.status_code}"}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"status": "not_implemented"}
            raise

    async def _run_health_check(self) -> Dict[str, Any]:
        """Check overall health of the knowledge base."""
        _log("health_check_started")

        try:
            # Get tree statistics
            response = await self._raptor_client.get("/api/v1/trees")

            if response.status_code != 200:
                return {"status": "failed", "error": f"Status {response.status_code}"}

            trees = response.json().get("trees", [])

            health_data = {
                "status": "completed",
                "trees_count": len(trees),
                "total_nodes": 0,
                "total_documents": 0,
                "avg_tree_depth": 0,
                "trees": [],
            }

            depths = []
            for tree in trees:
                tree_stats = {
                    "tree_id": tree.get("id"),
                    "name": tree.get("name"),
                    "node_count": tree.get("node_count", 0),
                    "document_count": tree.get("document_count", 0),
                    "depth": tree.get("depth", 0),
                    "last_updated": tree.get("last_updated"),
                }
                health_data["trees"].append(tree_stats)
                health_data["total_nodes"] += tree_stats["node_count"]
                health_data["total_documents"] += tree_stats["document_count"]
                if tree_stats["depth"] > 0:
                    depths.append(tree_stats["depth"])

            if depths:
                health_data["avg_tree_depth"] = sum(depths) / len(depths)

            return health_data

        except Exception as e:
            return {"status": "failed", "error": str(e)}
