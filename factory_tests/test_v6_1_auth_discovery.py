import os
import unittest
from unittest.mock import patch, MagicMock
from tools.factory import probe_harness_auth, probe_profile_auth, _AUTH_PROBE_CACHE

class TestV61AuthDiscovery(unittest.TestCase):
    def setUp(self):
        _AUTH_PROBE_CACHE.clear()
        self.orig_env = os.environ.copy()

    def tearDown(self):
        _AUTH_PROBE_CACHE.clear()
        os.environ.clear()
        os.environ.update(self.orig_env)

    def test_codex_auth_via_env(self):
        os.environ["OPENAI_API_KEY"] = "sk-test-mock-key"
        res = probe_harness_auth("codex", force_refresh=True)
        self.assertTrue(res["authenticated"])
        self.assertEqual(res["auth_source"], "api_key_env")

    @patch("subprocess.run")
    def test_codex_auth_via_stored_login(self, mock_run):
        os.environ.pop("OPENAI_API_KEY", None)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Logged in using ChatGPT subscription (user@example.com)"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res = probe_harness_auth("codex", force_refresh=True)
        self.assertTrue(res["authenticated"])
        self.assertEqual(res["auth_source"], "subscription_login")

    @patch("subprocess.run")
    def test_codex_unauthenticated(self, mock_run):
        os.environ.pop("OPENAI_API_KEY", None)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "Not logged in"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res = probe_harness_auth("codex", force_refresh=True)
        self.assertFalse(res["authenticated"])
        self.assertEqual(res["auth_source"], "unauthenticated")

    def test_claude_auth_via_env(self):
        os.environ["CLAUDE_CODE_TOKEN"] = "test-token"
        res = probe_harness_auth("claude", force_refresh=True)
        self.assertTrue(res["authenticated"])
        self.assertEqual(res["auth_source"], "api_key_env")

    @patch("subprocess.run")
    def test_claude_auth_via_oauth(self, mock_run):
        os.environ.pop("CLAUDE_CODE_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = '{"loggedIn": true, "authMethod": "claude.ai"}'
        mock_run.return_value = mock_proc

        res = probe_harness_auth("claude", force_refresh=True)
        self.assertTrue(res["authenticated"])
        self.assertEqual(res["auth_source"], "stored_oauth")

    @patch("subprocess.run")
    def test_claude_unauthenticated(self, mock_run):
        os.environ.pop("CLAUDE_CODE_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = '{"loggedIn": false, "authMethod": "none"}'
        mock_run.return_value = mock_proc

        res = probe_harness_auth("claude", force_refresh=True)
        self.assertFalse(res["authenticated"])
        self.assertEqual(res["auth_source"], "unauthenticated")

    def test_droid_auth_via_env(self):
        os.environ["FACTORY_API_KEY"] = "test-droid-key"
        res = probe_harness_auth("droid", force_refresh=True)
        self.assertTrue(res["authenticated"])
        self.assertEqual(res["auth_source"], "api_key_env")

    @patch("subprocess.run")
    def test_droid_unauthenticated(self, mock_run):
        os.environ.pop("FACTORY_API_KEY", None)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "no usable credentials found (not logged in)"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res = probe_harness_auth("droid", force_refresh=True)
        self.assertFalse(res["authenticated"])
        self.assertEqual(res["auth_source"], "unauthenticated")

    @patch("subprocess.run")
    def test_agy_auth(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "gemini-3.8-flash-high     Gemini 3.8 Flash (High)\nclaude-sonnet-4-6"
        mock_run.return_value = mock_proc

        res = probe_harness_auth("agy", force_refresh=True)
        self.assertTrue(res["authenticated"])
        self.assertEqual(res["auth_source"], "provider_credentials")

    @patch("subprocess.run")
    def test_opencode_profile_auth_differentiation(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "0 credentials"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        # opencode-mimo-free returns locally without consulting the live CLI.
        mimo_res = probe_profile_auth("opencode-mimo-free")
        self.assertTrue(mimo_res["authenticated"])

        # opencode-gemini-high is blocked unless direct OPENCODE_API_KEY is present
        os.environ.pop("OPENCODE_API_KEY", None)
        gemini_res = probe_profile_auth("opencode-gemini-high")
        self.assertFalse(gemini_res["authenticated"])
        self.assertIn("guardrail", gemini_res["evidence"])

if __name__ == "__main__":
    unittest.main()
