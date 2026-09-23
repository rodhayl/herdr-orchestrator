#!/usr/bin/env python3
"""
Unit and integration tests for AGY-Herdr Software Factory v5.0.0 capabilities:
1. CodexAdapter execution, CLI flags, JSON outputs, timeouts, error mapping, and attempt mismatch rejection.
2. Harness Profile data model, schema validation, and drift detection.
3. Deterministic capability router by Execution Profile (Section 20 priority table),
   concurrency constraints, fallback policies, and rich provenance recording.
4. Route explain read-only inspection engine.
5. One-way Kanban HerdrBoardProjector profile/harness/model/effort projection.
"""

import copy
import json
import os
import pathlib
import shutil
import tempfile
import unittest

from tools.factory import (
    PROJECT_ROOT,
    CodexAdapter,
    DroidAdapter,
    AgyAdapter,
    HerdrBoardProjector,
    ResourceManager,
    load_harness_profiles,
    validate_profile,
    validate_all_profiles,
    resolve_task_worker,
    explain_task_routing,
    PROFILE_TASK_TYPE_PREFERENCES
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


class TestV5CodexAdapter(unittest.TestCase):
    """Tests for CodexAdapter non-interactive execution, envelope parsing, and failure modes."""

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
            "family": "codex",
            "command": "/usr/local/bin/codex",
            "profile_home": "/root/.codex",
            "enabled": True,
            "capabilities": ["coding", "frontend", "debugging", "testing", "review"],
            "adapter": "codex",
            "invocation_adapter": "codex_cli",
            "default_model": "gpt-5.6-luna",
            "reasoning_effort": "high",
            "native": {
                "sandbox": "workspace-write",
                "approval_policy": "never",
                "network_access": False,
                "ephemeral": True
            },
            "concurrency_eligibility": False
        }
        self.adapter = CodexAdapter("codex", self.worker_cfg, self.mock_herdr, self.res_mgr)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_environment_preparation_and_resource_registration(self):
        """Verifies workspace allocation and registration in ownership registry for Codex."""
        env_info = self.adapter.prepare_environment("run-v5-001", "task_codex_frontend", 1, self.worktree)
        self.assertIn("workspace_id", env_info)
        self.assertIn("pane_id", env_info)
        self.assertEqual(env_info["worktree_path"], str(self.worktree))
        self.assertTrue(self.res_mgr.is_owned_workspace(env_info["workspace_id"]))

    def test_codex_execution_success(self):
        """Tests successful Codex execution and structured response parsing under test harness."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["CODEX_TEST_BEHAVIOR"] = "SUCCESS"
        try:
            env_info = self.adapter.prepare_environment("run-v5-001", "task_codex_frontend", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Implement frontend tags", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v5-001",
                task_id="task_codex_frontend",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=30,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
                model="gpt-5.6-luna"
            )

            self.assertEqual(result["exit_code"], 0)
            self.assertFalse(result["timed_out"])
            self.assertEqual(result["data"]["status"], "COMPLETED")
            self.assertEqual(result["data"]["task_id"], "task_codex_frontend")
            self.assertEqual(result["provenance"]["model"], "gpt-5.6-luna")
            self.assertEqual(result["provenance"]["reasoning_effort"], "high")
            self.assertEqual(result["provenance"]["sandbox"], "workspace-write")
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("CODEX_TEST_BEHAVIOR", None)

    def test_codex_execution_timeout(self):
        """Verifies that timeouts cancel the attempt and report timed_out."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["CODEX_TEST_BEHAVIOR"] = "TIMEOUT"
        try:
            env_info = self.adapter.prepare_environment("run-v5-001", "task_codex_frontend", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Slow task", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v5-001",
                task_id="task_codex_frontend",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=5,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
                model="gpt-5.6-luna"
            )

            self.assertTrue(result["timed_out"])
            self.assertEqual(result["exit_code"], -1)
            self.assertTrue(self.mock_herdr.workspaces[env_info["workspace_id"]]["closed"])
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("CODEX_TEST_BEHAVIOR", None)

    def test_codex_execution_error_envelope(self):
        """Verifies mapping of failure states from Codex output."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["CODEX_TEST_BEHAVIOR"] = "ERROR"
        try:
            env_info = self.adapter.prepare_environment("run-v5-001", "task_codex_frontend", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Failing task", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v5-001",
                task_id="task_codex_frontend",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=10,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
                model="gpt-5.6-luna"
            )

            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(result["data"]["status"], "FAILED")
            self.assertIn("Simulated Codex failure", result["data"]["error"])
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("CODEX_TEST_BEHAVIOR", None)

    def test_codex_execution_attempt_mismatch(self):
        """Verifies that an attempt mismatch is detected and rejected."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["CODEX_TEST_BEHAVIOR"] = "ATTEMPT_MISMATCH"
        try:
            env_info = self.adapter.prepare_environment("run-v5-001", "task_codex_frontend", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("Mismatch task", encoding="utf-8")
            schema_file = PROJECT_ROOT / "schemas" / "worker-result.schema.json"

            result = self.adapter.execute(
                run_id="run-v5-001",
                task_id="task_codex_frontend",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=10,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
                model="gpt-5.6-luna"
            )

            self.assertEqual(result["data"]["status"], "FAILED")
            self.assertIn("Mismatched attempt_id", result["data"]["error"])
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
            os.environ.pop("CODEX_TEST_BEHAVIOR", None)


class TestV5HarnessProfiles(unittest.TestCase):
    """Tests for Harness Profile data model, validation, and drift handling."""

    def test_load_all_certified_profiles(self):
        """Ensures all 8 certified profiles load successfully from repository configuration."""
        profiles = load_harness_profiles()
        self.assertGreaterEqual(len(profiles), 8)
        self.assertIn("agy-spec-high", profiles)
        self.assertIn("agy-backend-high", profiles)
        self.assertIn("agy-frontend-high", profiles)
        self.assertIn("agy-tests-medium", profiles)
        self.assertIn("agy-integration-high", profiles)
        self.assertIn("agy-audit-high", profiles)
        self.assertIn("droid-backend-deep", profiles)
        self.assertIn("codex-frontend-high", profiles)

    def test_validate_all_profiles_clean(self):
        """Ensures all production profiles in harness_profiles.json are completely valid."""
        results = validate_all_profiles()
        for pid, errs in results.items():
            self.assertEqual(errs, [], f"Profile '{pid}' had unexpected validation errors: {errs}")

    def test_validate_invalid_profile_id(self):
        """Rejects profile with invalid ID pattern."""
        bad_profile = {
            "id": "INVALID PROFILE ID!",
            "adapter": "agy",
            "harness": "agy",
            "enabled": True,
            "command": "agy",
            "worker_identity": "agy",
            "model": "gemini-3.8-flash",
            "effort": "high",
            "capabilities": ["coding"]
        }
        errs = validate_profile("INVALID PROFILE ID!", bad_profile)
        self.assertTrue(any("pattern" in e for e in errs))

    def test_validate_unknown_adapter(self):
        """Rejects profile with unknown adapter."""
        bad_profile = {
            "id": "test-unknown-adapter",
            "adapter": "nonexistent_adapter_xyz",
            "harness": "agy",
            "enabled": True,
            "command": "agy",
            "worker_identity": "agy",
            "model": "gemini-3.8-flash",
            "effort": "high",
            "capabilities": ["coding"]
        }
        errs = validate_profile("test-unknown-adapter", bad_profile)
        self.assertTrue(any("unknown adapter" in e for e in errs))

    def test_validate_unsupported_effort_level(self):
        """Rejects profile whose effort level is unsupported by the harness."""
        bad_profile = {
            "id": "test-bad-effort",
            "adapter": "agy",
            "harness": "agy",
            "enabled": True,
            "command": "agy",
            "worker_identity": "agy",
            "model": "gemini-3.8-flash",
            "effort": "ultra_maximum_deep",
            "capabilities": ["coding"]
        }
        errs = validate_profile("test-bad-effort", bad_profile)
        self.assertTrue(any("invalid effort" in e for e in errs))

    def test_validate_invalid_codex_sandbox(self):
        """Rejects profile declaring an illegal Codex sandbox policy."""
        bad_profile = {
            "id": "test-bad-sandbox",
            "adapter": "codex",
            "harness": "codex",
            "enabled": True,
            "command": "/usr/local/bin/codex",
            "worker_identity": "codex",
            "model": "gpt-5.6-luna",
            "effort": "high",
            "capabilities": ["coding"],
            "native": {
                "sandbox": "unrestricted_root_access"
            }
        }
        errs = validate_profile("test-bad-sandbox", bad_profile)
        self.assertTrue(any("invalid Codex sandbox" in e for e in errs))


class TestV5ExecutionProfileRouting(unittest.TestCase):
    """Tests for deterministic routing by execution profile (Section 20 priority table)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_root = pathlib.Path(self.temp_dir.name)
        self.profiles_path = self.test_root / "harness_profiles.json"
        # Copy real profiles into temporary location
        shutil.copyfile(PROJECT_ROOT / "harness_profiles.json", self.profiles_path)
        with open(PROJECT_ROOT / "factory.json", "r", encoding="utf-8") as f:
            self.factory_config = json.load(f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_section_20_specification_routing(self):
        """Verifies specification tasks route to agy-spec-high."""
        task_def = {
            "task_id": "t_spec",
            "task_type": "specification",
            "requires": ["planning", "specification"]
        }
        wid, meta, status = resolve_task_worker("t_spec", task_def, self.factory_config, profiles_path=self.profiles_path)
        self.assertEqual(status, "ROUTED")
        self.assertEqual(meta["selected_profile_id"], "agy-spec-high")
        self.assertEqual(meta["worker_identity"], "agy2")
        self.assertEqual(meta["selected_adapter"], "agy")
        self.assertEqual(meta["model"], "gemini-3.8-flash")
        self.assertEqual(meta["effort"], "high")

    def test_section_20_backend_priority_with_test_harness(self):
        """Under test harness, droid-backend-deep is preferred for backend tasks."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        try:
            task_def = {
                "task_id": "t_backend",
                "task_type": "backend",
                "requires": ["coding", "backend"]
            }
            wid, meta, status = resolve_task_worker("t_backend", task_def, self.factory_config, profiles_path=self.profiles_path)
            self.assertEqual(status, "ROUTED")
            self.assertEqual(meta["selected_profile_id"], "droid-backend-deep")
            self.assertEqual(meta["worker_identity"], "droid")
            self.assertEqual(meta["selected_adapter"], "droid")
            self.assertEqual(meta["model"], "qwen3.8-max")
            self.assertEqual(meta["effort"], "xhigh")
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)

    def test_section_20_backend_fallback_when_droid_busy(self):
        """When droid-backend-deep is busy, backend falls back deterministically to agy-backend-high."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        try:
            task_def = {
                "task_id": "t_backend_2",
                "task_type": "backend",
                "requires": ["coding", "backend"]
            }
            busy_profiles = {"droid-backend-deep"}
            busy_workers = {"droid"}
            wid, meta, status = resolve_task_worker(
                "t_backend_2", task_def, self.factory_config,
                busy_workers=busy_workers, busy_profiles=busy_profiles,
                profiles_path=self.profiles_path
            )
            self.assertEqual(status, "ROUTED")
            self.assertEqual(meta["selected_profile_id"], "agy-backend-high")
            self.assertEqual(meta["worker_identity"], "agy3")
            self.assertEqual(meta["selected_adapter"], "agy")
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)

    def test_section_20_frontend_priority_with_test_harness(self):
        """Under test harness, codex-frontend-high is preferred for frontend tasks."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        try:
            task_def = {
                "task_id": "t_frontend",
                "task_type": "frontend",
                "requires": ["coding", "frontend"]
            }
            wid, meta, status = resolve_task_worker("t_frontend", task_def, self.factory_config, profiles_path=self.profiles_path)
            self.assertEqual(status, "ROUTED")
            self.assertEqual(meta["selected_profile_id"], "codex-frontend-high")
            self.assertEqual(meta["worker_identity"], "codex")
            self.assertEqual(meta["selected_adapter"], "codex")
            self.assertEqual(meta["model"], "gpt-5.6-luna")
            self.assertEqual(meta["effort"], "high")
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)

    def test_section_20_frontend_fallback_when_codex_busy(self):
        """When codex-frontend-high is busy, frontend falls back deterministically to agy-frontend-high."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        try:
            task_def = {
                "task_id": "t_frontend_2",
                "task_type": "frontend",
                "requires": ["coding", "frontend"]
            }
            busy_profiles = {"codex-frontend-high"}
            busy_workers = {"codex"}
            wid, meta, status = resolve_task_worker(
                "t_frontend_2", task_def, self.factory_config,
                busy_workers=busy_workers, busy_profiles=busy_profiles,
                profiles_path=self.profiles_path
            )
            self.assertEqual(status, "ROUTED")
            self.assertEqual(meta["selected_profile_id"], "agy-frontend-high")
            self.assertEqual(meta["worker_identity"], "agy4")
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)

    def test_section_20_live_mode_auth_block_fallback(self):
        """In live mode without FACTORY_API_KEY / OPENAI_API_KEY, router falls back cleanly to AGY."""
        # Ensure credentials are unset
        old_fact = os.environ.pop("FACTORY_API_KEY", None)
        old_open = os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("FACTORY_TEST_HARNESS", None)

        try:
            # Backend task falls back to agy-backend-high
            t_backend = {"task_id": "tb", "task_type": "backend", "requires": ["coding", "backend"]}
            _, meta_b, status_b = resolve_task_worker("tb", t_backend, self.factory_config, profiles_path=self.profiles_path)
            self.assertEqual(status_b, "ROUTED")
            self.assertEqual(meta_b["selected_profile_id"], "agy-backend-high")

            # Frontend task falls back to agy-frontend-high
            t_frontend = {"task_id": "tf", "task_type": "frontend", "requires": ["coding", "frontend"]}
            _, meta_f, status_f = resolve_task_worker("tf", t_frontend, self.factory_config, profiles_path=self.profiles_path)
            self.assertEqual(status_f, "ROUTED")
            self.assertEqual(meta_f["selected_profile_id"], "agy-frontend-high")
        finally:
            if old_fact:
                os.environ["FACTORY_API_KEY"] = old_fact
            if old_open:
                os.environ["OPENAI_API_KEY"] = old_open

    def test_all_candidates_busy_returns_busy_status(self):
        """When all eligible candidates for a capability set are busy, scheduler returns BUSY."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        try:
            task_def = {"task_id": "tf", "task_type": "frontend", "requires": ["coding", "frontend"]}
            # Mark both codex-frontend-high and agy-frontend-high busy
            busy_profiles = {"codex-frontend-high", "agy-frontend-high"}
            busy_workers = {"codex", "agy4"}
            _, meta, status = resolve_task_worker(
                "tf", task_def, self.factory_config,
                busy_workers=busy_workers, busy_profiles=busy_profiles,
                profiles_path=self.profiles_path
            )
            self.assertEqual(status, "BUSY")
            self.assertIn("busy", meta["selection_reason"].lower())
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)

    def test_profile_drift_handling(self):
        """Modifying a profile to have an invalid effort causes it to be excluded while valid profiles route normally."""
        with open(self.profiles_path, "r", encoding="utf-8") as f:
            p_data = json.load(f)
        # Corrupt codex-frontend-high effort
        p_data["profiles"]["codex-frontend-high"]["effort"] = "invalid_drifted_effort"
        with open(self.profiles_path, "w", encoding="utf-8") as f:
            json.dump(p_data, f)

        os.environ["FACTORY_TEST_HARNESS"] = "1"
        try:
            task_def = {"task_id": "tf", "task_type": "frontend", "requires": ["coding", "frontend"]}
            wid, meta, status = resolve_task_worker("tf", task_def, self.factory_config, profiles_path=self.profiles_path)
            self.assertEqual(status, "ROUTED")
            # Must route around drifted profile to agy-frontend-high
            self.assertEqual(meta["selected_profile_id"], "agy-frontend-high")
            self.assertTrue(any(inv["profile_id"] == "codex-frontend-high" for inv in meta["invalid_profiles"]))
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)


class TestV5RouteExplain(unittest.TestCase):
    """Tests for route explain CLI inspection without mutation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_root = pathlib.Path(self.temp_dir.name)
        self.plan_path = self.test_root / "test_plan.json"
        plan_content = {
            "plan_id": "test_explain",
            "name": "Test Explain Plan",
            "version": "1.0.0",
            "tasks": [
                {
                    "task_id": "task_backend",
                    "task_type": "backend",
                    "requires": ["coding", "backend"]
                }
            ]
        }
        with open(self.plan_path, "w", encoding="utf-8") as f:
            json.dump(plan_content, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_explain_task_routing_structure(self):
        """Verifies explain_task_routing returns complete analysis dictionary."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        try:
            explanation = explain_task_routing(self.plan_path, "task_backend")
            self.assertEqual(explanation["task_id"], "task_backend")
            self.assertEqual(explanation["task_type"], "backend")
            self.assertEqual(sorted(explanation["required_capabilities"]), sorted(["coding", "backend"]))
            self.assertIsInstance(explanation["profiles"], list)
            self.assertGreaterEqual(len(explanation["profiles"]), 8)

            # Check top ranked profile is droid-backend-deep
            top_ranked = [p for p in explanation["profiles"] if p["priority_rank"] == 1][0]
            self.assertEqual(top_ranked["profile_id"], "droid-backend-deep")
            self.assertTrue(top_ranked["capability_match"])
            self.assertEqual(top_ranked["eligibility"], "ELIGIBLE")

            self.assertEqual(explanation["final_decision"]["status"], "ROUTED")
            self.assertEqual(explanation["final_decision"]["selected_profile"], "droid-backend-deep")
        finally:
            os.environ.pop("FACTORY_TEST_HARNESS", None)


class TestV5BoardProjection(unittest.TestCase):
    """Tests for Kanban board projection of profile/harness/model/effort metadata."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_root = pathlib.Path(self.temp_dir.name)
        self.projector = HerdrBoardProjector(root_dir=self.test_root)
        self.runs_dir = self.test_root / ".agy-factory" / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_board_projects_profile_metadata(self):
        """Verifies cards contain profile, harness, model, and effort fields."""
        run_id = "run-v5-test-01"
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "run_id": run_id,
            "tasks": {
                "t_fe": {
                    "task_id": "t_fe",
                    "canonical_state": "RUNNING",
                    "worker_id": "codex",
                    "profile_id": "codex-frontend-high",
                    "harness": "codex",
                    "adapter": "codex",
                    "model": "gpt-5.6-luna",
                    "effort": "high",
                    "current_attempt_id": 1,
                    "task_type": "frontend"
                },
                "t_be": {
                    "task_id": "t_be",
                    "canonical_state": "RUNNING",
                    "worker_id": "droid",
                    "profile_id": "droid-backend-deep",
                    "harness": "droid",
                    "adapter": "droid",
                    "model": "qwen3.8-max",
                    "effort": "xhigh",
                    "current_attempt_id": 1,
                    "task_type": "backend"
                }
            }
        }
        with open(run_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        res = self.projector.sync(run_id)
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["synced_cards_count"], 2)

        # Inspect cards
        with open(self.projector.cards_file, "r", encoding="utf-8") as f:
            cards = json.load(f)

        card_fe = [c for c in cards.values() if c["task_id"] == "t_fe"][0]
        self.assertEqual(card_fe["profile"], "codex-frontend-high")
        self.assertEqual(card_fe["harness"], "codex")
        self.assertEqual(card_fe["model"], "gpt-5.6-luna")
        self.assertEqual(card_fe["effort"], "high")
        self.assertEqual(card_fe["column"], "Running")

        card_be = [c for c in cards.values() if c["task_id"] == "t_be"][0]
        self.assertEqual(card_be["profile"], "droid-backend-deep")
        self.assertEqual(card_be["harness"], "droid")
        self.assertEqual(card_be["model"], "qwen3.8-max")
        self.assertEqual(card_be["effort"], "xhigh")
        self.assertEqual(card_be["column"], "Running")

    def test_board_authority_and_no_dispatch(self):
        """Verifies board projection status guarantees one-way authority and zero auto-dispatch."""
        status = self.projector.get_status()
        self.assertEqual(status["authority"], "factory (one-way)")
        self.assertFalse(status["auto_dispatch"])


if __name__ == "__main__":
    unittest.main()
