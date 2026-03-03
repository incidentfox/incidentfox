"""Tests for Phase 4 (Q&A), Phase 5 (files/images), and Phase 6 (setup/welcome) bot features."""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestGChatWelcomeAndSetup:
    """Phase 6: Google Chat welcome message and setup command."""

    def test_welcome_message_includes_setup_mention(self):
        with patch.dict(os.environ, {"WEB_UI_URL": "https://app.incidentfox.ai"}):
            import importlib

            import incidentfox_orchestrator.webhooks.google_chat_app as gca

            importlib.reload(gca)

            assert "setup" in gca.WELCOME_MESSAGE.lower()
            assert "https://app.incidentfox.ai/team/integrations" in gca.WELCOME_MESSAGE

    def test_welcome_message_without_web_ui_url(self):
        with patch.dict(os.environ, {"WEB_UI_URL": ""}, clear=False):
            import importlib

            import incidentfox_orchestrator.webhooks.google_chat_app as gca

            importlib.reload(gca)

            assert "setup" in gca.WELCOME_MESSAGE.lower()
            assert "/team/integrations" not in gca.WELCOME_MESSAGE

    def test_web_ui_url_strips_trailing_slash(self):
        with patch.dict(os.environ, {"WEB_UI_URL": "https://app.incidentfox.ai/"}):
            import importlib

            import incidentfox_orchestrator.webhooks.google_chat_app as gca

            importlib.reload(gca)

            assert "https://app.incidentfox.ai/team/integrations" in gca.WELCOME_MESSAGE
            assert "//team" not in gca.WELCOME_MESSAGE


class TestGChatCardClicked:
    """Phase 4: Google Chat answer submission via CARD_CLICKED."""

    @pytest.mark.asyncio
    async def test_handle_card_clicked_submit_answer(self):
        with patch.dict(os.environ, {"WEB_UI_URL": ""}):
            import importlib

            import incidentfox_orchestrator.webhooks.google_chat_app as gca

            importlib.reload(gca)

            mock_config = MagicMock()
            mock_agent = MagicMock()
            mock_agent.submit_answer = MagicMock()
            mock_audit = MagicMock()

            integration = gca.GoogleChatIntegration(
                config_service=mock_config,
                agent_api=mock_agent,
                audit_api=mock_audit,
                google_chat_project_id="test-project",
            )

            event_data = {
                "action": {
                    "actionMethodName": "submit_answer",
                    "parameters": [
                        {"key": "thread_id", "value": "session-123"},
                    ],
                },
                "common": {
                    "formInputs": {
                        "q0": {"stringInputs": {"value": ["auth"]}},
                        "q1": {"stringInputs": {"value": ["high", "medium"]}},
                    },
                },
                "user": {"name": "users/123"},
            }

            async def fake_to_thread(fn, *args, **kwargs):
                return fn(*args, **kwargs)

            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                result = await integration._handle_card_clicked(event_data, "corr-1")

            assert result.get("text") == "Your answers have been submitted!"
            assert result["actionResponse"]["type"] == "UPDATE_MESSAGE"

    @pytest.mark.asyncio
    async def test_handle_card_clicked_feedback(self):
        with patch.dict(os.environ, {"WEB_UI_URL": ""}):
            import importlib

            import incidentfox_orchestrator.webhooks.google_chat_app as gca

            importlib.reload(gca)

            mock_config = MagicMock()
            mock_agent = MagicMock()
            mock_audit = MagicMock()
            mock_audit.record_feedback = MagicMock()

            integration = gca.GoogleChatIntegration(
                config_service=mock_config,
                agent_api=mock_agent,
                audit_api=mock_audit,
                google_chat_project_id="test-project",
            )

            event_data = {
                "action": {
                    "actionMethodName": "submit_feedback",
                    "parameters": [
                        {"key": "run_id", "value": "run-1"},
                        {"key": "feedback_type", "value": "positive"},
                    ],
                },
                "user": {"name": "users/456"},
            }

            async def fake_to_thread(fn, *args, **kwargs):
                return fn(*args, **kwargs)

            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                result = await integration._handle_card_clicked(event_data, "corr-2")

            assert result.get("text") == "Thanks for your feedback!"


class TestStreamHandlerQuestionEvents:
    """Phase 4: Question and question_timeout events in stream handler."""

    def test_question_event_populates_pending_questions(self):
        from incidentfox_orchestrator.message_state import InvestigationState
        from incidentfox_orchestrator.stream_handler import handle_event

        state = InvestigationState(session_id="s1", run_id="r1", correlation_id="c1")
        event = {
            "type": "question",
            "data": {
                "questions": [
                    {
                        "question": "Which service is affected?",
                        "options": [
                            {"label": "Auth", "value": "auth"},
                            {"label": "API", "value": "api"},
                        ],
                    },
                ],
            },
        }

        changed = handle_event(state, event)
        assert changed is True
        assert len(state.pending_questions) == 1
        assert state.pending_questions[0]["question"] == "Which service is affected?"

    def test_question_timeout_clears_questions(self):
        from incidentfox_orchestrator.message_state import InvestigationState
        from incidentfox_orchestrator.stream_handler import handle_event

        state = InvestigationState(session_id="s1", run_id="r1", correlation_id="c1")
        state.pending_questions = [{"question": "Pick one", "options": ["A", "B"]}]

        event = {"type": "question_timeout"}
        changed = handle_event(state, event)
        assert changed is True
        # question_timeout sets pending_questions to None (cleared)
        assert state.pending_questions is None


class TestQuestionContentBuilding:
    """Phase 4: Question card building from IR."""

    def test_build_question_content_with_string_options(self):
        from incidentfox_orchestrator.message_builder import build_question_content

        questions = [
            {"question": "Choose one", "options": ["Option A", "Option B", "Option C"]},
        ]
        content = build_question_content(questions, thread_id="thread-1")

        assert len(content.questions) == 1
        q = content.questions[0]
        assert q.text == "Choose one"
        assert len(q.options) == 3
        assert q.options[0].label == "Option A"
        assert q.options[0].value == "Option A"

    def test_build_question_content_submit_action_has_thread_id(self):
        from incidentfox_orchestrator.message_builder import build_question_content

        content = build_question_content(
            [{"question": "Q?", "options": ["Y", "N"]}],
            thread_id="my-thread",
        )
        submit_actions = [a for a in content.actions if a.action_id == "submit_answer"]
        assert len(submit_actions) == 1
        assert submit_actions[0].data["thread_id"] == "my-thread"

    def test_build_question_content_free_text(self):
        from incidentfox_orchestrator.message_builder import build_question_content

        questions = [{"question": "Describe the issue"}]
        content = build_question_content(questions, thread_id="t1")

        assert len(content.questions) == 1
        assert content.questions[0].options == []
