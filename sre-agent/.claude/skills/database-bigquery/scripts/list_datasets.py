#!/usr/bin/env python3
"""List BigQuery datasets."""

import sys

from bq_client import format_output, get_client


def main():
    try:
        client = get_client()

        datasets = []
        for dataset in client.list_datasets():
            datasets.append(
                {
                    "dataset_id": dataset.dataset_id,
                    "full_name": dataset.full_dataset_id,
                    "location": dataset.location,
                }
            )

        print(
            format_output(
                {
                    "dataset_count": len(datasets),
                    "datasets": datasets,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
