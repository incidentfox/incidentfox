# RAG Benchmarking for Ultimate RAG

This directory contains tools for benchmarking the Ultimate RAG system against standard RAG benchmarks.

## Supported Benchmarks

| Benchmark | Type | Size | Metrics | Best For |
|-----------|------|------|---------|----------|
| **MultiHop-RAG** | Multi-hop QA | 2,556 queries | Recall@K, MRR, Hit Rate | Testing multi-document reasoning |
| **RAGBench** | Industry QA | 100K examples | TRACe metrics | Real-world domain evaluation |
| **CRAG** | Factual QA | 4,409 queries | Accuracy, Hallucination Rate | Measuring truthfulness |

## Quick Start

### 1. Download Benchmarks

```bash
# Download all benchmarks
chmod +x scripts/download_benchmarks.sh
./scripts/download_benchmarks.sh all

# Or download individually
./scripts/download_benchmarks.sh multihop
./scripts/download_benchmarks.sh ragbench
./scripts/download_benchmarks.sh crag
```

### 2. Start Ultimate RAG Server

```bash
# From the main repo directory
cd ..
python -m ultimate_rag.api.server
# Server runs at http://localhost:8000
```

### 3. Run Evaluation

```bash
# MultiHop-RAG evaluation
python scripts/run_multihop_eval.py --api-url http://localhost:8000 --top-k 5

# CRAG evaluation
python scripts/run_crag_eval.py --api-url http://localhost:8000 --top-k 5

# Quick test with limited queries
python scripts/run_multihop_eval.py --max-queries 50
```

## Directory Structure

```
rag_benchmarking/
├── adapters/
│   ├── __init__.py
│   └── ultimate_rag_adapter.py  # Adapter connecting Ultimate RAG to benchmarks
├── multihop_rag/                 # MultiHop-RAG benchmark (git clone)
├── ragbench/                     # RAGBench data
├── crag/                         # CRAG benchmark (git clone)
├── scripts/
│   ├── download_benchmarks.sh    # Download all benchmarks
│   ├── run_multihop_eval.py      # Run MultiHop-RAG evaluation
│   └── run_crag_eval.py          # Run CRAG evaluation
└── README.md
```

## Adapter Usage

You can use the adapter directly in Python:

```python
from adapters import UltimateRAGAdapter

# Initialize
adapter = UltimateRAGAdapter(
    api_url="http://localhost:8000",
    default_top_k=5,
    retrieval_mode="thorough",
)

# Health check
if adapter.health_check():
    print("Server is ready!")

# Retrieve
results, meta = adapter.retrieve("What is the incident resolution process?")
for r in results:
    print(f"Score: {r.score:.3f} | {r.text[:100]}...")

# Full RAG pipeline
result = adapter.retrieve_and_generate(
    query="How do I restart the payment service?",
    top_k=5,
)
print(f"Answer: {result.generated_answer}")
```

## Evaluation Metrics

### MultiHop-RAG Metrics
- **Recall@K**: Fraction of relevant evidence retrieved in top-K
- **MRR (Mean Reciprocal Rank)**: 1/rank of first relevant result
- **Hit Rate**: Fraction of queries with at least one relevant result

### CRAG Metrics
- **Accuracy**: Fraction of correct answers
- **Hallucination Rate**: Fraction of incorrect/hallucinated answers
- **CRAG Score**: (correct - hallucination) / total

### RAGBench TRACe Metrics
- **Utilization**: How much of retrieved context is used
- **Relevance**: Are retrieved documents relevant
- **Adherence**: Does answer stick to context (no hallucination)
- **Completeness**: Does answer cover all aspects

## Benchmark Details

### MultiHop-RAG
- **Paper**: [arXiv:2401.15391](https://arxiv.org/abs/2401.15391)
- **GitHub**: https://github.com/yixuantt/MultiHop-RAG
- **Focus**: Multi-hop reasoning across 2-4 documents
- **Query Types**: Inference, Comparison, Temporal, Null

### RAGBench
- **Paper**: [arXiv:2407.11005](https://arxiv.org/abs/2407.11005)
- **HuggingFace**: https://huggingface.co/datasets/rungalileo/ragbench
- **Focus**: Industry-specific domains (biomedical, legal, finance, etc.)
- **Size**: 100K examples across 12 sub-datasets

### CRAG
- **Paper**: [arXiv:2406.04744](https://arxiv.org/abs/2406.04744)
- **GitHub**: https://github.com/facebookresearch/CRAG
- **Focus**: Factual QA with hallucination detection
- **Domains**: Finance, Sports, Music, Movie, Open Domain

## Expected Results

Based on SOTA benchmarks, here's what to aim for:

| Benchmark | Metric | Vanilla RAG | GraphRAG | RAPTOR | Your Target |
|-----------|--------|-------------|----------|--------|-------------|
| MultiHop-RAG | Accuracy | 65.8% | 71.2% | ~72% | >70% |
| CRAG | Truthfulness | 34% | - | - | >50% |
| CRAG | Hallucination | 25%+ | - | - | <20% |

## Customization

### Custom Retrieval Modes

```python
# Use different retrieval modes
adapter.retrieval_mode = "fast"      # Speed optimized
adapter.retrieval_mode = "thorough"  # Quality optimized
adapter.retrieval_mode = "incident"  # Incident response mode
```

### Custom Evaluation

```python
from adapters import UltimateRAGAdapter, MultiHopRAGEvaluator

adapter = UltimateRAGAdapter(api_url="http://localhost:8000")
evaluator = MultiHopRAGEvaluator(adapter, "multihop_rag/")

# Load and filter queries
queries = evaluator.load_dataset()
inference_queries = [q for q in queries if q.get("query_type") == "inference"]

# Evaluate subset
results = evaluator.evaluate_retrieval(inference_queries, top_k=10)
```

## Troubleshooting

### Server not reachable
```bash
# Check if server is running
curl http://localhost:8000/health
```

### Dataset not found
```bash
# Re-download benchmarks
./scripts/download_benchmarks.sh all
```

### Out of memory during ingestion
```bash
# Ingest in smaller batches by editing the script
# or increase server memory
```

## Contributing

To add a new benchmark:

1. Create evaluator class in `adapters/ultimate_rag_adapter.py`
2. Add download logic to `scripts/download_benchmarks.sh`
3. Create evaluation script in `scripts/`
4. Update this README
