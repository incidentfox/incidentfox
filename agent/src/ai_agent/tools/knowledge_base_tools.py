"""
Knowledge Base tools for RAPTOR tree-organized retrieval.

These tools allow agents to query the team's knowledge base
for relevant runbooks, documentation, and past incident learnings.

Enhanced with ultimate_rag capabilities:
- Incident-aware retrieval (prioritizes runbooks and past resolutions)
- Graph-based entity queries (service dependencies, ownership)
- Teaching interface (agents can teach KB new knowledge)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from agents import function_tool

from ..core.logging import get_logger

logger = get_logger(__name__)

# Configuration
RAPTOR_URL = os.getenv("RAPTOR_URL", "http://localhost:8000")
DEFAULT_TREE = os.getenv("RAPTOR_DEFAULT_TREE", "k8s")
ULTIMATE_RAG_ENABLED = os.getenv("ULTIMATE_RAG_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)


def _get_raptor_client():
    """Get HTTP client for RAPTOR API."""
    try:
        import httpx
    except ImportError:
        raise RuntimeError("httpx not installed")

    return httpx.Client(base_url=RAPTOR_URL, timeout=30.0)


@function_tool
def search_knowledge_base(query: str, tree: str = "", top_k: int = 5) -> str:
    """
    Search the knowledge base for relevant information.

    Uses RAPTOR tree-organized retrieval to find relevant:
    - Runbooks and procedures
    - Past incident resolutions
    - System documentation
    - Kubernetes/AWS best practices

    The knowledge base is organized hierarchically:
    - Leaf nodes: Original document chunks
    - Parent nodes: AI-generated summaries of related content

    Use cases:
    - "How do I debug OOMKilled pods?"
    - "What's the procedure for database failover?"
    - "Find runbooks for the affected service"

    Args:
        query: Natural language search query
        tree: Knowledge tree to search (default: k8s). Options: k8s, runbooks, incidents
        top_k: Number of results to return (default: 5)

    Returns:
        JSON with relevant knowledge chunks, scores, and context
    """
    try:
        with _get_raptor_client() as client:
            response = client.post(
                "/api/v1/search",
                json={
                    "query": query,
                    "tree": tree or DEFAULT_TREE,
                    "top_k": top_k,
                    "include_summaries": True,
                },
            )
            response.raise_for_status()
            data = response.json()

            # Format results for agent consumption
            results = []
            for r in data.get("results", []):
                results.append(
                    {
                        "text": r.get("text", ""),
                        "relevance": r.get("score", 0),
                        "is_summary": r.get("is_summary", False),
                        "layer": r.get("layer", 0),
                    }
                )

            logger.info("knowledge_base_search", query=query[:50], results=len(results))

            return json.dumps(
                {
                    "ok": True,
                    "query": query,
                    "tree": data.get("tree", tree or DEFAULT_TREE),
                    "results": results,
                    "total_results": len(results),
                }
            )

    except Exception as e:
        logger.error("knowledge_base_search_failed", error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Knowledge base may not be available. Continue investigation with other tools.",
            }
        )


@function_tool
def ask_knowledge_base(question: str, tree: str = "", top_k: int = 5) -> str:
    """
    Ask a question and get a direct answer from the knowledge base.

    Unlike search_knowledge_base which returns chunks, this tool:
    1. Retrieves relevant context from the RAPTOR tree
    2. Uses an LLM to synthesize an answer
    3. Returns a concise answer with supporting evidence

    Best for:
    - Direct questions: "What causes OOMKilled?"
    - Procedural questions: "How do I restart a service?"
    - Lookup questions: "What's the oncall escalation path?"

    Args:
        question: Natural language question
        tree: Knowledge tree to query (default: k8s)
        top_k: Number of context chunks to use

    Returns:
        JSON with answer and supporting context
    """
    try:
        with _get_raptor_client() as client:
            response = client.post(
                "/api/v1/answer",
                json={
                    "question": question,
                    "tree": tree or DEFAULT_TREE,
                    "top_k": top_k,
                },
            )
            response.raise_for_status()
            data = response.json()

            logger.info("knowledge_base_answer", question=question[:50])

            # Include citations if available (new feature)
            citations = data.get("citations", [])
            citation_sources = [
                c.get("source", "") for c in citations if c.get("source")
            ]

            return json.dumps(
                {
                    "ok": True,
                    "question": question,
                    "answer": data.get("answer", ""),
                    "tree": data.get("tree", tree or DEFAULT_TREE),
                    "context_snippets": data.get("context_chunks", [])[
                        :3
                    ],  # First 3 for brevity
                    "sources": (
                        citation_sources[:5] if citation_sources else []
                    ),  # Top 5 sources
                }
            )

    except Exception as e:
        logger.error("knowledge_base_answer_failed", error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Knowledge base may not be available. Try web_search or llm_call instead.",
            }
        )


@function_tool
def get_knowledge_context(topic: str, tree: str = "", max_chunks: int = 10) -> str:
    """
    Get contextual knowledge for a topic (for augmenting investigation).

    Returns raw chunks that can be used to augment your investigation.
    Unlike ask_knowledge_base, this doesn't generate an answer -
    it just retrieves relevant background knowledge.

    Use cases:
    - Get background on a service before investigating
    - Understand typical architecture patterns
    - Find related past incidents

    Args:
        topic: Topic to get context for
        tree: Knowledge tree (default: k8s)
        max_chunks: Maximum chunks to return

    Returns:
        JSON with knowledge chunks for context
    """
    try:
        with _get_raptor_client() as client:
            response = client.post(
                "/api/v1/retrieve",
                json={
                    "query": topic,
                    "tree": tree or DEFAULT_TREE,
                    "top_k": max_chunks,
                    "collapse_tree": True,
                },
            )
            response.raise_for_status()
            data = response.json()

            chunks = data.get("chunks", [])

            # Combine into context string
            context_parts = []
            for i, chunk in enumerate(chunks[:max_chunks]):
                layer_info = (
                    f"[L{chunk.get('layer', 0)}]" if chunk.get("is_summary") else ""
                )
                context_parts.append(
                    f"--- Chunk {i+1} {layer_info} ---\n{chunk.get('text', '')[:1000]}"
                )

            context = "\n\n".join(context_parts)

            logger.info(
                "knowledge_context_retrieved", topic=topic[:50], chunks=len(chunks)
            )

            return json.dumps(
                {
                    "ok": True,
                    "topic": topic,
                    "tree": data.get("tree", tree or DEFAULT_TREE),
                    "chunks_retrieved": len(chunks),
                    "context": context,
                }
            )

    except Exception as e:
        logger.error("knowledge_context_failed", error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
            }
        )


@function_tool
def list_knowledge_trees() -> str:
    """
    List available knowledge trees.

    Different trees contain different types of knowledge:
    - k8s: Kubernetes documentation and best practices
    - runbooks: Team-specific runbooks and procedures
    - incidents: Past incident learnings and resolutions
    - aws: AWS documentation and patterns

    Returns:
        JSON with available trees
    """
    try:
        with _get_raptor_client() as client:
            response = client.get("/api/v1/trees")
            response.raise_for_status()
            data = response.json()

            return json.dumps(
                {
                    "ok": True,
                    "trees": data.get("trees", []),
                    "default": data.get("default", DEFAULT_TREE),
                    "loaded": data.get("loaded", []),
                }
            )

    except Exception as e:
        logger.error("list_trees_failed", error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "available_trees": ["k8s"],  # Fallback
            }
        )


# =============================================================================
# Enhanced RAG Tools (Ultimate RAG Integration)
# =============================================================================


@function_tool
def search_for_incident(
    symptoms: str,
    affected_service: str = "",
    include_runbooks: bool = True,
    include_past_incidents: bool = True,
    top_k: int = 5,
) -> str:
    """
    Search knowledge base with incident awareness.

    This tool is specifically designed for incident investigation:
    - Prioritizes runbooks matching your symptoms
    - Finds similar past incidents and their resolutions
    - Includes service dependency context
    - Weights recency (recent incidents rank higher)

    ALWAYS use this tool first when investigating an incident.
    It's more effective than general search_knowledge_base for troubleshooting.

    Args:
        symptoms: Description of the issue (error messages, alerts, behavior)
        affected_service: Name of affected service (optional but recommended)
        include_runbooks: Include runbook search (default: True)
        include_past_incidents: Include past incident search (default: True)
        top_k: Number of results to return

    Returns:
        JSON with categorized results: runbooks, past_incidents, service_context

    Example:
        search_for_incident(
            symptoms="OOMKilled pods, memory usage spike",
            affected_service="payment-service"
        )
    """
    try:
        with _get_raptor_client() as client:
            response = client.post(
                "/api/v1/incident-search",
                json={
                    "symptoms": symptoms,
                    "affected_service": affected_service,
                    "include_runbooks": include_runbooks,
                    "include_past_incidents": include_past_incidents,
                    "top_k": top_k,
                },
            )
            response.raise_for_status()
            data = response.json()

            # Structure results by category
            result = {
                "ok": True,
                "symptoms": symptoms,
                "affected_service": affected_service,
                "runbooks": [],
                "past_incidents": [],
                "service_context": [],
            }

            for item in data.get("results", []):
                category = item.get("category", "general")
                if category == "runbook" and include_runbooks:
                    result["runbooks"].append(
                        {
                            "title": item.get("title", ""),
                            "text": item.get("text", "")[:500],
                            "relevance": item.get("score", 0),
                            "runbook_id": item.get("metadata", {}).get("runbook_id"),
                        }
                    )
                elif category == "incident" and include_past_incidents:
                    result["past_incidents"].append(
                        {
                            "incident_id": item.get("metadata", {}).get("incident_id"),
                            "summary": item.get("text", "")[:500],
                            "resolution": item.get("metadata", {}).get(
                                "resolution", ""
                            ),
                            "relevance": item.get("score", 0),
                        }
                    )
                else:
                    result["service_context"].append(
                        {
                            "text": item.get("text", "")[:500],
                            "relevance": item.get("score", 0),
                        }
                    )

            logger.info(
                "incident_search",
                symptoms=symptoms[:50],
                service=affected_service,
                runbooks=len(result["runbooks"]),
                past_incidents=len(result["past_incidents"]),
            )

            return json.dumps(result)

    except Exception as e:
        logger.error("incident_search_failed", error=str(e))

        # Fallback to regular search
        return search_knowledge_base(
            query=f"troubleshoot {symptoms} {affected_service}".strip(),
            tree="runbooks",
            top_k=top_k,
        )


@function_tool
def query_service_graph(
    entity_name: str,
    query_type: str = "dependencies",
    max_hops: int = 2,
) -> str:
    """
    Query the knowledge graph for service relationships.

    The knowledge graph contains:
    - Service dependencies (what depends on what)
    - Team ownership (who owns each service)
    - Runbook linkages (which runbooks apply to which services)
    - Incident history (past incidents per service)

    Query types:
    - dependencies: What does this service depend on?
    - dependents: What services depend on this?
    - owner: Who owns this service?
    - runbooks: What runbooks exist for this service?
    - incidents: Recent incidents for this service
    - blast_radius: What's affected if this service fails?

    Args:
        entity_name: Name of the service/entity to query
        query_type: Type of relationship query
        max_hops: How many relationship hops to traverse (1-3)

    Returns:
        JSON with graph query results

    Example:
        query_service_graph("payment-service", query_type="blast_radius")
    """
    try:
        with _get_raptor_client() as client:
            response = client.post(
                "/api/v1/graph/query",
                json={
                    "entity_name": entity_name,
                    "query_type": query_type,
                    "max_hops": min(max_hops, 3),  # Cap at 3 hops
                },
            )
            response.raise_for_status()
            data = response.json()

            result = {
                "ok": True,
                "entity": entity_name,
                "query_type": query_type,
            }

            if query_type == "dependencies":
                result["dependencies"] = data.get("dependencies", [])
                result["hint"] = "These are services that this entity depends on"
            elif query_type == "dependents":
                result["dependents"] = data.get("dependents", [])
                result["hint"] = "These services will be affected if this entity fails"
            elif query_type == "owner":
                result["owner"] = data.get("owner", {})
                result["contact"] = data.get("contact", "")
            elif query_type == "runbooks":
                result["runbooks"] = data.get("runbooks", [])
            elif query_type == "incidents":
                result["incidents"] = data.get("incidents", [])
            elif query_type == "blast_radius":
                result["blast_radius"] = data.get("blast_radius", {})
                result["affected_services"] = data.get("affected_services", [])
                result["estimated_impact"] = data.get("estimated_impact", "unknown")

            logger.info(
                "graph_query",
                entity=entity_name,
                query_type=query_type,
            )

            return json.dumps(result)

    except Exception as e:
        logger.error("graph_query_failed", error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Knowledge graph may not be available. Try search_knowledge_base instead.",
            }
        )


@function_tool
def teach_knowledge_base(
    content: str,
    knowledge_type: str = "procedural",
    source: str = "agent_learning",
    confidence: float = 0.7,
    related_services: str = "",
    context: str = "",
) -> str:
    """
    Teach the knowledge base new information learned during investigation.

    IMPORTANT: Call this tool after successfully resolving an incident to
    capture the learning for future investigations.

    The knowledge base learns:
    - New troubleshooting procedures
    - Root cause patterns
    - Service behavior quirks
    - Resolution steps that worked

    Knowledge types:
    - procedural: How to do something (runbook-like)
    - factual: Facts about systems (config, limits, etc.)
    - temporal: Time-bound info (incident resolutions, changes)
    - relational: Relationships between services/teams

    Args:
        content: The knowledge to teach (should be detailed and specific)
        knowledge_type: Type of knowledge (procedural, factual, temporal, relational)
        source: Where this knowledge came from
        confidence: How confident you are (0.0-1.0)
        related_services: Comma-separated list of related service names
        context: Additional context (e.g., incident ID, task description)

    Returns:
        JSON with teaching result (created, merged, duplicate, or pending_review)

    Example:
        teach_knowledge_base(
            content="When payment-service shows OOMKilled, first check for memory leaks in the cache layer. The cache can grow unbounded if TTL is not set. Fix by adding CACHE_TTL=3600 to the environment.",
            knowledge_type="procedural",
            related_services="payment-service,cache-service",
            context="Learned from incident INC-2024-0123"
        )
    """
    # Validate content
    content = content.strip()
    if len(content) < 50:
        return json.dumps(
            {
                "ok": False,
                "error": "Content too short. Please provide detailed, specific knowledge (at least 50 characters).",
                "hint": "Include: what the problem was, how to identify it, and how to fix it.",
            }
        )

    if knowledge_type not in ["procedural", "factual", "temporal", "relational"]:
        knowledge_type = "procedural"

    services_list = [s.strip() for s in related_services.split(",") if s.strip()]

    try:
        with _get_raptor_client() as client:
            response = client.post(
                "/api/v1/teach",
                json={
                    "content": content,
                    "knowledge_type": knowledge_type,
                    "source": source,
                    "confidence": min(max(confidence, 0.0), 1.0),
                    "related_entities": services_list,
                    "learned_from": "agent_investigation",
                    "task_context": context,
                },
            )
            response.raise_for_status()
            data = response.json()

            result = {
                "ok": True,
                "status": data.get("status", "unknown"),
                "action": data.get("action", ""),
                "node_id": data.get("node_id"),
            }

            # Add helpful message based on status
            status = data.get("status", "")
            if status == "created":
                result["message"] = (
                    "New knowledge successfully added to the knowledge base."
                )
            elif status == "merged":
                result["message"] = "Knowledge merged with existing similar content."
            elif status == "duplicate":
                result["message"] = (
                    "This knowledge already exists in the knowledge base."
                )
            elif status == "pending_review":
                result["message"] = "Knowledge queued for human review before adding."
                result["needs_review"] = True
            elif status == "contradiction":
                result["message"] = (
                    "This may contradict existing knowledge. Queued for review."
                )
                result["needs_review"] = True

            logger.info(
                "knowledge_teaching",
                status=status,
                knowledge_type=knowledge_type,
                content_length=len(content),
            )

            return json.dumps(result)

    except Exception as e:
        logger.error("teaching_failed", error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Teaching service may not be available. The knowledge was not saved.",
            }
        )


@function_tool
def find_similar_past_incidents(
    symptoms: str,
    service: str = "",
    limit: int = 5,
) -> str:
    """
    Find past incidents with similar symptoms.

    This is specifically for finding "have we seen this before?" patterns.
    Returns past incidents that had similar symptoms, along with their
    root causes and resolutions.

    Args:
        symptoms: Current symptoms to match against past incidents
        service: Optionally filter by service name
        limit: Maximum number of similar incidents to return

    Returns:
        JSON with similar past incidents and their resolutions

    Example:
        find_similar_past_incidents(
            symptoms="High latency, connection timeouts to database",
            service="user-service"
        )
    """
    try:
        with _get_raptor_client() as client:
            response = client.post(
                "/api/v1/similar-incidents",
                json={
                    "symptoms": symptoms,
                    "service": service,
                    "limit": limit,
                },
            )
            response.raise_for_status()
            data = response.json()

            incidents = []
            for inc in data.get("incidents", []):
                incidents.append(
                    {
                        "incident_id": inc.get("incident_id"),
                        "date": inc.get("date"),
                        "similarity": inc.get("similarity", 0),
                        "symptoms": inc.get("symptoms", ""),
                        "root_cause": inc.get("root_cause", ""),
                        "resolution": inc.get("resolution", ""),
                        "services_affected": inc.get("services_affected", []),
                    }
                )

            result = {
                "ok": True,
                "query_symptoms": symptoms,
                "similar_incidents": incidents,
                "total_found": len(incidents),
            }

            if not incidents:
                result["hint"] = (
                    "No similar past incidents found. This may be a new issue type."
                )

            logger.info(
                "similar_incidents_search",
                symptoms=symptoms[:50],
                found=len(incidents),
            )

            return json.dumps(result)

    except Exception as e:
        logger.error("similar_incidents_failed", error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Could not search past incidents. Try search_knowledge_base with 'incidents' tree.",
            }
        )
