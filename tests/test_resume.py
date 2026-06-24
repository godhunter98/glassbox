import unittest
from unittest import mock
import sys
import types
from types import SimpleNamespace

# Ensure PYTHONPATH references are correctly mocked if modules have dependencies
from agent.storage import queries
from agent import coding_agent
from agent.context_manager import Session_state

class TestResumeFeature(unittest.TestCase):

    @mock.patch("agent.coding_agent.litellm.completion")
    def test_refresh_session_state_returns_false_for_empty_response(self, mock_completion):
        mock_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=""))]
        )
        state = Session_state(goal="Existing goal")

        refreshed = coding_agent.refresh_session_state(
            [{"role": "user", "content": "Continue the task"}],
            "test-model",
            "test-key",
            state,
        )

        self.assertIs(refreshed, False)
        self.assertEqual(state.goal, "Existing goal")

    @mock.patch("agent.coding_agent.litellm.completion")
    def test_refresh_session_state_returns_true_after_update(self, mock_completion):
        mock_completion.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"goal":"Updated goal","decisions":["Use SQLite"],"next_steps":["Add tests"]}'
                    )
                )
            ]
        )
        state = Session_state()

        refreshed = coding_agent.refresh_session_state(
            [{"role": "user", "content": "Continue the task"}],
            "test-model",
            "test-key",
            state,
        )

        self.assertIs(refreshed, True)
        self.assertEqual(state.goal, "Updated goal")
        self.assertEqual(state.decisions, ["Use SQLite"])
        self.assertEqual(state.next_steps, ["Add tests"])
    
    @mock.patch("agent.coding_agent.queries")
    def test_load_conversation_reconstruction(self, mock_queries):
        # 1. Mock DB messages
        mock_queries.get_conversation_messages.return_value = [
            {"message_id": 1, "role": "user", "content": "Hello!"},
            {"message_id": 2, "role": "assistant", "content": "Hi there! Let me run a tool."},
        ]
        
        # 2. Mock tool calls for assistant message (message_id = 2)
        mock_queries.get_tool_calls_for_message.return_value = [
            {
                "tool_id": 101,
                "tool_name": "view_file",
                "tool_args": '{"path": "test.txt"}',
                "tool_output": '{"content": "hello file"}'
            }
        ]
        
        convo = coding_agent.load_conversation(12)
        
        # We expect:
        # Index 0: system prompt
        # Index 1: user hello
        # Index 2: assistant with tool_calls
        # Index 3: tool result message matching fabricated tool_call_id
        
        self.assertEqual(len(convo), 4)
        self.assertEqual(convo[0]["role"], "system")
        
        self.assertEqual(convo[1]["role"], "user")
        self.assertEqual(convo[1]["content"], "Hello!")
        
        self.assertEqual(convo[2]["role"], "assistant")
        self.assertEqual(convo[2]["content"], "Hi there! Let me run a tool.")
        self.assertEqual(len(convo[2]["tool_calls"]), 1)
        self.assertEqual(convo[2]["tool_calls"][0]["id"], "call_101")
        self.assertEqual(convo[2]["tool_calls"][0]["function"]["name"], "view_file")
        self.assertEqual(convo[2]["tool_calls"][0]["function"]["arguments"], '{"path": "test.txt"}')
        
        self.assertEqual(convo[3]["role"], "tool")
        self.assertEqual(convo[3]["tool_call_id"], "call_101")
        self.assertEqual(convo[3]["name"], "view_file")
        self.assertEqual(convo[3]["content"], '{"content": "hello file"}')

    @mock.patch("agent.ui.queries")
    def test_display_sessions_dashboard(self, mock_queries):
        mock_queries.get_all_conversations.return_value = [
            {
                "conversation_id": 1,
                "started_at": "2026-05-20 12:00:00",
                "model": "deepseek-v4-flash",
                "summary": "Sample summary",
                "total_tokens": 100,
                "approx_cost": 0.0025,
                "status": "completed"
            }
        ]
        
        from agent import main
        ids = main.display_sessions_dashboard(all_sessions=False)
        self.assertEqual(ids, [1])

    @mock.patch("agent.main.agent_loop")
    @mock.patch("agent.main.display_sessions_dashboard")
    def test_main_routing_resume_arg(self, mock_dashboard, mock_agent_loop):
        from agent import main
        with mock.patch("sys.argv", ["main.py", "-r", "42"]):
            main.main()
            mock_agent_loop.assert_called_once_with(mock.ANY, mock.ANY, 10, resume_id=42)

    @mock.patch("agent.main.agent_loop")
    @mock.patch("agent.main.display_sessions_dashboard")
    def test_main_routing_new_arg(self, mock_dashboard, mock_agent_loop):
        from agent import main
        with mock.patch("sys.argv", ["main.py", "-n"]):
            main.main()
            mock_agent_loop.assert_called_once_with(mock.ANY, mock.ANY, 10, resume_id=None)

    @mock.patch("agent.main.agent_loop")
    @mock.patch("agent.main.display_sessions_dashboard")
    def test_main_routing_interactive_resume(self, mock_dashboard, mock_agent_loop):
        mock_dashboard.return_value = [10, 20]
        
        from agent import main
        # User inputs 20 to resume
        with mock.patch("sys.argv", ["main.py"]), mock.patch("builtins.input", return_value="20"):
            main.main()
            mock_agent_loop.assert_called_once_with(mock.ANY, mock.ANY, 10, resume_id=20)

    @mock.patch("agent.main.agent_loop")
    @mock.patch("agent.main.display_sessions_dashboard")
    def test_main_routing_interactive_new(self, mock_dashboard, mock_agent_loop):
        mock_dashboard.return_value = [10, 20]
        
        from agent import main
        # User hits enter to start a new session
        with mock.patch("sys.argv", ["main.py"]), mock.patch("builtins.input", return_value=""):
            main.main()
            mock_agent_loop.assert_called_once_with(mock.ANY, mock.ANY, 10, resume_id=None)

if __name__ == "__main__":
    unittest.main()
