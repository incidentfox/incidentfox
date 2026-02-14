"""
Dynamic model catalog using LiteLLM's model database.

Uses litellm.model_cost as the authoritative source for chat models compatible
with the acompletion endpoint, enriched with descriptions from OpenRouter.
"""

import json
import logging
import os
import re
import threading
import time
import urllib.request
from typing import Dict, List

import litellm

logger = logging.getLogger(__name__)

# Cache TTL: 1 hour
_CACHE_TTL = 3600

# Map our provider IDs to (litellm_provider, output_prefix)
# litellm_provider: value of "litellm_provider" in litellm.model_cost
# output_prefix: prefix for model IDs in our system (passed to credential-resolver)
_PROVIDER_CONFIG = {
    "anthropic": ("anthropic", ""),
    "openai": ("openai", "openai"),
    "gemini": ("gemini", "gemini"),
    "deepseek": ("deepseek", "deepseek"),
    "xai": ("xai", "xai"),
    "mistral": ("mistral", "mistral"),
    "cohere": ("cohere_chat", "cohere"),
    "qwen": ("dashscope", "qwen"),
    "groq": ("groq", "groq"),
    "together_ai": ("together_ai", "together_ai"),
    "fireworks_ai": ("fireworks_ai", "fireworks_ai"),
    "minimax": ("minimax", "minimax"),
    "moonshot": ("moonshot", "moonshot"),
    "zai": ("zai", "zai"),
}

# Providers whose models come from OpenRouter (not in litellm natively).
# Maps provider_id -> OpenRouter org prefix for filtering.
_OPENROUTER_PROVIDERS = {
    "arcee": "arcee-ai",
}

# Regex to extract a date like 2025-08-07 from model names
_DATE_RE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")


def _extract_date_score(name: str) -> int:
    """Extract a YYYYMMDD int from a model name for sorting, or 0 if none found."""
    m = _DATE_RE.search(name)
    if m:
        return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))
    return 0


def _fetch_json(url: str, headers: dict, timeout: int = 10) -> dict:
    """Fetch JSON from URL."""
    req = urllib.request.Request(
        url, headers={**headers, "User-Agent": "IncidentFox/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class ModelCatalog:
    """Model catalog: LiteLLM model_cost + OpenRouter descriptions."""

    def __init__(self):
        self._or_cache: List[Dict] = []  # Raw OpenRouter models
        self._or_descriptions: Dict[str, str] = {}  # raw_model_name -> description
        self._or_created: Dict[str, int] = {}  # raw_model_name -> created timestamp
        self._or_last_fetch: float = 0
        self._lock = threading.Lock()

    # --- OpenRouter (descriptions only) ---

    def _fetch_openrouter(self) -> List[Dict]:
        """Fetch models from OpenRouter for descriptions."""
        try:
            headers = {}
            api_key = os.getenv("OPENROUTER_API_KEY", "")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            data = _fetch_json("https://openrouter.ai/api/v1/models", headers)
            models = data.get("data", [])
            logger.info(f"Fetched {len(models)} models from OpenRouter")
            return models
        except Exception as e:
            logger.warning(f"Failed to fetch OpenRouter models: {e}")
            return []

    def _ensure_or_cache(self):
        """Refresh OpenRouter cache if stale."""
        now = time.time()
        if now - self._or_last_fetch > _CACHE_TTL:
            with self._lock:
                if time.time() - self._or_last_fetch > _CACHE_TTL:
                    self._or_cache = self._fetch_openrouter()
                    self._or_descriptions = {}
                    self._or_created = {}
                    for m in self._or_cache:
                        or_id = m.get("id", "")
                        desc = m.get("description", "")
                        created = m.get("created", 0)
                        if "/" in or_id:
                            raw = or_id.split("/", 1)[1]
                            if desc:
                                self._or_descriptions[raw] = desc
                            if created:
                                self._or_created[raw] = created
                            # Also store dash variant (OpenRouter uses dots: 3.5, litellm dashes: 3-5)
                            dash = raw.replace(".", "-")
                            if dash != raw:
                                if desc:
                                    self._or_descriptions[dash] = desc
                                if created:
                                    self._or_created[dash] = created
                    self._or_last_fetch = time.time()

    # --- Public API ---

    def get_models_for_provider(
        self,
        provider_id: str,
        query: str = "",
        limit: int = 100,
    ) -> List[Dict]:
        """Get models for a provider, filtered by query."""
        self._ensure_or_cache()

        if provider_id == "openrouter":
            return self._get_openrouter_models(query, limit)

        # Providers sourced from OpenRouter (not in litellm natively)
        or_org = _OPENROUTER_PROVIDERS.get(provider_id)
        if or_org:
            return self._get_or_provider_models(provider_id, or_org, query, limit)

        config = _PROVIDER_CONFIG.get(provider_id)
        if not config:
            return []

        litellm_provider, output_prefix = config
        seen = set()
        results = []

        for model_key, info in litellm.model_cost.items():
            if info.get("litellm_provider") != litellm_provider:
                continue
            if info.get("mode") != "chat":
                continue
            # Skip fine-tune templates
            if model_key.startswith("ft:"):
                continue

            # Extract raw model name (strip litellm prefix if present)
            if "/" in model_key:
                raw_name = model_key.split("/", 1)[1]
            else:
                raw_name = model_key

            # Build our system's model ID
            model_id = f"{output_prefix}/{raw_name}" if output_prefix else raw_name

            # Deduplicate (some models have both prefixed and non-prefixed entries)
            if model_id in seen:
                continue
            seen.add(model_id)

            if query:
                q = query.lower()
                if q not in raw_name.lower() and q not in model_id.lower():
                    continue

            description = self._or_descriptions.get(raw_name, "")
            created = self._or_created.get(raw_name, 0)
            # Try prefix match (e.g., "claude-3-5-haiku" matches "claude-3-5-haiku-20241022")
            if not description or not created:
                for or_key in self._or_descriptions:
                    if raw_name.startswith(or_key):
                        if not description and self._or_descriptions.get(or_key):
                            description = self._or_descriptions[or_key]
                        if not created and self._or_created.get(or_key):
                            created = self._or_created[or_key]
                        if description and created:
                            break

            # Use OpenRouter created timestamp, fall back to date in model name
            sort_key = created or _extract_date_score(raw_name)

            results.append(
                {
                    "id": model_id,
                    "name": raw_name,
                    "description": description,
                    "_sort": sort_key,
                }
            )

        # Newest first; models without any date info go to the end
        results.sort(key=lambda m: m.pop("_sort"), reverse=True)
        return results[:limit]

    def _get_or_provider_models(
        self,
        provider_id: str,
        or_org: str,
        query: str,
        limit: int,
    ) -> List[Dict]:
        """Get models for a provider from OpenRouter (for providers not in litellm)."""
        prefix = f"{or_org}/"
        results = []
        for m in self._or_cache:
            or_id = m.get("id", "")
            if not or_id.startswith(prefix):
                continue
            input_mods = m.get("architecture", {}).get("input_modalities") or []
            output_mods = m.get("architecture", {}).get("output_modalities") or []
            if input_mods and "text" not in input_mods:
                continue
            if output_mods and "text" not in output_mods:
                continue

            # Strip ":free" suffix and skip free duplicates if paid version exists
            if or_id.endswith(":free"):
                continue

            model_name = or_id[len(prefix) :]
            raw_name = m.get("name", or_id)
            name = raw_name.split(": ", 1)[1] if ": " in raw_name else raw_name
            model_id = f"{provider_id}/{model_name}"

            if query:
                q = query.lower()
                if q not in model_id.lower() and q not in name.lower():
                    continue

            results.append(
                {
                    "id": model_id,
                    "name": name,
                    "created": m.get("created", 0),
                    "description": m.get("description", ""),
                }
            )

        results.sort(key=lambda m: m.get("created", 0), reverse=True)
        return results[:limit]

    def _get_openrouter_models(self, query: str, limit: int) -> List[Dict]:
        """Get OpenRouter models (text input, text output)."""
        results = []
        for m in self._or_cache:
            input_mods = m.get("architecture", {}).get("input_modalities") or []
            output_mods = m.get("architecture", {}).get("output_modalities") or []
            if input_mods and "text" not in input_mods:
                continue
            if output_mods and "text" not in output_mods:
                continue

            or_id = m.get("id", "")
            name = m.get("name", or_id)
            model_id = f"openrouter/{or_id}"

            if query:
                q = query.lower()
                if q not in model_id.lower() and q not in name.lower():
                    continue

            results.append(
                {
                    "id": model_id,
                    "name": name,
                    "created": m.get("created", 0),
                    "description": m.get("description", ""),
                }
            )

        results.sort(key=lambda m: m.get("created", 0), reverse=True)
        return results[:limit]


# Singleton instance
_catalog = ModelCatalog()


def get_models_for_provider(
    provider_id: str, query: str = "", limit: int = 100
) -> List[Dict]:
    """Get models for a provider. Uses LiteLLM model database with OpenRouter descriptions."""
    return _catalog.get_models_for_provider(provider_id, query, limit)


def get_model_description(provider_id: str, model_id: str) -> str:
    """Look up a model's description by its LiteLLM model ID."""
    models = _catalog.get_models_for_provider(provider_id, limit=500)
    for m in models:
        if m["id"] == model_id:
            return m.get("description", "")
    return ""
