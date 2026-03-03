"""
Converts MessageContent IR to MS Teams Adaptive Card v1.5 JSON.

Adaptive Card reference:
  https://adaptivecards.io/explorer/

Key constraints:
  - Max card payload ~28KB
  - Teams supports Adaptive Card schema v1.5
  - Text supports a subset of markdown (bold, italic, links, lists)
  - Code blocks need monospace TextBlock in a Container with background
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from incidentfox_orchestrator.message_builder import (
    ActionButton,
    ContentSection,
    MessageContent,
    Question,
)

# Max total card payload size (leave margin for wrapper)
MAX_CARD_BYTES = 26000


def to_adaptive_card(content: MessageContent) -> Dict[str, Any]:
    """
    Convert MessageContent to an Adaptive Card v1.5 JSON dict.

    Returns a dict suitable for use as the 'content' field in a Teams
    Activity attachment with contentType "application/vnd.microsoft.card.adaptive".
    """
    body: List[Dict[str, Any]] = []

    for section in content.sections:
        element = _section_to_element(section)
        if element:
            body.append(element)

    # Questions (input fields)
    for question in content.questions:
        body.extend(_question_to_elements(question))

    # Actions
    actions = [_action_to_element(a) for a in content.actions]

    # Footer
    if content.footer:
        body.append({
            "type": "TextBlock",
            "text": content.footer,
            "size": "Small",
            "color": "Light",
            "wrap": True,
        })

    card: Dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
    }
    if actions:
        card["actions"] = actions

    # Enforce size limit — fall back to truncated text if too large
    card_json = json.dumps(card)
    if len(card_json.encode("utf-8")) > MAX_CARD_BYTES:
        card = _truncate_card(card)

    return card


def _section_to_element(section: ContentSection) -> Dict[str, Any] | None:
    """Convert a ContentSection to an Adaptive Card element."""
    if section.type == "header":
        size = {1: "ExtraLarge", 2: "Large", 3: "Medium"}.get(section.level, "Large")
        return {
            "type": "TextBlock",
            "text": section.text,
            "size": size,
            "weight": "Bolder",
            "wrap": True,
        }

    elif section.type == "text":
        return {
            "type": "TextBlock",
            "text": section.text,
            "wrap": True,
        }

    elif section.type == "code_block":
        return {
            "type": "Container",
            "style": "emphasis",
            "items": [
                {
                    "type": "TextBlock",
                    "text": section.text,
                    "fontType": "Monospace",
                    "wrap": True,
                    "size": "Small",
                }
            ],
        }

    elif section.type == "divider":
        # Adaptive Cards don't have a native divider; use a thin separator
        return {
            "type": "TextBlock",
            "text": " ",
            "separator": True,
            "spacing": "Medium",
        }

    elif section.type == "image":
        if section.image_url:
            return {
                "type": "Image",
                "url": section.image_url,
                "altText": section.alt_text or "Image",
                "size": "Auto",
            }
        elif section.image_data and section.image_media_type:
            # Base64 data URI — Adaptive Cards support data URIs
            data_uri = f"data:{section.image_media_type};base64,{section.image_data}"
            return {
                "type": "Image",
                "url": data_uri,
                "altText": section.alt_text or "Image",
                "size": "Auto",
            }
        return None

    elif section.type == "file":
        # File attachment — show as a link or description
        if section.file_url:
            size_str = ""
            if section.file_size:
                size_kb = section.file_size / 1024
                size_str = f" ({size_kb:.0f} KB)" if size_kb < 1024 else f" ({size_kb / 1024:.1f} MB)"
            return {
                "type": "TextBlock",
                "text": f"\U0001f4ce [{section.filename or 'Download'}]({section.file_url}){size_str}",
                "wrap": True,
            }
        elif section.text:
            return {
                "type": "TextBlock",
                "text": f"\U0001f4ce {section.text}",
                "wrap": True,
            }
        return None

    elif section.type == "progress":
        return {
            "type": "TextBlock",
            "text": section.text,
            "wrap": True,
            "spacing": "Small",
        }

    elif section.type == "list":
        # Render as markdown list in a TextBlock
        if section.style == "ordered":
            items_text = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(section.items))
        else:
            items_text = "\n".join(f"- {item}" for item in section.items)
        return {
            "type": "TextBlock",
            "text": items_text,
            "wrap": True,
        }

    return None


def _question_to_elements(question: Question) -> List[Dict[str, Any]]:
    """Convert a Question to Adaptive Card input elements."""
    elements: List[Dict[str, Any]] = []

    # Question text
    elements.append({
        "type": "TextBlock",
        "text": question.text,
        "wrap": True,
        "weight": "Bolder",
    })

    if question.options:
        # Use Input.ChoiceSet for options
        choices = [
            {"title": opt.label, "value": opt.value}
            for opt in question.options
        ]
        elements.append({
            "type": "Input.ChoiceSet",
            "id": question.question_id,
            "isMultiSelect": question.multi_select,
            "style": "expanded",
            "choices": choices,
        })
    else:
        # Free-form text input
        elements.append({
            "type": "Input.Text",
            "id": question.question_id,
            "placeholder": "Type your answer...",
            "isMultiline": True,
        })

    return elements


def _action_to_element(action: ActionButton) -> Dict[str, Any]:
    """Convert an ActionButton to an Adaptive Card action."""
    element: Dict[str, Any] = {
        "type": "Action.Submit",
        "title": action.label,
        "data": {**action.data, "action_id": action.action_id},
    }

    # Map style
    if action.style == "destructive":
        element["style"] = "destructive"
    elif action.style == "primary":
        element["style"] = "positive"

    # If there's a URL value, use Action.OpenUrl instead
    if action.value and action.value.startswith(("http://", "https://")):
        return {
            "type": "Action.OpenUrl",
            "title": action.label,
            "url": action.value,
        }

    return element


def _truncate_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce card size by truncating body elements until under limit."""
    body = card.get("body", [])

    # Keep header and last few elements, truncate middle
    while len(json.dumps(card).encode("utf-8")) > MAX_CARD_BYTES and len(body) > 3:
        # Remove the second-to-last body element (keep header + footer)
        body.pop(-2)

    # If still too large, add a truncation notice
    if len(json.dumps(card).encode("utf-8")) > MAX_CARD_BYTES:
        card["body"] = [
            body[0] if body else {"type": "TextBlock", "text": "Investigation Result"},
            {
                "type": "TextBlock",
                "text": "Result too large to display in card. "
                "Please view the full result in the web interface.",
                "wrap": True,
            },
        ]
        if card.get("actions"):
            pass  # keep actions

    return card
