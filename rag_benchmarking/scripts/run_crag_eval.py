#!/usr/bin/env python3
"""
Run CRAG (Comprehensive RAG) Evaluation on Ultimate RAG.

This script:
1. Loads the CRAG benchmark
2. Runs queries through Ultimate RAG
3. Scores answers using CRAG scoring (+1 correct, 0 missing, -1 hallucination)
4. Reports accuracy and hallucination rate

Usage:
    python run_crag_eval.py --api-url http://localhost:8000 --top-k 5
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.ultimate_rag_adapter import CRAGEvaluator, UltimateRAGAdapter


def main():
    parser = argparse.ArgumentParser(description="Run CRAG evaluation")
    parser.add_argument(
        "--api-url", default="http://localhost:8000", help="Ultimate RAG API URL"
    )
    parser.add_argument("--data-dir", default=None, help="CRAG data directory")
    parser.add_argument(
        "--top-k", type=int, default=5, help="Number of chunks to retrieve"
    )
    parser.add_argument(
        "--max-queries", type=int, default=None, help="Max queries to evaluate"
    )
    parser.add_argument(
        "--output", default="crag_results.json", help="Output file for results"
    )
    args = parser.parse_args()

    # Determine data directory
    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        data_dir = Path(__file__).parent.parent / "crag"

    print("=== CRAG Evaluation ===")
    print(f"API URL: {args.api_url}")
    print(f"Data directory: {data_dir}")
    print(f"Top-K: {args.top_k}")
    print("")

    # Initialize adapter
    adapter = UltimateRAGAdapter(
        api_url=args.api_url,
        default_top_k=args.top_k,
        retrieval_mode="thorough",
    )

    # Health check
    print("Checking API health...")
    if not adapter.health_check():
        print("ERROR: Ultimate RAG API not available!")
        sys.exit(1)
    print("API is healthy!")
    print("")

    evaluator = CRAGEvaluator(adapter, str(data_dir))

    # Load queries
    print("Loading CRAG queries...")
    try:
        queries = evaluator.load_dataset()
        print(f"Found {len(queries)} queries")
    except FileNotFoundError as e:
        print(f"ERROR: Could not load queries: {e}")
        print("Make sure you've downloaded CRAG:")
        print("  cd rag_benchmarking/crag")
        print("  git clone https://github.com/facebookresearch/CRAG.git .")
        print("  # Then follow docs/dataset.md for data download")
        sys.exit(1)

    if args.max_queries:
        queries = queries[: args.max_queries]
        print(f"Limited to {len(queries)} queries")

    # Run evaluation
    print("")
    print("Running CRAG evaluation...")
    print("(This includes answer generation, may take a while)")
    start_time = time.time()

    results = evaluator.evaluate(queries, top_k=args.top_k)

    elapsed = time.time() - start_time
    print(f"Evaluation complete in {elapsed:.1f}s")
    print("")

    # Print results
    print("=== CRAG Results ===")
    print(f"Total queries: {results['total']}")
    print(
        f"Correct (+1): {results['correct']} ({results['correct']/results['total']*100:.1f}%)"
    )
    print(
        f"Missing (0): {results['missing']} ({results['missing']/results['total']*100:.1f}%)"
    )
    print(
        f"Hallucination (-1): {results['hallucination']} ({results['hallucination']/results['total']*100:.1f}%)"
    )
    print("")
    print(f"Accuracy: {results['accuracy']:.4f}")
    print(f"Hallucination Rate: {results['hallucination_rate']:.4f}")
    print(f"CRAG Score: {results['crag_score']:.4f}")

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
