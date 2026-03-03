"""Unit tests for Google Chat markdown conversion utilities."""

import pytest
from incidentfox_orchestrator.webhooks.gchat_markdown_utils import (
    GCHAT_MESSAGE_CHAR_LIMIT,
    gchat_text,
    split_message,
    truncate_text,
)


class TestGchatText:
    """Test gchat_text() markdown-to-Google Chat conversion."""

    def test_empty_input(self):
        assert gchat_text("") == ""
        assert gchat_text(None) == ""

    def test_plain_text(self):
        assert gchat_text("hello world") == "hello world"

    def test_bold(self):
        assert gchat_text("**hello**") == "*hello*"

    def test_italic(self):
        result = gchat_text("*hello*")
        assert result == "_hello_"

    def test_italic_underscore(self):
        result = gchat_text("_hello_")
        assert result == "_hello_"

    def test_strikethrough(self):
        assert gchat_text("~~hello~~") == "~hello~"

    def test_inline_code(self):
        assert gchat_text("`hello`") == "`hello`"

    def test_code_block(self):
        result = gchat_text("```\nprint('hi')\n```")
        assert "```" in result
        assert "print('hi')" in result

    def test_link(self):
        result = gchat_text("[Example](https://example.com)")
        assert result == "<https://example.com|Example>"

    def test_link_no_text(self):
        result = gchat_text("https://example.com")
        assert "example.com" in result

    def test_image_as_link(self):
        result = gchat_text("![alt text](https://example.com/img.png)")
        assert "<https://example.com/img.png|alt text>" in result

    def test_heading_h1(self):
        result = gchat_text("# Title")
        assert "*Title*" in result

    def test_heading_h2(self):
        result = gchat_text("## Section")
        assert "*Section*" in result

    def test_heading_h3(self):
        result = gchat_text("### Subsection")
        assert "*Subsection*" in result

    def test_heading_h4(self):
        result = gchat_text("#### Minor")
        assert "*Minor*" in result

    def test_heading_no_nested_bold(self):
        """Heading with bold content should not produce nested bold markers."""
        result = gchat_text("## **Already Bold**")
        # Should be *Already Bold* not *(*Already Bold*)*
        assert "**" not in result
        assert "*Already Bold*" in result

    def test_bullet_list(self):
        result = gchat_text("- item 1\n- item 2\n- item 3")
        assert "- item 1" in result
        assert "- item 2" in result
        assert "- item 3" in result

    def test_nested_list(self):
        md = "- parent\n  - child"
        result = gchat_text(md)
        assert "- parent" in result
        assert "- child" in result

    def test_blockquote(self):
        result = gchat_text("> quoted text")
        assert "> quoted text" in result

    def test_horizontal_rule(self):
        result = gchat_text("above\n\n---\n\nbelow")
        assert "---" in result
        assert "above" in result
        assert "below" in result

    def test_mixed_formatting(self):
        md = "**bold** and _italic_ and `code`"
        result = gchat_text(md)
        assert "*bold*" in result
        assert "_italic_" in result
        assert "`code`" in result

    def test_complex_agent_output(self):
        """Test with typical agent investigation output."""
        md = (
            "## Investigation Summary\n\n"
            "The **checkout service** is experiencing high error rates.\n\n"
            "### Root Cause\n\n"
            "A recent deployment introduced a bug in the payment processing module.\n\n"
            "### Evidence\n\n"
            "- Error rate spiked from 0.1% to 15% at 14:30 UTC\n"
            "- Correlates with deployment `v2.3.1` at 14:28 UTC\n"
            "- Logs show `NullPointerException` in `PaymentService.process()`\n\n"
            "### Recommendations\n\n"
            "1. Roll back to `v2.3.0`\n"
            "2. Fix the null check in [PaymentService.java](https://github.com/example)\n"
        )
        result = gchat_text(md)
        # Headings rendered as bold
        assert "*Investigation Summary*" in result
        assert "*Root Cause*" in result
        # Bold text
        assert "*checkout service*" in result
        # Code spans preserved
        assert "`v2.3.1`" in result
        assert "`NullPointerException`" in result
        # Links converted
        assert "<https://github.com/example|PaymentService.java>" in result
        # Bullets present
        assert "- Error rate" in result or "Error rate" in result

    def test_table(self):
        """Tables should be rendered (mistune table plugin enabled)."""
        md = "| Name | Value |\n|------|-------|\n| CPU | 80% |\n| Mem | 60% |"
        result = gchat_text(md)
        assert "CPU" in result
        assert "80%" in result

    def test_angle_brackets_escaped(self):
        """Literal < and > should not be interpreted as link syntax."""
        result = gchat_text("Use x < 10 and y > 5")
        assert "&lt;" in result
        assert "&gt;" in result

    def test_html_in_markdown_escaped(self):
        """HTML tags in markdown should be escaped."""
        result = gchat_text("Hello <b>world</b>")
        assert "<b>" not in result

    def test_collapse_triple_newlines(self):
        md = "line1\n\n\n\nline2"
        result = gchat_text(md)
        assert "\n\n\n" not in result


class TestTruncateText:
    """Test truncate_text()."""

    def test_short_text_unchanged(self):
        assert truncate_text("hello", 100) == "hello"

    def test_truncate_at_paragraph(self):
        text = "First paragraph.\n\nSecond paragraph that is much longer."
        result = truncate_text(text, 30)
        assert result.endswith("...")
        assert len(result) <= 30

    def test_truncate_at_sentence(self):
        text = "First sentence. Second sentence that goes on and on."
        result = truncate_text(text, 30)
        assert result.endswith("...")

    def test_truncate_at_word(self):
        text = "word " * 100
        result = truncate_text(text, 30)
        assert result.endswith("...")
        assert len(result) <= 30

    def test_hard_truncate(self):
        text = "a" * 200
        result = truncate_text(text, 50)
        assert result.endswith("...")
        assert len(result) <= 50

    def test_default_limit(self):
        assert truncate_text("short") == "short"


class TestSplitMessage:
    """Test split_message()."""

    def test_empty(self):
        assert split_message("") == []
        assert split_message(None) == []

    def test_short_message_single_chunk(self):
        assert split_message("hello") == ["hello"]

    def test_within_limit(self):
        text = "a" * 100
        assert split_message(text, 200) == [text]

    def test_splits_on_paragraph_boundary(self):
        para1 = "a" * 50
        para2 = "b" * 50
        text = f"{para1}\n\n{para2}"
        chunks = split_message(text, 60)
        assert len(chunks) == 2
        assert chunks[0] == para1
        assert chunks[1] == para2

    def test_splits_on_newline(self):
        line1 = "a" * 50
        line2 = "b" * 50
        text = f"{line1}\n{line2}"
        chunks = split_message(text, 60)
        assert len(chunks) == 2

    def test_hard_split_long_line(self):
        text = "a" * 200
        chunks = split_message(text, 100)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_default_limit(self):
        short = "hello"
        assert split_message(short) == [short]

    def test_realistic_long_output(self):
        """Simulate a realistic agent output that exceeds the limit."""
        sections = [f"## Section {i}\n\nContent for section {i}. " * 10 for i in range(20)]
        text = "\n\n".join(sections)
        chunks = split_message(text, GCHAT_MESSAGE_CHAR_LIMIT)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= GCHAT_MESSAGE_CHAR_LIMIT
        # All content preserved
        reassembled = "\n\n".join(chunks)
        for i in range(20):
            assert f"Section {i}" in reassembled
