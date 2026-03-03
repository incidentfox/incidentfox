"""
Converts MessageContent IR to Google Chat Card v2 JSON.

Card v2 reference:
  https://developers.google.com/workspace/chat/api/reference/rest/v1/cards

Key constraints:
  - Max message payload ~256KB
  - Card v2 uses sections with widgets
  - TextParagraph supports basic HTML: <b>, <i>, <a>, <br>, <code>
  - No native markdown in TextParagraph — must convert to HTML
"""

from __future__ import annotations

import html
import json
import re
from typing import Any, Dict, List

from incidentfox_orchestrator.message_builder import (
    ActionButton,
    ContentSection,
    MessageContent,
    Question,
)

# Max total message payload size (leave margin)
MAX_PAYLOAD_BYTES = 200000


def to_card_v2(content: MessageContent) -> Dict[str, Any]:
    """
    Convert MessageContent to a Google Chat Card v2 JSON dict.

    Returns a dict suitable for use as a card in the cardsV2 array:
      {"cardId": "...", "card": to_card_v2(content)}
    """
    card: Dict[str, Any] = {}

    sections: List[Dict[str, Any]] = []
    current_widgets: List[Dict[str, Any]] = []

    for section in content.sections:
        if section.type == "header" and section.level <= 2 and not card.get("header"):
            # Use as card header (first H1/H2 only)
            card["header"] = {
                "title": section.text,
                "subtitle": "IncidentFox",
                "imageUrl": "https://incidentfox-assets.s3.us-west-2.amazonaws.com/slack/logo.png",
                "imageType": "CIRCLE",
            }
        elif section.type == "header":
            # Subsequent headers start a new section
            if current_widgets:
                sections.append({"widgets": current_widgets})
                current_widgets = []
            current_widgets.append(
                {
                    "decoratedText": {
                        "topLabel": "",
                        "text": f"<b>{_escape(section.text)}</b>",
                        "wrapText": True,
                    },
                }
            )
        elif section.type == "divider":
            # Flush current widgets into a section, start fresh
            if current_widgets:
                sections.append({"widgets": current_widgets})
                current_widgets = []
        else:
            widget = _section_to_widget(section)
            if widget:
                current_widgets.append(widget)

    # Questions
    for question in content.questions:
        current_widgets.extend(_question_to_widgets(question))

    # Actions
    action_widgets = _actions_to_widgets(content.actions)
    if action_widgets:
        current_widgets.extend(action_widgets)

    # Footer
    if content.footer:
        current_widgets.append(
            {
                "textParagraph": {"text": f"<i>{_escape(content.footer)}</i>"},
            }
        )

    # Flush remaining widgets
    if current_widgets:
        sections.append({"widgets": current_widgets})

    card["sections"] = sections

    # Enforce size limit
    card_json = json.dumps(card)
    if len(card_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        card = _truncate_card(card)

    return card


def _section_to_widget(section: ContentSection) -> Dict[str, Any] | None:
    """Convert a ContentSection to a Google Chat Card v2 widget."""
    if section.type == "text":
        return {
            "textParagraph": {"text": _markdown_to_html(section.text)},
        }

    elif section.type == "code_block":
        # Google Chat doesn't have great code block support
        # Use <code> tag within textParagraph
        escaped = _escape(section.text)
        # Replace newlines with <br> for display
        escaped = escaped.replace("\n", "<br>")
        return {
            "textParagraph": {
                "text": f"<code>{escaped}</code>",
            },
        }

    elif section.type == "image":
        if section.image_url:
            return {
                "image": {
                    "imageUrl": section.image_url,
                    "altText": section.alt_text or "Image",
                },
            }
        elif section.image_data and section.image_media_type:
            # Google Chat doesn't support data URIs in cards.
            # Show a placeholder text indicating an image was generated.
            return {
                "decoratedText": {
                    "icon": {"knownIcon": "PHOTO"},
                    "text": section.alt_text or "Image generated (view in web UI)",
                    "wrapText": True,
                },
            }
        return None

    elif section.type == "file":
        if section.file_url:
            size_str = ""
            if section.file_size:
                size_kb = section.file_size / 1024
                size_str = (
                    f" ({size_kb:.0f} KB)"
                    if size_kb < 1024
                    else f" ({size_kb / 1024:.1f} MB)"
                )
            return {
                "decoratedText": {
                    "icon": {"knownIcon": "DOCUMENT"},
                    "text": f"{section.filename or 'File'}{size_str}",
                    "bottomLabel": section.text or "",
                    "button": {
                        "text": "Download",
                        "onClick": {"openLink": {"url": section.file_url}},
                    },
                    "wrapText": True,
                },
            }
        elif section.text:
            return {
                "decoratedText": {
                    "icon": {"knownIcon": "DOCUMENT"},
                    "text": section.text,
                    "wrapText": True,
                },
            }
        return None

    elif section.type == "progress":
        return {
            "decoratedText": {
                "text": _escape(section.text),
                "wrapText": True,
            },
        }

    elif section.type == "list":
        if section.style == "ordered":
            items_html = "<br>".join(
                f"{i + 1}. {_escape(item)}" for i, item in enumerate(section.items)
            )
        else:
            items_html = "<br>".join(f"• {_escape(item)}" for item in section.items)
        return {
            "textParagraph": {"text": items_html},
        }

    return None


def _question_to_widgets(question: Question) -> List[Dict[str, Any]]:
    """Convert a Question to Google Chat Card v2 input widgets."""
    widgets: List[Dict[str, Any]] = []

    # Question text
    widgets.append(
        {
            "textParagraph": {"text": f"<b>{_escape(question.text)}</b>"},
        }
    )

    if question.options:
        # Use selectionInput for options
        items = [
            {"text": opt.label, "value": opt.value, "selected": False}
            for opt in question.options
        ]
        input_type = "CHECK_BOX" if question.multi_select else "RADIO_BUTTON"
        widgets.append(
            {
                "selectionInput": {
                    "name": question.question_id,
                    "type": input_type,
                    "items": items,
                },
            }
        )
    else:
        # Free-form text input
        widgets.append(
            {
                "textInput": {
                    "name": question.question_id,
                    "label": "Your answer",
                    "type": "MULTIPLE_LINE",
                },
            }
        )

    return widgets


def _actions_to_widgets(actions: List[ActionButton]) -> List[Dict[str, Any]]:
    """Convert ActionButtons to a Google Chat ButtonList widget."""
    if not actions:
        return []

    buttons: List[Dict[str, Any]] = []
    for action in actions:
        # If it's a URL, use openLink
        if action.value and action.value.startswith(("http://", "https://")):
            buttons.append(
                {
                    "text": action.label,
                    "onClick": {
                        "openLink": {"url": action.value},
                    },
                }
            )
        else:
            # Use action with parameters
            parameters = [{"key": k, "value": str(v)} for k, v in action.data.items()]
            parameters.append({"key": "action_id", "value": action.action_id})

            button: Dict[str, Any] = {
                "text": action.label,
                "onClick": {
                    "action": {
                        "function": action.action_id,
                        "parameters": parameters,
                    },
                },
            }

            if action.style == "primary":
                button["color"] = {
                    "red": 0.0,
                    "green": 0.45,
                    "blue": 0.83,
                    "alpha": 1.0,
                }

            buttons.append(button)

    return [{"buttonList": {"buttons": buttons}}]


# ---------------------------------------------------------------------------
# Markdown → HTML helpers
# ---------------------------------------------------------------------------

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_STRIKETHROUGH_RE = re.compile(r"~~(.+?)~~")


def _markdown_to_html(text: str) -> str:
    """
    Convert basic markdown to HTML suitable for Google Chat TextParagraph.

    Supports: bold, italic, inline code, links, strikethrough, line breaks.
    """
    # Escape HTML entities first (before adding our own tags)
    # But we need to be careful not to double-escape
    text = _escape(text)

    # Apply markdown conversions (on escaped text, so patterns use escaped chars)
    # Since we escaped first, ** becomes **  (no change, still works)
    # We need to work on the original text instead
    # Let's redo: convert markdown THEN escape non-markdown text

    # Actually, let's just do it properly:
    return _convert_markdown(text)


def _convert_markdown(text: str) -> str:
    """Convert markdown to HTML, handling escaping correctly."""
    # We receive already-escaped text, so markdown patterns still work
    # (** and * are not HTML special chars)

    # Bold: **text** → <b>text</b>
    text = _BOLD_RE.sub(r"<b>\1</b>", text)

    # Italic: *text* → <i>text</i> (must run after bold)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)

    # Strikethrough: ~~text~~ → <s>text</s>
    text = _STRIKETHROUGH_RE.sub(r"<s>\1</s>", text)

    # Inline code: `text` → <code>text</code>
    text = _INLINE_CODE_RE.sub(r"<code>\1</code>", text)

    # Links: [text](url) → <a href="url">text</a>
    text = _LINK_RE.sub(r'<a href="\2">\1</a>', text)

    # Line breaks
    text = text.replace("\n", "<br>")

    return text


def _escape(text: str) -> str:
    """Escape HTML special characters."""
    return html.escape(text, quote=False)


def _truncate_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce card size by truncating sections."""
    sections = card.get("sections", [])

    while (
        len(json.dumps(card).encode("utf-8")) > MAX_PAYLOAD_BYTES and len(sections) > 2
    ):
        sections.pop(-2)  # Remove second-to-last section (keep first + last)

    if len(json.dumps(card).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        card["sections"] = [
            {
                "widgets": [
                    {
                        "textParagraph": {
                            "text": "Result too large to display in card. "
                            "Please view the full result in the web interface.",
                        },
                    },
                ],
            },
        ]

    return card
