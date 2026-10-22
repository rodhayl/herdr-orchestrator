#!/usr/bin/env python3
"""
Unit tests for Factory v7.0.0 Post-Execution Validation, Final Audit, and Bounded Remediation.
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from tools.factory import (
    GoalController,
    ProjectPolicy,
    audit_project,
    compile_goal_spec,
    compile_plan_from_goal,
    set_project_context,
    get_project_context
)


class TestV7Remediation(unittest.TestCase):
    def setUp(self):
        self.orig_harness = os.environ.get("FACTORY_TEST_HARNESS")
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        self.tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="factory-v7-remediation-test-"))
        self.orig_ctx = get_project_context()

        subprocess.run(["git", "init"], cwd=str(self.tmp_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@remed.local"], cwd=str(self.tmp_dir), check=True)
        subprocess.run(["git", "config", "user.name", "Remediation User"], cwd=str(self.tmp_dir), check=True)
        (self.tmp_dir / "README.md").write_text("# Target\n", encoding="utf-8")
        ProjectPolicy.init_starter(self.tmp_dir, "RemediationProject")
        subprocess.run(["git", "add", "-A"], cwd=str(self.tmp_dir), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(self.tmp_dir), check=True)

    def tearDown(self):
        if self.orig_harness is not None:
            os.environ["FACTORY_TEST_HARNESS"] = self.orig_harness
        else:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
        if "AUDIT_TEST_VERDICT" in os.environ:
            del os.environ["AUDIT_TEST_VERDICT"]
        set_project_context(self.orig_ctx)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_post_execution_validations_pass(self):
        ctrl = GoalController(
            project_root=self.tmp_dir,
            goal_text="1. Verification feature",
            plan_only=True
        )
        ctrl.run()
        # All default validations exit 0
        all_passed = ctrl.execute_post_validations()
        self.assertTrue(all_passed)
        self.assertTrue(len(ctrl.state["validation_results"]) >= 1)
        for r in ctrl.state["validation_results"]:
            self.assertTrue(r["passed"])

    def test_post_execution_validations_detect_failure(self):
        ctrl = GoalController(
            project_root=self.tmp_dir,
            goal_text="1. Failing feature",
            plan_only=True
        )
        ctrl.run()
        # Inject failing validation into approved plan
        approved_path = pathlib.Path(ctrl.state["approved_plan_path"])
        with open(approved_path, "r", encoding="utf-8") as f:
            plan = json.load(f)
        plan["tasks"][0]["validations"] = [["python3", "-c", "import sys; sys.exit(1)"]]
        with open(approved_path, "w", encoding="utf-8") as f:
            json.dump(plan, f)

        all_passed = ctrl.execute_post_validations()
        self.assertFalse(all_passed)
        failed = [v for v in ctrl.state["validation_results"] if not v["passed"]]
        self.assertEqual(len(failed), 1)

    def test_audit_project_accepted(self):
        policy = ProjectPolicy.load(self.tmp_dir / "factory.project.json")
        goal_spec = compile_goal_spec("1. Clean feature", self.tmp_dir, policy)
        res = audit_project(self.tmp_dir, goal_spec, policy)
        self.assertEqual(res["verdict"], "ACCEPTED")
        self.assertEqual(res["findings"], [])

    def test_audit_project_simulated_remediation_required(self):
        policy = ProjectPolicy.load(self.tmp_dir / "factory.project.json")
        goal_spec = compile_goal_spec("1. Broken feature", self.tmp_dir, policy)
        os.environ["AUDIT_TEST_VERDICT"] = "REMEDIATION_REQUIRED"
        res = audit_project(self.tmp_dir, goal_spec, policy)
        self.assertEqual(res["verdict"], "REMEDIATION_REQUIRED")
        self.assertTrue(len(res["findings"]) >= 1)

    def test_compile_remediation_plan(self):
        ctrl = GoalController(
            project_root=self.tmp_dir,
            goal_text="1. Target feature",
            plan_only=True
        )
        ctrl.run()
        delta_plan = ctrl.compile_remediation_plan(round_num=1)
        self.assertIn("plan-remediation-", delta_plan["plan_id"])
        self.assertEqual(len(delta_plan["tasks"]), 1)
        self.assertEqual(delta_plan["tasks"][0]["task_id"], "remediate_round_1")
        self.assertEqual(delta_plan["tasks"][0]["satisfies"], ["R1"])


if __name__ == "__main__":
    unittest.main()
