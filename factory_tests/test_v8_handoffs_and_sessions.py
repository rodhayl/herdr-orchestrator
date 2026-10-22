#!/usr/bin/env python3
"""
factory_tests/test_v8_handoffs_and_sessions.py

Validates FACTORY v8.0.0 HandoffPackets, semantic bounding (<= 4096 bytes),
session isolation, and retry context compilation.
"""

import json
import pathlib
import tempfile
import unittest

from tools.context import (
    ContextCompiler,
    ContextPolicy,
    DEFAULT_CONTEXT_POLICY,
    FilesystemGitContextSource,
    HandoffPacket,
    MAX_SEMANTIC_HANDOFF_BYTES,
    save_handoff_packet,
    load_handoff_packet,
    SCHEMA_VERSION,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestV8HandoffsAndSessions(unittest.TestCase):
    def setUp(self):
        self.policy = ContextPolicy(DEFAULT_CONTEXT_POLICY)
        self.source = FilesystemGitContextSource(REPO_ROOT)
        self.compiler = ContextCompiler(self.policy, self.source)

        self.sample_handoff = HandoffPacket(
            handoff_id="ho-core-1",
            producer_task_id="task_core_impl",
            producer_attempt=1,
            changed_paths=["treehash/core.py", "treehash/__init__.py"],
            satisfied_criteria=["R1", "R2"],
            commit="abcdef123456",
            contracts="def tree_hash(data: bytes, chunk_size: int = 1024) -> str",
            decisions="Used SHA256 as internal leaf hash.",
            consumer_notes="CLI implementation can import tree_hash directly from treehash.core.",
            known_risks="Chunk size must be non-zero.",
            validation_result={"passed": True, "exit_code": 0, "summary": "12 tests pass"},
        )

        self.sample_task_def = {
            "task_id": "task_cli_impl",
            "title": "Implement CLI interface",
            "requirements": ["R3"],
            "allowed_paths": ["treehash/cli.py"],
            "validations": [
                {
                    "type": "command",
                    "command": ["python3", "-m", "unittest", "discover", "-s", "tests"],
                }
            ],
            "dependencies": ["task_core_impl"],
        }

        self.sample_goal_spec = {
            "goal_id": "goal-test-v8",
            "title": "TreeHash Test",
            "requirements": [
                {"id": "R1", "type": "USER_EXPLICIT", "description": "Support SHA256"},
                {"id": "R2", "type": "USER_EXPLICIT", "description": "Support BLAKE3"},
                {"id": "R3", "type": "USER_EXPLICIT", "description": "CLI interface"},
            ],
        }

        self.sample_plan = {
            "plan_id": "plan-test-v8",
            "tasks": [self.sample_task_def],
        }

    def test_handoff_packet_schema_compliance(self):
        """Validates that HandoffPacket serializes to conform to handoff-packet.schema.json."""
        d = self.sample_handoff.to_dict()
        self.assertEqual(d["schema_version"], SCHEMA_VERSION)
        self.assertEqual(d["handoff_id"], "ho-core-1")
        self.assertEqual(d["producer_task_id"], "task_core_impl")
        self.assertEqual(d["producer_attempt"], 1)
        self.assertIn("treehash/core.py", d["changed_paths"])
        self.assertTrue(d["validation_result"]["passed"])

        schema_file = REPO_ROOT / "schemas" / "handoff-packet.schema.json"
        if schema_file.exists():
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
            for req_field in schema.get("required", []):
                self.assertIn(req_field, d, f"Missing required field {req_field} in handoff packet")

    def test_handoff_semantic_bounding_enforced(self):
        """Verifies that large free-text notes/contracts are bounded with [TRUNCATED:BOUND]."""
        massive_notes = "Important note: " + ("X" * 10000)
        massive_contracts = "Contract signature: " + ("Y" * 10000)

        ho = HandoffPacket(
            handoff_id="ho-massive",
            producer_task_id="task_large",
            producer_attempt=1,
            changed_paths=["foo.py"],
            satisfied_criteria=["R1"],
            consumer_notes=massive_notes,
            contracts=massive_contracts,
        )

        # Bounds are enforced automatically in __post_init__ or via enforce_semantic_bounds
        self.assertIn("[TRUNCATED:BOUND]", ho.consumer_notes)
        self.assertIn("[TRUNCATED:BOUND]", ho.contracts)
        self.assertLessEqual(len(ho.consumer_notes.encode("utf-8")), MAX_SEMANTIC_HANDOFF_BYTES)
        self.assertLessEqual(len(ho.contracts.encode("utf-8")), MAX_SEMANTIC_HANDOFF_BYTES)

        # Deterministic facts must remain fully preserved
        self.assertEqual(ho.changed_paths, ["foo.py"])
        self.assertEqual(ho.satisfied_criteria, ["R1"])

    def test_handoff_markdown_rendering(self):
        """Verifies markdown rendering presents clean, actionable contracts and notes."""
        md = self.sample_handoff.render_markdown()
        self.assertIn("Predecessor Handoff: `task_core_impl`", md)
        self.assertIn("`treehash/core.py`", md)
        self.assertIn("`R1`", md)
        self.assertIn("tree_hash", md)
        self.assertIn("CLI implementation can import tree_hash directly", md)

    def test_handoff_save_and_load_roundtrip(self):
        """Verifies saving handoff packet to disk and reading it back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = pathlib.Path(tmpdir) / "handoff.json"
            save_handoff_packet(self.sample_handoff, target_path)
            self.assertTrue(target_path.exists())

            loaded = load_handoff_packet(target_path)
            self.assertEqual(loaded.handoff_id, self.sample_handoff.handoff_id)
            self.assertEqual(loaded.producer_task_id, self.sample_handoff.producer_task_id)
            self.assertEqual(loaded.changed_paths, sorted(self.sample_handoff.changed_paths))
            self.assertEqual(loaded.handoff_hash, self.sample_handoff.handoff_hash)

    def test_downstream_task_packet_includes_handoffs(self):
        """Verifies that downstream task packet automatically includes predecessor handoffs."""
        packet = self.compiler.compile_task_packet(
            goal_id="goal-test-v8",
            run_id="run-test-v8",
            task_id="task_cli_impl",
            attempt_id=1,
            task_def=self.sample_task_def,
            plan=self.sample_plan,
            goal_spec=self.sample_goal_spec,
            worktree_path=str(REPO_ROOT),
            allowed_paths=["treehash/cli.py"],
            dependencies=["task_core_impl"],
            handoffs=[self.sample_handoff],
        )

        # Downstream packet referenced_files should include producer's changed paths
        self.assertIn("treehash/core.py", packet.referenced_files)
        # Dynamic tail should render predecessor handoff section
        self.assertIn("Predecessor Task Handoffs", packet.rendered_tail)
        self.assertIn("task_core_impl", packet.rendered_tail)

    def test_retry_context_bounded(self):
        """Verifies retry context provides actionable failure guidance without history bloat."""
        retry_info = {
            "attempt": 1,
            "failure_reason": "Deterministic validation tests failed with exit code 1",
            "error_summary": "AssertionError: tree_hash() output did not match expected hex digest",
        }

        packet = self.compiler.compile_task_packet(
            goal_id="goal-test-v8",
            run_id="run-test-v8",
            task_id="task_core_impl",
            attempt_id=2,
            task_def=self.sample_task_def,
            plan=self.sample_plan,
            goal_spec=self.sample_goal_spec,
            worktree_path=str(REPO_ROOT),
            allowed_paths=["treehash/core.py"],
            dependencies=[],
            handoffs=[],
            retry_info=retry_info,
        )

        self.assertIn("Previous Attempt Failure Guidance", packet.rendered_tail)
        self.assertIn("AssertionError", packet.rendered_tail)
        self.assertIn("Attempt #2", packet.rendered_tail)
        # Verify budget is preserved (< 12KB)
        self.assertLess(packet.packet_bytes, 12000)


if __name__ == "__main__":
    unittest.main()
