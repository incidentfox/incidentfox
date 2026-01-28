#!/usr/bin/env python3
"""
Run MultiHop-RAG Evaluation on Ultimate RAG.

This script:
1. Loads the MultiHop-RAG corpus
2. Ingests documents into Ultimate RAG
3. Runs retrieval evaluation
4. Reports metrics (Recall@K, MRR, Hit Rate)

Usage:
    python run_multihop_eval.py --api-url http://localhost:8000 --top-k 5
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.ultimate_rag_adapter import UltimateRAGAdapter, MultiHopRAGEvaluator


def progress_bar(current: int, total: int, width: int = 50):
    """Simple progress bar."""
    percent = current / total
    filled = int(width * percent)
    bar = "=" * filled + "-" * (width - filled)
    print(f"\r[{bar}] {current}/{total} ({percent*100:.1f}%)", end="", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Run MultiHop-RAG evaluation")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Ultimate RAG API URL")
    parser.add_argument("--data-dir", default=None, help="MultiHop-RAG data directory")
    parser.add_argument("--top-k", type=int, default=5, help="Number of chunks to retrieve")
    parser.add_argument("--max-queries", type=int, default=None, help="Max queries to evaluate (for testing)")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip corpus ingestion")
    parser.add_argument("--output", default="multihop_results.json", help="Output file for results")
    args = parser.parse_args()

    # Determine data directory
    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        data_dir = Path(__file__).parent.parent / "multihop_rag"

    print(f"=== MultiHop-RAG Evaluation ===")
    print(f"API URL: {args.api_url}")
    print(f"Data directory: {data_dir}")
    print(f"Top-K: {args.top_k}")
    print("")

    # Initialize adapter and evaluator
    adapter = UltimateRAGAdapter(
        api_url=args.api_url,
        default_top_k=args.top_k,
        retrieval_mode="thorough",
    )

    # Health check
    print("Checking API health...")
    if not adapter.health_check():
        print("ERROR: Ultimate RAG API not available!")
        print("Make sure the server is running at", args.api_url)
        sys.exit(1)
    print("API is healthy!")
    print("")

    evaluator = MultiHopRAGEvaluator(adapter, str(data_dir))

    # Load corpus and ingest
    if not args.skip_ingest:
        print("Loading corpus...")
        try:
            corpus = evaluator.load_corpus()
            print(f"Found {len(corpus)} documents in corpus")

            print("Ingesting corpus into Ultimate RAG...")
            start_time = time.time()

            def progress_callback(current, total):
                progress_bar(current, total)

            ingest_results = adapter.ingest_benchmark_corpus(corpus, progress_callback)
            print("")  # New line after progress bar

            elapsed = time.time() - start_time
            print(f"Ingestion complete in {elapsed:.1f}s")
            print(f"  Successful: {ingest_results['successful']}/{ingest_results['total']}")
            print(f"  Chunks created: {ingest_results['total_chunks']}")
            print(f"  Entities found: {ingest_results['total_entities']}")
            if ingest_results['errors']:
                print(f"  Errors: {len(ingest_results['errors'])}")
            print("")

        except FileNotFoundError as e:
            print(f"WARNING: Could not load corpus: {e}")
            print("Continuing with evaluation (assuming data already ingested)...")
            print("")

    # Load queries
    print("Loading evaluation queries...")
    try:
        queries = evaluator.load_dataset()
        print(f"Found {len(queries)} queries")
    except FileNotFoundError as e:
        print(f"ERROR: Could not load queries: {e}")
        print("Make sure you've downloaded the MultiHop-RAG dataset:")
        print("  cd rag_benchmarking/multihop_rag")
        print("  git clone https://github.com/yixuantt/MultiHop-RAG.git .")
        sys.exit(1)

    # Limit queries if specified
    if args.max_queries:
        queries = queries[:args.max_queries]
        print(f"Limited to {len(queries)} queries for evaluation")

    # Run evaluation
    print("")
    print("Running retrieval evaluation...")
    start_time = time.time()

    results = evaluator.evaluate_retrieval(queries, top_k=args.top_k)

    elapsed = time.time() - start_time
    print(f"Evaluation complete in {elapsed:.1f}s")
    print("")

    # Print results
    print("=== Results ===")
    print(f"Total queries: {results['total_queries']}")
    print(f"Recall@{args.top_k}: {results['avg_recall_at_k']:.4f}")
    print(f"MRR: {results['avg_mrr']:.4f}")
    print(f"Hit Rate: {results['hit_rate']:.4f}")
    print(f"Avg retrieval time: {results['avg_retrieval_time_ms']:.1f}ms")

    # Save results
    output_path = Path(args.output)
    results["config"] = {
        "api_url": args.api_url,
        "top_k": args.top_k,
        "data_dir": str(data_dir),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
