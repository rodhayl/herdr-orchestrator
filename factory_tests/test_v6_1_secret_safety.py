import os
import unittest
from tools.factory import redact_secrets, snapshot_secret_env
from tools.context import _INITIAL_SECRET_ENV

class TestV61SecretSafety(unittest.TestCase):
    def setUp(self):
        self.sentinel_secrets = {
            "OPENROUTER_API_KEY": "sk-or-v1-9876543210abcdef9876543210abcdef",
            "OPENAI_API_KEY": "sk-proj-1234567890abcdef1234567890abcdef",
            "ANTHROPIC_API_KEY": "sk-ant-api03-fedcba0987654321fedcba0987654321",
            "FACTORY_API_KEY": "fact-secret-token-xyz-123456",
            "CLAUDE_CODE_TOKEN": "claude-code-secret-sess-9999"
        }
        self.orig_env = os.environ.copy()
        for k, v in self.sentinel_secrets.items():
            os.environ[k] = v
        snapshot_secret_env()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)
        _INITIAL_SECRET_ENV.clear()
        snapshot_secret_env()

    def test_redact_secrets_in_string(self):
        raw_text = f"Worker launched with key {self.sentinel_secrets['OPENROUTER_API_KEY']} and secret {self.sentinel_secrets['FACTORY_API_KEY']}"
        cleaned = redact_secrets(raw_text)
        for s in self.sentinel_secrets.values():
            self.assertNotIn(s, cleaned)
        self.assertIn("[REDACTED_OPENROUTER_API_KEY]", cleaned)
        self.assertIn("[REDACTED_FACTORY_API_KEY]", cleaned)

    def test_redact_secrets_in_nested_dict(self):
        payload = {
            "task_id": "test_task",
            "status": "COMPLETED",
            "model": "gemini-3.8-flash",
            "details": {
                "auth": {
                    "token": self.sentinel_secrets["ANTHROPIC_API_KEY"],
                    "nested_list": [
                        "cmd",
                        f"--api-key={self.sentinel_secrets['OPENAI_API_KEY']}",
                        {"extra": self.sentinel_secrets["CLAUDE_CODE_TOKEN"]}
                    ]
                }
            }
        }
        cleaned = redact_secrets(payload)
        self.assertEqual(cleaned["task_id"], "test_task")
        self.assertEqual(cleaned["status"], "COMPLETED")
        self.assertEqual(cleaned["model"], "gemini-3.8-flash")

        # Verify all sentinel secrets are gone
        for s in self.sentinel_secrets.values():
            self.assertNotIn(s, str(cleaned))

    def test_redact_secrets_pattern_matching_unregistered_keys(self):
        # Keys matching sk-ant-... or sk-proj-... even if not in env
        unregistered_key = "sk-ant-api03-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        text = f"Error communicating with provider using {unregistered_key}"
        cleaned = redact_secrets(text)
        self.assertNotIn(unregistered_key, cleaned)
        self.assertIn("[REDACTED_SECRET]", cleaned)

    def test_safe_values_preserved(self):
        safe_payload = {
            "run_id": "run-20260924-001000",
            "task_id": "backend",
            "exit_code": 0,
            "commit_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "churn": {"lines_added": 12, "lines_deleted": 0}
        }
        cleaned = redact_secrets(safe_payload)
        self.assertEqual(cleaned, safe_payload)

    def test_late_set_secret_snapshot_and_redaction(self):
        """Verifies that secrets set in os.environ after module import are captured by snapshot_secret_env and redacted."""
        late_secret_key = "DATABASE_URL_SECRET"
        late_secret_val = "postgres://admin:super_secret_pw_9999@localhost:5432/db"
        os.environ[late_secret_key] = late_secret_val
        snapshot_secret_env()
        raw_msg = f"Connecting to database using {late_secret_val} now"
        cleaned = redact_secrets(raw_msg)
        self.assertNotIn(late_secret_val, cleaned)
        self.assertIn("[REDACTED_DATABASE_URL_SECRET]", cleaned)

if __name__ == "__main__":
    unittest.main()
