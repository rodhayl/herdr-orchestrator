#!/usr/bin/env python3
"""
factory_tests/test_v8_derived_requirements.py

Validates FACTORY v8.0.0 Derived Requirement classification,
traceability to explicit criteria or hard invariants, orphan rejection,
and derivation metrics.
"""

import json
import pathlib
import unittest

from tools.context import (
    DerivedRequirementAuditor,
    OrphanDerivedRequirementError,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestV8DerivedRequirements(unittest.TestCase):
    def setUp(self):
        self.explicit_spec = {
            "goal_id": "goal-v8-explicit",
            "title": "Explicit Spec",
            "acceptance_criteria": [
                {"id": "R1", "provenance": "USER_EXPLICIT", "description": "Support SHA256"},
                {"id": "R2", "provenance": "USER_EXPLICIT", "description": "Support BLAKE3"},
                {"id": "R3", "provenance": "USER_EXPLICIT", "description": "CLI command interface"},
            ],
        }

    def test_audit_all_explicit_requirements(self):
        """Verifies audit passes when all requirements are USER_EXPLICIT."""
        metrics = DerivedRequirementAuditor.audit_requirements(self.explicit_spec)
        self.assertEqual(metrics["explicit_requirement_count"], 3)
        self.assertEqual(metrics["derived_requirement_count"], 0)
        self.assertEqual(metrics["derived_requirement_ratio"], 0.0)
        self.assertEqual(metrics["orphan_count"], 0)
        self.assertEqual(metrics["explicit_ids"], ["R1", "R2", "R3"])
        self.assertEqual(metrics["derived_ids"], [])

    def test_audit_valid_derived_requirement_traced_to_explicit(self):
        """Verifies derived requirement traced to an explicit criterion with rationale passes."""
        spec = {
            "goal_id": "goal-v8-valid-derived",
            "acceptance_criteria": [
                {"id": "R1", "provenance": "USER_EXPLICIT", "description": "Support SHA256"},
                {
                    "id": "D1",
                    "provenance": "DERIVED",
                    "description": "Deterministic chunking of large files",
                    "derived_from": ["R1"],
                    "rationale": "SHA256 tree hashing requires deterministic leaf chunk sizing.",
                    "created_by": "goal_structurer",
                },
            ],
        }
        metrics = DerivedRequirementAuditor.audit_requirements(spec)
        self.assertEqual(metrics["explicit_requirement_count"], 1)
        self.assertEqual(metrics["derived_requirement_count"], 1)
        self.assertEqual(metrics["derived_requirement_ratio"], 0.5)
        self.assertIn("D1", metrics["derived_ids"])

    def test_audit_valid_derived_requirement_traced_to_hard_invariant(self):
        """Verifies derived requirement traced to a hard invariant (e.g. INVARIANT:STDLIB_ONLY) passes."""
        spec = {
            "goal_id": "goal-v8-invariant-derived",
            "acceptance_criteria": [
                {"id": "R1", "provenance": "USER_EXPLICIT", "description": "Support SHA256"},
                {
                    "id": "D2",
                    "provenance": "DERIVED",
                    "description": "Zero external pip dependencies",
                    "derived_from": ["INVARIANT:STDLIB_ONLY"],
                    "rationale": "Clean room portability requires Python stdlib only.",
                    "created_by": "planner",
                },
            ],
        }
        metrics = DerivedRequirementAuditor.audit_requirements(spec)
        self.assertEqual(metrics["derived_requirement_count"], 1)
        self.assertIn("D2", metrics["derived_ids"])

    def test_orphan_derived_requirement_missing_parents_fails(self):
        """Verifies that a derived requirement with empty derived_from raises OrphanDerivedRequirementError."""
        spec = {
            "goal_id": "goal-v8-orphan-no-parents",
            "acceptance_criteria": [
                {"id": "R1", "provenance": "USER_EXPLICIT", "description": "Support SHA256"},
                {
                    "id": "D_ORPHAN",
                    "provenance": "DERIVED",
                    "description": "Unanchored optimization",
                    "derived_from": [],
                    "rationale": "Thought it was a good idea",
                },
            ],
        }
        with self.assertRaises(OrphanDerivedRequirementError) as ctx:
            DerivedRequirementAuditor.audit_requirements(spec)
        self.assertIn("D_ORPHAN", str(ctx.exception))

    def test_orphan_derived_requirement_invalid_parent_fails(self):
        """Verifies that a derived requirement pointing to an unknown criterion fails closed."""
        spec = {
            "goal_id": "goal-v8-orphan-bad-parent",
            "acceptance_criteria": [
                {"id": "R1", "provenance": "USER_EXPLICIT", "description": "Support SHA256"},
                {
                    "id": "D_BAD_PARENT",
                    "provenance": "DERIVED",
                    "description": "Unanchored optimization",
                    "derived_from": ["R_NON_EXISTENT"],
                    "rationale": "Traced to non-existent requirement",
                },
            ],
        }
        with self.assertRaises(OrphanDerivedRequirementError) as ctx:
            DerivedRequirementAuditor.audit_requirements(spec)
        self.assertIn("D_BAD_PARENT", str(ctx.exception))

    def test_orphan_derived_requirement_missing_rationale_fails(self):
        """Verifies that a derived requirement lacking a rationale fails closed."""
        spec = {
            "goal_id": "goal-v8-orphan-no-rationale",
            "acceptance_criteria": [
                {"id": "R1", "provenance": "USER_EXPLICIT", "description": "Support SHA256"},
                {
                    "id": "D_NO_RATIONALE",
                    "provenance": "DERIVED",
                    "description": "Unexplained requirement",
                    "derived_from": ["R1"],
                    "rationale": "",
                },
            ],
        }
        with self.assertRaises(OrphanDerivedRequirementError) as ctx:
            DerivedRequirementAuditor.audit_requirements(spec)
        self.assertIn("D_NO_RATIONALE", str(ctx.exception))

    def test_audit_with_plan_tasks_caused_by_derived(self):
        """Verifies calculation of tasks_caused_by_derived_requirements when a plan is audited."""
        spec = {
            "goal_id": "goal-v8-plan-audit",
            "acceptance_criteria": [
                {"id": "R1", "provenance": "USER_EXPLICIT", "description": "Support SHA256"},
                {
                    "id": "D1",
                    "provenance": "DERIVED",
                    "description": "Auxiliary hash cache",
                    "derived_from": ["R1"],
                    "rationale": "Performance optimization for repeated blocks",
                },
            ],
        }
        plan = {
            "tasks": [
                {"task_id": "task_core", "satisfies": ["R1"]},
                {"task_id": "task_cache", "satisfies": ["D1"]},  # pure derived task
            ]
        }
        metrics = DerivedRequirementAuditor.audit_requirements(spec, plan=plan)
        self.assertEqual(metrics["tasks_caused_by_derived_requirements"], 1)

    def test_treehash_baseline_derived_requirements_audit(self):
        """Audits the TreeHash baseline 12 explicit + 2 derived requirements structure."""
        baseline_criteria = [
            {"id": f"R{i}", "provenance": "USER_EXPLICIT", "description": f"Requirement {i}"}
            for i in range(1, 13)
        ]
        # Add 2 derived requirements representing TreeHash baseline
        baseline_criteria.extend([
            {
                "id": "D13",
                "provenance": "DERIVED",
                "description": "Chunk-aligned streaming buffer",
                "derived_from": ["R1", "R2"],
                "rationale": "Tree hash leaves require block-aligned streaming buffer for arbitrary stream sizes",
                "created_by": "goal_structurer",
            },
            {
                "id": "D14",
                "provenance": "DERIVED",
                "description": "Standard library hashlib digest equivalence testing",
                "derived_from": ["INVARIANT:DETERMINISTIC_TESTING", "R1"],
                "rationale": "Verify implementation against known reference test vectors",
                "created_by": "planner",
            },
        ])

        goal_spec = {
            "goal_id": "goal-20260924-100806",
            "title": "TreeHash Engine Baseline",
            "acceptance_criteria": baseline_criteria,
        }

        metrics = DerivedRequirementAuditor.audit_requirements(goal_spec)
        self.assertEqual(metrics["explicit_requirement_count"], 12)
        self.assertEqual(metrics["derived_requirement_count"], 2)
        self.assertEqual(len(metrics["derived_ids"]), 2)
        self.assertAlmostEqual(metrics["derived_requirement_ratio"], 2 / 14, places=3)
        self.assertEqual(metrics["orphan_count"], 0)

    def test_compile_goal_spec_rejects_orphan_derived_requirement(self):
        """Verifies compile_goal_spec audits derived requirements and rejects orphans."""
        from tools.factory import compile_goal_spec, ProjectPolicy
        policy = ProjectPolicy.load()
        spec = compile_goal_spec("Implement hash utility\n1. Deterministic hashing\n2. CLI interface", REPO_ROOT, policy)
        self.assertIn("derived_requirement_metrics", spec)
        self.assertEqual(spec["derived_requirement_metrics"]["orphan_count"], 0)

        # Confirm audit_requirements directly rejects an injected orphan
        malicious_spec = dict(spec)
        malicious_spec["acceptance_criteria"] = list(spec["acceptance_criteria"]) + [
            {"id": "D_ORPHAN", "provenance": "DERIVED", "description": "Unanchored requirement", "derived_from": [], "rationale": "None"}
        ]
        with self.assertRaises(OrphanDerivedRequirementError):
            DerivedRequirementAuditor.audit_requirements(malicious_spec)


if __name__ == "__main__":
    unittest.main()
