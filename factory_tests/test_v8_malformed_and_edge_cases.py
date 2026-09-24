#!/usr/bin/env python3
"""
factory_tests/test_v8_malformed_and_edge_cases.py

Validates FACTORY v8.0.0 handling of malformed schemas, corrupted packets,
binary files, path traversals, large file limits, and atomic crash recovery.
"""

import json
import pathlib
import re
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
    StablePrefixManager,
    calculate_context_redundancy,
    calculate_rendered_anchor_recall,
    HandoffPacket,
    canonical_json_dump,
    sha256_text,
    redact_secrets,
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

    def test_context_policy_corrupted_file_raises(self):
        """Verifies that an unreadable or corrupt policy file raises ContextError rather than falling back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_policy = pathlib.Path(tmpdir) / "corrupt_policy.json"
            bad_policy.write_text("{invalid json", encoding="utf-8")
            with self.assertRaises(ContextError) as ctx:
                ContextPolicy.load(bad_policy)
            self.assertIn("Failed to load context policy", str(ctx.exception))

    def test_context_policy_invalid_budget_override_raises(self):
        """Verifies that overriding hard budget below soft budget raises ContextError."""
        invalid_overrides = {
            "roles": {
                "task": {
                    "hard_budget_bytes": 1000,
                    "soft_budget_bytes": 2000,
                }
            }
        }
        with self.assertRaises(ContextError) as ctx:
            ContextPolicy(DEFAULT_CONTEXT_POLICY, project_overrides=invalid_overrides)
        self.assertIn("hard_budget_bytes (1000) < soft_budget_bytes (2000)", str(ctx.exception))

    def test_stable_prefix_unknown_role_raises(self):
        """Verifies that StablePrefixManager raises ContextError on unsupported or unknown role."""
        with self.assertRaises(ContextError) as ctx:
            StablePrefixManager.get_stable_prefix("nonexistent_role")
        self.assertIn("Unknown or unsupported role", str(ctx.exception))

    def test_stable_prefix_remediation_role(self):
        """Verifies that remediation role returns dedicated remediation contract prefix."""
        text, h, b = StablePrefixManager.get_stable_prefix("remediation")
        self.assertIn("Factory Remediation Worker Contract", text)
        self.assertEqual(len(h), 64)
        self.assertGreater(b, 0)

    def test_filesystem_git_sensitive_patterns_blocked(self):
        """Verifies that access to sensitive files (.env, .aws, .pem, id_rsa) raises ContextError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            t_root = pathlib.Path(tmpdir)
            env_file = t_root / ".env"
            env_file.write_text("SECRET=12345", encoding="utf-8")
            rsa_file = t_root / "id_rsa"
            rsa_file.write_text("PRIVATE KEY", encoding="utf-8")

            source = FilesystemGitContextSource(t_root)
            with self.assertRaises(ContextError):
                source.read_file_excerpt(".env")
            with self.assertRaises(ContextError):
                source.read_file_excerpt("id_rsa")

            inv = source.get_bounded_file_inventory()
            self.assertNotIn(".env", inv)
            self.assertNotIn("id_rsa", inv)

    def test_filesystem_git_diff_ref_injection_blocked(self):
        """Verifies that invalid or injected git refs raise ContextError."""
        with self.assertRaises(ContextError) as ctx:
            self.source.get_git_diff("--upload-pack=evil")
        self.assertIn("Invalid git base_commit ref", str(ctx.exception))

        with self.assertRaises(ContextError) as ctx:
            self.source.get_git_diff("HEAD; rm -rf /")
        self.assertIn("Invalid git base_commit ref", str(ctx.exception))

    def test_handoff_packet_exact_convergent_byte_count(self):
        """Verifies that handoff_bytes equals len(canonical_json_dump(hp.to_dict()).encode('utf-8')) exactly."""
        hp = HandoffPacket(
            handoff_id="ho-test-converge",
            producer_task_id="task_1",
            producer_attempt=1,
            changed_paths=["src/module.py"],
            satisfied_criteria=["R1"],
            decisions=["Decided to implement architecture X", "Selected approach Y"],
            known_risks=["Potential edge case Z"],
            consumer_notes="Downstream tasks should use module.py",
        )
        actual_bytes = len(canonical_json_dump(hp.to_dict()).encode("utf-8"))
        self.assertEqual(hp.handoff_bytes, actual_bytes)

    def test_calculate_context_redundancy_exact_sum(self):
        """Verifies that total_bytes == unique_bytes + repeated_bytes exactly."""
        texts = [
            "line alpha\nline beta\nline gamma\n",
            "line alpha\nline delta\nline beta\n",
            "line epsilon\nline zeta\n",
        ]
        res = calculate_context_redundancy(texts, chunk_size=16)
        self.assertEqual(
            res["total_factory_supplied_bytes"],
            res["unique_content_bytes"] + res["repeated_content_bytes"],
        )
        self.assertGreater(res["redundancy_ratio"], 0.0)

    def test_word_boundary_anchor_recall_prevents_false_substring_match(self):
        """Verifies word-boundary matching prevents false substring matches (e.g. 'pass' in 'compass')."""
        req_anchor = Anchor(
            anchor_id="crit:pass",
            anchor_type="requirement",
            source="spec",
            source_hash=sha256_text("pass"),
            content="pass",
            required=True,
        )
        # 'compass' contains 'pass' as a substring, but NOT as a word
        rendered_with_compass = "We will calibrate the compass for navigation."
        recall, missing = calculate_rendered_anchor_recall([req_anchor], rendered_with_compass)
        self.assertEqual(recall, 0.0)
        self.assertIn("crit:pass", missing)

        # Prompt with actual 'pass' word
        rendered_with_pass = "All validation tests must pass before dispatch."
        recall, missing = calculate_rendered_anchor_recall([req_anchor], rendered_with_pass)
        self.assertEqual(recall, 1.0)
        self.assertEqual(len(missing), 0)

    def test_path_boundary_anchor_recall_prevents_prefix_substring_match(self):
        """Verifies strict boundary matching prevents path prefix substring collisions (e.g. '/src' in '/src/core')."""
        path_anchor = Anchor(
            anchor_id="path:src",
            anchor_type="file_reference",
            source="spec",
            source_hash=sha256_text("/src"),
            content="/src",
            required=True,
        )
        rendered_with_subpath = "Inspect the /src/core/hasher.py file for implementation details."
        recall, missing = calculate_rendered_anchor_recall([path_anchor], rendered_with_subpath)
        self.assertEqual(recall, 0.0)
        self.assertIn("path:src", missing)

        rendered_with_exact = "Inspect the /src directory for implementation details."
        recall, missing = calculate_rendered_anchor_recall([path_anchor], rendered_with_exact)
        self.assertEqual(recall, 1.0)
        self.assertEqual(len(missing), 0)

    def test_redact_secrets_scans_dict_keys_and_broad_env_vars(self):
        """Verifies redact_secrets redacts secret keys in dictionaries and broad env vars."""
        d = {
            "sk-12345678901234567890": "valid_value",
            "normal_key": "Bearer my_secret_token_abcdef123456",
        }
        redacted = redact_secrets(d)
        self.assertNotIn("sk-12345678901234567890", redacted)
        self.assertIn("[REDACTED_SECRET]", redacted)
        self.assertEqual(redacted["[REDACTED_SECRET]"], "valid_value")

    def test_context_policy_non_integer_budget_override_raises(self):
        """Verifies that non-integer, negative, or boolean budget overrides raise ContextError."""
        policy = ContextPolicy.load()
        with self.assertRaises(ContextError) as ctx:
            policy.apply_project_overrides({"roles": {"task": {"soft_budget_bytes": "invalid"}}})
        self.assertIn("must be a positive integer", str(ctx.exception))

        with self.assertRaises(ContextError) as ctx:
            policy.apply_project_overrides({"roles": {"task": {"soft_budget_bytes": -100}}})
        self.assertIn("must be a positive integer", str(ctx.exception))

        with self.assertRaises(ContextError) as ctx:
            policy.apply_project_overrides({"roles": {"task": {"soft_budget_bytes": True}}})
        self.assertIn("must be a positive integer", str(ctx.exception))

    def test_handoff_packet_multi_field_proportional_bounding(self):
        """Verifies that all 4 free-text fields are proportionally bounded within max_bytes."""
        hp = HandoffPacket(
            handoff_id="ho-test-multi",
            producer_task_id="task_1",
            producer_attempt=1,
            changed_paths=["src/a.py"],
            satisfied_criteria=["R1"],
            contracts="C" * 2000,
            decisions="D" * 2000,
            consumer_notes="N" * 2000,
            known_risks="K" * 2000,
        )
        total_ft = (
            len(hp.contracts.encode("utf-8"))
            + len(hp.decisions.encode("utf-8"))
            + len(hp.consumer_notes.encode("utf-8"))
            + len(hp.known_risks.encode("utf-8"))
        )
        self.assertLessEqual(total_ft, 4096)
        self.assertLessEqual(hp.handoff_bytes, 4096)

    def test_filesystem_git_symbolic_refs_allowed(self):
        """Verifies symbolic refs like HEAD~1, HEAD^, main are allowed by VALID_REF_PATTERN."""
        source = FilesystemGitContextSource(REPO_ROOT)
        # Should not raise ContextError on valid symbolic ref syntax
        c = source.get_git_commit("HEAD~1")
        self.assertTrue(re.match(r"^[a-f0-9]{40}$", c))


if __name__ == "__main__":
    unittest.main()
