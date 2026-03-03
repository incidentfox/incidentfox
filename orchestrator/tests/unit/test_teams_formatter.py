"""Unit tests for teams_formatter.py (IR → Adaptive Card)."""

import json

from incidentfox_orchestrator.message_builder import (
    ActionButton,
    ContentSection,
    MessageContent,
    Question,
    QuestionOption,
)
from incidentfox_orchestrator.message_builder.teams_formatter import to_adaptive_card


class TestToAdaptiveCard:
    def test_basic_card_structure(self):
        content = MessageContent(
            sections=[ContentSection(type="header", text="Test", level=2)]
        )
        card = to_adaptive_card(content)
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.5"
        assert len(card["body"]) >= 1

    def test_header_sizing(self):
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="H1", level=1),
                ContentSection(type="header", text="H2", level=2),
                ContentSection(type="header", text="H3", level=3),
            ]
        )
        card = to_adaptive_card(content)
        assert card["body"][0]["size"] == "ExtraLarge"
        assert card["body"][1]["size"] == "Large"
        assert card["body"][2]["size"] == "Medium"

    def test_text_section(self):
        content = MessageContent(
            sections=[ContentSection(type="text", text="Hello world")]
        )
        card = to_adaptive_card(content)
        assert card["body"][0]["type"] == "TextBlock"
        assert card["body"][0]["text"] == "Hello world"
        assert card["body"][0]["wrap"] is True

    def test_code_block(self):
        content = MessageContent(
            sections=[
                ContentSection(type="code_block", text="print('hi')", language="python")
            ]
        )
        card = to_adaptive_card(content)
        container = card["body"][0]
        assert container["type"] == "Container"
        assert container["style"] == "emphasis"
        assert container["items"][0]["fontType"] == "Monospace"

    def test_divider(self):
        content = MessageContent(sections=[ContentSection(type="divider")])
        card = to_adaptive_card(content)
        assert card["body"][0]["separator"] is True

    def test_image(self):
        content = MessageContent(
            sections=[
                ContentSection(
                    type="image",
                    image_url="https://example.com/img.png",
                    alt_text="Chart",
                )
            ]
        )
        card = to_adaptive_card(content)
        assert card["body"][0]["type"] == "Image"
        assert card["body"][0]["url"] == "https://example.com/img.png"

    def test_feedback_actions(self):
        content = MessageContent(
            sections=[ContentSection(type="text", text="Result")],
            actions=[
                ActionButton(
                    label="\U0001f44d",
                    action_id="feedback_positive",
                    data={
                        "action_type": "feedback",
                        "feedback": "positive",
                        "run_id": "r1",
                    },
                ),
                ActionButton(
                    label="\U0001f44e",
                    action_id="feedback_negative",
                    data={
                        "action_type": "feedback",
                        "feedback": "negative",
                        "run_id": "r1",
                    },
                ),
            ],
        )
        card = to_adaptive_card(content)
        assert "actions" in card
        assert len(card["actions"]) == 2
        assert card["actions"][0]["type"] == "Action.Submit"
        assert card["actions"][0]["data"]["action_type"] == "feedback"

    def test_url_action_becomes_open_url(self):
        content = MessageContent(
            sections=[],
            actions=[
                ActionButton(
                    label="View", action_id="view", value="https://app.example.com"
                )
            ],
        )
        card = to_adaptive_card(content)
        assert card["actions"][0]["type"] == "Action.OpenUrl"
        assert card["actions"][0]["url"] == "https://app.example.com"

    def test_question_choice_set(self):
        content = MessageContent(
            sections=[],
            questions=[
                Question(
                    text="Which service?",
                    question_id="q0",
                    multi_select=False,
                    options=[
                        QuestionOption(label="Auth", value="auth"),
                        QuestionOption(label="API", value="api"),
                    ],
                )
            ],
        )
        card = to_adaptive_card(content)
        # Find ChoiceSet
        choice_sets = [e for e in card["body"] if e.get("type") == "Input.ChoiceSet"]
        assert len(choice_sets) == 1
        assert choice_sets[0]["id"] == "q0"
        assert len(choice_sets[0]["choices"]) == 2

    def test_card_size_truncation(self):
        """Card with very large content should be truncated."""
        sections = [ContentSection(type="text", text="x" * 5000) for _ in range(20)]
        content = MessageContent(sections=sections)
        card = to_adaptive_card(content)
        card_bytes = len(json.dumps(card).encode("utf-8"))
        assert card_bytes <= 28000  # Should be under limit

    def test_footer(self):
        content = MessageContent(
            sections=[ContentSection(type="text", text="body")],
            footer="Powered by IncidentFox",
        )
        card = to_adaptive_card(content)
        footer_blocks = [b for b in card["body"] if b.get("color") == "Light"]
        assert len(footer_blocks) == 1

    # --- Phase 5: File/Image support ---

    def test_base64_image(self):
        content = MessageContent(
            sections=[
                ContentSection(
                    type="image",
                    image_data="iVBORw0KGgoAAAANSUhEU",
                    image_media_type="image/png",
                    alt_text="CPU chart",
                ),
            ]
        )
        card = to_adaptive_card(content)
        img = card["body"][0]
        assert img["type"] == "Image"
        assert img["url"].startswith("data:image/png;base64,")
        assert img["altText"] == "CPU chart"

    def test_file_with_url(self):
        content = MessageContent(
            sections=[
                ContentSection(
                    type="file",
                    text="Thread dump analysis",
                    filename="thread_dump.txt",
                    file_url="https://files.example.com/dump.txt",
                    file_size=51200,
                ),
            ]
        )
        card = to_adaptive_card(content)
        block = card["body"][0]
        assert block["type"] == "TextBlock"
        assert "thread_dump.txt" in block["text"] or "Download" in block["text"]
        assert "https://files.example.com/dump.txt" in block["text"]

    def test_file_without_url(self):
        content = MessageContent(
            sections=[
                ContentSection(
                    type="file",
                    text="Generated report",
                ),
            ]
        )
        card = to_adaptive_card(content)
        block = card["body"][0]
        assert block["type"] == "TextBlock"
        assert "Generated report" in block["text"]

    def test_list_ordered(self):
        content = MessageContent(
            sections=[
                ContentSection(
                    type="list", items=["First", "Second", "Third"], style="ordered"
                ),
            ]
        )
        card = to_adaptive_card(content)
        block = card["body"][0]
        assert "1. First" in block["text"]
        assert "2. Second" in block["text"]

    def test_list_unordered(self):
        content = MessageContent(
            sections=[
                ContentSection(type="list", items=["Alpha", "Beta"], style="unordered"),
            ]
        )
        card = to_adaptive_card(content)
        block = card["body"][0]
        assert "- Alpha" in block["text"]

    def test_progress_section(self):
        content = MessageContent(
            sections=[
                ContentSection(type="progress", text="Analyzing logs..."),
            ]
        )
        card = to_adaptive_card(content)
        block = card["body"][0]
        assert block["type"] == "TextBlock"
        assert "Analyzing logs..." in block["text"]

    # --- Phase 4: Question rendering ---

    def test_question_free_text_input(self):
        content = MessageContent(
            sections=[],
            questions=[
                Question(
                    text="Describe the issue",
                    question_id="q0",
                    multi_select=False,
                    options=[],
                )
            ],
        )
        card = to_adaptive_card(content)
        text_inputs = [e for e in card["body"] if e.get("type") == "Input.Text"]
        assert len(text_inputs) == 1
        assert text_inputs[0]["id"] == "q0"

    def test_question_multi_select(self):
        content = MessageContent(
            sections=[],
            questions=[
                Question(
                    text="Select all affected services",
                    question_id="q0",
                    multi_select=True,
                    options=[
                        QuestionOption(label="Auth", value="auth"),
                        QuestionOption(label="API", value="api"),
                        QuestionOption(label="Web", value="web"),
                    ],
                )
            ],
        )
        card = to_adaptive_card(content)
        choice_sets = [e for e in card["body"] if e.get("type") == "Input.ChoiceSet"]
        assert len(choice_sets) == 1
        assert choice_sets[0]["isMultiSelect"] is True
        assert len(choice_sets[0]["choices"]) == 3
