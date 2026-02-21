#!/usr/bin/env python3
"""
Download RAGBench from HuggingFace.

RAGBench is a 100K example benchmark for RAG systems.
https://huggingface.co/datasets/rungalileo/ragbench
"""

import json
import os
import sys


def main():
    # Check for datasets library
    try:
        from datasets import load_dataset
    except ImportError:
        print("Installing datasets library...")
        os.system(f"{sys.executable} -m pip install datasets")
        from datasets import load_dataset

    print("Downloading RAGBench from HuggingFace...")
    print("This may take a few minutes...")
    print("")

    dataset = load_dataset("rungalileo/ragbench")

    print(f"Dataset loaded with {len(dataset)} splits")
    print("")

    # Save each split locally
    for split in dataset.keys():
        split_data = dataset[split]
        output_file = f"{split}.json"

        print(f"Saving {split} split ({len(split_data)} examples) to {output_file}...")

        # Convert to list of dicts
        data = [dict(row) for row in split_data]

        with open(output_file, "w") as f:
            json.dump(data, f, indent=2)

    print("")
    print("RAGBench downloaded successfully!")
    print(f"Files saved: {[f'{s}.json' for s in dataset.keys()]}")
    print("")

    # Print sample
    print("Sample entry:")
    sample = dataset[list(dataset.keys())[0]][0]
    for key in list(sample.keys())[:5]:
        value = (
            str(sample[key])[:100] + "..."
            if len(str(sample[key])) > 100
            else sample[key]
        )
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
