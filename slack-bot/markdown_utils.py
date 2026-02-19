#!/usr/bin/env python3
"""
Markdown Utilities - Convert standard Markdown to Slack mrkdwn format

Uses mistune (battle-tested markdown parser) for proper AST-based conversion.

Key differences (Markdown -> Slack mrkdwn):
- **bold** -> *bold*
- *italic* or _italic_ -> _italic_
- ~~strike~~ -> ~strike~
- [text](url) -> <url|text>
- # Heading -> *Heading*
- Code blocks and inline code work the same
- &, <, > must be escaped as &amp; &lt; &gt; (except in links)

Reference: https://api.slack.com/reference/surfaces/formatting
"""

import mistune

# Em space for indentation (Slack collapses regular ASCII spaces)
EM_SPACE = "\u2003"


class SlackRenderer(mistune.BaseRenderer):
    """Custom mistune renderer that outputs Slack mrkdwn format with visual hierarchy."""

    NAME = "slack"

    def __init__(self):
        super().__init__()
        self.list_depth = 0  # Track nesting level for child bullets
        self.in_mixed_list = False  # Track if current list has items with nested children (for visual consistency)

    def _get_children(self, token, state) -> str:
        """Render children tokens to string."""
        children = token.get("children")
        if children:
            return self.render_tokens(children, state)
        return token.get("raw", "")

    # Inline elements - mistune v3 passes (token, state)
    def text(self, token, state) -> str:
        """Escape special Slack characters, preserving Slack special syntax."""
        text = token["raw"]

        # Escape & first (before we add more &)
        text = text.replace("&", "&amp;")

        # Preserve Slack special syntax before escaping < >
        # Patterns: <@U123>, <#C123>, <!here>, <!channel>, <!everyone>,
        #           <!subteam^ID>, <!date^...>, <url|text>
        import re

        # Extract and preserve Slack special patterns
        slack_patterns = []

        def preserve_slack(match):
            slack_patterns.append(match.group(0))
            return f"__SLACK_{len(slack_patterns) - 1}__"

        # Match Slack special syntax:
        # <@U123> - user mention
        # <#C123> - channel link
        # <!here>, <!channel>, <!everyone> - special mentions
        # <!subteam^ID> - group mention
        # <!date^timestamp^format|fallback> - date formatting
        # <https://...|text> - explicit links (already handled by mistune link())
        text = re.sub(r"<(?:@[\w]+|#[\w]+|![^>]+)>", preserve_slack, text)

        # Now escape remaining < > (not part of Slack syntax)
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")

        # Restore Slack patterns
        for i, pattern in enumerate(slack_patterns):
            text = text.replace(f"__SLACK_{i}__", pattern)

        return text

    def strong(self, token, state) -> str:
        """Bold: **text** -> *text*"""
        text = self._get_children(token, state)
        return f"*{text}*"

    def emphasis(self, token, state) -> str:
        """Italic: *text* or _text_ -> _text_"""
        text = self._get_children(token, state)
        return f"_{text}_"

    def strikethrough(self, token, state) -> str:
        """Strikethrough: ~~text~~ -> ~text~"""
        text = self._get_children(token, state)
        return f"~{text}~"

    def link(self, token, state) -> str:
        """Link: [text](url) -> <url|text>"""
        text = self._get_children(token, state)
        url = token["attrs"]["url"]
        if text:
            return f"<{url}|{text}>"
        return f"<{url}>"

    def codespan(self, token, state) -> str:
        """Inline code: `code` -> `code`"""
        return f"`{token['raw']}`"

    def linebreak(self, token, state) -> str:
        """Line break."""
        return "\n"

    def softbreak(self, token, state) -> str:
        """Soft break (typically a space or newline)."""
        return "\n"

    def image(self, token, state) -> str:
        """Image: just show as link in Slack."""
        alt = token.get("alt", "image")
        url = token["attrs"]["url"]
        return f"<{url}|{alt}>"

    def inline_html(self, token, state) -> str:
        """Inline HTML: escape it like regular text."""
        html = token.get("raw", "")
        # Escape HTML entities for Slack mrkdwn
        html = html.replace("&", "&amp;")
        html = html.replace("<", "&lt;")
        html = html.replace(">", "&gt;")
        return html

    # Block elements
    def paragraph(self, token, state) -> str:
        """Paragraph."""
        text = self._get_children(token, state)
        return f"{text}\n\n"

    def heading(self, token, state) -> str:
        """
        Heading hierarchy optimized for LLM output:

        - H1 (#): Use special __HEADER__ marker (converted to header block)
          Rare in LLM output, usually plain text like "Overview"
        - H2-H3 (## ###): Bold with extra spacing (prominent subsection)
          Common in LLM output, often has code/formatting
        - H4-H6 (####...): Just bold, minimal spacing (minor detail)

        This creates clear visual hierarchy while preserving formatting support.
        """
        level = token["attrs"]["level"]
        text = self._get_children(token, state)

        # Strip any existing bold markers from text for consistency
        # Handle both cases:
        # 1. Entire text is bolded: *text* -> text
        # 2. Text contains bold at start or end (e.g., emoji + bold)
        import re

        # Remove pairs of * that would create nested bold
        # Match: *...* but only complete pairs
        if text.startswith("*") and text.endswith("*") and len(text) > 2:
            text = text[1:-1]
        elif "*" in text:
            # If there are * inside (from nested strong/em), remove them
            # to avoid nested bold rendering issues
            # Only strip if they're paired (opening and closing)
            text = re.sub(r"\*([^*]+)\*", r"\1", text)

        if level == 1:
            # H1 only: Mark for header block conversion (rare, plain text)
            # Using special marker that will be converted to header block in message_builder
            return f"\n__HEADER__{text}__HEADER__\n\n"
        elif level <= 3:
            # H2-H3: Bold with extra spacing (common, needs formatting)
            return f"\n*{text}*\n\n"
        else:
            # H4+: Just bold, minimal spacing
            return f"*{text}*\n"

    def block_code(self, token, state) -> str:
        """Code block: ```code``` -> ```code```"""
        code = token.get("raw", "")
        return f"```\n{code}```\n\n"

    def block_quote(self, token, state) -> str:
        """Block quote: > text -> > text (Slack supports this)"""
        text = self._get_children(token, state)
        lines = text.strip().split("\n")
        quoted = "\n".join(f">{line}" for line in lines)
        return f"{quoted}\n\n"

    def list(self, token, state) -> str:
        """List container - track depth for nested bullets."""
        self.list_depth += 1

        # For top-level lists, pre-scan to detect if any items have nested children
        # This ensures visual consistency in mixed lists (flat + hierarchical items)
        if self.list_depth == 1:
            children = token.get("children", [])
            has_any_nested = any(
                any(child.get("type") == "list" for child in item.get("children", []))
                for item in children
                if item.get("type") == "list_item"
            )
            self.in_mixed_list = has_any_nested

        text = self._get_children(token, state)

        # Nested lists need a leading newline so first child appears on new line
        is_nested = self.list_depth > 1

        self.list_depth -= 1

        # Reset flag when exiting top-level list
        if self.list_depth == 0:
            self.in_mixed_list = False

        # Add leading newline for nested lists
        if is_nested:
            return f"\n{text}\n"
        else:
            return f"{text}\n"

    def list_item(self, token, state) -> str:
        """
        List item rendering:
        - Top-level: ‣ (triangular bullet - light, directional, pairs well with ↳)
        - Nested (child): ↳ item (arrow shows hierarchy)

        Design principle: Keep it clean and breathable with clear visual hierarchy.
        - Flat lists (no nested children): Stay compact in same section block (single \n)
        - Hierarchical lists (with nested children): Get breathing room (double \n\n)
        """
        text = self._get_children(token, state)
        text = text.strip()

        if self.list_depth > 1:
            # Nested items - downward arrow for hierarchy
            # Use Em spaces for indentation (Slack collapses regular spaces)
            return f"{EM_SPACE}{EM_SPACE}↳ {text}\n"
        else:
            # Top-level - triangular bullet (forward-pointing)
            # Determine spacing based on list context:
            # - If we're in a mixed list (has items with nested children), ALL items get \n\n for visual consistency
            # - Otherwise, only items with nested children get \n\n
            # - Flat items in all-flat lists stay compact with \n

            if self.in_mixed_list:
                # Mixed list: all items get spacing for visual consistency
                return f"‣ {text}\n\n"
            else:
                # All-flat list: items stay compact
                return f"‣ {text}\n"

    def thematic_break(self, token, state) -> str:
        """Horizontal rule: --- -> ---"""
        return "---\n\n"

    def blank_line(self, token, state) -> str:
        """Blank line."""
        return "\n"

    def block_text(self, token, state) -> str:
        """Block text (used in list items)."""
        return self._get_children(token, state)

    def newline(self, token, state) -> str:
        """Newline token."""
        return ""

    def __getattr__(self, name: str):
        """Fallback for any missing render methods - just render children or raw."""

        def fallback(token, state):
            if "children" in token:
                return self.render_tokens(token["children"], state)
            return token.get("raw", "")

        return fallback


# Create the markdown parser with Slack renderer
# Enable strikethrough plugin
_slack_md = mistune.create_markdown(
    renderer=SlackRenderer(),
    plugins=["strikethrough"],
)


def slack_mrkdwn(text: str) -> str:
    """
    Convert standard Markdown to Slack mrkdwn format.

    Uses mistune for proper AST-based parsing - handles all edge cases
    like nested formatting, malformed input, etc.

    Args:
        text: Standard markdown text

    Returns:
        Slack mrkdwn formatted text
    """
    if not text:
        return ""

    result = _slack_md(text)

    # Clean up extra whitespace
    result = result.strip()

    # Collapse multiple newlines
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")

    return result


def truncate_text(text: str, max_length: int = 3000, suffix: str = "...") -> str:
    """
    Truncate text to a maximum length, trying to break at a natural point.

    Args:
        text: Text to truncate
        max_length: Maximum length (default 3000 for Slack blocks)
        suffix: Suffix to add when truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text

    # Leave room for suffix
    target_len = max_length - len(suffix)

    # Try to break at paragraph
    truncated = text[:target_len]
    last_para = truncated.rfind("\n\n")
    if last_para > target_len * 0.5:
        return text[:last_para] + suffix

    # Try to break at sentence
    last_sentence = max(
        truncated.rfind(". "),
        truncated.rfind(".\n"),
        truncated.rfind("! "),
        truncated.rfind("? "),
    )
    if last_sentence > target_len * 0.5:
        return text[: last_sentence + 1] + suffix

    # Try to break at word
    last_space = truncated.rfind(" ")
    if last_space > target_len * 0.5:
        return text[:last_space] + suffix

    # Hard truncate
    return text[:target_len] + suffix


def escape_mrkdwn(text: str) -> str:
    """
    Escape special Slack mrkdwn characters.

    Useful when you want to display text literally without formatting.

    Args:
        text: Text to escape

    Returns:
        Escaped text
    """
    # Escape special characters
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def format_code_output(output: str, max_lines: int = 20) -> str:
    """
    Format command output for display in Slack.

    Truncates long output and wraps in code block.

    Args:
        output: Raw command output
        max_lines: Maximum lines to show

    Returns:
        Formatted code block
    """
    if not output:
        return "_(no output)_"

    lines = output.split("\n")

    if len(lines) > max_lines:
        # Show first and last lines
        half = max_lines // 2
        omitted = len(lines) - max_lines
        shown_lines = (
            lines[:half]
            + [f"... ({omitted} {'line' if omitted == 1 else 'lines'} omitted) ..."]
            + lines[-half:]
        )
        output = "\n".join(shown_lines)

    return f"```\n{output}\n```"
