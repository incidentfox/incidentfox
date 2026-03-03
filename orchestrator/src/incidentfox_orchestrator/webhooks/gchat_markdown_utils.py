"""
Google Chat Markdown Utilities - Convert standard Markdown to Google Chat text format.

Uses mistune (AST-based parser) for reliable conversion, mirroring the approach
in slack-bot/markdown_utils.py.

Google Chat text messages use a format very similar to Slack mrkdwn:
- *bold*      (from **bold**)
- _italic_    (from *italic*)
- ~strike~    (from ~~strike~~)
- `code`      (unchanged)
- ```block``` (unchanged)
- <url|text>  (from [text](url))
- * item      (standard bullet lists)

Reference: https://developers.google.com/workspace/chat/format-messages
"""

from __future__ import annotations

import re

import mistune

# Google Chat text message limit (characters).
# The REST API enforces ~4096 chars per message for the text field.
GCHAT_MESSAGE_CHAR_LIMIT = 4096


class GoogleChatRenderer(mistune.BaseRenderer):
    """Mistune renderer that outputs Google Chat text format."""

    NAME = "google_chat"

    def __init__(self):
        super().__init__()
        self.list_depth = 0

    def _get_children(self, token, state) -> str:
        children = token.get("children")
        if children:
            return self.render_tokens(children, state)
        return token.get("raw", "")

    # -- Inline elements --

    def text(self, token, state) -> str:
        raw = token["raw"]
        # Escape angle brackets to prevent accidental <url|text> link interpretation.
        # Google Chat uses <...> for links, so bare < > in text (common in logs,
        # comparisons, HTML snippets) could corrupt formatting.
        raw = raw.replace("<", "&lt;")
        raw = raw.replace(">", "&gt;")
        return raw

    def strong(self, token, state) -> str:
        text = self._get_children(token, state)
        return f"*{text}*"

    def emphasis(self, token, state) -> str:
        text = self._get_children(token, state)
        return f"_{text}_"

    def strikethrough(self, token, state) -> str:
        text = self._get_children(token, state)
        return f"~{text}~"

    def link(self, token, state) -> str:
        text = self._get_children(token, state)
        url = token["attrs"]["url"]
        if text:
            return f"<{url}|{text}>"
        return f"<{url}>"

    def codespan(self, token, state) -> str:
        return f"`{token['raw']}`"

    def linebreak(self, token, state) -> str:
        return "\n"

    def softbreak(self, token, state) -> str:
        return "\n"

    def image(self, token, state) -> str:
        alt = self._get_children(token, state) or "image"
        url = token["attrs"]["url"]
        return f"<{url}|{alt}>"

    def inline_html(self, token, state) -> str:
        """Escape HTML tags — Google Chat text doesn't render HTML."""
        html = token.get("raw", "")
        html = html.replace("<", "&lt;")
        html = html.replace(">", "&gt;")
        return html

    # -- Block elements --

    def paragraph(self, token, state) -> str:
        text = self._get_children(token, state)
        return f"{text}\n\n"

    def heading(self, token, state) -> str:
        """Google Chat has no native headings — render as bold text."""
        text = self._get_children(token, state)
        # Strip nested bold markers to avoid *(*text*)*
        if text.startswith("*") and text.endswith("*") and len(text) > 2:
            text = text[1:-1]
        elif "*" in text:
            text = re.sub(r"\*([^*]+)\*", r"\1", text)
        level = token["attrs"]["level"]
        if level <= 3:
            return f"\n*{text}*\n\n"
        return f"*{text}*\n"

    def block_code(self, token, state) -> str:
        code = token.get("raw", "")
        return f"```\n{code}```\n\n"

    def block_quote(self, token, state) -> str:
        text = self._get_children(token, state)
        lines = text.strip().split("\n")
        quoted = "\n".join(f"> {line}" for line in lines)
        return f"{quoted}\n\n"

    def list(self, token, state) -> str:
        self.list_depth += 1
        text = self._get_children(token, state)
        is_nested = self.list_depth > 1
        self.list_depth -= 1

        if is_nested:
            return f"\n{text}"
        return f"{text}\n"

    def list_item(self, token, state) -> str:
        text = self._get_children(token, state).strip()
        if self.list_depth > 1:
            indent = "  " * (self.list_depth - 1)
            return f"{indent}- {text}\n"
        return f"- {text}\n"

    # -- Table elements --

    def table(self, token, state) -> str:
        """Render a table as aligned text (Google Chat has no native tables)."""
        # Extract headers and rows from AST
        headers: list[str] = []
        rows: list[list[str]] = []
        for child in token.get("children", []):
            if child["type"] == "table_head":
                headers = [
                    self._get_children(cell, state)
                    for cell in child.get("children", [])
                    if cell.get("type") == "table_cell"
                ]
            elif child["type"] == "table_body":
                for row in child.get("children", []):
                    if row.get("type") == "table_row":
                        cells = [
                            self._get_children(cell, state)
                            for cell in row.get("children", [])
                            if cell.get("type") == "table_cell"
                        ]
                        rows.append(cells)

        if not headers and not rows:
            return self._get_children(token, state)

        # Render as key-value cards (mobile-friendly, like Slack fallback)
        if not rows:
            return "*" + "* | *".join(headers) + "*\n\n"

        cards = []
        for i, row in enumerate(rows, 1):
            lines = []
            if len(rows) > 1:
                lines.append(f"*{i}.*")
            for header, value in zip(headers, row):
                if value:
                    lines.append(f"- *{header}*: {value}")
            cards.append("\n".join(lines))

        return "\n\n".join(cards) + "\n\n"

    def table_head(self, token, state) -> str:
        return self._get_children(token, state)

    def table_body(self, token, state) -> str:
        return self._get_children(token, state)

    def table_row(self, token, state) -> str:
        return self._get_children(token, state)

    def table_cell(self, token, state) -> str:
        return self._get_children(token, state)

    def thematic_break(self, token, state) -> str:
        return "---\n\n"

    def blank_line(self, token, state) -> str:
        return "\n"

    def block_text(self, token, state) -> str:
        return self._get_children(token, state)

    def newline(self, token, state) -> str:
        return ""

    def __getattr__(self, name: str):
        """Fallback for any missing render methods."""

        def fallback(token, state):
            if "children" in token:
                return self.render_tokens(token["children"], state)
            return token.get("raw", "")

        return fallback


# Markdown parser with Google Chat renderer
_gchat_md = mistune.create_markdown(
    renderer=GoogleChatRenderer(),
    plugins=["strikethrough", "table"],
)


def gchat_text(text: str | None) -> str:
    """
    Convert standard Markdown to Google Chat text format.

    Args:
        text: Standard markdown text (e.g. from Claude agent output)

    Returns:
        Google Chat formatted text
    """
    if not text:
        return ""

    # Reset mutable renderer state (list_depth) before each conversion
    # to prevent corruption if a prior render raised mid-list.
    _gchat_md.renderer.list_depth = 0  # type: ignore[union-attr]
    result = _gchat_md(text)
    result = result.strip()

    # Collapse triple+ newlines
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")

    return result


def truncate_text(text: str | None, max_length: int = GCHAT_MESSAGE_CHAR_LIMIT, suffix: str = "...") -> str:
    """
    Truncate text to max_length, breaking at a natural point.
    """
    if len(text) <= max_length:
        return text

    target_len = max_length - len(suffix)

    # Try paragraph break
    truncated = text[:target_len]
    last_para = truncated.rfind("\n\n")
    if last_para > target_len * 0.5:
        return text[:last_para] + suffix

    # Try sentence break
    last_sentence = max(
        truncated.rfind(". "),
        truncated.rfind(".\n"),
        truncated.rfind("! "),
        truncated.rfind("? "),
    )
    if last_sentence > target_len * 0.5:
        return text[: last_sentence + 1] + suffix

    # Try word break
    last_space = truncated.rfind(" ")
    if last_space > target_len * 0.5:
        return text[:last_space] + suffix

    return text[:target_len] + suffix


def split_message(text: str | None, max_length: int = GCHAT_MESSAGE_CHAR_LIMIT) -> list[str]:
    """
    Split a long message into chunks that fit within Google Chat's limit.

    Splits on paragraph boundaries (double newlines), falling back to
    single newlines, then hard-truncating as a last resort.

    Args:
        text: Formatted text to split
        max_length: Maximum characters per chunk

    Returns:
        List of message chunks
    """
    if not text or len(text) <= max_length:
        return [text] if text else []

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Find a split point within the limit
        candidate = remaining[:max_length]

        # Prefer splitting on paragraph boundary
        split_at = candidate.rfind("\n\n")
        if split_at > max_length * 0.3:
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip("\n")
            continue

        # Fall back to single newline
        split_at = candidate.rfind("\n")
        if split_at > max_length * 0.3:
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip("\n")
            continue

        # Hard truncate at word boundary
        split_at = candidate.rfind(" ")
        if split_at > max_length * 0.3:
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()
            continue

        # Absolute last resort
        chunks.append(remaining[:max_length])
        remaining = remaining[max_length:]

    return chunks
