"""Unit tests for message_builder IR and builder functions."""

from incidentfox_orchestrator.message_builder import (
    _parse_markdown_to_sections,
    build_final_content,
    build_progress_content,
    build_question_content,
)
from incidentfox_orchestrator.message_state import (
    InvestigationState,
    ThoughtSection,
    ToolInfo,
)


def _make_state(**overrides) -> InvestigationState:
    defaults = {"session_id": "s1", "run_id": "r1", "correlation_id": "c1"}
    defaults.update(overrides)
    return InvestigationState(**defaults)


class TestBuildProgressContent:
    def test_empty_state(self):
        state = _make_state()
        content = build_progress_content(state)
        assert len(content.sections) >= 1
        assert content.sections[0].type == "header"

    def test_with_thoughts_and_tools(self):
        state = _make_state(
            thoughts=[
                ThoughtSection(
                    text="Analyzing logs",
                    completed=True,
                    tools=[
                        ToolInfo(
                            name="Bash",
                            command="kubectl logs",
                            running=False,
                            success=True,
                        ),
                    ],
                ),
                ThoughtSection(text="Checking metrics", completed=False),
            ]
        )
        state.current_tool = ToolInfo(name="Grep", pattern="error", running=True)

        content = build_progress_content(state)

        # Should have header + thoughts + tools + current tool + stats
        assert any(s.type == "progress" for s in content.sections)
        texts = " ".join(s.text for s in content.sections)
        assert "Analyzing logs" in texts
        assert "Checking metrics" in texts


class TestBuildFinalContent:
    def test_successful_result(self):
        state = _make_state(
            final_result="The issue is OOMKill",
            result_success=True,
            thoughts=[ThoughtSection(text="t1", completed=True)],
        )
        content = build_final_content(state, run_id="r1")

        assert content.sections[0].type == "header"
        assert "Result" in content.sections[0].text
        assert len(content.actions) == 2  # feedback buttons
        assert content.actions[0].action_id == "feedback_positive"
        assert content.actions[1].action_id == "feedback_negative"

    def test_error_result(self):
        state = _make_state(error="Agent crashed")
        content = build_final_content(state, run_id="r1")

        assert "Error" in content.sections[0].text
        assert any("Agent crashed" in s.text for s in content.sections)

    def test_feedback_buttons_have_run_id(self):
        state = _make_state(final_result="Done")
        content = build_final_content(state, run_id="test-run-123")

        for action in content.actions:
            if "feedback" in action.action_id:
                assert action.data["run_id"] == "test-run-123"

    def test_web_ui_link(self):
        state = _make_state(final_result="Done")
        content = build_final_content(
            state, run_id="r1", web_ui_url="https://app.incidentfox.ai"
        )
        url_actions = [a for a in content.actions if a.action_id == "view_result"]
        assert len(url_actions) == 1
        assert url_actions[0].value == "https://app.incidentfox.ai"


class TestBuildQuestionContent:
    def test_single_select_question(self):
        questions = [
            {
                "question": "Which service?",
                "options": [
                    {"label": "Auth", "value": "auth"},
                    {"label": "Payments", "value": "payments"},
                ],
                "multiSelect": False,
            },
        ]
        content = build_question_content(questions, thread_id="t1")

        assert len(content.questions) == 1
        assert content.questions[0].text == "Which service?"
        assert len(content.questions[0].options) == 2
        assert content.questions[0].multi_select is False

    def test_multi_select_question(self):
        questions = [
            {
                "question": "Select all affected",
                "options": ["A", "B", "C"],
                "multiSelect": True,
            },
        ]
        content = build_question_content(questions, thread_id="t1")

        assert content.questions[0].multi_select is True
        assert len(content.questions[0].options) == 3

    def test_submit_button(self):
        content = build_question_content(
            [{"question": "Q?", "options": ["A"]}],
            thread_id="t1",
        )
        assert any(a.action_id == "submit_answer" for a in content.actions)


class TestBuildFinalContentPhase5:
    """Phase 5: File/image rendering in final content."""

    def test_result_with_image_url(self):
        state = _make_state(
            final_result="Here's the chart",
            result_images=[
                {"url": "https://files.example.com/chart.png", "alt": "CPU usage"}
            ],
        )
        content = build_final_content(state, run_id="r1")
        image_sections = [s for s in content.sections if s.type == "image"]
        assert len(image_sections) == 1
        assert image_sections[0].image_url == "https://files.example.com/chart.png"
        assert image_sections[0].alt_text == "CPU usage"

    def test_result_with_base64_image(self):
        state = _make_state(
            final_result="Chart below",
            result_images=[
                {"data": "iVBORw0KGg==", "media_type": "image/png", "alt": "Memory"}
            ],
        )
        content = build_final_content(state, run_id="r1")
        image_sections = [s for s in content.sections if s.type == "image"]
        assert len(image_sections) == 1
        assert image_sections[0].image_data == "iVBORw0KGg=="
        assert image_sections[0].image_media_type == "image/png"

    def test_result_with_file_attachment(self):
        state = _make_state(
            final_result="Report attached",
            result_files=[
                {
                    "filename": "report.txt",
                    "description": "Thread dump analysis",
                    "url": "https://files.example.com/report.txt",
                    "size": 51200,
                }
            ],
        )
        content = build_final_content(state, run_id="r1")
        file_sections = [s for s in content.sections if s.type == "file"]
        assert len(file_sections) == 1
        assert file_sections[0].filename == "report.txt"
        assert file_sections[0].file_url == "https://files.example.com/report.txt"
        assert file_sections[0].file_size == 51200

    def test_result_with_file_no_url(self):
        state = _make_state(
            final_result="File generated",
            result_files=[{"filename": "data.csv", "description": "Export data"}],
        )
        content = build_final_content(state, run_id="r1")
        text_sections = [
            s
            for s in content.sections
            if s.type == "text" and "Attached file" in s.text
        ]
        assert len(text_sections) == 1


class TestMarkdownParsing:
    def test_headings(self):
        sections = _parse_markdown_to_sections(
            "# Title\nSome text\n## Subtitle\nMore text"
        )
        types = [s.type for s in sections]
        assert "header" in types
        headers = [s for s in sections if s.type == "header"]
        assert headers[0].text == "Title"
        assert headers[0].level == 1
        assert headers[1].text == "Subtitle"
        assert headers[1].level == 2

    def test_code_blocks(self):
        md = "Before\n```python\nprint('hello')\n```\nAfter"
        sections = _parse_markdown_to_sections(md)
        code_blocks = [s for s in sections if s.type == "code_block"]
        assert len(code_blocks) == 1
        assert "print" in code_blocks[0].text
        assert code_blocks[0].language == "python"

    def test_plain_text(self):
        sections = _parse_markdown_to_sections("Just plain text here.")
        assert len(sections) == 1
        assert sections[0].type == "text"

    def test_empty_input(self):
        assert _parse_markdown_to_sections("") == []
        assert _parse_markdown_to_sections("   ") == []
