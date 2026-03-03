"""Unit tests for gchat_formatter.py (IR → Google Chat Card v2)."""

from incidentfox_orchestrator.message_builder import (
    ActionButton,
    ContentSection,
    MessageContent,
    Question,
    QuestionOption,
)
from incidentfox_orchestrator.message_builder.gchat_formatter import (
    _escape,
    _markdown_to_html,
    to_card_v2,
)


class TestToCardV2:
    def test_basic_card_structure(self):
        content = MessageContent(
            sections=[ContentSection(type="header", text="Test Result", level=1)]
        )
        card = to_card_v2(content)
        assert "header" in card
        assert card["header"]["title"] == "Test Result"
        assert "sections" in card

    def test_text_section(self):
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="Title", level=1),
                ContentSection(type="text", text="Hello world"),
            ]
        )
        card = to_card_v2(content)
        # Text should be in a section widget
        assert len(card["sections"]) >= 1
        widgets = card["sections"][0]["widgets"]
        text_widgets = [w for w in widgets if "textParagraph" in w]
        assert len(text_widgets) >= 1

    def test_code_block(self):
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="Title", level=1),
                ContentSection(type="code_block", text="print('hi')"),
            ]
        )
        card = to_card_v2(content)
        widgets = card["sections"][0]["widgets"]
        code_widgets = [
            w
            for w in widgets
            if "textParagraph" in w and "<code>" in w["textParagraph"]["text"]
        ]
        assert len(code_widgets) == 1

    def test_image_widget(self):
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="Title", level=1),
                ContentSection(
                    type="image",
                    image_url="https://example.com/img.png",
                    alt_text="Chart",
                ),
            ]
        )
        card = to_card_v2(content)
        widgets = card["sections"][0]["widgets"]
        img_widgets = [w for w in widgets if "image" in w]
        assert len(img_widgets) == 1
        assert img_widgets[0]["image"]["imageUrl"] == "https://example.com/img.png"

    def test_divider_creates_new_section(self):
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="Title", level=1),
                ContentSection(type="text", text="Before"),
                ContentSection(type="divider"),
                ContentSection(type="text", text="After"),
            ]
        )
        card = to_card_v2(content)
        # Divider should split into multiple sections
        assert len(card["sections"]) >= 2

    def test_feedback_buttons(self):
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="Result", level=1),
                ContentSection(type="text", text="Done"),
            ],
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
        card = to_card_v2(content)
        # Find buttonList in any section
        all_widgets = []
        for sec in card["sections"]:
            all_widgets.extend(sec.get("widgets", []))
        button_lists = [w for w in all_widgets if "buttonList" in w]
        assert len(button_lists) == 1
        buttons = button_lists[0]["buttonList"]["buttons"]
        assert len(buttons) == 2

    def test_url_action_uses_open_link(self):
        content = MessageContent(
            sections=[ContentSection(type="header", text="Title", level=1)],
            actions=[
                ActionButton(
                    label="View", action_id="view", value="https://example.com"
                )
            ],
        )
        card = to_card_v2(content)
        all_widgets = []
        for sec in card["sections"]:
            all_widgets.extend(sec.get("widgets", []))
        button_lists = [w for w in all_widgets if "buttonList" in w]
        assert len(button_lists) == 1
        button = button_lists[0]["buttonList"]["buttons"][0]
        assert "openLink" in button["onClick"]

    def test_question_selection_input(self):
        content = MessageContent(
            sections=[ContentSection(type="header", text="Q", level=1)],
            questions=[
                Question(
                    text="Which service?",
                    question_id="q0",
                    multi_select=True,
                    options=[
                        QuestionOption(label="Auth", value="auth"),
                        QuestionOption(label="API", value="api"),
                    ],
                )
            ],
        )
        card = to_card_v2(content)
        all_widgets = []
        for sec in card["sections"]:
            all_widgets.extend(sec.get("widgets", []))
        selection_inputs = [w for w in all_widgets if "selectionInput" in w]
        assert len(selection_inputs) == 1
        assert selection_inputs[0]["selectionInput"]["type"] == "CHECK_BOX"


class TestMarkdownToHtml:
    def test_bold(self):
        assert "<b>bold</b>" in _markdown_to_html("**bold**")

    def test_italic(self):
        result = _markdown_to_html("*italic*")
        assert "<i>italic</i>" in result

    def test_inline_code(self):
        assert "<code>code</code>" in _markdown_to_html("`code`")

    def test_link(self):
        result = _markdown_to_html("[click](https://example.com)")
        assert 'href="https://example.com"' in result
        assert ">click</a>" in result

    def test_strikethrough(self):
        assert "<s>struck</s>" in _markdown_to_html("~~struck~~")

    def test_line_breaks(self):
        assert "<br>" in _markdown_to_html("line1\nline2")


class TestToCardV2Phase5:
    """Phase 5: File/Image support in Google Chat Card v2."""

    def test_base64_image_placeholder(self):
        """Google Chat doesn't support data URIs — should show placeholder text."""
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="Title", level=1),
                ContentSection(
                    type="image",
                    image_data="iVBORw0KGgoAAAANSUhEU",
                    image_media_type="image/png",
                    alt_text="CPU chart",
                ),
            ]
        )
        card = to_card_v2(content)
        all_widgets = []
        for sec in card["sections"]:
            all_widgets.extend(sec.get("widgets", []))
        # Should be a decoratedText placeholder, not an image widget
        decorated = [w for w in all_widgets if "decoratedText" in w]
        assert len(decorated) >= 1
        assert "CPU chart" in decorated[0]["decoratedText"]["text"]

    def test_file_with_url(self):
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="Title", level=1),
                ContentSection(
                    type="file",
                    text="Analysis report",
                    filename="report.txt",
                    file_url="https://files.example.com/report.txt",
                    file_size=102400,
                ),
            ]
        )
        card = to_card_v2(content)
        all_widgets = []
        for sec in card["sections"]:
            all_widgets.extend(sec.get("widgets", []))
        # Should have a decoratedText with a Download button
        file_widgets = [
            w
            for w in all_widgets
            if "decoratedText" in w and w["decoratedText"].get("button")
        ]
        assert len(file_widgets) == 1
        assert file_widgets[0]["decoratedText"]["button"]["text"] == "Download"

    def test_file_without_url(self):
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="Title", level=1),
                ContentSection(type="file", text="Generated report"),
            ]
        )
        card = to_card_v2(content)
        all_widgets = []
        for sec in card["sections"]:
            all_widgets.extend(sec.get("widgets", []))
        decorated = [w for w in all_widgets if "decoratedText" in w]
        assert len(decorated) >= 1
        assert "Generated report" in decorated[0]["decoratedText"]["text"]

    def test_list_ordered(self):
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="Title", level=1),
                ContentSection(type="list", items=["First", "Second"], style="ordered"),
            ]
        )
        card = to_card_v2(content)
        all_widgets = []
        for sec in card["sections"]:
            all_widgets.extend(sec.get("widgets", []))
        text_paragraphs = [w for w in all_widgets if "textParagraph" in w]
        list_widget = [w for w in text_paragraphs if "1." in w["textParagraph"]["text"]]
        assert len(list_widget) >= 1

    def test_list_unordered(self):
        content = MessageContent(
            sections=[
                ContentSection(type="header", text="Title", level=1),
                ContentSection(type="list", items=["Alpha", "Beta"], style="unordered"),
            ]
        )
        card = to_card_v2(content)
        all_widgets = []
        for sec in card["sections"]:
            all_widgets.extend(sec.get("widgets", []))
        text_paragraphs = [w for w in all_widgets if "textParagraph" in w]
        list_text = " ".join(w["textParagraph"]["text"] for w in text_paragraphs)
        assert "•" in list_text

    def test_question_free_text(self):
        content = MessageContent(
            sections=[ContentSection(type="header", text="Q", level=1)],
            questions=[
                Question(
                    text="Describe the issue",
                    question_id="q0",
                    options=[],
                )
            ],
        )
        card = to_card_v2(content)
        all_widgets = []
        for sec in card["sections"]:
            all_widgets.extend(sec.get("widgets", []))
        text_inputs = [w for w in all_widgets if "textInput" in w]
        assert len(text_inputs) == 1
        assert text_inputs[0]["textInput"]["name"] == "q0"

    def test_question_radio_buttons(self):
        content = MessageContent(
            sections=[ContentSection(type="header", text="Q", level=1)],
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
        card = to_card_v2(content)
        all_widgets = []
        for sec in card["sections"]:
            all_widgets.extend(sec.get("widgets", []))
        selection_inputs = [w for w in all_widgets if "selectionInput" in w]
        assert len(selection_inputs) == 1
        assert selection_inputs[0]["selectionInput"]["type"] == "RADIO_BUTTON"


class TestEscape:
    def test_html_entities(self):
        assert (
            _escape("<script>alert('xss')</script>")
            == "&lt;script&gt;alert('xss')&lt;/script&gt;"
        )

    def test_ampersand(self):
        assert _escape("A & B") == "A &amp; B"
