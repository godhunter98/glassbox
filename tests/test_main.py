import os
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock


class TestMain(unittest.TestCase):
    def test_main_calls_agent_loop(self):
        litellm_stub = types.ModuleType("litellm")
        litellm_stub.litellm = types.SimpleNamespace(completion=lambda **_kwargs: None)
        dotenv_stub = types.ModuleType("dotenv")
        dotenv_stub.load_dotenv = lambda: None
        sys.modules["litellm"] = litellm_stub
        sys.modules["dotenv"] = dotenv_stub

        sys.modules.pop("agent.main", None)

        from agent import main

        with mock.patch.object(main, "agent_loop") as mock_loop, mock.patch.object(main, "ensure_config", return_value=("test-model", "test-key")), mock.patch("sys.argv", ["main.py", "-n"]):
            main.main()
            mock_loop.assert_called_once()

    def test_ensure_config_uses_existing_env(self):
        from agent import main

        with mock.patch.dict(os.environ, {"MODEL": "test-model", "API_KEY": "test-key"}, clear=True), mock.patch.object(main, "load_dotenv"):
            result = main.ensure_config()

        self.assertEqual(result, ("test-model", "test-key"))

    def test_ensure_config_prompts_and_saves_missing_env(self):
        from agent import main

        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = pathlib.Path(temp_dir) / ".env"
            with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(main, "load_dotenv"), \
                mock.patch.object(main.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(main.Path, "cwd", return_value=pathlib.Path(temp_dir)), \
                mock.patch("builtins.input", side_effect=["", "", ""]), \
                mock.patch.object(main, "getpass", return_value="test-key"):
                result = main.ensure_config()

            self.assertEqual(result, (main.DEFAULT_MODEL, "test-key"))
            self.assertIn(f'MODEL="{main.DEFAULT_MODEL}"', env_path.read_text(encoding="utf-8"))
            self.assertIn('API_KEY="test-key"', env_path.read_text(encoding="utf-8"))

    def test_ensure_config_non_interactive_missing_env(self):
        from agent import main

        with mock.patch.dict(os.environ, {}, clear=True), \
            mock.patch.object(main, "load_dotenv"), \
            mock.patch.object(main.sys.stdin, "isatty", return_value=False):
            result = main.ensure_config()

        self.assertIsNone(result)

    def test_list_sessions_does_not_require_config(self):
        from agent import main

        with mock.patch.object(main, "ensure_config") as mock_ensure_config, \
            mock.patch.object(main, "display_sessions_dashboard", return_value=[]), \
            mock.patch.object(main, "agent_loop") as mock_loop, \
            mock.patch("sys.argv", ["main.py", "-l"]):
            main.main()

        mock_ensure_config.assert_not_called()
        mock_loop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
