#!/usr/bin/env python3
"""
Unit and integration tests for Herdr Orchestrator v6.0.0 capabilities:
1. ClaudeAdapter execution, script generation, JSON envelope parsing, timeouts, error mapping, and attempt mismatch rejection.
2. OpenCodeAdapter execution, script generation, JSON envelope parsing, timeouts, error mapping, and attempt mismatch rejection.
3. Multi-effort Harness Profile schema validation (v6.0.0, 19 profiles).
4. Deterministic execution_class derivation (routine, standard, deep) and ROUTING_PRIORITY_MATRIX routing.
5. Telemetry metrics schema validation, Git churn computation, and observation-only reporting.
"""

import copy
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.factory import (
    PROJECT_ROOT,
    ClaudeAdapter,
    OpenCodeAdapter,
    CodexAdapter,
    DroidAdapter,
    AgyAdapter,
    ResourceManager,
    derive_execution_class,
    ROUTING_PRIORITY_MATRIX,
    summarize_execution_metrics,
    load_harness_profiles,
    validate_profile,
    validate_all_profiles,
    resolve_task_worker,
    explain_task_routing,
)


class MockHerdrClient:
    """Mock HerdrClient simulating socket workspace operations without host mutation."""
    def __init__(self):
        self.control_plane = {
            "workspace_id": "mock_w",
            "pane_id": "mock_w:p1",
            "tab_id": "mock_w:t1",
            "cwd": "/mock/cwd",
            "herdr_socket": "/mock/herdr.sock"
        }
        self.workspaces = {}
        self.counter = 0

    def create_workspace(self, cwd: str, label: str = None) -> tuple:
        self.counter += 1
        ws_id = f"w_mock_{self.counter}"
        pane_id = f"{ws_id}:p1"
        self.workspaces[ws_id] = {"cwd": cwd, "label": label, "closed": False}
        return ws_id, pane_id

    def close_workspace(self, ws_id: str) -> bool:
        if ws_id in self.workspaces:
            self.workspaces[ws_id]["closed"] = True
            return True
        return False

    def run_in_pane(self, pane_id: str, command: str) -> bool:
        return True

    def report_agent(self, pane_id: str, agent: str, state: str, source: str = "factory",
                     seq: int = None, message: str = None, session_id: str = None, session_path: str = None) -> bool:
        return True

    def report_agent_session(self, pane_id: str, agent: str, session_id: str = None, session_path: str = None,
                             source: str = "factory", seq: int = None) -> bool:
        return True

    def release_agent(self, pane_id: str, agent: str, source: str = "factory", seq: int = None) -> bool:
        return True

    def agent_wait(self, target: str, until: list = None, timeout_ms: int = None) -> dict:
        return {"matched": True, "status": "done", "agent": {"agent_status": "done", "pane_id": target}}



class TestV6ClaudeAdapter(unittest.TestCase):
    """Tests for ClaudeAdapter execution, flags, JSON output parsing, and failure modes."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_root = pathlib.Path(self.temp_dir.name)
        self.worktree = self.test_root / "worktree"
        self.worktree.mkdir(parents=True, exist_ok=True)
        self.task_attempt_dir = self.test_root / "attempt"
        self.task_attempt_dir.mkdir(parents=True, exist_ok=True)

        self.mock_herdr = MockHerdrClient()
        self.res_mgr = ResourceManager(self.mock_herdr, state_file=self.test_root / "ownership.json")

        self.worker_cfg = {
            "family": "claude",
            "command": "/root/.local/bin/claude",
            "profile_home": "/root/.claude",
            "enabled": True,
            "capabilities": ["coding", "frontend", "backend", "testing", "review"],
            "adapter": "claude",
            "default_model": "claude-sonnet-5",
            "reasoning_effort": "high",
            "native": {
                "permission_mode": "acceptEdits",
                "no_session_persistence": True,
                "output_format": "json"
            },
            "concurrency_eligibility": False
        }
        self.adapter = ClaudeAdapter("claude", self.worker_cfg, self.mock_herdr, self.res_mgr)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_environment_preparation(self):
        """Verifies Claude environment preparation registers workspace and pane."""
        env_info = self.adapter.prepare_environment("run-v6-001", "T4", 1, self.worktree)
        self.assertIn("workspace_id", env_info)
        self.assertIn("pane_id", env_info)
        self.assertEqual(env_info["worktree_path"], str(self.worktree))
        self.assertTrue(self.res_mgr.is_owned_workspace(env_info["workspace_id"]))

    @patch("subprocess.run")
    def test_live_auth_check_when_credentials_absent(self, mock_run):
        """Verifies execution fails safely with AUTH_BLOCKED when credentials are not configured."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = '{"loggedIn": false, "authMethod": "none"}'
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        old_token = os.environ.pop("CLAUDE_CODE_TOKEN", None)
        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        old_harness = os.environ.pop("FACTORY_TEST_HARNESS", None)
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T4", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T4",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
            )
            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(result["data"]["error"], "AUTH_BLOCKED")
            self.assertEqual(result["provenance"]["auth_status"], "AUTH_BLOCKED")
        finally:
            if old_token:
                os.environ["CLAUDE_CODE_TOKEN"] = old_token
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key
            if old_harness:
                os.environ["FACTORY_TEST_HARNESS"] = old_harness

    def test_successful_execution_simulation(self):
        """Verifies successful Claude execution parsing under test harness."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["CLAUDE_TEST_BEHAVIOR"] = "SUCCESS"
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T4", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T4",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
                model="claude-sonnet-5",
                effort="high"
            )
            self.assertEqual(result["exit_code"], 0)
            self.assertFalse(result["timed_out"])
            self.assertEqual(result["data"]["status"], "COMPLETED")
            self.assertEqual(result["data"]["task_id"], "T4")
            self.assertEqual(result["provenance"]["model"], "claude-sonnet-5")
            self.assertEqual(result["provenance"]["reasoning_effort"], "high")
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("CLAUDE_TEST_BEHAVIOR", None)

    def test_timeout_execution_simulation(self):
        """Verifies TIMEOUT classification with CLAUDE_TEST_BEHAVIOR=TIMEOUT."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["CLAUDE_TEST_BEHAVIOR"] = "TIMEOUT"
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T4", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T4",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=1,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
            )
            self.assertTrue(result["timed_out"])
            self.assertIn("timed out", result["error"])
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("CLAUDE_TEST_BEHAVIOR", None)

    def test_error_execution_simulation(self):
        """Verifies ERROR classification with CLAUDE_TEST_BEHAVIOR=ERROR."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["CLAUDE_TEST_BEHAVIOR"] = "ERROR"
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T4", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T4",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
            )
            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(result["data"]["status"], "FAILED")
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("CLAUDE_TEST_BEHAVIOR", None)

    def test_malformed_json_simulation(self):
        """Verifies MALFORMED classification when Claude output is not valid JSON."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["CLAUDE_TEST_BEHAVIOR"] = "MALFORMED"
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T4", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T4",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
            )
            self.assertEqual(result["data"], {})
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("CLAUDE_TEST_BEHAVIOR", None)

    def test_attempt_mismatch_simulation(self):
        """Verifies ATTEMPT_MISMATCH rejection when returned attempt_id differs."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["CLAUDE_TEST_BEHAVIOR"] = "ATTEMPT_MISMATCH"
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T4", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T4",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
            )
            self.assertEqual(result["data"]["status"], "FAILED")
            self.assertIn("Mismatched attempt_id", result["data"]["error"])
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("CLAUDE_TEST_BEHAVIOR", None)


class TestV6OpenCodeAdapter(unittest.TestCase):
    """Tests for OpenCodeAdapter execution, flags, JSON output parsing, and failure modes."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_root = pathlib.Path(self.temp_dir.name)
        self.worktree = self.test_root / "worktree"
        self.worktree.mkdir(parents=True, exist_ok=True)
        self.task_attempt_dir = self.test_root / "attempt"
        self.task_attempt_dir.mkdir(parents=True, exist_ok=True)

        self.mock_herdr = MockHerdrClient()
        self.res_mgr = ResourceManager(self.mock_herdr, state_file=self.test_root / "ownership.json")

        self.worker_cfg = {
            "family": "opencode",
            "command": "/root/.opencode/bin/opencode",
            "profile_home": "/root/.config/opencode",
            "enabled": True,
            "capabilities": ["coding", "frontend", "backend", "support", "testing", "review"],
            "adapter": "opencode",
            "default_model": "openrouter/google/gemini-2.5-flash",
            "reasoning_effort": "high",
            "native": {
                "format": "json",
                "auto": True,
                "pure": True
            },
            "concurrency_eligibility": True
        }
        self.adapter = OpenCodeAdapter("opencode", self.worker_cfg, self.mock_herdr, self.res_mgr)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_environment_preparation(self):
        """Verifies OpenCode environment preparation registers workspace and pane."""
        env_info = self.adapter.prepare_environment("run-v6-001", "T8", 1, self.worktree)
        self.assertIn("workspace_id", env_info)
        self.assertIn("pane_id", env_info)
        self.assertEqual(env_info["worktree_path"], str(self.worktree))
        self.assertTrue(self.res_mgr.is_owned_workspace(env_info["workspace_id"]))

    @patch("subprocess.run")
    def test_live_auth_check_when_credentials_absent(self, mock_run):
        """Verifies execution fails safely with AUTH_BLOCKED when credentials are not configured."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = '{"loggedIn": false, "authMethod": "none"}'
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        old_router = os.environ.pop("OPENROUTER_API_KEY", None)
        old_key = os.environ.pop("OPENCODE_API_KEY", None)
        old_harness = os.environ.pop("FACTORY_TEST_HARNESS", None)
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T8", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T8",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
            )
            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(result["data"]["error"], "AUTH_BLOCKED")
            self.assertEqual(result["provenance"]["auth_status"], "AUTH_BLOCKED")
        finally:
            if old_router:
                os.environ["OPENROUTER_API_KEY"] = old_router
            if old_key:
                os.environ["OPENCODE_API_KEY"] = old_key
            if old_harness:
                os.environ["FACTORY_TEST_HARNESS"] = old_harness

    def test_successful_execution_simulation(self):
        """Verifies successful OpenCode execution parsing under test harness."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["OPENCODE_TEST_BEHAVIOR"] = "SUCCESS"
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T8", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T8",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
                model="openrouter/google/gemini-2.5-flash",
                effort="high"
            )
            self.assertEqual(result["exit_code"], 0)
            self.assertFalse(result["timed_out"])
            self.assertEqual(result["data"]["status"], "COMPLETED")
            self.assertEqual(result["data"]["task_id"], "T8")
            self.assertEqual(result["provenance"]["model"], "openrouter/google/gemini-2.5-flash")
            self.assertEqual(result["provenance"]["reasoning_effort"], "high")
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("OPENCODE_TEST_BEHAVIOR", None)

    def test_timeout_execution_simulation(self):
        """Verifies TIMEOUT classification with OPENCODE_TEST_BEHAVIOR=TIMEOUT."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["OPENCODE_TEST_BEHAVIOR"] = "TIMEOUT"
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T8", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T8",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=1,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
            )
            self.assertTrue(result["timed_out"])
            self.assertIn("timed out", result["error"])
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("OPENCODE_TEST_BEHAVIOR", None)

    def test_error_execution_simulation(self):
        """Verifies ERROR classification with OPENCODE_TEST_BEHAVIOR=ERROR."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["OPENCODE_TEST_BEHAVIOR"] = "ERROR"
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T8", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T8",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
            )
            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(result["data"]["status"], "FAILED")
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("OPENCODE_TEST_BEHAVIOR", None)

    def test_malformed_json_simulation(self):
        """Verifies MALFORMED classification when OpenCode output is not valid JSON."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["OPENCODE_TEST_BEHAVIOR"] = "MALFORMED"
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T8", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T8",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
            )
            self.assertEqual(result["data"], {})
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("OPENCODE_TEST_BEHAVIOR", None)

    def test_attempt_mismatch_simulation(self):
        """Verifies ATTEMPT_MISMATCH rejection when returned attempt_id differs."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["OPENCODE_TEST_BEHAVIOR"] = "ATTEMPT_MISMATCH"
        try:
            env_info = self.adapter.prepare_environment("run-v6-001", "T8", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Test", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v6-001",
                task_id="T8",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
            )
            self.assertEqual(result["data"]["status"], "FAILED")
            self.assertIn("Mismatched attempt_id", result["data"]["error"])
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("OPENCODE_TEST_BEHAVIOR", None)


class TestV6ProfilesAndRouting(unittest.TestCase):
    """Tests for v6.0.0 profiles, execution classes, and deterministic routing priority matrix."""

    def test_v6_profiles_validation(self):
        """Verifies the canonical profile catalog and its top-level schema version."""
        config_path = PROJECT_ROOT / "harness_profiles.json"
        schema_path = PROJECT_ROOT / "schemas" / "harness-profiles.schema.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertIn(config["schema_version"], schema["properties"]["schema_version"]["enum"])
        allowed_cert_statuses = set(
            schema["definitions"]["HarnessProfile"]["properties"]["certification"]["properties"]["status"]["enum"]
        )
        for profile_id, profile in config["profiles"].items():
            status = profile.get("certification", {}).get("status")
            if status is not None:
                self.assertIn(status, allowed_cert_statuses, profile_id)

        profiles = load_harness_profiles()
        self.assertEqual(len(profiles), 17)

        validation = validate_all_profiles()
        self.assertTrue(all(len(errs) == 0 for errs in validation.values()), f"Validation failed: {validation}")

        # Ensure all 5 harnesses are present
        harnesses = {p["harness"] for p in profiles.values()}
        self.assertIn("agy", harnesses)
        self.assertIn("droid", harnesses)
        self.assertIn("codex", harnesses)
        self.assertIn("claude", harnesses)
        self.assertIn("opencode", harnesses)

    def test_derive_execution_class(self):
        """Verifies execution_class derivation for routine, standard, and deep."""
        # Explicit override
        self.assertEqual(derive_execution_class("backend", "routine"), "routine")
        self.assertEqual(derive_execution_class("specification", "deep"), "deep")
        self.assertEqual(derive_execution_class("support", "standard"), "standard")

        # Inferred from task_type
        self.assertEqual(derive_execution_class("audit"), "deep")
        self.assertEqual(derive_execution_class("debugging"), "deep")
        self.assertEqual(derive_execution_class("support"), "routine")
        self.assertEqual(derive_execution_class("testing"), "routine")
        self.assertEqual(derive_execution_class("mechanical_change"), "routine")
        self.assertEqual(derive_execution_class("backend"), "standard")
        self.assertEqual(derive_execution_class("frontend"), "standard")

    def test_routing_priority_matrix_coverage(self):
        """Verifies ROUTING_PRIORITY_MATRIX covers task types and execution classes."""
        expected_types = ["specification", "backend", "frontend", "testing", "integration", "review"]
        expected_classes = ["routine", "standard", "deep"]

        for t in expected_types:
            for c in expected_classes:
                self.assertIn((t, c), ROUTING_PRIORITY_MATRIX, f"Missing matrix entry for ({t}, {c})")
                prefs = ROUTING_PRIORITY_MATRIX[(t, c)]
                self.assertIsInstance(prefs, list)
                self.assertGreater(len(prefs), 0)

    def test_routing_resolution_prefers_v6_adapters(self):
        """Verifies resolve_task_worker properly selects priority profiles."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        try:
            factory_config = {
                "worker_registry": {
                    "agy": {"enabled": True, "capabilities": ["specification", "backend", "frontend", "testing", "review", "audit", "integration"]},
                    "droid": {"enabled": True, "capabilities": ["coding", "backend", "debugging", "testing", "review"]},
                    "codex": {"enabled": True, "capabilities": ["coding", "frontend", "debugging", "testing", "review"]},
                    "claude": {"enabled": True, "capabilities": ["coding", "frontend", "backend", "testing", "review"]},
                    "opencode": {"enabled": True, "capabilities": ["coding", "frontend", "backend", "support", "testing", "review"]},
                }
            }

            # Testing with routine execution class prefers claude-sonnet5-high
            wid, meta, status = resolve_task_worker(
                task_id="T_TEST",
                task_def={"task_type": "testing", "execution_class": "routine", "requires": ["testing"]},
                factory_config=factory_config
            )
            self.assertEqual(status, "ROUTED")
            self.assertIn(meta["selected_profile_id"], ["claude-sonnet5-high", "agy-tests-medium", "claude-sonnet5-medium"])

            # Support with routine execution class prefers opencode-gemini-high
            wid, meta, status = resolve_task_worker(
                task_id="T_SUPP",
                task_def={"task_type": "support", "execution_class": "routine", "requires": ["support"]},
                factory_config=factory_config
            )
            self.assertEqual(status, "ROUTED")
            self.assertIn(meta["selected_profile_id"], ["opencode-gemini-high", "opencode-mimo-free", "agy-tests-medium"])
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)

    def test_explain_task_routing_includes_execution_class(self):
        """Verifies explain_task_routing outputs execution_class and priority trace."""
        temp_dir = tempfile.TemporaryDirectory()
        try:
            plan_file = pathlib.Path(temp_dir.name) / "test_plan.json"
            plan_file.write_text(json.dumps({
                "plan_id": "test_plan",
                "tasks": [
                    {
                        "task_id": "T_SAMPLE",
                        "task_type": "frontend",
                        "execution_class": "standard",
                        "requires": ["frontend"]
                    }
                ]
            }), encoding="utf-8")

            explanation = explain_task_routing(
                plan_file,
                task_id="T_SAMPLE"
            )
            self.assertEqual(explanation["task_id"], "T_SAMPLE")
            self.assertEqual(explanation["task_type"], "frontend")
            self.assertEqual(explanation["execution_class"], "standard")
            self.assertIn("profiles", explanation)
            self.assertGreater(len(explanation["profiles"]), 0)
            self.assertIn("final_decision", explanation)
        finally:
            temp_dir.cleanup()


class TestV6ExecutionTelemetryAndMetrics(unittest.TestCase):
    """Tests for telemetry metrics schema, Git churn computation, and observation-only reporting."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = pathlib.Path(self.temp_dir.name)
        self.metrics_file = self.test_dir / "telemetry.jsonl"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_metrics_schema_validation(self):
        """Verifies telemetry metrics against schemas/execution-metrics.schema.json."""
        schema_path = PROJECT_ROOT / "schemas" / "execution-metrics.schema.json"
        self.assertTrue(schema_path.exists())
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        self.assertEqual(schema["title"], "FactoryExecutionMetrics")

        sample_record = {
            "schema_version": "1.0.0",
            "metric_id": "met-12345678",
            "recorded_at": "2026-09-23T12:00:00Z",
            "run_id": "test_run",
            "task_id": "T1",
            "attempt_id": 1,
            "harness": "claude",
            "adapter": "claude",
            "profile_id": "claude-sonnet5-high",
            "model": "claude-sonnet-5",
            "effort": "high",
            "execution_class": "standard",
            "duration_ms": 12500.0,
            "status": "SUCCESS",
            "git_churn": {
                "files_changed": 3,
                "lines_added": 45,
                "lines_deleted": 10
            }
        }

        # Validate required properties exist
        for prop in schema["required"]:
            self.assertIn(prop, sample_record)

    def test_summarize_execution_metrics_observation_only(self):
        """Verifies summarize_execution_metrics provides descriptive telemetry without changing routing."""
        records = [
            {
                "schema_version": "1.0.0",
                "metric_id": "m1",
                "recorded_at": "2026-09-23T12:00:00Z",
                "run_id": "run-v6",
                "task_id": "T1",
                "attempt_id": 1,
                "harness": "claude",
                "adapter": "claude",
                "profile_id": "claude-sonnet5-high",
                "model": "claude-sonnet-5",
                "effort": "high",
                "execution_class": "standard",
                "duration_ms": 10000.0,
                "status": "COMPLETED",
                "churn": {"files_changed": 1, "lines_added": 20, "lines_deleted": 0}
            },
            {
                "schema_version": "1.0.0",
                "metric_id": "m2",
                "recorded_at": "2026-09-23T12:01:00Z",
                "run_id": "run-v6",
                "task_id": "T2",
                "attempt_id": 1,
                "harness": "opencode",
                "adapter": "opencode",
                "profile_id": "opencode-gemini-high",
                "model": "openrouter/google/gemini-2.5-flash",
                "effort": "high",
                "execution_class": "routine",
                "duration_ms": 15000.0,
                "status": "COMPLETED",
                "churn": {"files_changed": 2, "lines_added": 50, "lines_deleted": 5}
            }
        ]
        with open(self.metrics_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        summary = summarize_execution_metrics(telemetry_file=self.metrics_file)

        self.assertEqual(summary["total_attempts"], 2)
        self.assertEqual(summary["successful_attempts"], 2)
        self.assertEqual(summary["total_churn"]["files_changed"], 3)
        self.assertEqual(summary["total_churn"]["lines_added"], 70)
        self.assertEqual(summary["total_churn"]["lines_deleted"], 5)

        self.assertIn("claude-sonnet5-high", summary["by_profile"])
        self.assertIn("opencode-gemini-high", summary["by_profile"])
        self.assertIn("claude", summary["by_harness"])
        self.assertIn("opencode", summary["by_harness"])
        self.assertIn("standard", summary["by_execution_class"])
        self.assertIn("routine", summary["by_execution_class"])


if __name__ == "__main__":
    unittest.main()
