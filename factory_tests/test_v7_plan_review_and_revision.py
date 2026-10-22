#!/usr/bin/env python3
"""
Unit tests for Factory v7.0.0 Independent Plan Review and Bounded Revision.
"""

import os
import pathlib
import shutil
import tempfile
import unittest

from tools.factory import (
    ProjectPolicy,
    compile_goal_spec,
    compile_plan_from_goal,
    review_plan,
    revise_plan
)


class TestV7PlanReviewAndRevision(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="factory-v7-review-test-"))
        self.policy = ProjectPolicy({
            "project_name": "ReviewTest",
            "version": "7.0.0",
            "limits": {"max_plan_revisions": 2}
        }, self.tmp_dir)
        self.old_harness = os.environ.get("FACTORY_TEST_HARNESS")

    def tearDown(self):
        if "PLAN_REVIEW_TEST_VERDICT" in os.environ:
            del os.environ["PLAN_REVIEW_TEST_VERDICT"]
        if self.old_harness is None:
            os.environ.pop("FACTORY_TEST_HARNESS", None)
        else:
            os.environ["FACTORY_TEST_HARNESS"] = self.old_harness
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_review_approves_valid_plan(self):
        goal_spec = compile_goal_spec("1. Feature Alpha\n2. Feature Beta", self.tmp_dir, self.policy)
        plan = compile_plan_from_goal(goal_spec, self.policy)

        review = review_plan(plan, goal_spec, self.policy, revision_index=0)
        self.assertEqual(review["verdict"], "APPROVED")
        self.assertEqual(review["revision_index"], 0)
        self.assertEqual(review["findings"], [])

    def test_review_requests_revision_on_traceability_gap(self):
        goal_spec = compile_goal_spec("1. Feature Alpha\n2. Feature Beta", self.tmp_dir, self.policy)
        plan = compile_plan_from_goal(goal_spec, self.policy)
        # Introduce gap by removing satisfies
        plan["tasks"][0]["satisfies"] = []

        review = review_plan(plan, goal_spec, self.policy, revision_index=0)
        self.assertEqual(review["verdict"], "REVISE")
        self.assertTrue(len(review["findings"]) >= 1)
        self.assertTrue(any(f["severity"] in ("CRITICAL", "MAJOR") for f in review["findings"]))

    def test_plan_revision_resolves_gap(self):
        goal_spec = compile_goal_spec("1. Feature Alpha\n2. Feature Beta", self.tmp_dir, self.policy)
        plan = compile_plan_from_goal(goal_spec, self.policy)
        plan["tasks"][0]["satisfies"] = []

        review1 = review_plan(plan, goal_spec, self.policy, revision_index=0)
        self.assertEqual(review1["verdict"], "REVISE")

        # Revise plan
        revised = revise_plan(plan, review1["findings"], goal_spec, self.policy, revision_index=1)
        review2 = review_plan(revised, goal_spec, self.policy, revision_index=1)
        self.assertEqual(review2["verdict"], "APPROVED")

    def test_simulated_bounded_revision_loop(self):
        goal_spec = compile_goal_spec("1. Feature Alpha", self.tmp_dir, self.policy)
        plan = compile_plan_from_goal(goal_spec, self.policy)

        os.environ["FACTORY_TEST_HARNESS"] = "1"
        os.environ["PLAN_REVIEW_TEST_VERDICT"] = "REVISE"
        r0 = review_plan(plan, goal_spec, self.policy, revision_index=0)
        self.assertEqual(r0["verdict"], "REVISE")

        # Second revision should be approved by simulation hook
        r1 = review_plan(plan, goal_spec, self.policy, revision_index=1)
        self.assertEqual(r1["verdict"], "APPROVED")


if __name__ == "__main__":
    unittest.main()
