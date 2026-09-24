#!/usr/bin/env python3
"""
Unit tests for Factory v7.0.0 GoalController, Failpoints, and Crash Recovery.
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
    FailpointTriggered,
    set_project_context,
    get_project_context
)


class TestV7GoalControllerRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="factory-v7-controller-test-"))
        self.orig_ctx = get_project_context()

        # Initialize clean Git repo
        subprocess.run(["git", "init"], cwd=str(self.tmp_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@local.test"], cwd=str(self.tmp_dir), check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(self.tmp_dir), check=True)
        (self.tmp_dir / "README.md").write_text("# Target\n", encoding="utf-8")
        ProjectPolicy.init_starter(self.tmp_dir, "ControllerProject")
        subprocess.run(["git", "add", "-A"], cwd=str(self.tmp_dir), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(self.tmp_dir), check=True)

    def tearDown(self):
        set_project_context(self.orig_ctx)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_plan_only_stops_at_ready(self):
        ctrl = GoalController(
            project_root=self.tmp_dir,
            goal_text="1. Build parser\n2. Build writer",
            plan_only=True
        )
        state = ctrl.run()
        self.assertEqual(state["phase"], "READY")
        self.assertTrue(pathlib.Path(state["approved_plan_path"]).exists())
        self.assertTrue(pathlib.Path(state["goal_spec_path"]).exists())
        self.assertIsNone(state["run_id"])

    def test_failpoint_after_goal_structured_and_resume(self):
        # 1. Run with failpoint after_goal_structured
        ctrl = GoalController(
            project_root=self.tmp_dir,
            goal_text="1. Compute hashes",
            failpoint="after_goal_structured",
            plan_only=True
        )
        with self.assertRaises(FailpointTriggered):
            ctrl.run()

        # Verify state is saved at STRUCTURING
        self.assertEqual(ctrl.state["phase"], "STRUCTURING")
        self.assertEqual(ctrl.state["failpoint_hit"], "after_goal_structured")
        self.assertTrue(pathlib.Path(ctrl.state["goal_spec_path"]).exists())

        # 2. Resume goal without failpoint
        resume_ctrl = GoalController(
            goal_id=ctrl.goal_id,
            project_root=self.tmp_dir,
            plan_only=True
        )
        final_state = resume_ctrl.resume()
        self.assertEqual(final_state["phase"], "READY")
        self.assertTrue(pathlib.Path(final_state["approved_plan_path"]).exists())

    def test_failpoint_after_plan_generated_and_resume(self):
        ctrl = GoalController(
            project_root=self.tmp_dir,
            goal_text="1. Implement tree hashing\n2. Add CLI",
            failpoint="after_plan_generated",
            plan_only=True
        )
        with self.assertRaises(FailpointTriggered):
            ctrl.run()

        self.assertEqual(ctrl.state["phase"], "PLANNING")
        self.assertTrue(pathlib.Path(ctrl.state["current_plan_path"]).exists())

        # Resume to READY
        resume_ctrl = GoalController(
            goal_id=ctrl.goal_id,
            project_root=self.tmp_dir,
            plan_only=True
        )
        final_state = resume_ctrl.resume()
        self.assertEqual(final_state["phase"], "READY")

    def test_failpoint_after_plan_reviewed_and_resume(self):
        ctrl = GoalController(
            project_root=self.tmp_dir,
            goal_text="1. Core engine",
            failpoint="after_plan_reviewed",
            plan_only=True
        )
        with self.assertRaises(FailpointTriggered):
            ctrl.run()

        self.assertEqual(ctrl.state["phase"], "READY")
        self.assertTrue(pathlib.Path(ctrl.state["approved_plan_path"]).exists())

    def test_goal_report_generation(self):
        ctrl = GoalController(
            project_root=self.tmp_dir,
            goal_text="1. Report test",
            plan_only=True
        )
        ctrl.run()
        report = ctrl.generate_report()
        self.assertEqual(report["goal_id"], ctrl.goal_id)
        self.assertEqual(report["phase"], "READY")
        self.assertEqual(report["plan_revisions"], 0)


if __name__ == "__main__":
    unittest.main()
