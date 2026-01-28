#!/usr/bin/env python3
"""
Test script to convert markdown test cases to Slack blocks.
Usage: python test_blocks.py [input_file]

If no input_file is provided, processes all .md files in inputs/
and outputs results to outputs/
"""

import json
import sys
from pathlib import Path

# Add parent directory to path to import production modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from markdown_utils import slack_mrkdwn
from message_builder import _add_text_blocks
from table_converter import PreformattedText, extract_and_convert_all_tables


def process_markdown(markdown_text):
    """Convert markdown text to Slack blocks."""
    # Extract all tables first (before markdown conversion)
    # This returns a list of text segments, table blocks, and pre-formatted text
    segments = extract_and_convert_all_tables(markdown_text)

    blocks = []
    truncated = False

    # Process each segment
    for segment in segments:
        if isinstance(segment, dict):
            # This is a native Slack table block
            blocks.append(segment)
        elif isinstance(segment, PreformattedText):
            # This is pre-formatted text (already in Slack mrkdwn) - skip markdown conversion
            text_blocks, text_truncated = _add_text_blocks(segment.text)
            blocks.extend(text_blocks)
            truncated = truncated or text_truncated
        elif isinstance(segment, str) and segment.strip():
            # This is raw text - convert markdown to Slack mrkdwn
            formatted_text = slack_mrkdwn(segment)
            text_blocks, text_truncated = _add_text_blocks(formatted_text)
            blocks.extend(text_blocks)
            truncated = truncated or text_truncated

    return blocks, truncated


def main():
    if len(sys.argv) > 1:
        # Single file mode (legacy behavior)
        input_file = sys.argv[1]
        with open(input_file, "r") as f:
            markdown_text = f.read()

        blocks, truncated = process_markdown(markdown_text)

        if truncated:
            print("WARNING: Output was truncated due to block limit", file=sys.stderr)

        output = {"blocks": blocks}
        print(json.dumps(output, indent=2))
    else:
        # Batch mode - process all test cases
        script_dir = Path(__file__).parent
        inputs_dir = script_dir / "inputs"
        output_dir = script_dir / "outputs"
        output_dir.mkdir(exist_ok=True)

        # Get all .md files in inputs/ (excluding subdirectories)
        test_files = sorted(inputs_dir.glob("*.md"))

        if not test_files:
            print("No test cases found in inputs/", file=sys.stderr)
            return

        print(f"Processing {len(test_files)} test cases...", file=sys.stderr)

        for test_file in test_files:
            try:
                # Read markdown
                with open(test_file, "r") as f:
                    markdown_text = f.read()

                # Skip empty files
                if not markdown_text.strip():
                    print(f"  SKIP {test_file.name} (empty)", file=sys.stderr)
                    continue

                # Process
                blocks, truncated = process_markdown(markdown_text)

                # Write output
                output_file = output_dir / f"{test_file.stem}.json"
                output = {"blocks": blocks}

                with open(output_file, "w") as f:
                    json.dump(output, f, indent=2)

                status = "TRUNCATED" if truncated else "OK"
                print(
                    f"  {status:10s} {test_file.name} -> {output_file.name} ({len(blocks)} blocks)",
                    file=sys.stderr,
                )

            except Exception as e:
                print(f"  ERROR {test_file.name}: {e}", file=sys.stderr)

        print(f"\nDone! Results in {output_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()
