"""
Knowledge Teaching Processor Task.

Processes pending knowledge teachings from agents:
- Fetches pending teachings from config service
- Checks for contradictions with existing knowledge
- Auto-approves high-confidence, non-contradicting teachings
- Sends approved teachings to the knowledge base
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

import httpx


def _log(event: str, **fields) -> None:
    """Structured logging."""
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-learning-pipeline",
        "module": "tasks.teaching",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


class TeachingProcessorTask:
    """
    Processes pending knowledge teachings from agents.

    Workflow:
    1. Fetch pending teachings from config service
    2. For each teaching:
       - Check similarity with existing knowledge
       - Detect potential contradictions
       - Auto-approve if high confidence and no contradictions
       - Send approved teachings to knowledge base
    3. Update teaching status in config service
    """

    def __init__(
        self,
        org_id: str,
        team_node_id: str,
        config_client: Optional[httpx.AsyncClient] = None,
        raptor_client: Optional[httpx.AsyncClient] = None,
        teaching_config: Optional[Dict[str, Any]] = None,
    ):
        self.org_id = org_id
        self.team_node_id = team_node_id
        self._config_client = config_client
        self._raptor_client = raptor_client
        self.teaching_config = teaching_config or {}
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
        _log(
            "teaching_task_initialized",
            org_id=self.org_id,
            team_node_id=self.team_node_id,
        )

    async def run(self) -> Dict[str, Any]:
        """Run the teaching processor task."""
        if not self._initialized:
            await self.initialize()

        results = {
            "started_at": datetime.utcnow().isoformat(),
            "teachings_processed": 0,
            "auto_approved": 0,
            "pending_review": 0,
            "contradictions_found": 0,
            "errors": [],
        }

        auto_approve_threshold = self.teaching_config.get("auto_approve_threshold", 0.8)
        require_review_for_contradictions = self.teaching_config.get(
            "require_review_for_contradictions", True
        )
        max_pending = self.teaching_config.get("max_pending_per_day", 50)

        try:
            # Fetch pending teachings
            response = await self._config_client.get(
                f"/api/v1/orgs/{self.org_id}/teams/{self.team_node_id}/pending-teachings",
                params={"status": "pending", "limit": max_pending},
            )

            if response.status_code != 200:
                _log("fetch_teachings_failed", status_code=response.status_code)
                return results

            teachings = response.json().get("teachings", [])
            _log("teachings_fetched", count=len(teachings))

            for teaching in teachings:
                try:
                    processed = await self._process_teaching(
                        teaching,
                        auto_approve_threshold,
                        require_review_for_contradictions,
                    )
                    results["teachings_processed"] += 1

                    if processed.get("auto_approved"):
                        results["auto_approved"] += 1
                    elif processed.get("pending_review"):
                        results["pending_review"] += 1

                    if processed.get("contradiction_found"):
                        results["contradictions_found"] += 1

                except Exception as e:
                    _log(
                        "teaching_processing_failed",
                        teaching_id=teaching.get("id"),
                        error=str(e),
                    )
                    results["errors"].append(
                        {
                            "teaching_id": teaching.get("id"),
                            "error": str(e),
                        }
                    )

        except Exception as e:
            _log("teaching_task_failed", error=str(e))
            results["errors"].append({"error": str(e)})

        results["completed_at"] = datetime.utcnow().isoformat()

        _log(
            "teaching_task_completed",
            teachings_processed=results["teachings_processed"],
            auto_approved=results["auto_approved"],
            pending_review=results["pending_review"],
            contradictions_found=results["contradictions_found"],
        )

        return results

    async def _process_teaching(
        self,
        teaching: Dict[str, Any],
        auto_approve_threshold: float,
        require_review_for_contradictions: bool,
    ) -> Dict[str, Any]:
        """Process a single pending teaching."""
        teaching_id = teaching["id"]
        content = teaching["content"]
        confidence = teaching.get("confidence", 0.7)

        result = {
            "auto_approved": False,
            "pending_review": False,
            "contradiction_found": False,
        }

        # Check similarity with existing knowledge
        similarity_result = await self._check_similarity(content)
        similar_node_id = similarity_result.get("most_similar_node_id")
        similarity_score = similarity_result.get("similarity_score", 0.0)
        is_contradiction = similarity_result.get("is_potential_contradiction", False)

        if is_contradiction:
            result["contradiction_found"] = True

        # Update teaching with similarity info
        await self._update_teaching_similarity(
            teaching_id,
            similar_node_id,
            similarity_score,
            is_contradiction,
        )

        # Decide on auto-approval
        should_auto_approve = confidence >= auto_approve_threshold and not (
            is_contradiction and require_review_for_contradictions
        )

        if should_auto_approve:
            # Send to knowledge base
            ingest_result = await self._ingest_teaching(teaching)

            if ingest_result.get("success"):
                await self._update_teaching_status(
                    teaching_id,
                    status="auto_approved",
                    created_node_id=ingest_result.get("node_id"),
                )
                result["auto_approved"] = True
            else:
                result["pending_review"] = True
        else:
            result["pending_review"] = True

        return result

    async def _check_similarity(self, content: str) -> Dict[str, Any]:
        """Check similarity of content with existing knowledge."""
        try:
            response = await self._raptor_client.post(
                "/api/v1/search",
                json={
                    "query": content,
                    "top_k": 5,
                    "include_scores": True,
                },
            )

            if response.status_code != 200:
                return {}

            results = response.json().get("results", [])
            if not results:
                return {}

            top_result = results[0]
            similarity_score = top_result.get("score", 0.0)

            # Check for potential contradiction (high similarity but different meaning)
            # This is a simplified heuristic - real implementation would use LLM
            is_potential_contradiction = (
                similarity_score > 0.7
                and self._detect_contradiction_heuristic(
                    content, top_result.get("content", "")
                )
            )

            return {
                "most_similar_node_id": top_result.get("node_id"),
                "similarity_score": similarity_score,
                "is_potential_contradiction": is_potential_contradiction,
            }

        except Exception as e:
            _log("similarity_check_failed", error=str(e))
            return {}

    def _detect_contradiction_heuristic(
        self, new_content: str, existing_content: str
    ) -> bool:
        """Simple heuristic to detect potential contradictions."""
        # Look for negation patterns that might indicate contradiction
        negation_words = [
            "not",
            "never",
            "don't",
            "doesn't",
            "shouldn't",
            "cannot",
            "won't",
        ]
        new_lower = new_content.lower()
        existing_lower = existing_content.lower()

        # If one has negation and other doesn't for similar topics, flag for review
        new_has_negation = any(word in new_lower for word in negation_words)
        existing_has_negation = any(word in existing_lower for word in negation_words)

        return new_has_negation != existing_has_negation

    async def _update_teaching_similarity(
        self,
        teaching_id: str,
        similar_node_id: Optional[int],
        similarity_score: float,
        is_contradiction: bool,
    ) -> None:
        """Update teaching with similarity analysis results."""
        try:
            await self._config_client.patch(
                f"/api/v1/pending-teachings/{teaching_id}",
                json={
                    "similar_node_id": similar_node_id,
                    "similarity_score": similarity_score,
                    "is_potential_contradiction": is_contradiction,
                },
            )
        except Exception as e:
            _log(
                "update_teaching_similarity_failed",
                teaching_id=teaching_id,
                error=str(e),
            )

    async def _ingest_teaching(self, teaching: Dict[str, Any]) -> Dict[str, Any]:
        """Send approved teaching to knowledge base."""
        try:
            response = await self._raptor_client.post(
                "/api/v1/teach",
                json={
                    "content": teaching["content"],
                    "knowledge_type": teaching.get("knowledge_type", "procedural"),
                    "metadata": {
                        "source": "agent_teaching",
                        "teaching_id": teaching["id"],
                        "correlation_id": teaching.get("correlation_id"),
                        "agent_name": teaching.get("agent_name"),
                        "confidence": teaching.get("confidence"),
                        "services": teaching.get("related_services", []),
                    },
                },
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "success": True,
                    "node_id": result.get("node_id"),
                }
            else:
                return {"success": False, "error": f"Status {response.status_code}"}

        except Exception as e:
            _log("ingest_teaching_failed", teaching_id=teaching.get("id"), error=str(e))
            return {"success": False, "error": str(e)}

    async def _update_teaching_status(
        self,
        teaching_id: str,
        status: str,
        created_node_id: Optional[int] = None,
        merged_with_node_id: Optional[int] = None,
    ) -> None:
        """Update teaching status in config service."""
        try:
            payload = {
                "status": status,
                "applied_at": (
                    datetime.utcnow().isoformat()
                    if status in ("auto_approved", "approved")
                    else None
                ),
            }
            if created_node_id:
                payload["created_node_id"] = created_node_id
            if merged_with_node_id:
                payload["merged_with_node_id"] = merged_with_node_id

            await self._config_client.patch(
                f"/api/v1/pending-teachings/{teaching_id}",
                json=payload,
            )
        except Exception as e:
            _log("update_teaching_status_failed", teaching_id=teaching_id, error=str(e))
