#!/usr/bin/env python3
"""
Table Converter - Convert Markdown tables to Slack table blocks

Uses mistune AST parser to detect tables, then regex to remove them from text.
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Union

import mistune


class PreformattedText:
    """
    Wrapper for text that's already in Slack mrkdwn format.
    This text should bypass markdown conversion.
    """

    def __init__(self, text: str):
        self.text = text

    def __str__(self):
        return self.text


def extract_and_convert_all_tables(
    text: str,
) -> List[Union[str, dict, PreformattedText]]:
    """
    Extract markdown tables from text and convert to Slack format.

    SLACK LIMITATION: Only ONE table block allowed per message!
    Strategy: First table → native Slack table block
              Additional tables → PreformattedText (already in Slack mrkdwn format)

    Returns a list of segments:
    - str: Raw text (needs markdown conversion)
    - dict: Native Slack table block
    - PreformattedText: Pre-formatted text (skip markdown conversion)
    """
    if not text:
        return [text]

    result = []
    remaining_text = text
    table_count = 0

    while remaining_text:
        # Try to extract the first table from remaining text
        text_before, table_block, text_after = extract_and_convert_table(remaining_text)

        if not table_block:
            # No more tables found, add remaining text and break
            if remaining_text.strip():
                result.append(remaining_text)
            break

        # Add text before table (if any)
        if text_before.strip():
            result.append(text_before)

        table_count += 1

        if table_count == 1:
            # First table: Use native Slack table block
            result.append(table_block)
        else:
            # Additional tables: Convert to formatted text (Slack limitation: only 1 table per message)
            formatted_table = _convert_table_to_text(table_block)
            # Wrap in PreformattedText to indicate it's already in Slack format (bypass markdown conversion)
            result.append(PreformattedText(formatted_table))

        # Continue with text after table
        remaining_text = text_after

    return result if result else [text]


def _convert_table_to_text(table_block: dict) -> str:
    """
    Convert a table block to mobile-friendly card layout (when native table can't be used).

    Uses a stacked card format that works well on both desktop and mobile:
    - Each row becomes a separate card
    - Key-value pairs with triangular bullets (‣) for consistency
    - Proper spacing and visual hierarchy
    """
    if not table_block or "rows" not in table_block:
        return ""

    rows = table_block["rows"]
    if not rows:
        return ""

    # Extract headers (first row) and data rows
    headers = [cell.get("text", "") for cell in rows[0]]
    data_rows = [[cell.get("text", "") for cell in row] for row in rows[1:]]

    if not data_rows:
        return ""

    cards = []

    # Create a card for each row
    for row_num, row_data in enumerate(data_rows, 1):
        card_lines = []

        # Row number/identifier (if there are multiple rows)
        if len(data_rows) > 1:
            card_lines.append(f"*{row_num}.*")

        # Key-value pairs with triangular bullet (‣) for consistency
        for header, value in zip(headers, row_data):
            if value:  # Only show non-empty values
                card_lines.append(f"‣ *{header}*: {value}")

        cards.append("\n".join(card_lines))

    # Join cards with blank lines
    return "\n\n".join(cards)


def extract_and_convert_table(text: str) -> Tuple[str, Optional[dict], str]:
    """
    Extract first markdown table from text and convert to Slack table block.

    Uses mistune AST parser to find tables, then regex to split text.

    Returns:
        Tuple of (text_before_table, table_block or None, text_after_table)
    """
    if not text:
        return text, None, ""

    # Parse markdown into AST with table plugin enabled
    markdown = mistune.create_markdown(renderer=None, plugins=["table"])
    tokens = markdown(text)

    # Find first table in AST
    def find_table(tokens_list: List[Dict[str, Any]]) -> Optional[Dict]:
        """Recursively find first table token in AST."""
        if not isinstance(tokens_list, list):
            tokens_list = [tokens_list]

        for token in tokens_list:
            if token.get("type") == "table":
                return token

            # Check children
            if "children" in token and token["children"]:
                result = find_table(token["children"])
                if result:
                    return result

        return None

    table_token = find_table(tokens)

    if not table_token:
        return text, None, ""

    # Convert table token to Slack format
    table_block = _convert_table_ast_to_slack(table_token)

    if not table_block:
        return text, None, ""

    # Split text around table using regex
    # Match markdown table pattern: lines starting with |
    table_pattern = r"\n?\|[^\n]+\|\n\|[\s\-:|]+\|\n(?:\|[^\n]+\|\n?)+"
    match = re.search(table_pattern, text)

    if not match:
        # Fallback: couldn't find table in text, return text as-is
        return text, table_block, ""

    # Split into before and after
    text_before = text[: match.start()].strip()
    text_after = text[match.end() :].strip()

    return text_before, table_block, text_after


def _convert_table_ast_to_slack(table_token: Dict[str, Any]) -> Optional[dict]:
    """Convert mistune table AST to Slack table block."""
    if not table_token or table_token.get("type") != "table":
        return None

    rows = []

    # Get table head (headers)
    # Note: table_head cells are direct children, not wrapped in table_row
    table_head = None
    for child in table_token.get("children", []):
        if child.get("type") == "table_head":
            table_head = child
            break

    if table_head:
        header_row = []
        for cell in table_head.get("children", [])[:20]:  # Max 20 columns
            if cell.get("type") == "table_cell":
                cell_text = _extract_text_from_ast(cell)
                header_row.append({"type": "raw_text", "text": cell_text})
        if header_row:
            rows.append(header_row)

    # Get table body (data rows)
    table_body = None
    for child in table_token.get("children", []):
        if child.get("type") == "table_body":
            table_body = child
            break

    if table_body:
        for row in table_body.get("children", [])[:99]:  # Max 100 total rows
            if row.get("type") == "table_row":
                data_row = []
                for cell in row.get("children", [])[:20]:  # Max 20 columns
                    if cell.get("type") == "table_cell":
                        cell_text = _extract_text_from_ast(cell)
                        data_row.append({"type": "raw_text", "text": cell_text})

                # Pad row to match header column count
                if rows and len(data_row) < len(rows[0]):
                    while len(data_row) < len(rows[0]):
                        data_row.append({"type": "raw_text", "text": ""})

                if data_row:
                    rows.append(data_row)

    if not rows:
        return None

    return {"type": "table", "rows": rows}


def _extract_text_from_ast(token: Dict[str, Any]) -> str:
    """Extract plain text from AST token recursively."""
    if not token:
        return ""

    # If it's a text token, return its raw content
    if token.get("type") == "text":
        return token.get("raw", "")

    # If it has children, recursively extract text
    if "children" in token and token["children"]:
        texts = []
        for child in token["children"]:
            texts.append(_extract_text_from_ast(child))
        return "".join(texts)

    # Fallback: try 'raw' field
    return token.get("raw", "")
