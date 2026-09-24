#!/usr/bin/env python3
"""
factory_tests/test_v8_malformed_and_edge_cases.py

Validates FACTORY v8.0.0 handling of malformed schemas, corrupted packets,
binary files, path traversals, large file limits, and atomic crash recovery.
"""

import json
import pathlib
import tempfile
import unittest

from tools.context import (
    Anchor,
    ContextError,
    MalformedContextPacketError,
    load_context_packet,
    load_handoff_packet,
    save_context_packet,
    FilesystemGitContextSource,
    ContextCompiler,
    ContextPolicy,
    DEFAULT_CONTEXT_POLICY,
    sha256_text,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestV8MalformedAndEdgeCases(unittest.TestCase):
    def setUp(self):
        self.policy = ContextPolicy(DEFAULT_CONTEXT_POLICY)
        self.source = FilesystemGitContextSource(REPO_ROOT)
        self.compiler = ContextCompiler(self.policy, self.source)

    def test_load_corrupted_json_packet_raises_malformed(self):
        """Verifies loading invalid JSON raises MalformedContextPacketError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_json = pathlib.Path(tmpdir) / "corrupt.json"
            bad_json.write_text("{ incomplete json: true,", encoding="utf-8")

            with self.assertRaises(MalformedContextPacketError):
                load_context_packet(bad_json)

    def test_load_missing_required_fields_raises_malformed(self):
        """Verifies loading packet missing required schema fields raises MalformedContextPacketError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_pkt = pathlib.Path(tmpdir) / "missing_fields.json"
            bad_pkt.write_text(json.dumps({"some_random_field": "hello"}), encoding="utf-8")

            with self.assertRaises(MalformedContextPacketError):
                load_context_packet(bad_pkt)

    def test_load_corrupted_handoff_raises_malformed(self):
        """Verifies loading corrupted handoff packet raises MalformedContextPacketError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_ho = pathlib.Path(tmpdir) / "corrupt_handoff.json"
            bad_ho.write_text("NOT_JSON_AT_ALL", encoding="utf-8")

            with self.assertRaises(MalformedContextPacketError):
                load_handoff_packet(bad_ho)

    def test_invalid_anchor_type_raises_malformed(self):
        """Verifies Anchor rejects invalid anchor types."""
        with self.assertRaises(MalformedContextPacketError):
            Anchor(
                anchor_id="anchor_1",
                anchor_type="INVALID_TYPE",
                source="goal_spec",
                source_hash=sha256_text("content"),
                content="test",
            )

    def test_empty_anchor_id_or_source_raises_malformed(self):
        """Verifies Anchor rejects empty anchor_id or source."""
        with self.assertRaises(MalformedContextPacketError):
            Anchor(
                anchor_id="",
                anchor_type="requirement",
                source="goal_spec",
                source_hash="hash",
                content="content",
            )

        with self.assertRaises(MalformedContextPacketError):
            Anchor(
                anchor_id="req:1",
                anchor_type="requirement",
                source="",
                source_hash="hash",
                content="content",
            )

    def test_binary_file_detection_in_context_source(self):
        """Verifies that binary files (containing null bytes) are detected and not inlined as code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            t_root = pathlib.Path(tmpdir)
            bin_file = t_root / "sample.bin"
            bin_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe\x00\x00DATA")

            source = FilesystemGitContextSource(t_root)
            text, truncated, fhash = source.read_file_excerpt("sample.bin", max_bytes=100)

            self.assertIn("[BINARY FILE", text)
            self.assertFalse(truncated)
            self.assertEqual(len(fhash), 64)

    def test_file_traversal_escapes_project_root_raises(self):
        """Verifies that requesting paths escaping project root raises ContextError."""
        with self.assertRaises(ContextError) as ctx:
            self.source._resolve_safe_path("../../../etc/passwd")
        self.assertIn("Path traversal detected", str(ctx.exception))

    def test_atomic_packet_persistence_crash_safety(self):
        """Verifies save_context_packet safely writes via temporary file and atomic replace."""
        sample_task_def = {
            "task_id": "task_atomic_test",
            "title": "Atomic Persistence Test",
            "requirements": ["R1"],
            "allowed_paths": ["src/app.py"],
            "validations": [["python3 -m unittest"]],
        }
        sample_goal_spec = {
            "goal_id": "goal-atomic-test",
            "acceptance_criteria": [
                {"id": "R1", "provenance": "USER_EXPLICIT", "description": "Support SHA256"}
            ],
        }
        packet = self.compiler.compile_task_packet(
            goal_id="goal-atomic-test",
            run_id="run-atomic-test",
            task_id="task_atomic_test",
            attempt_id=1,
            task_def=sample_task_def,
            plan={"tasks": [sample_task_def]},
            goal_spec=sample_goal_spec,
            worktree_path=str(REPO_ROOT),
            allowed_paths=["src/app.py"],
            dependencies=[],
            handoffs=[],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            target_file = pathlib.Path(tmpdir) / "packet.json"
            saved_path = save_context_packet(packet, target_file)
            self.assertTrue(saved_path.exists())

            # No dangling temp files
            tmp_files = list(pathlib.Path(tmpdir).glob("*.tmp.*"))
            self.assertEqual(len(tmp_files), 0)

            loaded = load_context_packet(target_file)
            self.assertEqual(loaded.packet_id, packet.packet_id)

    def test_large_file_inlining_bounded(self):
        """Verifies that files larger than max_bytes are bounded and marked truncated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            t_root = pathlib.Path(tmpdir)
            large_file = t_root / "large.txt"
            large_file.write_text("A" * 5000, encoding="utf-8")

            source = FilesystemGitContextSource(t_root)
            text, truncated, fhash = source.read_file_excerpt("large.txt", max_bytes=1000)

            self.assertTrue(truncated)
            self.assertEqual(len(text.encode("utf-8")), 1000)
            self.assertEqual(len(fhash), 64)


if __name__ == "__main__":
    unittest.main()
