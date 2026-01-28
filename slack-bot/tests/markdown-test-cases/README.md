# Markdown Test Cases

This directory contains test samples for validating the markdown to Slack Block Kit conversion pipeline.

## Purpose

These markdown files test the `markdown_utils.py` module's ability to convert various markdown formats into Slack's Block Kit format. The converter handles:

- Basic markdown formatting (bold, italic, code, links)
- Tables (converted to native Slack table blocks)
- Lists and nested structures
- Code blocks
- Pre-formatted text

## Structure

```
markdown-test-cases/
├── README.md           # This file
├── test_blocks.py      # Conversion script
├── inputs/             # Markdown test samples (*.md)
└── outputs/            # Generated Block Kit JSON (*.json)
```

## Usage

Run the conversion script to process all markdown samples:

```bash
cd tests/markdown-test-cases
python test_blocks.py
```

This will:
1. Read all `.md` files from `inputs/`
2. Convert them to Slack Block Kit format
3. Save JSON outputs to `outputs/`

You can then copy/paste the JSON from `outputs/` into [Slack's Block Kit Builder](https://app.slack.com/block-kit-builder) to preview how they render.

## Single File Mode

To test a specific markdown file:

```bash
python test_blocks.py path/to/file.md
```

This outputs JSON to stdout.

## Adding New Test Cases

To add a new test case:
1. Create a new `.md` file in `inputs/` with your markdown content
2. Run `python test_blocks.py` to generate the output
3. Verify the output in Block Kit Builder
