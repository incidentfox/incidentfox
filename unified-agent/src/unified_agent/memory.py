"""
Memory Layer for IncidentFox Unified Agent.

Provides persistent investigation memory using mem0. Memories are:
- Searched before investigations (context injection into prompt)
- Saved after investigations (automatic fact extraction from results)

Feature-gated via MEMORY_ENABLED=true env var.
All operations are fail-safe -- memory failures never block investigations.
"""

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Singleton instance
_memory_manager: Optional["MemoryManager"] = None


class MemoryManager:
    """
    Wraps mem0.Memory for async-safe investigation memory.

    mem0 operations are synchronous, so all public methods use
    asyncio.to_thread() to avoid blocking the event loop.

    Scoping model:
    - user_id = "{tenant_id}/{team_id}" (tenant isolation)
    - agent_id = "sre-investigator"
    - run_id = thread_id (links memories to investigation threads)
    """

    def __init__(self):
        from mem0 import Memory

        config = self._build_config()
        self._memory = Memory.from_config(config)
        self._search_limit = int(os.getenv("MEMORY_SEARCH_LIMIT", "5"))
        logger.info("[MEMORY] MemoryManager initialized")

    def _build_config(self) -> dict:
        """Build mem0 config from environment variables."""
        config: dict[str, Any] = {"version": "v1.1"}

        # LLM config (for fact extraction)
        llm_provider = os.getenv("MEMORY_LLM_PROVIDER", "anthropic")
        llm_model = os.getenv("MEMORY_LLM_MODEL", "claude-haiku-4-5-20251001")
        llm_api_key = os.getenv("MEMORY_LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY", "")

        config["llm"] = {
            "provider": llm_provider,
            "config": {
                "model": llm_model,
                "temperature": 0.1,
                "api_key": llm_api_key,
            },
        }

        # Embedder config
        embedding_provider = os.getenv("MEMORY_EMBEDDING_PROVIDER", "openai")
        embedding_model = os.getenv("MEMORY_EMBEDDING_MODEL", "text-embedding-3-small")
        embedding_api_key = os.getenv("MEMORY_EMBEDDING_API_KEY") or os.getenv(
            "OPENAI_API_KEY", ""
        )

        config["embedder"] = {
            "provider": embedding_provider,
            "config": {
                "model": embedding_model,
                "api_key": embedding_api_key,
            },
        }

        # Vector store config
        vector_store = os.getenv("MEMORY_VECTOR_STORE", "qdrant")
        collection_name = os.getenv("MEMORY_COLLECTION_NAME", "sre_memories")

        if vector_store == "pgvector":
            config["vector_store"] = {
                "provider": "pgvector",
                "config": {
                    "host": os.getenv("MEMORY_DB_HOST", "localhost"),
                    "port": int(os.getenv("MEMORY_DB_PORT", "5432")),
                    "dbname": os.getenv("MEMORY_DB_NAME", "mem0"),
                    "user": os.getenv("MEMORY_DB_USER", "mem0"),
                    "password": os.getenv("MEMORY_DB_PASSWORD", ""),
                    "collection_name": collection_name,
                },
            }
        else:
            # Default: Qdrant (embedded mode if no host specified)
            qdrant_config: dict[str, Any] = {"collection_name": collection_name}
            qdrant_host = os.getenv("MEMORY_QDRANT_HOST")
            if qdrant_host:
                qdrant_config["host"] = qdrant_host
                qdrant_config["port"] = int(os.getenv("MEMORY_QDRANT_PORT", "6333"))
            else:
                # Embedded mode - local storage
                qdrant_config["path"] = os.getenv("MEMORY_QDRANT_PATH", "/tmp/qdrant_mem0")

            config["vector_store"] = {
                "provider": "qdrant",
                "config": qdrant_config,
            }

        logger.info(
            f"[MEMORY] Config: llm={llm_provider}/{llm_model}, "
            f"embedder={embedding_provider}/{embedding_model}, "
            f"vector_store={vector_store}"
        )
        return config

    @staticmethod
    def _make_user_id(tenant_id: str, team_id: str) -> str:
        return f"{tenant_id}/{team_id}"

    async def search(
        self,
        query: str,
        tenant_id: str,
        team_id: str,
        timeout: float = 2.0,
    ) -> list[dict]:
        """
        Search for relevant memories.

        Returns list of memory dicts or empty list on failure.
        Times out after `timeout` seconds to avoid blocking investigations.
        """
        try:
            user_id = self._make_user_id(tenant_id, team_id)
            results = await asyncio.wait_for(
                asyncio.to_thread(
                    self._memory.search,
                    query,
                    user_id=user_id,
                    limit=self._search_limit,
                ),
                timeout=timeout,
            )
            memories = results.get("results", []) if isinstance(results, dict) else results
            logger.info(
                f"[MEMORY] Search returned {len(memories)} memories for {user_id}"
            )
            return memories
        except asyncio.TimeoutError:
            logger.warning(f"[MEMORY] Search timed out after {timeout}s")
            return []
        except Exception as e:
            logger.warning(f"[MEMORY] Search failed: {e}")
            return []

    async def save(
        self,
        prompt: str,
        result_text: str,
        tenant_id: str,
        team_id: str,
        thread_id: str,
    ) -> None:
        """
        Save investigation results as memories (fire-and-forget).

        Uses mem0's fact extraction to automatically extract key facts
        from the investigation prompt + result pair.
        """
        try:
            user_id = self._make_user_id(tenant_id, team_id)

            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": result_text},
            ]

            await asyncio.to_thread(
                self._memory.add,
                messages,
                user_id=user_id,
                agent_id="sre-investigator",
                run_id=thread_id,
            )
            logger.info(f"[MEMORY] Saved memories for thread {thread_id} ({user_id})")
        except Exception as e:
            logger.warning(f"[MEMORY] Save failed for thread {thread_id}: {e}")


def format_memory_context(memories: list[dict]) -> str:
    """
    Format memories as XML context block for prompt injection.

    Returns empty string if no memories.
    """
    if not memories:
        return ""

    lines = []
    for i, mem in enumerate(memories, 1):
        # mem0 returns {"memory": "...", "score": 0.9, ...} or {"text": "..."}
        text = mem.get("memory") or mem.get("text") or str(mem)
        lines.append(f"  {i}. {text}")

    memory_block = "\n".join(lines)
    return (
        "<memory_context>\n"
        "The following are relevant findings from previous investigations.\n"
        "Use them as context but always verify current state -- systems change.\n"
        "\n"
        f"{memory_block}\n"
        "</memory_context>\n\n"
    )


def get_memory_manager() -> Optional[MemoryManager]:
    """
    Get the singleton MemoryManager instance.

    Returns None if MEMORY_ENABLED is not 'true'.
    Initialization failures return None (fail-safe).
    """
    global _memory_manager

    if os.getenv("MEMORY_ENABLED", "false").lower() != "true":
        return None

    if _memory_manager is None:
        try:
            _memory_manager = MemoryManager()
        except Exception as e:
            logger.error(f"[MEMORY] Failed to initialize MemoryManager: {e}")
            return None

    return _memory_manager
