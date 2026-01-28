"""
Slack mrkdwn helpers.

Converts common Markdown to Slack mrkdwn format.
Centralized here to avoid circular imports between Slack integration and workflow code.
"""

from __future__ import annotations

import re


def markdown_to_slack_mrkdwn(text: str) -> str:
    """
    Best-effort conversion from common Markdown -> Slack mrkdwn.
    This prevents ugly rendering when the model outputs GitHub-flavored Markdown.

    Key conversions:
    - ### Header -> *Header* (bold, since Slack has no headers)
    - **bold** -> *bold*
    - [label](url) -> <url|label>
    - - bullet -> • bullet
    """
    if not text:
        return ""

    t = text.replace("\r\n", "\n").replace("\r", "\n")

    # Convert markdown links [label](url) -> <url|label>
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"<\2|\1>", t)

    # Convert **bold** -> *bold* (must be done before header conversion)
    t = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", t)

    # Convert headings to bold text (Slack has no native headers)
    # Pattern: ### Header text at start of line
    # Also handle case where header runs into next text without newline (run-on headers)
    def _convert_header(m):
        title = m.group(2).strip()

        # Detect run-on headers where title word merges with next sentence
        # e.g., "SummaryThe payment service..." -> "Summary" + "The payment service..."
        # Look for lowercase->uppercase transition (camelCase boundary)
        for i, char in enumerate(title[1:], 1):
            if char.isupper() and title[i - 1].islower():
                # Found camelCase boundary - split here
                header_part = title[:i]
                rest_part = title[i:]
                return f"*{header_part}*\n{rest_part}"

        return f"*{title}*"

    # Match headers: ### followed by optional space and content
    # This handles both "### Header" and "###Header" and "### HeaderText"
    t = re.sub(
        r"^(#{1,6})\s*([^\n]+)$",
        _convert_header,
        t,
        flags=re.MULTILINE,
    )

    # Convert dash bullets to Slack bullets
    t = re.sub(r"^(\s*)-\s+", r"\1• ", t, flags=re.MULTILINE)

    # Convert Markdown tables into code blocks (simple heuristic)
    lines = t.split("\n")
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # detect header + separator like: | a | b | + |---|---|
        if (
            "|" in line
            and i + 1 < len(lines)
            and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1])
        ):
            out_lines.append("```")
            # consume table block
            while i < len(lines) and "|" in lines[i]:
                out_lines.append(lines[i])
                i += 1
            out_lines.append("```")
            continue
        out_lines.append(line)
        i += 1

    return "\n".join(out_lines).strip()


def chunk_mrkdwn(text: str, limit: int = 2900) -> list[str]:
    """
    Split mrkdwn into chunks small enough for Slack section blocks (<= 3000 chars).
    """
    t = (text or "").strip()
    if not t:
        return ["_No details available yet._"]

    if len(t) <= limit:
        return [t]

    # Prefer paragraph boundaries
    parts = [p.strip() for p in t.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for part in parts:
        candidate = (buf + "\n\n" + part).strip() if buf else part
        if len(candidate) <= limit:
            buf = candidate
            continue

        if buf:
            chunks.append(buf)
            buf = ""

        # If a single paragraph is too large, split on newlines
        while len(part) > limit:
            break_point = part.rfind("\n", 0, limit)
            if break_point == -1:
                break_point = limit
            chunks.append(part[:break_point].strip())
            part = part[break_point:].strip()
        if part:
            buf = part

    if buf:
        chunks.append(buf)

    return [c for c in chunks if c]
