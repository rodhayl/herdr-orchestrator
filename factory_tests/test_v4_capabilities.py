#!/usr/bin/env python3
"""
Unit and integration tests for AGY-Herdr Software Factory v4.0.0 capabilities:
1. DroidAdapter execution, CLI flags, JSON envelopes, timeouts, and error handling.
2. Deterministic capability router: capability matching, task-type preference order,
   busy worker fallback, explicit worker backward compatibility, and routing provenance.
3. One-way Kanban HerdrBoardProjector: 7 columns, idempotency, self-correction,
   offline resilience, and zero worker dispatch.
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
    DroidAdapter,
    HerdrBoardProjector,
    HerdrClient,
    ResourceManager,
    resolve_task_worker,
    WORKER_CAPABILITIES,
    TASK_TYPE_PREFERENCES
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

    def create_workspace(self, cwd: str, label: str = None) -> tuple[str, str]:
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


class TestV4DroidAdapter(unittest.TestCase):
    """Tests for DroidAdapter command construction, envelope parsing, and failure modes."""

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
            "family": "droid",
            "command": "/root/.local/bin/droid",
            "profile_home": "/root/.factory",
            "enabled": True,
            "capabilities": ["coding", "backend", "testing", "debugging", "mechanical_change"],
            "adapter": "droid",
            "invocation_adapter": "droid_cli",
            "default_model": "qwen3.8-max",
            "reasoning_effort": "xhigh",
            "autonomy": "low",
            "concurrency_eligibility": False
        }
        self.adapter = DroidAdapter("droid", self.worker_cfg, self.mock_herdr, self.res_mgr)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_environment_preparation_and_resource_registration(self):
        """Verifies workspace allocation and registration in ownership registry."""
        env_info = self.adapter.prepare_environment("run-v4-001", "task_droid_backend", 1, self.worktree)
        self.assertIn("workspace_id", env_info)
        self.assertIn("pane_id", env_info)
        self.assertEqual(env_info["worktree_path"], str(self.worktree))
        # Must be recorded in ResourceManager
        self.assertTrue(self.res_mgr.is_owned_workspace(env_info["workspace_id"]))

    def test_droid_cli_envelope_parsing_success(self):
        """Verifies proper extraction of outer envelope provenance and inner task data."""
        inner_task_json = {
            "run_id": "run-v4-001",
            "task_id": "t_backend",
            "attempt_id": 1,
            "status": "SUCCESS",
            "summary": "Implemented bookmarks API",
            "changed_files": ["backend/app.py"]
        }
        outer_envelope = {
            "session_id": "droid-sess-12345",
            "duration_ms": 5280,
            "turns": 4,
            "model": "qwen3.8-max",
            "reasoning_effort": "xhigh",
            "is_error": False,
            "result": json.dumps(inner_task_json)
        }
        raw_output = json.dumps(outer_envelope)
        parsed = self.adapter._parse_droid_output(raw_output, "run-v4-001", "t_backend", 1)

        self.assertEqual(parsed["task_data"]["status"], "SUCCESS")
        self.assertEqual(parsed["task_data"]["summary"], "Implemented bookmarks API")
        self.assertEqual(parsed["provenance"]["session_id"], "droid-sess-12345")
        self.assertEqual(parsed["provenance"]["duration_ms"], 5280)
        self.assertEqual(parsed["provenance"]["turns"], 4)
        self.assertEqual(parsed["provenance"]["model"], "qwen3.8-max")
        self.assertEqual(parsed["provenance"]["reasoning_effort"], "xhigh")

    def test_droid_outer_envelope_error(self):
        """Verifies that is_error=True in outer envelope is cleanly propagated as failure."""
        outer_envelope = {
            "is_error": True,
            "error": "Context window exceeded",
            "result": "Process failed"
        }
        raw_output = json.dumps(outer_envelope)
        parsed = self.adapter._parse_droid_output(raw_output, "run-v4-001", "t_backend", 1)
        self.assertEqual(parsed["task_data"]["status"], "FAILED")
        self.assertIn("Context window exceeded", parsed["task_data"]["error"])

    def test_droid_mismatched_task_id_rejection(self):
        """Verifies rejection if returned task JSON references an unexpected task ID."""
        inner_task_json = {
            "task_id": "WRONG_TASK",
            "attempt_id": 1,
            "status": "SUCCESS"
        }
        outer_envelope = {"is_error": False, "result": json.dumps(inner_task_json)}
        parsed = self.adapter._parse_droid_output(json.dumps(outer_envelope), "run-v4-001", "t_backend", 1)
        self.assertEqual(parsed["task_data"]["status"], "FAILED")
        self.assertIn("Mismatched task_id", parsed["task_data"]["error"])

    def test_droid_mismatched_attempt_id_rejection(self):
        """Verifies rejection if returned attempt ID does not match current attempt."""
        inner_task_json = {
            "task_id": "t_backend",
            "attempt_id": 999,
            "status": "SUCCESS"
        }
        outer_envelope = {"is_error": False, "result": json.dumps(inner_task_json)}
        parsed = self.adapter._parse_droid_output(json.dumps(outer_envelope), "run-v4-001", "t_backend", 1)
        self.assertEqual(parsed["task_data"]["status"], "FAILED")
        self.assertIn("Mismatched attempt_id", parsed["task_data"]["error"])

    def test_droid_test_harness_timeout_behavior(self):
        """Tests controlled TIMEOUT injection via test harness."""
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["DROID_TEST_BEHAVIOR"] = "TIMEOUT"
        try:
            env_info = self.adapter.prepare_environment("run-v4-001", "t_timeout", 1, self.worktree)
            prompt_file = self.task_attempt_dir / "prompt.md"
            prompt_file.write_text("prompt")
            schema_file = self.task_attempt_dir / "schema.json"
            schema_file.write_text("{}")

            res = self.adapter.execute(
                run_id="run-v4-001",
                task_id="t_timeout",
                attempt_id=1,
                worktree_path=self.worktree,
                prompt_file=prompt_file,
                schema_file=schema_file,
                timeout=1,
                task_attempt_dir=self.task_attempt_dir,
                env_info=env_info,
                model="qwen3.8-max"
            )
            self.assertTrue(res["timed_out"])
            self.assertEqual(res["exit_code"], -1)
            # Must have closed workspace
            self.assertTrue(self.mock_herdr.workspaces[env_info["workspace_id"]]["closed"])
        finally:
            del os.environ["DROID_TEST_BEHAVIOR"]
            del os.environ["FACTORY_TEST_HARNESS"]


class TestV4CapabilityRouter(unittest.TestCase):
    """Tests for deterministic capability-based routing and fallback logic."""

    def setUp(self):
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        with open(PROJECT_ROOT / "factory.json", "r", encoding="utf-8") as f:
            self.config = json.load(f)

    def tearDown(self):
        if "FACTORY_TEST_HARNESS" in os.environ:
            del os.environ["FACTORY_TEST_HARNESS"]

    def test_explicit_worker_assignment_backward_compatibility(self):
        """Verifies that tasks with explicit worker_id bypass capability selection."""
        task_def = {
            "task_id": "legacy_spec",
            "worker_id": "agy2",
            "requires": ["spec"]
        }
        wid, meta, status = resolve_task_worker("legacy_spec", task_def, self.config)
        self.assertEqual(status, "ROUTED")
        self.assertEqual(wid, "agy2")
        self.assertEqual(meta["routing_mode"], "explicit")
        self.assertEqual(meta["selected_adapter"], "agy")

    def test_explicit_worker_unknown_blocks(self):
        """Verifies that an unknown explicit worker is blocked with error."""
        task_def = {
            "task_id": "legacy_unknown",
            "worker_id": "nonexistent_worker"
        }
        wid, meta, status = resolve_task_worker("legacy_unknown", task_def, self.config)
        self.assertEqual(status, "BLOCKED")
        self.assertIsNone(wid)

    def test_capability_matching_and_preference_ordering(self):
        """Verifies that task_type='backend' routes to droid as first preference."""
        task_def = {
            "task_id": "backend_task",
            "task_type": "backend",
            "requires": ["coding", "backend"]
        }
        wid, meta, status = resolve_task_worker("backend_task", task_def, self.config, busy_workers=set())
        self.assertEqual(status, "ROUTED")
        self.assertEqual(wid, "droid")
        self.assertEqual(meta["selected_adapter"], "droid")
        self.assertIn("droid", meta["eligible_candidates"])
        self.assertIn("agy3", meta["eligible_candidates"])

    def test_busy_worker_fallback_simultaneous_backend_tasks(self):
        """
        Verifies fallback: when droid is busy with Task 1,
        Task 2 (also backend) falls back to agy3.
        """
        task_def_1 = {
            "task_id": "backend_task_1",
            "task_type": "backend",
            "requires": ["coding", "backend"]
        }
        # First task gets droid
        wid_1, meta_1, status_1 = resolve_task_worker("backend_task_1", task_def_1, self.config, busy_workers=set())
        self.assertEqual(status_1, "ROUTED")
        self.assertEqual(wid_1, "droid")

        # Second simultaneous backend task with droid busy
        task_def_2 = {
            "task_id": "backend_task_2",
            "task_type": "backend",
            "requires": ["coding", "backend"]
        }
        wid_2, meta_2, status_2 = resolve_task_worker("backend_task_2", task_def_2, self.config, busy_workers={"droid"})
        self.assertEqual(status_2, "ROUTED")
        self.assertEqual(wid_2, "agy3")
        self.assertEqual(meta_2["selected_adapter"], "agy")
        self.assertIn("droid", meta_2["busy_candidates"])

    def test_all_eligible_workers_busy_yields_busy_status(self):
        """Verifies that when all eligible candidates are busy, router returns BUSY."""
        task_def = {
            "task_id": "backend_task_3",
            "task_type": "backend",
            "requires": ["coding", "backend"]
        }
        # Both droid and agy3 busy
        wid, meta, status = resolve_task_worker("backend_task_3", task_def, self.config, busy_workers={"droid", "agy3"})
        self.assertEqual(status, "BUSY")
        self.assertIsNone(wid)
        self.assertEqual(len(meta["busy_candidates"]), 2)

    def test_impossible_capabilities_yields_blocked_status(self):
        """Verifies that tasks demanding nonexistent capabilities are blocked."""
        task_def = {
            "task_id": "quantum_task",
            "task_type": "backend",
            "requires": ["quantum_cryptography", "teleportation"]
        }
        wid, meta, status = resolve_task_worker("quantum_task", task_def, self.config)
        self.assertEqual(status, "BLOCKED")
        self.assertIsNone(wid)
        self.assertIn("No worker satisfies required capabilities", meta["selection_reason"])

    def test_routing_provenance_structure(self):
        """Verifies completeness of routing provenance metadata for auditability."""
        task_def = {
            "task_id": "spec_task",
            "task_type": "specification",
            "requires": ["planning", "specification"]
        }
        wid, meta, status = resolve_task_worker("spec_task", task_def, self.config)
        self.assertEqual(status, "ROUTED")
        for key in ["routing_mode", "task_type", "required_capabilities", "eligible_candidates",
                    "busy_candidates", "selected_worker", "selected_adapter", "selection_reason"]:
            self.assertIn(key, meta)


class TestV4HerdrBoardProjector(unittest.TestCase):
    """Tests for one-way Kanban HerdrBoardProjector engine."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = pathlib.Path(self.temp_dir.name)
        self.runs_dir = self.project_root / ".agy-factory" / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.projector = HerdrBoardProjector(root_dir=self.project_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_mock_run(self, run_id: str, tasks: dict):
        run_path = self.runs_dir / run_id
        run_path.mkdir(parents=True, exist_ok=True)
        manifest = {
            "run_id": run_id,
            "plan_id": "test_plan",
            "tasks": tasks
        }
        with open(run_path / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)

    def test_seven_columns_defined(self):
        """Verifies the exact 7 Kanban columns defined by contract."""
        expected = ["Backlog", "Ready", "Running", "Blocked", "Review", "Done", "Failed"]
        self.assertEqual(self.projector.COLUMNS, expected)

    def test_canonical_state_column_projection(self):
        """Verifies translation of canonical task states to the 7 board columns."""
        mock_tasks = {
            "t1": {"canonical_state": "PENDING", "worker_id": "agy2"},
            "t2": {"canonical_state": "READY", "worker_id": "droid"},
            "t3": {"canonical_state": "RUNNING", "worker_id": "droid"},
            "t4": {"canonical_state": "BLOCKED", "worker_id": "agy3"},
            "t5": {"canonical_state": "INTEGRATED", "worker_id": "agy4"},
            "t6": {"canonical_state": "COMPLETED", "worker_id": "agy7"},
            "t7": {"canonical_state": "FAILED", "worker_id": "agy5"},
            "t8": {"canonical_state": "CONFLICTED", "worker_id": "agy6"}
        }
        self._create_mock_run("run-test-cols", mock_tasks)
        sync_res = self.projector.sync()
        self.assertEqual(sync_res["status"], "OK")

        status = self.projector.get_status()
        view = status["columns_view"]

        self.assertEqual(len(view["Backlog"]), 1)
        self.assertEqual(view["Backlog"][0]["task_id"], "t1")

        self.assertEqual(len(view["Ready"]), 1)
        self.assertEqual(view["Ready"][0]["task_id"], "t2")

        self.assertEqual(len(view["Running"]), 1)
        self.assertEqual(view["Running"][0]["task_id"], "t3")

        self.assertEqual(len(view["Blocked"]), 1)
        self.assertEqual(view["Blocked"][0]["task_id"], "t4")

        self.assertEqual(len(view["Review"]), 1)
        self.assertEqual(view["Review"][0]["task_id"], "t5")

        self.assertEqual(len(view["Done"]), 1)
        self.assertEqual(view["Done"][0]["task_id"], "t6")

        self.assertEqual(len(view["Failed"]), 2)  # FAILED + CONFLICTED
        failed_ids = {c["task_id"] for c in view["Failed"]}
        self.assertEqual(failed_ids, {"t7", "t8"})

    def test_sync_idempotency_zero_duplicate_cards(self):
        """Verifies that multiple sync calls create zero duplicate cards."""
        mock_tasks = {
            "t1": {"canonical_state": "READY", "worker_id": "droid"},
            "t2": {"canonical_state": "RUNNING", "worker_id": "agy3"}
        }
        self._create_mock_run("run-idemp", mock_tasks)

        sync1 = self.projector.sync()
        self.assertEqual(sync1["total_cards"], 2)

        sync2 = self.projector.sync()
        self.assertEqual(sync2["total_cards"], 2)

        sync3 = self.projector.sync()
        self.assertEqual(sync3["total_cards"], 2)

    def test_self_correction_after_manual_tampering(self):
        """
        Verifies strict one-way authority:
        If a user or UI manually moves a card (e.g. moves RUNNING card to 'Done'),
        sync() restores the card to its canonical state column ('Running').
        """
        mock_tasks = {
            "t_active": {"canonical_state": "RUNNING", "worker_id": "droid"}
        }
        self._create_mock_run("run-tamper", mock_tasks)
        self.projector.sync()

        card_id = self.projector.mapping["run-tamper:t_active"]
        self.assertEqual(self.projector.cards[card_id]["column"], "Running")

        # Manually tamper with card column (simulate external move)
        self.projector.cards[card_id]["column"] = "Done"
        self.projector._save()

        # Reload fresh instance
        fresh_projector = HerdrBoardProjector(root_dir=self.project_root)
        self.assertEqual(fresh_projector.cards[card_id]["column"], "Done")

        # Run sync: must self-correct to "Running"
        fresh_projector.sync()
        self.assertEqual(fresh_projector.cards[card_id]["column"], "Running")

    def test_offline_resilience_and_compatibility_reporting(self):
        """Verifies that projector works cleanly when board daemon is not installed."""
        status = self.projector.get_status()
        self.assertEqual(status["authority"], "factory (one-way)")
        self.assertEqual(status["compatibility_status"], "BLOCKED_EXTERNAL_COMPATIBILITY")
        self.assertFalse(status["auto_dispatch"])


if __name__ == "__main__":
    unittest.main()
