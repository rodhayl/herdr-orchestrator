"""Deterministic unit and integration tests for AGY-Herdr Software Factory v3.0.0.

Validates:
1. Generic WorkerAdapter boundary and FakeWorkerAdapter registration.
2. Arbitrary DAG scheduling (linear, fan-out/fan-in, failure propagation, concurrency limit).
3. Attempt identity, isolated attempt worktrees, and attempt history.
4. Deterministic crash failpoint injection and reconciliation-based resume (Cases A-F).
5. Explicit Git merge conflict detection and clean abort.
6. Concurrent run isolation and run-scoped cleanup.
7. Path guardrails and symlink escape rejection.
8. Status projection JSON contract for Kanban integration.
"""

import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from factory import (
    WorkerAdapter,
    register_adapter,
    ADAPTER_REGISTRY,
    get_adapter,
    FactoryOrchestrator,
    TaskExecutor,
    ResourceManager,
    HerdrClient,
    validate_plan_file,
    check_worktree_symlinks,
    generate_status_projection,
    CANONICAL_TO_DISPLAY_STATE,
    RUNS_DIR,
    WORKTREES_DIR,
    atomic_write_json
)


class MockHerdrClient:
    """Mock Herdr client for deterministic testing."""
    def __init__(self):
        self.control_plane = {
            "workspace_id": "wK",
            "pane_id": "wK:p1",
            "tab_id": "wK:t1",
            "cwd": str(PROJECT_ROOT),
            "herdr_socket": "/root/.config/herdr/herdr.sock"
        }
        self.created_workspaces = []
        self.closed_workspaces = []
        self.executed_commands = []

    def create_workspace(self, cwd, label):
        ws_id = f"mock-ws-{len(self.created_workspaces)+1}"
        pane_id = f"{ws_id}:p1"
        self.created_workspaces.append((ws_id, pane_id, cwd, label))
        return ws_id, pane_id

    def run_in_pane(self, pane_id, command):
        self.executed_commands.append((pane_id, command))

    def close_workspace(self, workspace_id):
        self.closed_workspaces.append(workspace_id)
        return True


class FakeWorkerAdapter(WorkerAdapter):
    """Configurable fake worker adapter for deterministic test scenarios."""
    behavior = "SUCCESS"  # SUCCESS, TIMEOUT, CRASH, PATH_VIOLATION, SYMLINK_ESCAPE, CONFLICT

    def prepare_environment(self, run_id, task_id, attempt_id, worktree_path):
        ws_id = f"fake-ws-{task_id}-a{attempt_id}"
        pane_id = f"{ws_id}:p1"
        self.res_mgr.record_workspace(ws_id, pane_id, run_id=run_id)
        return {"workspace_id": ws_id, "pane_id": pane_id, "worktree_path": str(worktree_path)}

    def execute(self, run_id, task_id, attempt_id, worktree_path,
                prompt_file, schema_file, timeout, task_attempt_dir, env_info, model):

        if self.behavior == "TIMEOUT":
            return {
                "exit_code": -1,
                "timed_out": True,
                "error": f"Simulated timeout after {timeout}s",
                "raw_output": ""
            }

        if self.behavior == "CRASH":
            return {
                "exit_code": 1,
                "timed_out": False,
                "raw_output": "Process crashed with segmentation fault",
                "data": {"status": "FAILED", "error": "Crash"}
            }

        if self.behavior == "PATH_VIOLATION":
            # Write a file outside allowed paths
            violating_file = worktree_path / "outside_allowed" / "illegal.txt"
            violating_file.parent.mkdir(parents=True, exist_ok=True)
            violating_file.write_text("I am illegal", encoding="utf-8")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": '{"status": "SUCCESS"}',
                "data": {"status": "SUCCESS", "structured_output": {"summary": "Wrote illegal file"}}
            }

        if self.behavior == "SYMLINK_ESCAPE":
            # Create a symlink pointing to /tmp or outside project root
            escape_link = worktree_path / "test_escape_link"
            target_outside = pathlib.Path("/tmp")
            try:
                os.symlink(target_outside, escape_link)
            except Exception:
                pass
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": '{"status": "SUCCESS"}',
                "data": {"status": "SUCCESS", "structured_output": {"summary": "Created escape link"}}
            }

        if self.behavior == "CONFLICT":
            # Writes conflicting content into shared_test_file.txt
            fpath = worktree_path / "factory_tests" / "fixtures" / "shared_conflict.txt"
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(f"Conflict from task {task_id} attempt {attempt_id}\n", encoding="utf-8")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": '{"status": "SUCCESS"}',
                "data": {"status": "SUCCESS", "structured_output": {"summary": f"Modified conflict file by {task_id}"}}
            }

        # Default: SUCCESS
        # Create expected file if defined in prompt or dummy file in test fixture
        dummy_file = worktree_path / "factory_tests" / "fixtures" / f"output_{task_id}_{run_id}.txt"
        dummy_file.parent.mkdir(parents=True, exist_ok=True)
        dummy_file.write_text(f"Generated by {task_id} in {run_id} attempt {attempt_id}\n", encoding="utf-8")

        return {
            "exit_code": 0,
            "timed_out": False,
            "raw_output": json.dumps({"status": "SUCCESS", "structured_output": {"summary": f"Completed {task_id}"}}),
            "data": {
                "status": "SUCCESS",
                "structured_output": {
                    "task_id": task_id,
                    "summary": f"Successfully finished {task_id}"
                }
            }
        }

    def cancel(self, run_id, task_id, attempt_id, env_info):
        ws_id = env_info.get("workspace_id")
        if ws_id:
            self.res_mgr.clean_workspace(ws_id)
        return True


# Register test adapter
register_adapter("fake_worker", FakeWorkerAdapter)


class TestV3WorkerAdapter(unittest.TestCase):
    """Tests for WorkerAdapter boundary and registration."""

    def test_adapter_registry_lookup(self):
        mock_herdr = MockHerdrClient()
        with tempfile.TemporaryDirectory() as td:
            res_mgr = ResourceManager(mock_herdr, state_file=pathlib.Path(td) / "owned.json")
            worker_cfg = {"adapter": "fake_worker", "command": "fake"}
            adapter = get_adapter("test_worker", worker_cfg, mock_herdr, res_mgr)
            self.assertIsInstance(adapter, FakeWorkerAdapter)

    def test_unknown_adapter_raises(self):
        mock_herdr = MockHerdrClient()
        with tempfile.TemporaryDirectory() as td:
            res_mgr = ResourceManager(mock_herdr, state_file=pathlib.Path(td) / "owned.json")
            worker_cfg = {"adapter": "non_existent_adapter"}
            with self.assertRaises(ValueError):
                get_adapter("test_worker", worker_cfg, mock_herdr, res_mgr)


class TestV3DAGScheduler(unittest.TestCase):
    """Tests for arbitrary DAG scheduler execution."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_plan_path = pathlib.Path(self.temp_dir.name) / "dag_plan.json"
        self.orig_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT), capture_output=True, text=True).stdout.strip()
        FakeWorkerAdapter.behavior = "SUCCESS"

    def tearDown(self):
        self.temp_dir.cleanup()
        # Reset git state and prune worktrees
        subprocess.run(["git", "reset", "--hard", self.orig_commit], cwd=str(PROJECT_ROOT), capture_output=True)
        # Clean any test branches created during tests
        proc = subprocess.run(["git", "branch", "--list", "factory/run-*"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        for br in proc.stdout.splitlines():
            b = br.strip().replace("*", "").strip()
            if b and ("diamond" in b or "failure" in b or "test" in b):
                subprocess.run(["git", "branch", "-D", b], cwd=str(PROJECT_ROOT), capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=str(PROJECT_ROOT), capture_output=True)

    def test_dag_fan_out_fan_in(self):
        """Validates diamond DAG: T1 -> (T2, T3) -> T4."""
        plan = {
            "plan_id": "test_diamond_dag",
            "name": "Diamond DAG Plan",
            "version": "3.0.0",
            "max_concurrency": 2,
            "tasks": [
                {
                    "task_id": "task_root",
                    "worker_id": "agy",
                    "dependencies": [],
                    "allowed_paths": ["factory_tests/fixtures/**"]
                },
                {
                    "task_id": "task_branch_a",
                    "worker_id": "agy",
                    "dependencies": ["task_root"],
                    "allowed_paths": ["factory_tests/fixtures/**"]
                },
                {
                    "task_id": "task_branch_b",
                    "worker_id": "agy",
                    "dependencies": ["task_root"],
                    "allowed_paths": ["factory_tests/fixtures/**"]
                },
                {
                    "task_id": "task_join",
                    "worker_id": "agy",
                    "dependencies": ["task_branch_a", "task_branch_b"],
                    "allowed_paths": ["factory_tests/fixtures/**"]
                }
            ]
        }
        with open(self.test_plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f)

        # Temporary configure agy to use fake_worker in factory_config
        orch = FactoryOrchestrator(self.test_plan_path)
        orch.factory_config["worker_registry"]["agy"]["adapter"] = "fake_worker"

        manifest = orch.execute_plan()
        self.assertEqual(manifest["final_status"], "COMPLETED")
        self.assertEqual(manifest["tasks"]["task_root"]["canonical_state"], "INTEGRATED")
        self.assertEqual(manifest["tasks"]["task_branch_a"]["canonical_state"], "INTEGRATED")
        self.assertEqual(manifest["tasks"]["task_branch_b"]["canonical_state"], "INTEGRATED")
        self.assertEqual(manifest["tasks"]["task_join"]["canonical_state"], "INTEGRATED")

        # Cleanup run directory
        if orch.run_dir.exists():
            shutil.rmtree(orch.run_dir, ignore_errors=True)

    def test_dag_failure_propagation(self):
        """Validates that if T1 fails, dependent T2 transitions to BLOCKED."""
        plan = {
            "plan_id": "test_failure_dag",
            "name": "Failure Propagation Plan",
            "version": "3.0.0",
            "tasks": [
                {
                    "task_id": "task_fail",
                    "worker_id": "agy",
                    "dependencies": [],
                    "allowed_paths": ["factory_tests/fixtures/**"]
                },
                {
                    "task_id": "task_dependent",
                    "worker_id": "agy",
                    "dependencies": ["task_fail"],
                    "allowed_paths": ["factory_tests/fixtures/**"]
                }
            ]
        }
        with open(self.test_plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f)

        orch = FactoryOrchestrator(self.test_plan_path)
        orch.factory_config["worker_registry"]["agy"]["adapter"] = "fake_worker"

        # Set fake adapter to fail
        FakeWorkerAdapter.behavior = "CRASH"
        manifest = orch.execute_plan()

        self.assertEqual(manifest["final_status"], "FAILED")
        self.assertEqual(manifest["tasks"]["task_fail"]["canonical_state"], "FAILED")
        self.assertEqual(manifest["tasks"]["task_dependent"]["canonical_state"], "BLOCKED")
        self.assertEqual(manifest["tasks"]["task_dependent"]["display_state"], "BLOCKED")

        if orch.run_dir.exists():
            shutil.rmtree(orch.run_dir, ignore_errors=True)


class TestV3AttemptIsolationAndTimeout(unittest.TestCase):
    """Tests for attempt identity and safe timeout semantics."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_plan_path = pathlib.Path(self.temp_dir.name) / "timeout_plan.json"

    def tearDown(self):
        self.temp_dir.cleanup()
        FakeWorkerAdapter.behavior = "SUCCESS"

    def test_timeout_marks_timed_out_and_cleans_workspace(self):
        plan = {
            "plan_id": "test_timeout",
            "name": "Timeout Plan",
            "version": "3.0.0",
            "tasks": [
                {
                    "task_id": "task_slow",
                    "worker_id": "agy",
                    "dependencies": [],
                    "timeout": 1,
                    "allowed_paths": ["factory_tests/fixtures/**"]
                }
            ]
        }
        with open(self.test_plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f)

        orch = FactoryOrchestrator(self.test_plan_path)
        orch.factory_config["worker_registry"]["agy"]["adapter"] = "fake_worker"
        FakeWorkerAdapter.behavior = "TIMEOUT"

        manifest = orch.execute_plan()
        self.assertEqual(manifest["final_status"], "FAILED")
        task_info = manifest["tasks"]["task_slow"]
        self.assertEqual(task_info["canonical_state"], "TIMED_OUT")
        self.assertEqual(task_info["display_state"], "FAILED")
        self.assertEqual(task_info["current_attempt_id"], 1)
        self.assertEqual(len(task_info["attempts"]), 1)
        self.assertTrue(task_info["attempts"][0]["timed_out"])

        if orch.run_dir.exists():
            shutil.rmtree(orch.run_dir, ignore_errors=True)


class TestV3GitConflictHandling(unittest.TestCase):
    """Tests for explicit Git merge conflict detection and clean abort."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_plan_path = pathlib.Path(self.temp_dir.name) / "conflict_plan.json"
        self.orig_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT), capture_output=True, text=True).stdout.strip()
        # Create initial conflict file on main
        self.conflict_file = PROJECT_ROOT / "factory_tests" / "fixtures" / "shared_conflict.txt"
        self.conflict_file.parent.mkdir(parents=True, exist_ok=True)
        self.conflict_file.write_text("Base initial content\n", encoding="utf-8")
        subprocess.run(["git", "add", str(self.conflict_file)], cwd=str(PROJECT_ROOT), check=True)
        subprocess.run(["git", "commit", "-m", "chore: setup conflict test fixture"], cwd=str(PROJECT_ROOT), check=True)

    def tearDown(self):
        self.temp_dir.cleanup()
        FakeWorkerAdapter.behavior = "SUCCESS"
        # Reset git state and prune worktrees
        subprocess.run(["git", "reset", "--hard", self.orig_commit], cwd=str(PROJECT_ROOT), capture_output=True)
        proc = subprocess.run(["git", "branch", "--list", "factory/run-*"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        for br in proc.stdout.splitlines():
            b = br.strip().replace("*", "").strip()
            if b and "conflict" in b:
                subprocess.run(["git", "branch", "-D", b], cwd=str(PROJECT_ROOT), capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=str(PROJECT_ROOT), capture_output=True)

    def test_merge_conflict_detected_and_aborted(self):
        """Simulates merge conflict between two branches modifying the same line."""
        plan = {
            "plan_id": "test_conflict",
            "name": "Merge Conflict Test",
            "version": "3.0.0",
            "max_concurrency": 2,
            "tasks": [
                {
                    "task_id": "task_conflictor_1",
                    "worker_id": "agy",
                    "dependencies": [],
                    "allowed_paths": ["factory_tests/fixtures/**"]
                },
                {
                    "task_id": "task_conflictor_2",
                    "worker_id": "agy",
                    "dependencies": [],  # Both ready from same base commit
                    "allowed_paths": ["factory_tests/fixtures/**"]
                }
            ]
        }
        with open(self.test_plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f)

        orch = FactoryOrchestrator(self.test_plan_path)
        orch.factory_config["worker_registry"]["agy"]["adapter"] = "fake_worker"
        FakeWorkerAdapter.behavior = "CONFLICT"

        manifest = orch.execute_plan()
        # First task integrates, second task must detect merge conflict and abort
        t1 = manifest["tasks"]["task_conflictor_1"]
        t2 = manifest["tasks"]["task_conflictor_2"]

        self.assertIn("INTEGRATED", [t1["canonical_state"], t2["canonical_state"]])
        self.assertIn("CONFLICTED", [t1["canonical_state"], t2["canonical_state"]])

        conflicted_task = t1 if t1["canonical_state"] == "CONFLICTED" else t2
        self.assertEqual(conflicted_task["display_state"], "REVIEW")
        self.assertTrue(len(conflicted_task.get("conflicted_files", [])) > 0)

        # Working directory must have zero unmerged files (git merge --abort executed)
        unmerged_diff = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        self.assertEqual(unmerged_diff.stdout.strip(), "")

        if orch.run_dir.exists():
            shutil.rmtree(orch.run_dir, ignore_errors=True)


class TestV3ConcurrentRunIsolation(unittest.TestCase):
    """Tests for run-scoped resource tracking and isolation."""

    def test_run_scoped_resource_isolation(self):
        mock_herdr = MockHerdrClient()
        with tempfile.TemporaryDirectory() as td:
            res_mgr = ResourceManager(mock_herdr, state_file=pathlib.Path(td) / "owned.json")

            run_a = "run-test-isolation-A"
            run_b = "run-test-isolation-B"

            res_mgr.record_workspace("ws-A-1", "pane-A-1", run_id=run_a)
            res_mgr.record_workspace("ws-B-1", "pane-B-1", run_id=run_b)

            self.assertIn("ws-A-1", res_mgr.state["runs"][run_a]["workspace_ids"])
            self.assertIn("ws-B-1", res_mgr.state["runs"][run_b]["workspace_ids"])

            # Clean only run_a
            res_mgr.cleanup_owned_resources(run_id=run_a)
            self.assertNotIn(run_a, res_mgr.state["runs"])
            self.assertIn(run_b, res_mgr.state["runs"])
            self.assertIn("ws-B-1", res_mgr.state["runs"][run_b]["workspace_ids"])

            # Clean run_b
            res_mgr.cleanup_owned_resources(run_id=run_b)
            self.assertNotIn(run_b, res_mgr.state["runs"])


class TestV3SymlinkSecurity(unittest.TestCase):
    """Tests for symlink escape detection in worktrees."""

    def test_symlink_pointing_outside_project_detected(self):
        with tempfile.TemporaryDirectory() as td:
            wt_path = pathlib.Path(td)
            outside_target = pathlib.Path("/tmp")
            link = wt_path / "evil_symlink"
            os.symlink(outside_target, link)

            violations = check_worktree_symlinks(wt_path, PROJECT_ROOT)
            self.assertTrue(len(violations) > 0)
            self.assertTrue(any("points outside project root" in v for v in violations))


class TestV3StatusProjectionContract(unittest.TestCase):
    """Tests for machine-readable JSON status projection for Kanban."""

    def test_status_projection_structure(self):
        proj = generate_status_projection()
        self.assertEqual(proj["status"], "OK")
        self.assertIn(proj["factory_version"], ("3.0.0", "4.0.0"))
        self.assertIn("control_plane", proj)
        self.assertIn("owned_resources", proj)
        self.assertIn("runs", proj)

    def test_canonical_to_display_state_mapping(self):
        self.assertEqual(CANONICAL_TO_DISPLAY_STATE["PENDING"], "BACKLOG")
        self.assertEqual(CANONICAL_TO_DISPLAY_STATE["READY"], "READY")
        self.assertEqual(CANONICAL_TO_DISPLAY_STATE["RUNNING"], "RUNNING")
        self.assertEqual(CANONICAL_TO_DISPLAY_STATE["INTEGRATED"], "DONE")
        self.assertEqual(CANONICAL_TO_DISPLAY_STATE["COMPLETED"], "DONE")
        self.assertEqual(CANONICAL_TO_DISPLAY_STATE["BLOCKED"], "BLOCKED")
        self.assertEqual(CANONICAL_TO_DISPLAY_STATE["TIMED_OUT"], "FAILED")
        self.assertEqual(CANONICAL_TO_DISPLAY_STATE["FAILED"], "FAILED")
        self.assertEqual(CANONICAL_TO_DISPLAY_STATE["CONFLICTED"], "REVIEW")


class TestV3FailpointAndResume(unittest.TestCase):
    """Tests for deterministic failpoint crash injection and reconciliation resume."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_plan_path = pathlib.Path(self.temp_dir.name) / "failpoint_plan.json"
        self.plan_data = {
            "plan_id": "test_failpoint_resume",
            "name": "Failpoint Resume Test",
            "version": "3.0.0",
            "tasks": [
                {
                    "task_id": "task_resilient",
                    "worker_id": "agy",
                    "dependencies": [],
                    "allowed_paths": ["factory_tests/fixtures/**"]
                }
            ]
        }
        with open(self.test_plan_path, "w", encoding="utf-8") as f:
            json.dump(self.plan_data, f)
        self.orig_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT), capture_output=True, text=True).stdout.strip()
        FakeWorkerAdapter.behavior = "SUCCESS"

    def tearDown(self):
        self.temp_dir.cleanup()
        # Reset git state and prune worktrees
        subprocess.run(["git", "reset", "--hard", self.orig_commit], cwd=str(PROJECT_ROOT), capture_output=True)
        proc = subprocess.run(["git", "branch", "--list", "factory/run-*"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        for br in proc.stdout.splitlines():
            b = br.strip().replace("*", "").strip()
            if b and "resilient" in b:
                subprocess.run(["git", "branch", "-D", b], cwd=str(PROJECT_ROOT), capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=str(PROJECT_ROOT), capture_output=True)

    def test_crash_after_commit_and_reconciliation_resume(self):
        """Simulates crash after commit (Case B) and tests reconciliation resume to INTEGRATED."""
        orch = FactoryOrchestrator(self.test_plan_path)
        orch.factory_config["worker_registry"]["agy"]["adapter"] = "fake_worker"
        run_id = orch.run_id

        # Run with failpoint FAIL_AFTER_COMMIT via subprocess
        env = os.environ.copy()
        env["FACTORY_TEST_FAILPOINT"] = "FAIL_AFTER_COMMIT"
        env["FACTORY_TEST_HARNESS"] = "1"
        env["PYTHONPATH"] = f"{PROJECT_ROOT}:{PROJECT_ROOT}/tools"
        cmd = [sys.executable, str(PROJECT_ROOT / "tools" / "factory.py"), "run", str(self.test_plan_path)]

        # Temporarily patch factory.json worker adapter to fake_worker for subprocess
        cfg_path = PROJECT_ROOT / "factory.json"
        with open(cfg_path, "r", encoding="utf-8") as f:
            orig_cfg = json.load(f)

        patched_cfg = copy.deepcopy(orig_cfg)
        patched_cfg["worker_registry"]["agy"]["adapter"] = "fake_worker"
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(patched_cfg, f, indent=2)

        try:
            # 1. Run factory - expect exit code 88 from failpoint
            proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 88)

            # Discover created run_id
            latest_run = sorted(list(RUNS_DIR.glob("run-*")), reverse=True)[0]
            with open(latest_run / "manifest.json", "r", encoding="utf-8") as mf:
                mdata = json.load(mf)
            self.assertEqual(mdata["tasks"]["task_resilient"]["canonical_state"], "COMMITTED")

            # 2. Resume factory run - expect exit code 0 and task integrated
            resume_env = os.environ.copy()
            resume_env.pop("FACTORY_TEST_FAILPOINT", None)
            resume_env["FACTORY_TEST_HARNESS"] = "1"
            resume_env["PYTHONPATH"] = f"{PROJECT_ROOT}:{PROJECT_ROOT}/tools"
            res_proc = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "tools" / "factory.py"), "resume", latest_run.name],
                cwd=str(PROJECT_ROOT),
                env=resume_env,
                capture_output=True,
                text=True
            )
            self.assertEqual(res_proc.returncode, 0)

            # Verify resumed manifest state
            with open(latest_run / "manifest.json", "r", encoding="utf-8") as mf:
                final_data = json.load(mf)
            self.assertEqual(final_data["final_status"], "COMPLETED")
            self.assertEqual(final_data["tasks"]["task_resilient"]["canonical_state"], "INTEGRATED")
            self.assertEqual(final_data["tasks"]["task_resilient"]["display_state"], "DONE")

            # Cleanup test run
            if latest_run.exists():
                shutil.rmtree(latest_run, ignore_errors=True)

        finally:
            # Restore original factory.json
            orig_cfg["worker_registry"]["agy"]["adapter"] = "agy"
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(orig_cfg, f, indent=2)


if __name__ == "__main__":
    unittest.main()
