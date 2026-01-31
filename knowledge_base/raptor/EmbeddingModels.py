import logging
import threading
from abc import ABC, abstractmethod
from typing import List

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_random_exponential

from .usage_log import _Timer, log_usage

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)

# OpenAI embeddings API limits
OPENAI_BATCH_LIMIT = 2048  # Max texts per batch
OPENAI_TOKEN_LIMIT = 100000  # Max tokens per batch (300K is limit, use 100K for safety)


class BaseEmbeddingModel(ABC):
    @abstractmethod
    def create_embedding(self, text):
        pass

    def create_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Create embeddings for multiple texts. Default implementation calls single method."""
        return [self.create_embedding(t) for t in texts]


class OpenAIEmbeddingModel(BaseEmbeddingModel):
    def __init__(self, model="text-embedding-3-large"):
        self.model = model
        # The OpenAI client uses an underlying HTTP client that may not be safe to share
        # across threads. Create one client per thread (important when building embeddings
        # with ThreadPoolExecutor).
        self._tls = threading.local()

    def _client(self) -> OpenAI:
        c = getattr(self._tls, "client", None)
        if c is None:
            c = OpenAI()
            self._tls.client = c
        return c

    def _normalize_text(self, text: str) -> str:
        """Normalize text for embedding: replace newlines, truncate, handle empty strings."""
        text = (text or "").replace("\n", " ").strip()
        # Truncate to ~8000 tokens (32000 chars) to stay under model's 8192 token limit
        max_chars = 32000
        if len(text) > max_chars:
            text = text[:max_chars]
        return text if text else " "

    # Embeddings can hit rate limits; use more patient exponential backoff.
    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(12))
    def create_embedding(self, text):
        t = _Timer()
        text = self._normalize_text(text)
        resp = self._client().embeddings.create(input=[text], model=self.model)
        log_usage(
            kind="embeddings",
            model=self.model,
            usage=getattr(resp, "usage", None),
            duration_s=t.elapsed(),
        )
        return resp.data[0].embedding

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(12))
    def _embed_batch_chunk(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts (must be <= OPENAI_BATCH_LIMIT)."""
        t = _Timer()
        resp = self._client().embeddings.create(input=texts, model=self.model)
        log_usage(
            kind="embeddings",
            model=self.model,
            usage=getattr(resp, "usage", None),
            duration_s=t.elapsed(),
        )
        # OpenAI returns embeddings in same order as input
        return [d.embedding for d in resp.data]

    def create_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Create embeddings for multiple texts using batch API calls.

        This is significantly faster than calling create_embedding() for each text
        individually since OpenAI's batch API reduces network round-trips.
        OpenAI charges per-token, not per-request, so there's no cost difference.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embeddings in the same order as input texts.
        """
        if not texts:
            return []

        # Normalize all texts
        normalized = [self._normalize_text(t) for t in texts]

        # Process in token-aware chunks to respect OpenAI's token limits
        # Rough estimate: 1 token ≈ 4 chars for English text
        all_embeddings: List[List[float]] = []
        current_batch = []
        current_tokens = 0

        for text in normalized:
            # Estimate tokens (roughly 1 token per 4 chars)
            text_tokens = len(text) // 4 + 1

            # If adding this text would exceed token limit, process current batch first
            if current_tokens + text_tokens > OPENAI_TOKEN_LIMIT and current_batch:
                chunk_embeddings = self._embed_batch_chunk(current_batch)
                all_embeddings.extend(chunk_embeddings)
                current_batch = []
                current_tokens = 0

            # Also respect text count limit
            if len(current_batch) >= OPENAI_BATCH_LIMIT:
                chunk_embeddings = self._embed_batch_chunk(current_batch)
                all_embeddings.extend(chunk_embeddings)
                current_batch = []
                current_tokens = 0

            current_batch.append(text)
            current_tokens += text_tokens

        # Process remaining batch
        if current_batch:
            chunk_embeddings = self._embed_batch_chunk(current_batch)
            all_embeddings.extend(chunk_embeddings)

        return all_embeddings


class SBertEmbeddingModel(BaseEmbeddingModel):
    def __init__(self, model_name="sentence-transformers/multi-qa-mpnet-base-cos-v1"):
        # Import lazily to avoid hard dependency / version-coupling at module import time.
        # (Some environments will have transformers + huggingface_hub versions that break old sentence-transformers.)
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except Exception as e:  # pragma: no cover
            raise ImportError(
                "SBertEmbeddingModel requires the 'sentence-transformers' package to be installed "
                "and compatible with your 'huggingface_hub' version."
            ) from e

        self.model = SentenceTransformer(model_name)

    def create_embedding(self, text):
        return self.model.encode(text)

    def create_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch embed using sentence-transformers native batch support."""
        if not texts:
            return []
        # sentence-transformers encode() accepts a list and returns a numpy array
        embeddings = self.model.encode(texts)
        return [emb.tolist() for emb in embeddings]
