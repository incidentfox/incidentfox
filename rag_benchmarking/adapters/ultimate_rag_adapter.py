"""
Ultimate RAG Adapter for Benchmark Evaluation.

This adapter connects the Ultimate RAG system to standard RAG benchmarks,
allowing evaluation against MultiHop-RAG, RAGBench, CRAG, and others.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


@dataclass
class RetrievalResult:
    """A single retrieved chunk."""

    text: str
    score: float
    importance: float = 0.0
    source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """Result of running a benchmark query."""

    query: str
    retrieved_chunks: List[RetrievalResult]
    generated_answer: Optional[str] = None
    ground_truth: Optional[str] = None
    retrieval_time_ms: float = 0.0
    generation_time_ms: float = 0.0
    strategies_used: List[str] = field(default_factory=list)


class UltimateRAGAdapter:
    """
    Adapter to connect Ultimate RAG to standard RAG benchmarks.

    This adapter provides a unified interface for:
    1. Ingesting benchmark documents into Ultimate RAG
    2. Running retrieval queries
    3. Generating answers using retrieved context
    4. Evaluating results against ground truth
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        timeout: int = 30,
        default_top_k: int = 5,
        retrieval_mode: str = "thorough",
    ):
        """
        Initialize the adapter.

        Args:
            api_url: Base URL of the Ultimate RAG API server
            timeout: Request timeout in seconds
            default_top_k: Default number of chunks to retrieve
            retrieval_mode: Default retrieval mode (standard, fast, thorough, incident)
        """
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.default_top_k = default_top_k
        self.retrieval_mode = retrieval_mode
        self._session = requests.Session()

    def health_check(self) -> bool:
        """Check if the Ultimate RAG server is healthy."""
        try:
            resp = self._session.get(f"{self.api_url}/health", timeout=self.timeout)
            return resp.status_code == 200 and resp.json().get("status") == "healthy"
        except Exception as e:
            print(f"Health check failed: {e}")
            return False

    def ingest_document(
        self,
        content: str,
        source_url: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ingest a document into Ultimate RAG.

        Args:
            content: Document content
            source_url: Optional source URL
            content_type: Optional content type (markdown, text, html, etc.)
            metadata: Optional additional metadata

        Returns:
            Ingestion response with chunks_created, entities_found, etc.
        """
        payload = {
            "content": content,
            "source_url": source_url,
            "content_type": content_type,
            "metadata": metadata or {},
        }

        resp = self._session.post(
            f"{self.api_url}/ingest",
            json=payload,
            timeout=self.timeout * 2,  # Ingestion can take longer
        )
        resp.raise_for_status()
        return resp.json()

    def ingest_benchmark_corpus(
        self,
        documents: List[Dict[str, Any]],
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Ingest an entire benchmark corpus.

        Args:
            documents: List of documents, each with 'content' and optional metadata
            progress_callback: Optional callback(current, total) for progress

        Returns:
            Summary of ingestion results
        """
        results = {
            "total": len(documents),
            "successful": 0,
            "failed": 0,
            "total_chunks": 0,
            "total_entities": 0,
            "errors": [],
        }

        for i, doc in enumerate(documents):
            try:
                content = doc.get("content", doc.get("text", ""))
                source = doc.get("source", doc.get("url", doc.get("id", f"doc_{i}")))
                metadata = doc.get("metadata", {})

                result = self.ingest_document(
                    content=content,
                    source_url=source,
                    metadata=metadata,
                )

                if result.get("success"):
                    results["successful"] += 1
                    results["total_chunks"] += result.get("chunks_created", 0)
                    results["total_entities"] += len(result.get("entities_found", []))
                else:
                    results["failed"] += 1
                    results["errors"].append(f"Doc {i}: {result}")

            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"Doc {i}: {str(e)}")

            if progress_callback:
                progress_callback(i + 1, len(documents))

        return results

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        mode: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        include_graph: bool = True,
    ) -> Tuple[List[RetrievalResult], Dict[str, Any]]:
        """
        Retrieve relevant chunks for a query.

        Args:
            query: The search query
            top_k: Number of chunks to retrieve
            mode: Retrieval mode (standard, fast, thorough, incident)
            filters: Optional filters
            include_graph: Whether to include graph context

        Returns:
            Tuple of (list of RetrievalResult, metadata dict)
        """
        start_time = time.time()

        payload = {
            "query": query,
            "top_k": top_k or self.default_top_k,
            "mode": mode or self.retrieval_mode,
            "filters": filters,
            "include_graph": include_graph,
        }

        resp = self._session.post(
            f"{self.api_url}/query",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        elapsed_ms = (time.time() - start_time) * 1000

        results = [
            RetrievalResult(
                text=r["text"],
                score=r["score"],
                importance=r.get("importance", 0.0),
                source=r.get("source"),
                metadata=r.get("metadata", {}),
            )
            for r in data.get("results", [])
        ]

        metadata = {
            "retrieval_time_ms": elapsed_ms,
            "total_candidates": data.get("total_candidates", 0),
            "mode": data.get("mode", ""),
            "strategies_used": data.get("strategies_used", []),
        }

        return results, metadata

    def retrieve_for_benchmark(
        self,
        query: str,
        top_k: Optional[int] = None,
    ) -> BenchmarkResult:
        """
        Retrieve for benchmark evaluation - returns BenchmarkResult.

        Args:
            query: The search query
            top_k: Number of chunks to retrieve

        Returns:
            BenchmarkResult with retrieved chunks
        """
        results, metadata = self.retrieve(query, top_k=top_k)

        return BenchmarkResult(
            query=query,
            retrieved_chunks=results,
            retrieval_time_ms=metadata["retrieval_time_ms"],
            strategies_used=metadata["strategies_used"],
        )

    def generate_answer(
        self,
        query: str,
        context_chunks: List[str],
        max_tokens: int = 500,
    ) -> str:
        """
        Generate an answer using retrieved context.

        Note: This uses the v1 /answer endpoint. For more control,
        you may want to use your own LLM with the retrieved context.

        Args:
            query: The question
            context_chunks: Retrieved context chunks
            max_tokens: Maximum tokens in response

        Returns:
            Generated answer string
        """
        # Use v1 answer endpoint
        payload = {
            "question": query,
            "top_k": len(context_chunks),
        }

        resp = self._session.post(
            f"{self.api_url}/api/v1/answer",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("answer", "")

    def retrieve_and_generate(
        self,
        query: str,
        top_k: Optional[int] = None,
        ground_truth: Optional[str] = None,
    ) -> BenchmarkResult:
        """
        Full RAG pipeline: retrieve then generate.

        Args:
            query: The question
            top_k: Number of chunks to retrieve
            ground_truth: Optional ground truth answer for evaluation

        Returns:
            BenchmarkResult with retrieval and generation results
        """
        # Retrieve
        results, retrieval_meta = self.retrieve(query, top_k=top_k)

        # Generate
        gen_start = time.time()
        context_chunks = [r.text for r in results]
        answer = self.generate_answer(query, context_chunks)
        gen_time_ms = (time.time() - gen_start) * 1000

        return BenchmarkResult(
            query=query,
            retrieved_chunks=results,
            generated_answer=answer,
            ground_truth=ground_truth,
            retrieval_time_ms=retrieval_meta["retrieval_time_ms"],
            generation_time_ms=gen_time_ms,
            strategies_used=retrieval_meta["strategies_used"],
        )

    def get_context_string(self, results: List[RetrievalResult]) -> str:
        """
        Format retrieved results as a context string for LLM input.

        Args:
            results: List of RetrievalResult

        Returns:
            Formatted context string
        """
        context_parts = []
        for i, r in enumerate(results, 1):
            source_info = f" (source: {r.source})" if r.source else ""
            context_parts.append(f"[{i}]{source_info}\n{r.text}")

        return "\n\n---\n\n".join(context_parts)


class MultiHopRAGEvaluator:
    """
    Evaluator for the MultiHop-RAG benchmark.

    This handles the specific format and metrics of MultiHop-RAG.
    """

    def __init__(self, adapter: UltimateRAGAdapter, data_dir: str):
        self.adapter = adapter
        self.data_dir = Path(data_dir)

    def load_dataset(self) -> List[Dict[str, Any]]:
        """Load the MultiHop-RAG dataset."""
        dataset_path = self.data_dir / "dataset"

        # Try to load from common locations
        for filename in ["MultiHopRAG.json", "dataset.json", "queries.json"]:
            path = dataset_path / filename
            if path.exists():
                with open(path) as f:
                    return json.load(f)

        raise FileNotFoundError(f"Could not find dataset in {dataset_path}")

    def load_corpus(self) -> List[Dict[str, Any]]:
        """Load the document corpus."""
        corpus_path = self.data_dir / "dataset" / "corpus"

        documents = []
        if corpus_path.exists():
            for json_file in corpus_path.glob("*.json"):
                with open(json_file) as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        documents.extend(data)
                    else:
                        documents.append(data)

        return documents

    def evaluate_retrieval(
        self,
        queries: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        Evaluate retrieval performance.

        Args:
            queries: List of query dicts with 'query' and 'evidence_list'
            top_k: Number of chunks to retrieve

        Returns:
            Metrics dict with recall, MRR, hit_rate, etc.
        """
        results = {
            "total_queries": len(queries),
            "recall_at_k": [],
            "mrr": [],
            "hit_rate": 0,
            "avg_retrieval_time_ms": 0,
        }

        total_time = 0
        hits = 0

        for q in queries:
            query_text = q.get("query", q.get("question", ""))
            evidence_list = q.get("evidence_list", q.get("supporting_facts", []))

            # Retrieve
            benchmark_result = self.adapter.retrieve_for_benchmark(
                query_text, top_k=top_k
            )
            total_time += benchmark_result.retrieval_time_ms

            # Get retrieved texts
            retrieved_texts = [
                r.text.lower() for r in benchmark_result.retrieved_chunks
            ]

            # Calculate recall
            if evidence_list:
                found = 0
                first_rank = None
                for i, evidence in enumerate(evidence_list):
                    evidence_text = (
                        evidence.lower()
                        if isinstance(evidence, str)
                        else str(evidence).lower()
                    )
                    for rank, retrieved in enumerate(retrieved_texts):
                        if evidence_text in retrieved or retrieved in evidence_text:
                            found += 1
                            if first_rank is None:
                                first_rank = rank + 1
                            break

                recall = found / len(evidence_list) if evidence_list else 0
                results["recall_at_k"].append(recall)

                if first_rank:
                    results["mrr"].append(1.0 / first_rank)
                    hits += 1
                else:
                    results["mrr"].append(0.0)

        # Aggregate metrics
        results["avg_recall_at_k"] = (
            sum(results["recall_at_k"]) / len(results["recall_at_k"])
            if results["recall_at_k"]
            else 0
        )
        results["avg_mrr"] = (
            sum(results["mrr"]) / len(results["mrr"]) if results["mrr"] else 0
        )
        results["hit_rate"] = hits / len(queries) if queries else 0
        results["avg_retrieval_time_ms"] = total_time / len(queries) if queries else 0

        return results


class RAGBenchEvaluator:
    """
    Evaluator for the RAGBench benchmark.

    Implements TRACe evaluation metrics.
    """

    def __init__(self, adapter: UltimateRAGAdapter, data_dir: str):
        self.adapter = adapter
        self.data_dir = Path(data_dir)

    def load_dataset(self, split: str = "test") -> List[Dict[str, Any]]:
        """
        Load RAGBench dataset.

        Note: RAGBench is typically loaded from HuggingFace:
            from datasets import load_dataset
            dataset = load_dataset("rungalileo/ragbench")
        """
        # Try local file first
        local_path = self.data_dir / f"{split}.json"
        if local_path.exists():
            with open(local_path) as f:
                return json.load(f)

        raise FileNotFoundError(
            f"Dataset not found at {local_path}. "
            "Load from HuggingFace: load_dataset('rungalileo/ragbench')"
        )

    def evaluate_trace_metrics(
        self,
        queries: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        Evaluate using TRACe metrics.

        TRACe = Truthfulness, Relevance, Adherence, Completeness

        Args:
            queries: List of query dicts
            top_k: Number of chunks to retrieve

        Returns:
            TRACe metrics dict
        """
        results = {
            "utilization": [],  # How much of retrieved context is used
            "relevance": [],  # Are retrieved docs relevant
            "adherence": [],  # Does answer stick to context (no hallucination)
            "completeness": [],  # Does answer cover all aspects
        }

        for q in queries:
            query_text = q.get("query", q.get("question", ""))
            ground_truth = q.get("answer", q.get("ground_truth", ""))

            # Full RAG pipeline
            benchmark_result = self.adapter.retrieve_and_generate(
                query_text, top_k=top_k, ground_truth=ground_truth
            )

            # Note: Full TRACe evaluation requires LLM-as-judge
            # This is a simplified version using text overlap
            if benchmark_result.generated_answer and ground_truth:
                answer_lower = benchmark_result.generated_answer.lower()
                truth_lower = ground_truth.lower()

                # Simplified completeness: word overlap
                truth_words = set(truth_lower.split())
                answer_words = set(answer_lower.split())
                overlap = len(truth_words & answer_words)
                completeness = overlap / len(truth_words) if truth_words else 0
                results["completeness"].append(completeness)

        # Aggregate
        return {
            "avg_completeness": (
                sum(results["completeness"]) / len(results["completeness"])
                if results["completeness"]
                else 0
            ),
            "total_evaluated": len(queries),
        }


class CRAGEvaluator:
    """
    Evaluator for Meta's CRAG benchmark.

    Implements the scoring: correct (+1), missing (0), hallucination (-1)
    """

    def __init__(self, adapter: UltimateRAGAdapter, data_dir: str):
        self.adapter = adapter
        self.data_dir = Path(data_dir)

    def load_dataset(self) -> List[Dict[str, Any]]:
        """Load CRAG dataset."""
        dataset_path = self.data_dir / "data"

        queries = []
        for json_file in dataset_path.glob("*.json"):
            with open(json_file) as f:
                data = json.load(f)
                if isinstance(data, list):
                    queries.extend(data)
                else:
                    queries.append(data)

        return queries

    def score_answer(
        self,
        generated: str,
        ground_truth: str,
        acceptable_answers: Optional[List[str]] = None,
    ) -> int:
        """
        Score an answer using CRAG scoring.

        Returns:
            +1 for correct
            0 for missing/abstain
            -1 for incorrect/hallucination
        """
        generated = generated.strip().lower()
        ground_truth = ground_truth.strip().lower()

        # Check for abstention
        abstention_phrases = [
            "i don't know",
            "cannot answer",
            "no information",
            "unclear",
        ]
        if any(phrase in generated for phrase in abstention_phrases):
            return 0  # Missing

        # Check for correct answer
        if ground_truth in generated:
            return 1  # Correct

        # Check acceptable alternatives
        if acceptable_answers:
            for alt in acceptable_answers:
                if alt.lower() in generated:
                    return 1

        # Otherwise, hallucination
        return -1

    def evaluate(
        self,
        queries: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        Evaluate on CRAG benchmark.

        Args:
            queries: CRAG query dicts
            top_k: Number of chunks to retrieve

        Returns:
            CRAG metrics including accuracy and hallucination rate
        """
        results = {
            "correct": 0,
            "missing": 0,
            "hallucination": 0,
            "total": len(queries),
        }

        for q in queries:
            query_text = q.get("query", q.get("question", ""))
            ground_truth = q.get("answer", "")
            acceptable = q.get("acceptable_answers", [])

            # Generate answer
            benchmark_result = self.adapter.retrieve_and_generate(
                query_text,
                top_k=top_k,
                ground_truth=ground_truth,
            )

            # Score
            score = self.score_answer(
                benchmark_result.generated_answer or "",
                ground_truth,
                acceptable,
            )

            if score == 1:
                results["correct"] += 1
            elif score == 0:
                results["missing"] += 1
            else:
                results["hallucination"] += 1

        # Calculate rates
        total = results["total"]
        results["accuracy"] = results["correct"] / total if total else 0
        results["hallucination_rate"] = results["hallucination"] / total if total else 0
        results["crag_score"] = (
            (results["correct"] - results["hallucination"]) / total if total else 0
        )

        return results


def run_quick_test(api_url: str = "http://localhost:8000"):
    """Quick test to verify the adapter works."""
    print(f"Testing Ultimate RAG adapter at {api_url}")

    adapter = UltimateRAGAdapter(api_url=api_url)

    # Health check
    if not adapter.health_check():
        print("ERROR: Server not healthy or not reachable")
        return False
    print("Health check passed")

    # Test retrieval
    results, meta = adapter.retrieve("test query", top_k=3)
    print(
        f"Retrieval test: got {len(results)} results in {meta['retrieval_time_ms']:.1f}ms"
    )
    print(f"Strategies used: {meta['strategies_used']}")

    return True


if __name__ == "__main__":
    import sys

    api_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    run_quick_test(api_url)
