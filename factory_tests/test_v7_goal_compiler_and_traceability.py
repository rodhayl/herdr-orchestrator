#!/usr/bin/env python3
"""
Unit tests for Factory v7.0.0 GoalSpec compilation, DAG planning, and requirement traceability.
"""

import json
import os
import pathlib
import shutil
import tempfile
import unittest

from tools.factory import (
    ProjectPolicy,
    generate_discovery_packet,
    compile_goal_spec,
    compile_plan_from_goal,
    validate_plan_traceability
)


class TestV7GoalCompilerAndTraceability(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="factory-v7-compiler-test-"))
        self.policy = ProjectPolicy({
            "project_name": "CompilerTest",
            "version": "7.0.0",
            "limits": {"max_tasks": 6}
        }, self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_discovery_packet_generation(self):
        (self.tmp_dir / "README.md").write_text("# Test Project\nDiscovery test.", encoding="utf-8")
        tests_dir = self.tmp_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_sample.py").write_text("def test_dummy(): pass\n", encoding="utf-8")

        packet = generate_discovery_packet(self.tmp_dir)
        self.assertIn("README.md", packet["file_tree"])
        self.assertIn("tests/test_sample.py", packet["test_files"])
        self.assertIn("README.md", packet["top_level_files"])

    def test_compile_goal_spec_provenance_tagging(self):
        goal_text = """# Build TreeHasher Utility
1. File content hashing using SHA-256.
2. Directory Merkle tree calculation.
3. Empty directory handling.
Non-goals: Do not build network server.
Constraints: Python 3 stdlib only.
"""
        goal_spec = compile_goal_spec(goal_text, self.tmp_dir, self.policy)
        self.assertTrue(goal_spec["goal_id"].startswith("goal-"))
        self.assertIn("TreeHasher", goal_spec["title"])

        criteria = goal_spec["acceptance_criteria"]
        self.assertTrue(len(criteria) >= 4)

        explicit_criteria = [c for c in criteria if c["provenance"] == "USER_EXPLICIT"]
        derived_criteria = [c for c in criteria if c["provenance"] == "DERIVED"]

        self.assertEqual(len(explicit_criteria), 3)
        self.assertTrue(len(derived_criteria) >= 1)
        self.assertIn("Deterministic Unit", derived_criteria[0]["title"])
        self.assertTrue(len(goal_spec["non_goals"]) >= 1)

    def test_compile_plan_and_traceability_matrix(self):
        goal_text = "1. Feature A\n2. Feature B\n3. CLI command"
        goal_spec = compile_goal_spec(goal_text, self.tmp_dir, self.policy)
        plan = compile_plan_from_goal(goal_spec, self.policy)

        self.assertIn("requirements_traceability", plan)
        traceability = plan["requirements_traceability"]

        # Every requirement must have at least one satisfying task
        for c in goal_spec["acceptance_criteria"]:
            self.assertIn(c["id"], traceability)
            self.assertTrue(len(traceability[c["id"]]) >= 1)

        # Plan passes traceability validation
        errs = validate_plan_traceability(plan, goal_spec, self.policy)
        self.assertEqual(errs, [])

    def test_validate_plan_traceability_catches_coverage_gap(self):
        goal_spec = {
            "acceptance_criteria": [
                {"id": "R1", "title": "Core Feature", "provenance": "USER_EXPLICIT"},
                {"id": "R2", "title": "Missing Feature", "provenance": "USER_EXPLICIT"}
            ]
        }
        plan = {
            "plan_id": "test-gap",
            "version": "2.0.0",
            "name": "Gap Plan",
            "tasks": [{
                "task_id": "task_1",
                "satisfies": ["R1"],
                "validations": [["python3", "-c", "pass"]],
                "allowed_paths": ["**"],
                "dependencies": []
            }]
        }
        errs = validate_plan_traceability(plan, goal_spec, self.policy)
        self.assertTrue(any("R2" in e and "Traceability gap" in e for e in errs))

    def test_validate_plan_traceability_catches_unknown_criterion(self):
        goal_spec = {
            "acceptance_criteria": [
                {"id": "R1", "title": "Core Feature", "provenance": "USER_EXPLICIT"}
            ]
        }
        plan = {
            "plan_id": "test-unknown",
            "version": "2.0.0",
            "name": "Unknown Plan",
            "tasks": [{
                "task_id": "task_1",
                "satisfies": ["R1", "R99"],
                "validations": [["python3", "-c", "pass"]],
                "allowed_paths": ["**"],
                "dependencies": []
            }]
        }
        errs = validate_plan_traceability(plan, goal_spec, self.policy)
        self.assertTrue(any("R99" in e and "unknown criterion" in e for e in errs))

    def test_validate_plan_traceability_catches_missing_validations(self):
        goal_spec = {
            "acceptance_criteria": [
                {"id": "R1", "title": "Core Feature", "provenance": "USER_EXPLICIT"}
            ]
        }
        plan = {
            "plan_id": "test-no-val",
            "version": "2.0.0",
            "name": "No Val Plan",
            "tasks": [{
                "task_id": "task_1",
                "satisfies": ["R1"],
                "validations": [],
                "allowed_paths": ["**"],
                "dependencies": []
            }]
        }
        errs = validate_plan_traceability(plan, goal_spec, self.policy)
        self.assertTrue(any("no validation commands defined" in e for e in errs))

    def test_validate_plan_traceability_catches_unsafe_validation(self):
        goal_spec = {
            "acceptance_criteria": [
                {"id": "R1", "title": "Core Feature", "provenance": "USER_EXPLICIT"}
            ]
        }
        plan = {
            "plan_id": "test-unsafe",
            "version": "2.0.0",
            "name": "Unsafe Plan",
            "tasks": [{
                "task_id": "task_1",
                "satisfies": ["R1"],
                "validations": [["rm", "-rf", "/"]],
                "allowed_paths": ["**"],
                "dependencies": []
            }]
        }
        errs = validate_plan_traceability(plan, goal_spec, self.policy)
        self.assertTrue(any("unsafe validation command" in e for e in errs))

    def test_validate_plan_traceability_catches_task_limit(self):
        goal_spec = {"acceptance_criteria": [{"id": f"R{i}", "title": f"F{i}", "provenance": "USER_EXPLICIT"} for i in range(1, 15)]}
        plan = {
            "plan_id": "test-limit",
            "version": "2.0.0",
            "name": "Limit Plan",
            "tasks": [
                {"task_id": f"task_{i}", "satisfies": [f"R{i}"], "validations": [["true"]], "allowed_paths": ["**"], "dependencies": []}
                for i in range(1, 15)
            ]
        }
        errs = validate_plan_traceability(plan, goal_spec, self.policy)
        self.assertTrue(any("exceeds maximum permitted limit" in e for e in errs))

    def test_validate_plan_traceability_catches_cycles(self):
        goal_spec = {"acceptance_criteria": [{"id": "R1", "title": "A", "provenance": "USER_EXPLICIT"}, {"id": "R2", "title": "B", "provenance": "USER_EXPLICIT"}]}
        plan = {
            "plan_id": "test-cycle",
            "version": "2.0.0",
            "name": "Cycle Plan",
            "tasks": [
                {"task_id": "t1", "satisfies": ["R1"], "validations": [["true"]], "allowed_paths": ["**"], "dependencies": ["t2"]},
                {"task_id": "t2", "satisfies": ["R2"], "validations": [["true"]], "allowed_paths": ["**"], "dependencies": ["t1"]}
            ]
        }
        errs = validate_plan_traceability(plan, goal_spec, self.policy)
        self.assertTrue(any("Dependency cycle detected" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
