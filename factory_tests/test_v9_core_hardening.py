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
        _is_final_audit_approved,
        _is_valid_final_audit_result,
        ReasoningPolicyConflictError,
        resolve_task_worker,
        TaskExecutor,
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

    def test_project_policy_positive_limits_fail_closed_and_concurrency_propagates(self):
        policy_path = self.root / "factory.project.json"
        data = json.loads(policy_path.read_text(encoding="utf-8"))
        data["limits"]["max_concurrency"] = 1
        data["limits"]["max_task_attempts"] = 1
        data["limits"]["max_task_duration_seconds"] = 30
        policy_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        policy = ProjectPolicy.load(policy_path)
        self.assertEqual(policy.validate(), [])

        goal_spec = compile_goal_spec("- Feature must work", self.root, policy, goal_id="goal-limits", real_only=False)
        plan = compile_plan_from_goal(goal_spec, policy, plan_id="plan-limits", real_only=False)
        self.assertEqual(plan["max_concurrency"], 1)
        self.assertTrue(plan["tasks"])
        self.assertTrue(all(task["timeout"] == 30 for task in plan["tasks"]))

        invalid_cases = {
            "max_concurrency": 0,
            "max_task_attempts": 0,
            "max_task_duration_seconds": 9,
        }
        for field, invalid_value in invalid_cases.items():
            invalid_data = json.loads(json.dumps(data))
            invalid_data["limits"][field] = invalid_value
            policy_path.write_text(json.dumps(invalid_data, indent=2) + "\n", encoding="utf-8")
            invalid = ProjectPolicy.load(policy_path)
            self.assertTrue(any(field in err for err in invalid.validate()), field)

        policy_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

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
        fake_context_compiler = mock.Mock()
        with mock.patch("tools.factory.HerdrClient", return_value=fake_herdr), \
             mock.patch("tools.factory.ResourceManager", return_value=fake_resource_manager), \
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

    def test_plan_review_passes_structured_schema_to_provider(self):
        policy = ProjectPolicy.load(self.root / "factory.project.json")
        goal_spec = compile_goal_spec("- Feature must work", self.root, policy, goal_id="goal-review-schema", real_only=False)
        plan = compile_plan_from_goal(goal_spec, policy, plan_id="plan-review-schema", real_only=False)
        captured = {}

        def provider(cmd, *args, **kwargs):
            captured["cmd"] = list(cmd)
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps({"verdict": "APPROVED", "revision_index": 0, "findings": []}),
                "",
            )

        fake_packet = SimpleNamespace(rendered_tail="review packet")
        with mock.patch.dict(os.environ, {"FACTORY_TEST_HARNESS": "0"}, clear=False), \
             mock.patch("tools.factory.subprocess.run", side_effect=provider), \
             mock.patch("tools.factory.ContextPolicy.load", return_value=mock.Mock()), \
             mock.patch("tools.factory.ContextCompiler.compile_plan_review_packet", return_value=fake_packet), \
             mock.patch("tools.factory.StablePrefixManager.get_stable_prefix", return_value=("prefix", "hash", 6)):
            result = review_plan(plan, goal_spec, policy, real_only=True)

        self.assertEqual(result["verdict"], "APPROVED")
        self.assertIn("--json-schema", captured["cmd"])
        schema_arg = captured["cmd"][captured["cmd"].index("--json-schema") + 1]
        self.assertIn('"title": "PlanReviewResult"', schema_arg)
        self.assertIn('"REVISE"', schema_arg)
        self.assertIn('"traceability"', schema_arg)
        self.assertIn('"security"', schema_arg)
        self.assertNotIn('"CHANGES_REQUESTED"', schema_arg)

    def test_final_audit_passes_structured_schema_to_provider(self):
        policy = ProjectPolicy.load(self.root / "factory.project.json")
        goal_spec = compile_goal_spec("- Feature must work", self.root, policy, goal_id="goal-audit-schema", real_only=False)
        captured = {}

        def provider(cmd, *args, **kwargs):
            if cmd and cmd[0] == "git":
                return subprocess.CompletedProcess(cmd, 1, "", "")
            captured["cmd"] = list(cmd)
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps({"verdict": "ACCEPTED", "findings": []}),
                "",
            )

        fake_packet = SimpleNamespace(rendered_tail="audit packet")
        with mock.patch.dict(os.environ, {"FACTORY_TEST_HARNESS": "0"}, clear=False), \
             mock.patch("tools.factory.subprocess.run", side_effect=provider), \
             mock.patch("tools.factory.ContextPolicy.load", return_value=mock.Mock()), \
             mock.patch("tools.factory.ContextCompiler.compile_audit_packet", return_value=fake_packet), \
             mock.patch("tools.factory.StablePrefixManager.get_stable_prefix", return_value=("prefix", "hash", 6)):
            result = audit_project(self.root, goal_spec, policy, real_only=True)

        self.assertEqual(result["verdict"], "ACCEPTED")
        self.assertIn("--json-schema", captured["cmd"])
        schema_arg = captured["cmd"][captured["cmd"].index("--json-schema") + 1]
        self.assertIn('"title": "FinalAuditResult"', schema_arg)
        self.assertIn('"REMEDIATION_REQUIRED"', schema_arg)
        self.assertNotIn('"CHANGES_REQUESTED"', schema_arg)

    def test_real_plan_review_and_audit_reject_malformed_structured_verdicts(self):
        policy = ProjectPolicy.load(self.root / "factory.project.json")
        goal_spec = compile_goal_spec("- Feature must work", self.root, policy, goal_id="goal-structured", real_only=False)
        plan = compile_plan_from_goal(goal_spec, policy, plan_id="plan-structured", real_only=False)
        fake_packet = SimpleNamespace(rendered_tail="structured packet")

        def invalid_provider(cmd, *args, **kwargs):
            if "audit" in " ".join(str(x) for x in cmd).lower():
                payload = {"verdict": "MAYBE", "findings": []}
            else:
                payload = {"verdict": "APPROVED", "findings": [{"severity": "MAJOR"}]}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

        common = [
            mock.patch.dict(os.environ, {"FACTORY_TEST_HARNESS": "0"}, clear=False),
            mock.patch("tools.factory.subprocess.run", side_effect=invalid_provider),
            mock.patch("tools.factory.ContextPolicy.load", return_value=mock.Mock()),
            mock.patch("tools.factory.ContextCompiler.compile_plan_review_packet", return_value=fake_packet),
            mock.patch("tools.factory.ContextCompiler.compile_audit_packet", return_value=fake_packet),
            mock.patch("tools.factory.StablePrefixManager.get_stable_prefix", return_value=("prefix", "hash", 6)),
        ]
        with common[0], common[1], common[2], common[3], common[4], common[5]:
            with self.assertRaises(RealProviderRequiredError):
                review_plan(plan, goal_spec, policy, real_only=True)
            with self.assertRaises(RealProviderRequiredError):
                audit_project(self.root, goal_spec, policy, real_only=True)

    def test_final_audit_contract_and_approval_gate(self):
        accepted = {"verdict": "ACCEPTED", "findings": []}
        accepted_minor = {
            "verdict": "ACCEPTED",
            "findings": [{
                "severity": "MINOR",
                "area": "tests",
                "evidence": "Minor coverage gap",
                "recommendation": "Add one regression",
            }],
        }
        accepted_blocking = {
            "verdict": "ACCEPTED",
            "findings": [{
                "severity": "MAJOR",
                "area": "implementation",
                "evidence": "Blocking defect",
                "recommendation": "Fix before release",
            }],
        }
        remediation = {
            "verdict": "REMEDIATION_REQUIRED",
            "findings": [{
                "severity": "MAJOR",
                "area": "implementation",
                "evidence": "Needs remediation",
                "recommendation": "Repair implementation",
            }],
        }

        self.assertTrue(_is_valid_final_audit_result(accepted))
        self.assertTrue(_is_final_audit_approved(accepted))
        self.assertTrue(_is_final_audit_approved(accepted_minor))
        self.assertTrue(_is_valid_final_audit_result(remediation))
        self.assertFalse(_is_final_audit_approved(remediation))
        self.assertFalse(_is_final_audit_approved(accepted_blocking))

        malformed = [
            {"status": "APPROVED", "findings": []},
            {"verdict": "MAYBE", "findings": []},
            {"verdict": "ACCEPTED", "findings": "not-a-list"},
            {"verdict": "ACCEPTED", "findings": [], "extra": True},
            {"verdict": "ACCEPTED", "findings": [{"severity": "MAJOR"}]},
        ]
        for value in malformed:
            self.assertFalse(_is_valid_final_audit_result(value), value)

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

    def test_task_explicit_effort_cannot_exceed_project_max_effort(self):
        policy_path = self.root / "factory.project.json"
        policy_data = json.loads(policy_path.read_text(encoding="utf-8"))
        policy_data["execution_policy"]["max_effort"] = "low"
        policy = ProjectPolicy(policy_data, self.root)

        factory_cfg = {
            "worker_registry": {
                "test-agy": {
                    "adapter": "agy",
                    "default_model": "gemini-3.8-flash",
                }
            }
        }
        # Explicit worker with effort exceeding policy
        task_def_explicit = {
            "task_id": "t1",
            "worker_id": "test-agy",
            "effort": "high",
        }
        with self.assertRaises(ReasoningPolicyConflictError):
            resolve_task_worker("t1", task_def_explicit, factory_cfg, project_policy=policy)

        # Profile routing with effort exceeding policy
        task_def_profile = {
            "task_id": "t2",
            "requires": ["spec_generation"],
            "effort": "high",
        }
        with self.assertRaises(ReasoningPolicyConflictError):
            resolve_task_worker("t2", task_def_profile, factory_cfg, project_policy=policy)

    def test_task_timeout_capped_by_project_policy_max_duration(self):
        policy_path = self.root / "factory.project.json"
        policy_data = json.loads(policy_path.read_text(encoding="utf-8"))
        policy_data["limits"]["max_task_duration_seconds"] = 120
        policy = ProjectPolicy(policy_data, self.root)

        plan_task = {
            "task_id": "task-long",
            "worker_id": "test-w",
            "timeout": 600,
        }
        factory_cfg = {
            "worker_registry": {
                "test-w": {"adapter": "agy"}
            }
        }
        executor = TaskExecutor(
            "run-1",
            plan_task,
            self.root,
            mock.Mock(),
            mock.Mock(),
            factory_cfg,
            project_policy=policy
        )
        self.assertEqual(executor.timeout, 120)

    def test_task_retry_and_reconciliation_enforce_project_max_task_attempts(self):
        policy_path = self.root / "factory.project.json"
        policy_data = json.loads(policy_path.read_text(encoding="utf-8"))
        policy_data["limits"]["max_task_attempts"] = 1
        policy = ProjectPolicy(policy_data, self.root)

        from tools.factory import FactoryOrchestrator
        run_id = "run-retry-test"
        runs_dir = self.root / ".agy-factory" / "runs"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        plan = {
            "plan_id": "plan-retry",
            "tasks": [
                {
                    "task_id": "t1",
                    "name": "Task 1",
                    "requires": ["code_generation"],
                    "dependencies": [],
                    "max_retries": 5,
                }
            ]
        }
        plan_file = run_dir / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        manifest_data = {
            "run_id": run_id,
            "run_state": "RUNNING",
            "plan_path": str(plan_file),
            "tasks": {
                "t1": {
                    "task_id": "t1",
                    "canonical_state": "FAILED",
                    "status": "FAILED",
                    "attempts_count": 1,
                    "current_attempt_id": 1,
                }
            }
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

        with mock.patch("tools.factory.RUNS_DIR", runs_dir):
            pe = FactoryOrchestrator(
                plan_path=plan_file,
                run_id=run_id,
            )
            pe.project_policy = policy
            # Reconcile should NOT reset t1 to PENDING because attempts_count >= max_task_attempts (1)
            pe.reconcile_state()
            self.assertEqual(pe.manifest["tasks"]["t1"]["canonical_state"], "FAILED")


if __name__ == "__main__":
    unittest.main()
