"""
Platform-agnostic message builder.

Defines a structured intermediate representation (IR) for rich messages and
provides builder functions that convert InvestigationState into MessageContent.
Platform-specific formatters (teams_formatter, gchat_formatter) then convert
MessageContent into Adaptive Card JSON or Google Chat Card v2 JSON.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from incidentfox_orchestrator.message_state import InvestigationState, ToolInfo


# ---------------------------------------------------------------------------
# Intermediate Representation
# ---------------------------------------------------------------------------


@dataclass
class ContentSection:
    """A single content element in a message."""

    type: str  # "header", "text", "code_block", "divider", "image", "progress", "list", "file"
    text: str = ""
    language: str = ""  # For code blocks
    image_url: str = ""
    image_data: str = ""  # Base64-encoded image data
    image_media_type: str = ""  # e.g. "image/png"
    alt_text: str = ""
    level: int = 1  # For headers (1-3)
    items: List[str] = field(default_factory=list)  # For list type
    style: str = ""  # "ordered" or "unordered" for lists
    # File attachment fields
    filename: str = ""
    file_url: str = ""
    file_size: int = 0


@dataclass
class ActionButton:
    """An interactive button in a message."""

    label: str
    action_id: str
    value: str = ""
    style: str = "default"  # "default", "primary", "destructive"
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QuestionOption:
    """An option in an interactive question."""

    label: str
    value: str
    description: str = ""


@dataclass
class Question:
    """An interactive question for the user."""

    text: str
    options: List[QuestionOption] = field(default_factory=list)
    multi_select: bool = False
    question_id: str = ""


@dataclass
class MessageContent:
    """Platform-agnostic message content, ready for formatter conversion."""

    sections: List[ContentSection] = field(default_factory=list)
    actions: List[ActionButton] = field(default_factory=list)
    questions: List[Question] = field(default_factory=list)
    footer: str = ""


# ---------------------------------------------------------------------------
# Builder Functions
# ---------------------------------------------------------------------------

# Icons for progress display (Unicode, works on both platforms)
ICON_THINKING = "\U0001f9e0"  # 🧠
ICON_TOOL = "\U0001f527"  # 🔧
ICON_DONE = "\u2705"  # ✅
ICON_ERROR = "\u274c"  # ❌
ICON_LOADING = "\u23f3"  # ⏳


def build_progress_content(state: InvestigationState) -> MessageContent:
    """
    Build a progress message showing current investigation status.

    Shows completed thoughts, current thought, and running tool.
    """
    sections: List[ContentSection] = []

    sections.append(ContentSection(
        type="header",
        text="Investigation in progress",
        level=2,
    ))

    # Show completed thoughts
    for i, thought in enumerate(state.thoughts):
        icon = ICON_DONE if thought.completed else ICON_THINKING
        thought_text = _truncate(thought.text, 200)
        sections.append(ContentSection(
            type="progress",
            text=f"{icon} {thought_text}",
        ))

        # Show tools for this thought (summarized)
        for tool in thought.tools:
            tool_text = _format_tool_summary(tool)
            sections.append(ContentSection(
                type="text",
                text=f"    {tool_text}",
            ))

    # Show current tool if any
    if state.current_tool and state.current_tool.running:
        tool_name = state.current_tool.name
        detail = _tool_detail(state.current_tool)
        sections.append(ContentSection(
            type="progress",
            text=f"{ICON_LOADING} Running {tool_name}{detail}...",
        ))

    # Stats footer
    stats = f"{state.thought_count} thoughts, {state.tool_count} tools"
    sections.append(ContentSection(type="text", text=stats))

    return MessageContent(sections=sections)


def build_final_content(
    state: InvestigationState,
    run_id: str,
    web_ui_url: str = "",
) -> MessageContent:
    """
    Build the final result message with formatted content and feedback buttons.
    """
    sections: List[ContentSection] = []

    if state.error:
        sections.append(ContentSection(
            type="header",
            text=f"{ICON_ERROR} Investigation Error",
            level=2,
        ))
        sections.append(ContentSection(type="text", text=state.error))
    else:
        sections.append(ContentSection(
            type="header",
            text="Investigation Result",
            level=2,
        ))

        # Parse the markdown result into sections
        result_text = state.final_result or ""
        parsed = _parse_markdown_to_sections(result_text)
        sections.extend(parsed)

    # Images (may come as URL or base64 data from sre-agent)
    if state.result_images:
        for img in state.result_images:
            url = img.get("url", "")
            data = img.get("data", "")
            media_type = img.get("media_type", "image/png")
            alt = img.get("alt", "Investigation image")
            if url:
                sections.append(ContentSection(
                    type="image",
                    image_url=url,
                    alt_text=alt,
                ))
            elif data:
                # Base64-encoded image from agent sandbox
                sections.append(ContentSection(
                    type="image",
                    image_data=data,
                    image_media_type=media_type,
                    alt_text=alt,
                ))

    # File attachments
    if state.result_files:
        for f in state.result_files:
            filename = f.get("filename", "file")
            description = f.get("description", "")
            url = f.get("url", "")
            size = f.get("size", 0)
            display = description or filename
            if url:
                sections.append(ContentSection(
                    type="file",
                    text=display,
                    filename=filename,
                    file_url=url,
                    file_size=size,
                ))
            else:
                # No URL available — just mention the file
                sections.append(ContentSection(
                    type="text",
                    text=f"Attached file: {display}",
                ))

    # Summary stats
    stats = f"{state.thought_count} thoughts, {state.tool_count} tools used"
    sections.append(ContentSection(type="divider"))
    sections.append(ContentSection(type="text", text=stats))

    # Feedback buttons
    actions = [
        ActionButton(
            label="\U0001f44d",
            action_id="feedback_positive",
            style="default",
            data={
                "action_type": "feedback",
                "feedback": "positive",
                "run_id": run_id,
            },
        ),
        ActionButton(
            label="\U0001f44e",
            action_id="feedback_negative",
            style="default",
            data={
                "action_type": "feedback",
                "feedback": "negative",
                "run_id": run_id,
            },
        ),
    ]

    # Optional: link to web UI for full investigation view
    if web_ui_url:
        actions.append(ActionButton(
            label="View Full Result",
            action_id="view_result",
            value=web_ui_url,
            style="primary",
        ))

    return MessageContent(sections=sections, actions=actions)


def build_question_content(
    questions: List[Dict[str, Any]],
    thread_id: str,
) -> MessageContent:
    """Build interactive question form for AskUserQuestion."""
    parsed_questions: List[Question] = []

    for i, q in enumerate(questions):
        options = []
        for opt in q.get("options", []):
            if isinstance(opt, str):
                options.append(QuestionOption(label=opt, value=opt))
            elif isinstance(opt, dict):
                options.append(QuestionOption(
                    label=opt.get("label", ""),
                    value=opt.get("value", opt.get("label", "")),
                    description=opt.get("description", ""),
                ))

        parsed_questions.append(Question(
            text=q.get("question", q.get("text", "")),
            options=options,
            multi_select=q.get("multiSelect", False),
            question_id=f"q{i}",
        ))

    sections = [
        ContentSection(
            type="header",
            text="IncidentFox needs your input",
            level=2,
        ),
    ]

    actions = [
        ActionButton(
            label="Submit",
            action_id="submit_answer",
            style="primary",
            data={"thread_id": thread_id},
        ),
    ]

    return MessageContent(
        sections=sections,
        questions=parsed_questions,
        actions=actions,
    )


# ---------------------------------------------------------------------------
# Markdown → Sections Parser
# ---------------------------------------------------------------------------

# Regex patterns for markdown elements
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_UNORDERED_LIST_RE = re.compile(r"^[-*]\s+(.+)$", re.MULTILINE)


def _parse_markdown_to_sections(text: str) -> List[ContentSection]:
    """
    Parse markdown text into ContentSection elements.

    Handles: headings, code blocks, paragraphs. Keeps it simple —
    we don't need a full markdown AST, just structural separation.
    """
    if not text:
        return []

    sections: List[ContentSection] = []

    # First, extract code blocks (they can contain headings, etc.)
    parts = _CODE_BLOCK_RE.split(text)

    # parts alternates: text, language, code, text, language, code, ...
    i = 0
    while i < len(parts):
        if i + 2 < len(parts) and (i % 3) == 0:
            # Text before code block
            _parse_text_segment(parts[i], sections)
            # Code block
            language = parts[i + 1]
            code = parts[i + 2]
            if code.strip():
                sections.append(ContentSection(
                    type="code_block",
                    text=code.strip(),
                    language=language,
                ))
            i += 3
        else:
            # Remaining text after last code block
            _parse_text_segment(parts[i], sections)
            i += 1

    return sections


def _parse_text_segment(text: str, sections: List[ContentSection]) -> None:
    """Parse a text segment (no code blocks) into sections."""
    if not text.strip():
        return

    lines = text.split("\n")
    current_paragraph: List[str] = []

    for line in lines:
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            # Flush paragraph
            _flush_paragraph(current_paragraph, sections)
            level = len(heading_match.group(1))
            sections.append(ContentSection(
                type="header",
                text=heading_match.group(2).strip(),
                level=level,
            ))
        else:
            current_paragraph.append(line)

    _flush_paragraph(current_paragraph, sections)


def _flush_paragraph(lines: List[str], sections: List[ContentSection]) -> None:
    """Flush accumulated paragraph lines into a text section."""
    text = "\n".join(lines).strip()
    if text:
        sections.append(ContentSection(type="text", text=text))
    lines.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, max_length: int = 200) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def _format_tool_summary(tool: ToolInfo) -> str:
    """Format a tool execution as a one-line summary."""
    icon = ICON_DONE if not tool.running else ICON_LOADING
    if tool.success is False:
        icon = ICON_ERROR

    detail = _tool_detail(tool)
    status = ""
    if tool.summary:
        status = f" — {_truncate(tool.summary, 80)}"

    return f"{icon} {tool.name}{detail}{status}"


def _tool_detail(tool: ToolInfo) -> str:
    """Extract a short detail string from a tool's input."""
    if tool.command:
        return f": `{_truncate(tool.command, 60)}`"
    if tool.file_path:
        return f": {tool.file_path}"
    if tool.pattern:
        return f": {tool.pattern}"
    if tool.description:
        return f": {_truncate(tool.description, 60)}"
    return ""
