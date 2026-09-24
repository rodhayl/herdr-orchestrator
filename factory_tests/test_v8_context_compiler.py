#!/usr/bin/env python3
"""factory_tests/test_v8_context_compiler.py

Comprehensive tests for ContextCompiler, role-specific packets, budgets, and pruning hierarchy.
"""
import copy
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools.context import (
    ContextCompiler,
    ContextPolicy,
    FilesystemGitContextSource,
    StablePrefixManager,
    Anchor,
    HandoffPacket,
    ContextPacket,
    save_context_packet,
    load_context_packet,
    calculate_anchor_recall,
    calculate_rendered_anchor_recall,
    ContextBudgetExceededError,
    ContextAnchorMissingError,
    DEFAULT_CONTEXT_POLICY,
    SCHEMA_VERSION,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestV8ContextCompiler(unittest.TestCase):
    def setUp(self):
        self.policy = ContextPolicy.load()
        self.source = FilesystemGitContextSource(REPO_ROOT)
        self.compiler = ContextCompiler(self.policy, self.source)

        self.sample_goal_spec = {
            "goal_id": "goal-test-v8",
            "title": "TreeHash Engine Test",
            "raw_goal": "Implement high performance TreeHash in Python 3 stdlib",
            "acceptance_criteria": [
                {
                    "id": "R1",
                    "title": "SHA-256 Engine",
                    "description": "Deterministic SHA-256 leaf and node hashing",
                    "provenance": "USER_EXPLICIT",
                },
                {
                    "id": "R2",
                    "title": "CLI Subcommands",
                    "description": "CLI subcommands compute and verify",
                    "provenance": "USER_EXPLICIT",
                },
                {
                    "id": "R3",
                    "title": "Deterministic Test Suite",
                    "description": "Comprehensive test suite passing 100%",
                    "provenance": "DERIVED",
                    "derived_from": ["R1", "INVARIANT:DETERMINISTIC_TESTING"],
                    "rationale": "Required verification",
                    "created_by": "GoalSpecCompiler",
                },
            ],
        }

        self.sample_task_def = {
            "task_id": "task_core_impl",
            "task_type": "backend",
            "name": "Core Engine Implementation",
            "description": "Implement core hashing logic",
            "satisfies": ["R1"],
            "allowed_paths": ["treehash/**"],
            "validations": [["python3", "-c", "import treehash"]],
            "dependencies": [],
            "prompt": "Implement the core algorithms directly in treehash/.",
        }

        self.sample_plan = {
            "plan_id": "plan-test-v8",
            "name": "Test Plan",
            "tasks": [self.sample_task_def],
        }

    def test_compile_task_packet_structure_and_schema(self):
        """Validates that compiled TaskContextPacket conforms to context-packet schema."""
        packet = self.compiler.compile_task_packet(
            goal_id="goal-test-v8",
            run_id="run-test-v8",
            task_id="task_core_impl",
            attempt_id=1,
            task_def=self.sample_task_def,
            plan=self.sample_plan,
            goal_spec=self.sample_goal_spec,
            worktree_path="/tmp/test_worktree",
            allowed_paths=["treehash/**"],
            dependencies=[],
            handoffs=[],
        )

        self.assertEqual(packet.schema_version, SCHEMA_VERSION)
        self.assertEqual(packet.packet_role, "task")
        self.assertEqual(packet.task_id, "task_core_impl")
        self.assertEqual(packet.attempt_id, 1)
        self.assertTrue(len(packet.required_anchors) >= 3)  # R1, allowed_path, validation

        # Schema validation
        schema_path = REPO_ROOT / "schemas" / "context-packet.schema.json"
        if schema_path.exists():
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            d = packet.to_dict()
            for req_field in schema.get("required", []):
                self.assertIn(req_field, d, f"Missing required field {req_field} in packet")

    def test_stable_prefix_integrity(self):
        """Verifies deterministic stable prefixes for all roles."""
        roles = ["task", "reviewer", "auditor", "planner"]
        hashes = {}
        for r in roles:
            prefix, h, b = StablePrefixManager.get_stable_prefix(r)
            self.assertIn("Contract", prefix)
            self.assertTrue(len(prefix) > 100)
            self.assertEqual(len(h), 64)
            self.assertEqual(b, len(prefix.encode("utf-8")))
            hashes[r] = h

        # Role prefixes must be distinct
        self.assertEqual(len(set(hashes.values())), len(roles))

    def test_plan_review_packet_compilation(self):
        """Validates PlanReviewContextPacket compilation and budget."""
        packet = self.compiler.compile_plan_review_packet(
            goal_spec=self.sample_goal_spec,
            plan=self.sample_plan,
            project_policy_summary={"max_tasks": 10},
            revision_index=0,
        )
        self.assertEqual(packet.packet_role, "reviewer")
        self.assertTrue(packet.packet_bytes < 8192)
        self.assertIn("TreeHash Engine Test", packet.rendered_tail)
        self.assertIn("R1", packet.rendered_tail)
        self.assertIn("task_core_impl", packet.rendered_tail)

    def test_audit_packet_compilation(self):
        """Validates AuditContextPacket compilation with bounded git diff."""
        packet = self.compiler.compile_audit_packet(
            goal_spec=self.sample_goal_spec,
            project_policy_summary={"max_tasks": 10},
            validation_results=[
                {"task_id": "task_core_impl", "command": ["python3", "-m", "unittest"], "passed": True}
            ],
            base_commit="HEAD",
            round_num=0,
        )
        self.assertEqual(packet.packet_role, "auditor")
        self.assertTrue(packet.packet_bytes < 10240)
        self.assertIn("Final Code Audit Assignment", packet.rendered_tail)
        self.assertIn("Deterministic Validation Evidence", packet.rendered_tail)

    def test_hard_budget_exceeded_fails_closed(self):
        """Verifies that exceeding the hard budget raises ContextBudgetExceededError without blind truncation."""
        strict_policy_dict = copy.deepcopy(DEFAULT_CONTEXT_POLICY)
        strict_policy_dict["roles"]["task"]["soft_budget_bytes"] = 100
        strict_policy_dict["roles"]["task"]["hard_budget_bytes"] = 150  # tiny budget
        strict_policy = ContextPolicy(strict_policy_dict)
        strict_compiler = ContextCompiler(strict_policy, self.source)

        with self.assertRaises(ContextBudgetExceededError):
            strict_compiler.compile_task_packet(
                goal_id="goal-test-v8",
                run_id="run-test-v8",
                task_id="task_core_impl",
                attempt_id=1,
                task_def=self.sample_task_def,
                plan=self.sample_plan,
                goal_spec=self.sample_goal_spec,
                worktree_path="/tmp/test_worktree",
                allowed_paths=["treehash/**"],
                dependencies=[],
                handoffs=[],
            )

    def test_packet_save_and_load_roundtrip(self):
        """Validates saving to disk and loading returns identical packet state."""
        import tempfile

        packet = self.compiler.compile_task_packet(
            goal_id="goal-test-v8",
            run_id="run-test-v8",
            task_id="task_core_impl",
            attempt_id=1,
            task_def=self.sample_task_def,
            plan=self.sample_plan,
            goal_spec=self.sample_goal_spec,
            worktree_path="/tmp/test_worktree",
            allowed_paths=["treehash/**"],
            dependencies=[],
            handoffs=[],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            pkt_file = pathlib.Path(tmpdir) / "context_packet.json"
            save_context_packet(packet, pkt_file)
            self.assertTrue(pkt_file.exists())

            loaded = load_context_packet(pkt_file)
            self.assertEqual(loaded.packet_id, packet.packet_id)
            self.assertEqual(loaded.packet_hash, packet.packet_hash)
            self.assertEqual(loaded.packet_bytes, packet.packet_bytes)
            self.assertEqual(len(loaded.required_anchors), len(packet.required_anchors))

    def test_canonical_packet_bytes_and_honest_token_source(self):
        """Verifies packet_bytes includes full prompt (prefix + tail) and token_count_source is explicit."""
        packet = self.compiler.compile_task_packet(
            goal_id="goal-test-v8",
            run_id="run-test-v8",
            task_id="task_core_impl",
            attempt_id=1,
            task_def=self.sample_task_def,
            plan=self.sample_plan,
            goal_spec=self.sample_goal_spec,
            worktree_path="/tmp/test_worktree",
            allowed_paths=["treehash/**"],
            dependencies=[],
            handoffs=[],
        )
        full_prompt = packet.render_full_prompt()
        self.assertEqual(packet.packet_bytes, len(full_prompt.encode("utf-8")))
        self.assertIsNone(packet.token_count)
        self.assertEqual(packet.token_count_source, "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
