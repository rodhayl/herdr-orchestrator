"""Provider-free regressions for Factory v9 fail-closed recovery and real-only invariants."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

FACTORY_PATH = pathlib.Path(__file__).resolve().parents[1] / "tools" / "factory.py"
if FACTORY_PATH.exists():
    from tools.factory import (
        GoalController,
        FactoryOrchestrator,
        ProjectContext,
        ProjectPolicy,
        RealProviderRequiredError,
        audit_project,
        compile_goal_spec,
        compile_plan_from_goal,
        review_plan,
        set_project_context,
        _CURRENT_CONTEXT,
    )


@unittest.skipUnless(FACTORY_PATH.exists(), "requires full repository checkout")
class CoreHardeningTests(unittest.TestCase):
    def setUp(self):
        self.orig_ctx = _CURRENT_CONTEXT
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "factory-tests@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Factory Tests"], cwd=self.root, check=True)
        (self.root / "README.md").write_text("# target\n", encoding="utf-8")
        ProjectPolicy.init_starter(self.root, "core-hardening")
        policy_path = self.root / "factory.project.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["execution_policy"]["mode"] = "mock_allowed"
        policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md", "factory.project.json"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "test fixture"], cwd=self.root, check=True)
        self.old_harness = os.environ.get("FACTORY_TEST_HARNESS")
        os.environ["FACTORY_TEST_HARNESS"] = "1"

    def tearDown(self):
        set_project_context(self.orig_ctx)
        if self.old_harness is None:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
        else:
            os.environ["FACTORY_TEST_HARNESS"] = self.old_harness
        self.temp.cleanup()

    def test_missing_goal_id_fails_closed(self):
        with self.assertRaises(FileNotFoundError):
            GoalController(goal_id="goal-does-not-exist", project_root=self.root)

    def test_real_only_is_persisted_and_monotonic_across_resume(self):
        ctrl = GoalController(project_root=self.root, goal_text="Implement a small feature", real_only=True, plan_only=True)
        self.assertTrue(ctrl.state["real_only"])
        resumed = GoalController(goal_id=ctrl.goal_id, project_root=self.root)
        self.assertTrue(resumed.real_only)
        self.assertTrue(resumed.state["real_only"])

    def test_fresh_goal_execution_does_not_enter_resume_reconciliation(self):
        ctrl = GoalController(project_root=self.root, goal_text="Implement a small feature")
        goal_spec_path = ctrl.goal_dir / "goal-spec.json"
        plan_path = ctrl.goal_dir / "plan-approved.json"
        goal_spec_path.write_text(json.dumps({
            "goal_id": ctrl.goal_id,
            "title": "Feature",
            "raw_goal": "Feature",
            "acceptance_criteria": [{"id": "R1", "title": "Feature", "description": "works", "provenance": "USER_EXPLICIT"}],
        }), encoding="utf-8")
        plan_path.write_text(json.dumps({
            "plan_id": "plan-test", "version": "2.0.0", "name": "test",
            "tasks": [{"task_id": "task-1", "satisfies": ["R1"], "validations": [["python3", "-c", "import sys; sys.exit(0)"]], "allowed_paths": ["**"], "dependencies": []}],
        }), encoding="utf-8")
        ctrl.state.update({
            "phase": "READY",
            "goal_spec_path": str(goal_spec_path),
            "current_plan_path": str(plan_path),
            "approved_plan_path": str(plan_path),
            "run_id": None,
        })
        ctrl.save_state()

        resume_modes = []

        class FakeOrchestrator:
            def __init__(self, *args, run_id=None, **kwargs):
                self.run_id = run_id or "run-fresh"

            def execute_plan(self, resume_mode=False):
                resume_modes.append(resume_mode)
                return {"final_status": "COMPLETED"}

        with mock.patch("tools.factory.FactoryOrchestrator", FakeOrchestrator), \
             mock.patch.object(GoalController, "execute_post_validations", return_value=True), \
             mock.patch("tools.factory.audit_project", return_value={"verdict": "ACCEPTED", "findings": []}):
            state = ctrl.run()

        self.assertEqual(resume_modes, [False])
        self.assertEqual(state["phase"], "COMPLETE")

    def test_run_manifest_persists_real_only_and_current_engine_version(self):
        set_project_context(ProjectContext(self.root))
        plan_path = self.root / "plan-run.json"
        plan_path.write_text(json.dumps({
            "plan_id": "plan-run", "version": "2.0.0", "name": "run",
            "tasks": [],
        }), encoding="utf-8")

        fake_herdr = mock.Mock(control_plane={"type": "test"})
        fake_resource_manager = mock.Mock()
        fake_board = mock.Mock()
        fake_context_compiler = mock.Mock()
        with mock.patch("tools.factory.HerdrClient", return_value=fake_herdr), \
             mock.patch("tools.factory.ResourceManager", return_value=fake_resource_manager), \
             mock.patch("tools.factory.HerdrBoardProjector", return_value=fake_board), \
             mock.patch("tools.factory.ContextCompiler", return_value=fake_context_compiler), \
             mock.patch("tools.factory.ReasoningPolicy.load", side_effect=RuntimeError("not needed")):
            first = FactoryOrchestrator(plan_path, real_only=True)
            self.assertEqual(first.manifest["factory_version"], "9.0.0")
            self.assertTrue(first.manifest["real_only"])
            resumed = FactoryOrchestrator(plan_path, run_id=first.run_id, real_only=False)
            self.assertTrue(resumed.real_only)
            self.assertTrue(resumed.manifest["real_only"])

    def test_clean_git_ignores_runtime_root_only_not_substring_matches(self):
        runtime_file = self.root / ".agy-factory" / "tmp" / "runtime.txt"
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_text("runtime\n", encoding="utf-8")
        ProjectContext(self.root).ensure_clean_git()

        suspicious = self.root / "src" / "foo.agy-factory.py"
        suspicious.parent.mkdir()
        suspicious.write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            ProjectContext(self.root).ensure_clean_git()

    def test_post_validation_string_uses_shell_quoting_rules_without_shell(self):
        ctrl = GoalController(project_root=self.root, goal_text="Quoted validation")
        plan_path = ctrl.goal_dir / "plan-approved.json"
        plan_path.write_text(json.dumps({
            "plan_id": "plan-quoted", "version": "2.0.0", "name": "quoted",
            "tasks": [{
                "task_id": "task-quoted",
                "validations": ['python3 -c "import sys; sys.exit(0)"'],
                "satisfies": ["R1"], "allowed_paths": ["**"], "dependencies": [],
            }],
        }), encoding="utf-8")
        ctrl.state["approved_plan_path"] = str(plan_path)
        ctrl.save_state()
        self.assertTrue(ctrl.execute_post_validations())
        self.assertEqual(ctrl.state["validation_results"][0]["command"], ["python3", "-c", "import sys; sys.exit(0)"])

    def test_live_real_only_semantic_roles_fail_closed_on_provider_failure(self):
        # Build deterministic fixtures while the explicit test harness is enabled.
        policy = ProjectPolicy.load(self.root / "factory.project.json")
        goal_spec = compile_goal_spec("- Feature must work", self.root, policy, goal_id="goal-real", real_only=False)
        plan = compile_plan_from_goal(goal_spec, policy, plan_id="plan-real", real_only=False)

        real_run = subprocess.run

        def fail_provider(cmd, *args, **kwargs):
            if cmd and cmd[0] == "agy":
                return subprocess.CompletedProcess(cmd, 1, "", "simulated provider failure")
            return real_run(cmd, *args, **kwargs)

        fake_packet = SimpleNamespace(rendered_tail="safe test packet")
        with mock.patch.dict(os.environ, {
            "FACTORY_TEST_HARNESS": "0",
            "PLAN_REVIEW_TEST_VERDICT": "APPROVED",
            "AUDIT_TEST_VERDICT": "ACCEPTED",
        }, clear=False), \
             mock.patch("tools.factory.subprocess.run", side_effect=fail_provider), \
             mock.patch("tools.factory.ContextPolicy.load", return_value=mock.Mock()), \
             mock.patch("tools.factory.ContextCompiler.compile_plan_review_packet", return_value=fake_packet), \
             mock.patch("tools.factory.ContextCompiler.compile_audit_packet", return_value=fake_packet), \
             mock.patch("tools.factory.StablePrefixManager.get_stable_prefix", return_value=("prefix", "hash", 6)):
            with self.assertRaises(RealProviderRequiredError):
                compile_goal_spec("- Feature must work", self.root, policy, goal_id="goal-live", real_only=True)
            with self.assertRaises(RealProviderRequiredError):
                compile_plan_from_goal(goal_spec, policy, plan_id="plan-live", real_only=True)
            with self.assertRaises(RealProviderRequiredError):
                review_plan(plan, goal_spec, policy, real_only=True)
            with self.assertRaises(RealProviderRequiredError):
                audit_project(self.root, goal_spec, policy, real_only=True)


if __name__ == "__main__":
    unittest.main()
