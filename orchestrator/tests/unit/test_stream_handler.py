"""Unit tests for stream_handler.py."""

from incidentfox_orchestrator.message_state import InvestigationState
from incidentfox_orchestrator.stream_handler import handle_event, parse_sse_event


def _make_state() -> InvestigationState:
    return InvestigationState(session_id="s1", run_id="r1", correlation_id="c1")


class TestParseSSEEvent:
    def test_valid_data_line(self):
        event = parse_sse_event('data: {"type": "thought", "data": {"text": "hi"}}')
        assert event is not None
        assert event["type"] == "thought"

    def test_empty_line(self):
        assert parse_sse_event("") is None

    def test_non_data_line(self):
        assert parse_sse_event("event: thought") is None

    def test_invalid_json(self):
        assert parse_sse_event("data: not json") is None


class TestHandleThought:
    def test_first_thought(self):
        state = _make_state()
        changed = handle_event(state, {"type": "thought", "data": {"text": "Analyzing..."}})
        assert changed is True
        assert len(state.thoughts) == 1
        assert state.thoughts[0].text == "Analyzing..."
        assert state.thoughts[0].completed is False

    def test_second_thought_completes_first(self):
        state = _make_state()
        handle_event(state, {"type": "thought", "data": {"text": "First"}})
        handle_event(state, {"type": "thought", "data": {"text": "Second"}})
        assert len(state.thoughts) == 2
        assert state.thoughts[0].completed is True
        assert state.thoughts[1].completed is False


class TestHandleToolStart:
    def test_tool_added_to_current_thought(self):
        state = _make_state()
        handle_event(state, {"type": "thought", "data": {"text": "t1"}})
        changed = handle_event(state, {
            "type": "tool_start",
            "data": {"name": "Read", "tool_use_id": "tu1", "file_path": "/foo.py"},
        })
        assert changed is True
        assert len(state.thoughts[0].tools) == 1
        assert state.thoughts[0].tools[0].name == "Read"
        assert state.thoughts[0].tools[0].running is True
        assert state.current_tool is not None

    def test_tool_creates_thought_if_none(self):
        state = _make_state()
        handle_event(state, {
            "type": "tool_start",
            "data": {"name": "Bash", "tool_use_id": "tu1"},
        })
        assert len(state.thoughts) == 1
        assert len(state.thoughts[0].tools) == 1

    def test_subagent_tracked(self):
        state = _make_state()
        handle_event(state, {"type": "thought", "data": {"text": "t1"}})
        handle_event(state, {
            "type": "tool_start",
            "data": {
                "name": "Task",
                "tool_use_id": "task1",
                "description": "Search code",
                "subagent_type": "Explore",
            },
        })
        assert "task1" in state.subagents
        assert state.subagents["task1"].description == "Search code"


class TestHandleToolEnd:
    def test_tool_marked_completed(self):
        state = _make_state()
        handle_event(state, {"type": "thought", "data": {"text": "t1"}})
        handle_event(state, {
            "type": "tool_start",
            "data": {"name": "Read", "tool_use_id": "tu1"},
        })
        changed = handle_event(state, {
            "type": "tool_end",
            "data": {"name": "Read", "tool_use_id": "tu1", "success": True, "summary": "OK"},
        })
        assert changed is True
        assert state.thoughts[0].tools[0].running is False
        assert state.thoughts[0].tools[0].success is True
        assert state.current_tool is None


class TestHandleResult:
    def test_result_sets_final_state(self):
        state = _make_state()
        handle_event(state, {"type": "thought", "data": {"text": "t1"}})
        changed = handle_event(state, {
            "type": "result",
            "data": {"text": "Found the issue", "success": True},
        })
        assert changed is True
        assert state.final_result == "Found the issue"
        assert state.result_success is True
        assert state.is_complete is True
        assert state.thoughts[0].completed is True

    def test_result_with_images(self):
        state = _make_state()
        handle_event(state, {
            "type": "result",
            "data": {
                "text": "Result",
                "success": True,
                "images": [{"path": "img.png", "data": "base64..."}],
            },
        })
        assert state.result_images is not None
        assert len(state.result_images) == 1


class TestHandleError:
    def test_error_sets_state(self):
        state = _make_state()
        changed = handle_event(state, {
            "type": "error",
            "data": {"message": "Agent crashed"},
        })
        assert changed is True
        assert state.error == "Agent crashed"
        assert state.is_complete is True


class TestHandleQuestion:
    def test_question_stored(self):
        state = _make_state()
        changed = handle_event(state, {
            "type": "question",
            "data": {"questions": [{"question": "Which service?", "options": ["A", "B"]}]},
        })
        assert changed is True
        assert state.pending_questions is not None
        assert len(state.pending_questions) == 1


class TestHandleQuestionTimeout:
    def test_timeout_clears_questions(self):
        state = _make_state()
        handle_event(state, {"type": "thought", "data": {"text": "t1"}})
        handle_event(state, {
            "type": "tool_start",
            "data": {"name": "AskUserQuestion", "tool_use_id": "q1"},
        })
        handle_event(state, {
            "type": "question",
            "data": {"questions": [{"question": "Which?"}]},
        })
        changed = handle_event(state, {"type": "question_timeout", "data": {}})
        assert changed is True
        assert state.pending_questions is None
        assert state.thoughts[0].tools[0].timed_out is True
        assert state.thoughts[0].tools[0].running is False


class TestFullLifecycle:
    def test_complete_investigation_flow(self):
        """Simulate a full investigation: thought → tool_start → tool_end → result."""
        state = _make_state()

        handle_event(state, {"type": "thought", "data": {"text": "Looking at logs"}})
        handle_event(state, {
            "type": "tool_start",
            "data": {"name": "Bash", "tool_use_id": "t1", "command": "kubectl logs"},
        })
        handle_event(state, {
            "type": "tool_end",
            "data": {"name": "Bash", "tool_use_id": "t1", "success": True, "output": "error found"},
        })
        handle_event(state, {"type": "thought", "data": {"text": "Found the issue"}})
        handle_event(state, {
            "type": "result",
            "data": {"text": "The pod is OOMKilled", "success": True},
        })

        assert state.is_complete
        assert state.thought_count == 2
        assert state.tool_count == 1
        assert state.final_result == "The pod is OOMKilled"
