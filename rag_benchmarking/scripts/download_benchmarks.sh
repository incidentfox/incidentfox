#!/bin/bash
# Download RAG Benchmarks
# Usage: ./download_benchmarks.sh [benchmark_name]
# Options: multihop, ragbench, crag, all

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== RAG Benchmark Downloader ==="
echo "Benchmark directory: $BENCHMARK_DIR"
echo ""

download_multihop_rag() {
    echo ">>> Downloading MultiHop-RAG..."
    cd "$BENCHMARK_DIR/multihop_rag"

    if [ -d ".git" ]; then
        echo "Repository exists, pulling latest..."
        git pull
    else
        echo "Cloning MultiHop-RAG repository..."
        git clone https://github.com/yixuantt/MultiHop-RAG.git .
    fi

    echo "MultiHop-RAG downloaded successfully!"
    echo "Dataset location: $BENCHMARK_DIR/multihop_rag/dataset/"
    echo ""
}

download_ragbench() {
    echo ">>> Downloading RAGBench..."
    cd "$BENCHMARK_DIR/ragbench"

    # RAGBench is primarily on HuggingFace, create a download script
    cat > download_ragbench.py << 'EOF'
"""Download RAGBench from HuggingFace."""
import os
import json

try:
    from datasets import load_dataset
except ImportError:
    print("Installing datasets library...")
    os.system("pip install datasets")
    from datasets import load_dataset

print("Downloading RAGBench from HuggingFace...")
dataset = load_dataset("rungalileo/ragbench")

# Save splits locally
for split in dataset.keys():
    print(f"Saving {split} split ({len(dataset[split])} examples)...")
    with open(f"{split}.json", "w") as f:
        json.dump([dict(row) for row in dataset[split]], f, indent=2)

print("RAGBench downloaded successfully!")
print(f"Files saved: {[f'{s}.json' for s in dataset.keys()]}")
EOF

    echo "Created download script. Run: python download_ragbench.py"
    echo "Or use directly: from datasets import load_dataset; ds = load_dataset('rungalileo/ragbench')"
    echo ""
}

download_crag() {
    echo ">>> Downloading CRAG..."
    cd "$BENCHMARK_DIR/crag"

    if [ -d ".git" ]; then
        echo "Repository exists, pulling latest..."
        git pull
    else
        echo "Cloning CRAG repository..."
        git clone https://github.com/facebookresearch/CRAG.git .
    fi

    echo "CRAG downloaded successfully!"
    echo "See docs/dataset.md for dataset download instructions"
    echo ""
}

# Main
case "${1:-all}" in
    multihop|multihop-rag|MultiHop-RAG)
        download_multihop_rag
        ;;
    ragbench|RAGBench)
        download_ragbench
        ;;
    crag|CRAG)
        download_crag
        ;;
    all)
        download_multihop_rag
        download_ragbench
        download_crag
        echo "=== All benchmarks downloaded! ==="
        ;;
    *)
        echo "Unknown benchmark: $1"
        echo "Usage: $0 [multihop|ragbench|crag|all]"
        exit 1
        ;;
esac

echo ""
echo "Next steps:"
echo "1. Review each benchmark's README for specific setup"
echo "2. Install benchmark dependencies: pip install -r requirements.txt"
echo "3. Run evaluation using the adapter scripts"
