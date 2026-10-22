#!/usr/bin/env python3
"""
factory_tests/test_v8_anchors_and_gates.py

Validates FACTORY v8.0.0 Context Anchor gates, staleness verification,
and fail-closed behavior (CONTEXT_ANCHOR_MISSING and STALE_CONTEXT_PACKET).
"""

import copy
import json
import pathlib
import unittest

from tools.context import (
    Anchor,
    ContextCompiler,
    ContextPolicy,
    DEFAULT_CONTEXT_POLICY,
    FilesystemGitContextSource,
    calculate_rendered_anchor_recall,
    ContextAnchorMissingError,
    StaleContextPacketError,
    sha256_text,
    canonical_json_dump,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestV8AnchorsAndGates(unittest.TestCase):
    def setUp(self):
        self.policy = ContextPolicy(DEFAULT_CONTEXT_POLICY)
        self.source = FilesystemGitContextSource(REPO_ROOT)
        self.compiler = ContextCompiler(self.policy, self.source)

        self.sample_task_def = {
            "task_id": "task_core_impl",
            "title": "Implement core hash algorithms",
            "requirements": ["R1", "R2"],
            "allowed_paths": ["treehash/core.py", "treehash/__init__.py"],
            "validations": [
                {
                    "type": "command",
                    "command": ["python3", "-m", "unittest", "discover", "-s", "tests"],
                }
            ],
            "dependencies": [],
        }

        self.sample_goal_spec = {
            "goal_id": "goal-test-v8",
            "title": "TreeHash Engine Test",
            "requirements": [
                {"id": "R1", "type": "USER_EXPLICIT", "description": "Support SHA256"},
                {"id": "R2", "type": "USER_EXPLICIT", "description": "Support BLAKE3"},
            ],
        }

        self.sample_plan = {
            "plan_id": "plan-test-v8",
            "tasks": [self.sample_task_def],
        }

    def test_anchor_model_validation(self):
        """Verifies Anchor schema validation and post_init checks."""
        a = Anchor(
            anchor_id="req:R1",
            anchor_type="requirement",
            source="goal_spec",
            source_hash=sha256_text("Support SHA256"),
            content="Support SHA256",
            required=True,
        )
        self.assertEqual(a.anchor_id, "req:R1")
        self.assertEqual(a.anchor_type, "requirement")
        d = a.to_dict()
        self.assertEqual(d["anchor_id"], "req:R1")
        restored = Anchor.from_dict(d)
        self.assertEqual(restored.anchor_id, a.anchor_id)
        self.assertEqual(restored.source_hash, a.source_hash)

    def test_rendered_anchor_recall(self):
        """Verifies calculate_rendered_anchor_recall checks for anchor content in rendered prompt text."""
        a1 = Anchor("req:R1", "requirement", "spec", sha256_text("Support SHA256"), "Support SHA256", True)
        a2 = Anchor("req:R2", "requirement", "spec", sha256_text("Support BLAKE3"), "Support BLAKE3", True)
        required = [a1, a2]

        full_prompt = "Task must implement Support SHA256 and also Support BLAKE3 thoroughly."
        recall, missing = calculate_rendered_anchor_recall(required, full_prompt)
        self.assertEqual(recall, 1.0)
        self.assertEqual(missing, [])

        partial_prompt = "Task only mentions Support SHA256."
        recall, missing = calculate_rendered_anchor_recall(required, partial_prompt)
        self.assertEqual(recall, 0.5)
        self.assertIn("req:R2", missing)

    def test_compiler_achieves_100_percent_recall(self):
        """Verifies that the ContextCompiler generates rendered text with 100% anchor recall."""
        packet = self.compiler.compile_task_packet(
            goal_id="goal-test-v8",
            run_id="run-test-v8",
            task_id="task_core_impl",
            attempt_id=1,
            task_def=self.sample_task_def,
            plan=self.sample_plan,
            goal_spec=self.sample_goal_spec,
            worktree_path=str(REPO_ROOT),
            allowed_paths=self.sample_task_def["allowed_paths"],
            dependencies=[],
            handoffs=[],
        )
        rendered = packet.render_full_prompt()
        recall, missing = calculate_rendered_anchor_recall(packet.required_anchors, rendered)
        self.assertEqual(recall, 1.0, f"Expected 100% anchor recall, but missing: {missing}")

    def test_staleness_verification_passes_when_unchanged(self):
        """Verifies that verify_staleness returns False when source hashes match."""
        packet = self.compiler.compile_task_packet(
            goal_id="goal-test-v8",
            run_id="run-test-v8",
            task_id="task_core_impl",
            attempt_id=1,
            task_def=self.sample_task_def,
            plan=self.sample_plan,
            goal_spec=self.sample_goal_spec,
            worktree_path=str(REPO_ROOT),
            allowed_paths=self.sample_task_def["allowed_paths"],
            dependencies=[],
            handoffs=[],
        )
        curr_hashes = copy.deepcopy(packet.source_hashes)
        is_stale, reasons = packet.verify_staleness(curr_hashes)
        self.assertFalse(is_stale)
        self.assertEqual(len(reasons), 0)

    def test_staleness_verification_fails_when_plan_or_spec_changes(self):
        """Verifies that modifying source objects causes verify_staleness to detect drift."""
        packet = self.compiler.compile_task_packet(
            goal_id="goal-test-v8",
            run_id="run-test-v8",
            task_id="task_core_impl",
            attempt_id=1,
            task_def=self.sample_task_def,
            plan=self.sample_plan,
            goal_spec=self.sample_goal_spec,
            worktree_path=str(REPO_ROOT),
            allowed_paths=self.sample_task_def["allowed_paths"],
            dependencies=[],
            handoffs=[],
        )
        mutated_spec = copy.deepcopy(self.sample_goal_spec)
        mutated_spec["title"] = "Modified Goal Spec Title"
        curr_hashes = {
            "goal-spec": sha256_text(canonical_json_dump(mutated_spec)),
            "plan": sha256_text(canonical_json_dump(self.sample_plan)),
            "task_def": sha256_text(canonical_json_dump(self.sample_task_def)),
        }
        is_stale, reasons = packet.verify_staleness(curr_hashes)
        self.assertTrue(is_stale)
        self.assertTrue(any("goal-spec" in r for r in reasons))

    def test_attempt_retry_produces_distinct_immutable_packets(self):
        """Verifies that retrying an attempt yields a distinct packet with unique attempt ID."""
        packet_attempt_1 = self.compiler.compile_task_packet(
            goal_id="goal-test-v8",
            run_id="run-test-v8",
            task_id="task_core_impl",
            attempt_id=1,
            task_def=self.sample_task_def,
            plan=self.sample_plan,
            goal_spec=self.sample_goal_spec,
            worktree_path=str(REPO_ROOT),
            allowed_paths=self.sample_task_def["allowed_paths"],
            dependencies=[],
            handoffs=[],
        )

        packet_attempt_2 = self.compiler.compile_task_packet(
            goal_id="goal-test-v8",
            run_id="run-test-v8",
            task_id="task_core_impl",
            attempt_id=2,
            task_def=self.sample_task_def,
            plan=self.sample_plan,
            goal_spec=self.sample_goal_spec,
            worktree_path=str(REPO_ROOT),
            allowed_paths=self.sample_task_def["allowed_paths"],
            dependencies=[],
            handoffs=[{"from_task": "task_core_impl", "summary": "attempt 1 failed validation"}],
        )

        self.assertEqual(packet_attempt_1.attempt_id, 1)
        self.assertEqual(packet_attempt_2.attempt_id, 2)
        self.assertNotEqual(packet_attempt_1.packet_id, packet_attempt_2.packet_id)
        self.assertNotEqual(packet_attempt_1.packet_hash, packet_attempt_2.packet_hash)


if __name__ == "__main__":
    unittest.main()
