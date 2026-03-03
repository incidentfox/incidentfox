"""Unit tests for message_state.py."""

from incidentfox_orchestrator.message_state import (
    InvestigationState,
    ThoughtSection,
    ToolInfo,
)


class TestInvestigationState:
    def test_empty_state(self):
        state = InvestigationState(
            session_id="s1", run_id="r1", correlation_id="c1"
        )
        assert state.thought_count == 0
        assert state.tool_count == 0
        assert state.is_complete is False
        assert state.current_thought_section is None

    def test_thought_counting(self):
        state = InvestigationState(
            session_id="s1",
            run_id="r1",
            correlation_id="c1",
            thoughts=[
                ThoughtSection(text="t1", completed=True),
                ThoughtSection(text="t2", completed=False),
            ],
        )
        assert state.thought_count == 1  # only completed
        assert state.current_thought_section is not None
        assert state.current_thought_section.text == "t2"

    def test_tool_counting(self):
        state = InvestigationState(
            session_id="s1",
            run_id="r1",
            correlation_id="c1",
            thoughts=[
                ThoughtSection(
                    text="t1",
                    tools=[ToolInfo(name="Read"), ToolInfo(name="Bash")],
                ),
                ThoughtSection(text="t2", tools=[ToolInfo(name="Grep")]),
            ],
        )
        assert state.tool_count == 3

    def test_is_complete_with_result(self):
        state = InvestigationState(
            session_id="s1",
            run_id="r1",
            correlation_id="c1",
            final_result="done",
        )
        assert state.is_complete is True

    def test_is_complete_with_error(self):
        state = InvestigationState(
            session_id="s1",
            run_id="r1",
            correlation_id="c1",
            error="something went wrong",
        )
        assert state.is_complete is True
