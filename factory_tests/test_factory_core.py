"""Deterministic unit tests for the Herdr Orchestrator Core Engine.

Validates:
1. Plan schema and semantic validation (validate_plan_file).
2. Cycle detection and dependency graph validation.
3. Path allowlist matching and project escape protection.
4. Foreign resource protection and exact-ID ownership enforcement.
5. Cleanup idempotency and state safety.
"""

import copy
import json
import os
import pathlib
import sys
import tempfile
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from factory import (
    validate_plan_file,
    match_path_allowlist,
    ResourceManager,
    STATE_DIR,
)


class TestPlanValidation(unittest.TestCase):
    """Tests for validate_plan_file and semantic plan checks."""

    def setUp(self):
        self.valid_plan = {
            "plan_id": "test_app",
            "name": "Test Application Plan",
            "version": "2.0.0",
            "target_application": {
                "name": "TestApp",
                "description": "Test app",
                "root_directory": "examples/testapp"
            },
            "tasks": [
                {
                    "task_id": "task_spec",
                    "worker_id": "agy2",
                    "description": "Write spec",
                    "allowed_paths": ["examples/testapp/SPEC.md"],
                    "expected_files": ["examples/testapp/SPEC.md"],
                    "dependencies": []
                },
                {
                    "task_id": "task_backend",
                    "worker_id": "agy3",
                    "dependencies": ["task_spec"],
                    "description": "Write backend",
                    "allowed_paths": ["examples/testapp/app/**"],
                    "expected_files": ["examples/testapp/app/main.py"]
                },
                {
                    "task_id": "task_frontend",
                    "worker_id": "agy4",
                    "dependencies": ["task_spec"],
                    "description": "Write frontend",
                    "allowed_paths": ["examples/testapp/web/**"],
                    "expected_files": ["examples/testapp/web/index.html"]
                }
            ]
        }

    def _validate_data(self, data):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            temp_path = pathlib.Path(f.name)
        try:
            return validate_plan_file(temp_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_valid_plan_passes(self):
        errors = self._validate_data(self.valid_plan)
        self.assertEqual(errors, [])

    def test_missing_required_top_level_fields(self):
        data = copy.deepcopy(self.valid_plan)
        del data["plan_id"]
        del data["tasks"]
        errors = self._validate_data(data)
        self.assertTrue(any("Missing required top-level field: 'plan_id'" in e for e in errors))
        self.assertTrue(any("Missing required top-level field: 'tasks'" in e for e in errors))

    def test_empty_tasks_rejected(self):
        data = copy.deepcopy(self.valid_plan)
        data["tasks"] = []
        errors = self._validate_data(data)
        self.assertIn("Plan must contain at least one task", errors)

    def test_duplicate_task_ids_rejected(self):
        data = copy.deepcopy(self.valid_plan)
        data["tasks"][2]["task_id"] = "task_backend"
        errors = self._validate_data(data)
        self.assertTrue(any("Duplicate task_id detected: 'task_backend'" in e for e in errors))

    def test_unknown_worker_rejected(self):
        data = copy.deepcopy(self.valid_plan)
        data["tasks"][0]["worker_id"] = "unknown_worker_99"
        errors = self._validate_data(data)
        self.assertTrue(any("specifies unknown worker: 'unknown_worker_99'" in e for e in errors))

    def test_missing_dependency_rejected(self):
        data = copy.deepcopy(self.valid_plan)
        data["tasks"][1]["dependencies"] = ["non_existent_task"]
        errors = self._validate_data(data)
        self.assertTrue(any("references nonexistent dependency 'non_existent_task'" in e for e in errors))

    def test_dependency_cycle_rejected(self):
        data = copy.deepcopy(self.valid_plan)
        # Create cycle: task_spec -> task_backend -> task_spec
        data["tasks"][0]["dependencies"] = ["task_backend"]
        errors = self._validate_data(data)
        self.assertTrue(any("Dependency cycle detected" in e for e in errors))

    def test_unsafe_path_escape_rejected(self):
        data = copy.deepcopy(self.valid_plan)
        data["tasks"][0]["allowed_paths"] = ["../../etc/passwd"]
        errors = self._validate_data(data)
        self.assertTrue(any("specifies unsafe path escaping project root" in e for e in errors))

    def test_absolute_path_escape_rejected(self):
        data = copy.deepcopy(self.valid_plan)
        data["tasks"][0]["allowed_paths"] = ["/var/run/herdr.sock"]
        errors = self._validate_data(data)
        self.assertTrue(any("specifies unsafe path escaping project root" in e for e in errors))


class TestPathAllowlist(unittest.TestCase):
    """Tests for match_path_allowlist isolation enforcement."""

    def test_exact_path_match(self):
        self.assertTrue(match_path_allowlist("docs/SPECIFICATION.md", ["docs/SPECIFICATION.md"]))
        self.assertFalse(match_path_allowlist("docs/OTHER.md", ["docs/SPECIFICATION.md"]))

    def test_directory_glob_boundary(self):
        # app/** should match files in app/ and subdirs, but NOT apple.py or app_test.py
        allowlist = ["app/**"]
        self.assertTrue(match_path_allowlist("app/server.py", allowlist))
        self.assertTrue(match_path_allowlist("app/sub/nested.py", allowlist))
        self.assertFalse(match_path_allowlist("apple.py", allowlist))
        self.assertFalse(match_path_allowlist("app_extra.py", allowlist))
        self.assertFalse(match_path_allowlist("other/app/server.py", allowlist))

    def test_prefix_boundary_without_glob(self):
        allowlist = ["examples/minilinks/"]
        self.assertTrue(match_path_allowlist("examples/minilinks/SPEC.md", allowlist))
        self.assertFalse(match_path_allowlist("examples/minilinks_fake/test.py", allowlist))

    def test_multi_pattern_matching(self):
        allowlist = ["tests/**", "scripts/**", "package.json"]
        self.assertTrue(match_path_allowlist("tests/test_api.py", allowlist))
        self.assertTrue(match_path_allowlist("scripts/smoke_test.py", allowlist))
        self.assertTrue(match_path_allowlist("package.json", allowlist))
        self.assertFalse(match_path_allowlist("src/index.js", allowlist))


class MockHerdrClient:
    """Mock Herdr client for testing foreign resource isolation."""
    def __init__(self):
        self.deleted_workspaces = []
        self.existing_workspaces = ["wT", "wQ", "wE", "wP", "w8", "wA", "wS", "wK", "wN", "wC", "wD"]

    def close_workspace(self, ws_id):
        self.deleted_workspaces.append(ws_id)
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



class TestResourceManagerSafety(unittest.TestCase):
    """Tests for ownership registry and strict foreign resource protection."""

    def setUp(self):
        self.temp_state_dir = tempfile.TemporaryDirectory()
        self.temp_state_file = pathlib.Path(self.temp_state_dir.name) / "ownership.json"
        self.mock_herdr = MockHerdrClient()

        # Patch state file path for testing
        self.res_mgr = ResourceManager(self.mock_herdr, state_file=self.temp_state_file)
        self.res_mgr.state = {
            "control_plane": {"workspace_id": "wK", "pane_id": "wK:p1"},
            "owned": {
                "workspace_ids": [],
                "pane_ids": [],
                "branches": [],
                "worktrees": []
            }
        }
        self.res_mgr.save()

    def tearDown(self):
        self.temp_state_dir.cleanup()

    def test_register_and_verify_ownership(self):
        self.res_mgr.record_workspace("w_owned_123", "p_owned_123")
        self.assertTrue(self.res_mgr.is_owned_workspace("w_owned_123"))
        self.assertFalse(self.res_mgr.is_owned_workspace("wT"))
        self.assertFalse(self.res_mgr.is_owned_workspace("wK"))

    def test_foreign_workspace_mutation_strictly_forbidden(self):
        # Existing pre-existing Herdr workspaces MUST NOT be touched
        for foreign_ws in ["wT", "wQ", "wK", "w8", "wA"]:
            with self.assertRaises(PermissionError):
                self.res_mgr.clean_workspace(foreign_ws)
        self.assertEqual(self.mock_herdr.deleted_workspaces, [])

    def test_owned_workspace_cleanup_allowed(self):
        self.res_mgr.record_workspace("w_owned_456", "p_owned_456")
        self.res_mgr.clean_workspace("w_owned_456")
        self.assertIn("w_owned_456", self.mock_herdr.deleted_workspaces)
        self.assertNotIn("w_owned_456", self.res_mgr.state["owned"]["workspace_ids"])

    def test_clean_owned_resources_idempotent(self):
        self.res_mgr.record_workspace("w_owned_789", "p_owned_789")
        # First cleanup
        cleaned1 = self.res_mgr.cleanup_owned_resources()
        self.assertIn("w_owned_789", cleaned1["workspaces_closed"])
        self.assertEqual(self.res_mgr.state["owned"]["workspace_ids"], [])

        # Second cleanup (idempotent, nothing to clean)
        cleaned2 = self.res_mgr.cleanup_owned_resources()
        self.assertEqual(cleaned2["workspaces_closed"], [])
        self.assertEqual(len(self.mock_herdr.deleted_workspaces), 1)


class TestMutationSafety(unittest.TestCase):
    """Direct tests for check_mutation_safety invariant."""

    def test_invariant_enforced(self):
        from factory import check_mutation_safety
        owned = ["w1", "w2", "p1"]
        self.assertTrue(check_mutation_safety("w1", owned))
        self.assertTrue(check_mutation_safety("p1", owned))
        self.assertFalse(check_mutation_safety("wT", owned))
        self.assertFalse(check_mutation_safety("", owned))
        self.assertFalse(check_mutation_safety(None, owned))


class TestPathSafety(unittest.TestCase):
    """Direct tests for is_path_safe_under_root."""

    def test_safe_paths(self):
        from factory import is_path_safe_under_root
        self.assertTrue(is_path_safe_under_root("examples/minilinks/SPEC.md", PROJECT_ROOT))
        self.assertTrue(is_path_safe_under_root("app/server.py", PROJECT_ROOT))
        self.assertTrue(is_path_safe_under_root("README.md", PROJECT_ROOT))

    def test_unsafe_escape_paths(self):
        from factory import is_path_safe_under_root
        self.assertFalse(is_path_safe_under_root("../../../etc/shadow", PROJECT_ROOT))
        self.assertFalse(is_path_safe_under_root("/root/.config/herdr/herdr.sock", PROJECT_ROOT))
        self.assertFalse(is_path_safe_under_root("/tmp/evil", PROJECT_ROOT))


class TestValidationCommandExecution(unittest.TestCase):
    """Tests for FactoryOrchestrator.run_validation_commands."""

    def setUp(self):
        self.temp_plan = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        plan_content = {
            "plan_id": "test_val",
            "name": "Val Test",
            "version": "1.0",
            "target_application": {"name": "Val", "description": "Val", "root_directory": "."},
            "tasks": [
                {
                    "task_id": "validation_fixture",
                    "worker_id": "agy2",
                    "description": "Validation helper fixture",
                    "dependencies": []
                }
            ]
        }
        json.dump(plan_content, self.temp_plan)
        self.temp_plan.close()
        from factory import FactoryOrchestrator
        self.orch = FactoryOrchestrator(pathlib.Path(self.temp_plan.name))

    def tearDown(self):
        pathlib.Path(self.temp_plan.name).unlink(missing_ok=True)
        # Clean run directory if created
        if self.orch.run_dir.exists():
            import shutil
            shutil.rmtree(self.orch.run_dir, ignore_errors=True)

    def test_passing_command(self):
        cmds = [{"name": "echo_test", "command": ["python3", "-c", "print('hello from val')"]}]
        results = self.orch.run_validation_commands(cmds)
        self.assertIn("echo_test", results)
        self.assertTrue(results["echo_test"]["passed"])
        self.assertEqual(results["echo_test"]["returncode"], 0)
        self.assertIn("hello from val", results["echo_test"]["stdout"])

    def test_failing_command(self):
        cmds = [{"name": "fail_test", "command": ["python3", "-c", "import sys; sys.exit(42)"]}]
        results = self.orch.run_validation_commands(cmds)
        self.assertIn("fail_test", results)
        self.assertFalse(results["fail_test"]["passed"])
        self.assertEqual(results["fail_test"]["returncode"], 42)



if __name__ == "__main__":
    unittest.main()


