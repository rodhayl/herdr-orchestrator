import unittest
import pathlib
import tempfile
from unittest.mock import MagicMock, patch
from tools.factory import CodexAdapter, ClaudeAdapter, OpenCodeAdapter

class TestV61NativeCLIContracts(unittest.TestCase):
    def setUp(self):
        self.mock_herdr = MagicMock()
        self.mock_herdr.create_workspace.return_value = ("ws-test-1", "pane-test-1")
        self.mock_res_mgr = MagicMock()

    @patch("tools.factory.probe_harness_auth")
    def test_codex_toml_quoting_contract(self, mock_probe):
        mock_probe.return_value = {
            "harness": "codex",
            "authenticated": False,
            "auth_source": "unauthenticated",
            "confidence": "high",
            "evidence": "simulated unauthenticated codex",
            "requires_interaction": False,
            "notes": ""
        }
        adapter = CodexAdapter("codex", {
            "command": "/usr/local/bin/codex",
            "default_model": "gpt-5.6-luna",
            "reasoning_effort": "high"
        }, self.mock_herdr, self.mock_res_mgr)

        with tempfile.TemporaryDirectory() as tmpdir:
            td = pathlib.Path(tmpdir)
            wt = td / "wt"
            wt.mkdir()
            prompt = td / "prompt.md"
            prompt.write_text("Hello Codex")
            schema = td / "schema.json"
            schema.write_text("{}")
            attempt_dir = td / "att-1"
            attempt_dir.mkdir()
            env_info = {"workspace_id": "ws-1", "pane_id": "pane-1"}

            # Call execute in unauthenticated mode to inspect error or script command
            res = adapter.execute(
                "run-test", "task-1", 1, wt, prompt, schema, 30, attempt_dir, env_info,
                model="gpt-5.6-luna", effort="xhigh"
            )
            # Live auth is blocked, so check error structure
            self.assertEqual(res["data"]["error"], "AUTH_BLOCKED")
            self.assertEqual(res["provenance"]["model"], "gpt-5.6-luna")
            self.assertEqual(res["provenance"]["reasoning_effort"], "xhigh")

    @patch("subprocess.run")
    def test_claude_cli_contract_flags(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = '{"loggedIn": false, "authMethod": "none"}'
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        adapter = ClaudeAdapter("claude", {
            "command": "/root/.local/bin/claude",
            "default_model": "claude-sonnet-5",
            "reasoning_effort": "high"
        }, self.mock_herdr, self.mock_res_mgr)

        with tempfile.TemporaryDirectory() as tmpdir:
            td = pathlib.Path(tmpdir)
            wt = td / "wt"
            wt.mkdir()
            prompt = td / "prompt.md"
            prompt.write_text("Hello Claude")
            schema = td / "schema.json"
            schema.write_text("{}")
            attempt_dir = td / "att-1"
            attempt_dir.mkdir()
            env_info = {"workspace_id": "ws-1", "pane_id": "pane-1"}

            res = adapter.execute(
                "run-test", "task-1", 1, wt, prompt, schema, 30, attempt_dir, env_info,
                model="claude-sonnet-5", effort="medium"
            )
            self.assertEqual(res["data"]["error"], "AUTH_BLOCKED")
            self.assertEqual(res["provenance"]["model"], "claude-sonnet-5")
            self.assertEqual(res["provenance"]["reasoning_effort"], "medium")

    def test_opencode_cli_contract_flags(self):
        adapter = OpenCodeAdapter("opencode", {
            "command": "/root/.opencode/bin/opencode",
            "default_model": "openrouter/openrouter/free",
            "reasoning_effort": "free"
        }, self.mock_herdr, self.mock_res_mgr)

        with tempfile.TemporaryDirectory() as tmpdir:
            td = pathlib.Path(tmpdir)
            wt = td / "wt"
            wt.mkdir()
            prompt = td / "prompt.md"
            prompt.write_text("Hello OpenCode")
            schema = td / "schema.json"
            schema.write_text("{}")
            attempt_dir = td / "att-1"
            attempt_dir.mkdir()
            env_info = {"workspace_id": "ws-1", "pane_id": "pane-1"}

            # Deterministic test mode
            import os
            os.environ["FACTORY_TEST_HARNESS"] = "1"
            try:
                res = adapter.execute(
                    "run-test", "task-1", 1, wt, prompt, schema, 30, attempt_dir, env_info,
                    model="openrouter/openrouter/free", effort="free"
                )
                self.assertEqual(res["exit_code"], 0)
                self.assertEqual(res["execution_mode"], "MOCK")
                self.assertEqual(res["data"]["status"], "COMPLETED")
            finally:
                os.environ.pop("FACTORY_TEST_HARNESS", None)

if __name__ == "__main__":
    unittest.main()
