<USER_REQUEST>
You are the Project Autopilot Independent Final Auditor.
Audit the codebase against the Goal Specification:

=== GOAL SPECIFICATION ===
{
  "goal_id": "goal-20260924-100806",
  "title": "TreeHash \u2014 Deterministic Merkle Directory Hashing Utility",
  "raw_goal": "# TreeHash \u2014 Deterministic Merkle Directory Hashing Utility\n\nBuild a deterministic cryptographic directory and Merkle tree hashing utility and Python library using Python 3 standard library only.\n\n## Requirements\n\n1. R1: Content SHA-256 Hashing \u2014 Deterministic file content SHA-256 hashing.\n2. R2: Merkle Node Hashing \u2014 Directory Merkle node hashing using sorted child entries: hash(sorted(name + \":\" + child_hash)).\n3. R3: Empty Directory Handling \u2014 Empty directories must have a deterministic canonical empty-node hash.\n4. R4: Symlink Handling \u2014 Configurable symlink behavior (--follow-symlinks vs default --no-follow-symlinks).\n5. R5: Ignore Patterns \u2014 Automatically ignore .git, __pycache__, *.pyc, and optional .treehashignore patterns.\n6. R6: Lexicographical Ordering \u2014 Deterministic canonical lexicographical path sorting regardless of filesystem traversal order.\n7. R7: CLI Compute \u2014 CLI command `treehash compute <path>` (or `python3 -m treehash compute <path>`) computes and prints the root tree hash.\n8. R8: CLI Formatting \u2014 Output formats: `--format text` (default, printing root hash) and `--format json` (full Merkle manifest).\n9. R9: CLI Verify \u2014 CLI command `treehash verify <path> <manifest.json>` verifying an existing directory against a manifest (exit code 0 on match, 1 on mismatch).\n10. R10: Python Library API \u2014 Python library module exporting `compute_tree_hash(path, ...)` and `verify_tree_hash(path, manifest, ...)`.\n11. R11: Error Handling \u2014 Clean error handling, reporting errors to stderr and exiting with non-zero exit codes on missing paths or errors.\n12. R12: Unit Test Suite \u2014 Comprehensive deterministic test suite in `tests/` passing 100% under `python3 -m unittest discover -s tests -v`.\n\n## Constraints & Policy\n\nConstraints: Python 3 standard library only (hashlib, os, sys, pathlib, argparse, json, unittest).\nNon-goals: Do not use external packages, pip dependencies, or remote network operations.\n",
  "user_explicit_criteria": [
    "R1: Content SHA-256 Hashing \u2014 Deterministic file content SHA-256 hashing.",
    "R2: Merkle Node Hashing \u2014 Directory Merkle node hashing using sorted child entries: hash(sorted(name + \":\" + child_hash)).",
    "R3: Empty Directory Handling \u2014 Empty directories must have a deterministic canonical empty-node hash.",
    "R4: Symlink Handling \u2014 Configurable symlink behavior (--follow-symlinks vs default --no-follow-symlinks).",
    "R5: Ignore Patterns \u2014 Automatically ignore .git, __pycache__, *.pyc, and optional .treehashignore patterns.",
    "R6: Lexicographical Ordering \u2014 Deterministic canonical lexicographical path sorting regardless of filesystem traversal order.",
    "R7: CLI Compute \u2014 CLI command `treehash compute <path>` (or `python3 -m treehash compute <path>`) computes and prints the root tree hash.",
    "R8: CLI Formatting \u2014 Output formats: `--format text` (default, printing root hash) and `--format json` (full Merkle manifest).",
    "R9: CLI Verify \u2014 CLI command `treehash verify <path> <manifest.json>` verifying an existing directory against a manifest (exit code 0 on match, 1 on mismatch).",
    "R10: Python Library API \u2014 Python library module exporting `compute_tree_hash(path, ...)` and `verify_tree_hash(path, manifest, ...)`.",
    "R11: Error Handling \u2014 Clean error handling, reporting errors to stderr and exiting with non-zero exit codes on missing paths or errors.",
    "R12: Unit Test Suite \u2014 Comprehensive deterministic test suite in `tests/` passing 100% under `python3 -m unittest discover -s tests -v`."
  ],
  "derived_criteria": [
    "Deterministic post-execution verification test suite passing 100%",
    "Robust CLI error handling, non-zero exit codes on failure, and stdin/stdout contracts"
  ],
  "non_goals": [
    "Non-goals: Do not use external packages, pip dependencies, or remote network operations."
  ],
  "constraints": [],
  "acceptance_criteria": [
    {
      "id": "R1",
      "title": "R1",
      "description": "Content SHA-256 Hashing \u2014 Deterministic file content SHA-256 hashing.",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R2",
      "title": "R2",
      "description": "Merkle Node Hashing \u2014 Directory Merkle node hashing using sorted child entries: hash(sorted(name + \":\" + child_hash)).",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R3",
      "title": "R3",
      "description": "Empty Directory Handling \u2014 Empty directories must have a deterministic canonical empty-node hash.",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R4",
      "title": "R4",
      "description": "Symlink Handling \u2014 Configurable symlink behavior (--follow-symlinks vs default --no-follow-symlinks).",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R5",
      "title": "R5",
      "description": "Ignore Patterns \u2014 Automatically ignore .git, __pycache__, *.pyc, and optional .treehashignore patterns.",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R6",
      "title": "R6",
      "description": "Lexicographical Ordering \u2014 Deterministic canonical lexicographical path sorting regardless of filesystem traversal order.",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R7",
      "title": "R7",
      "description": "CLI Compute \u2014 CLI command `treehash compute <path>` (or `python3 -m treehash compute <path>`) computes and prints the root tree hash.",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R8",
      "title": "R8",
      "description": "CLI Formatting \u2014 Output formats: `--format text` (default, printing root hash) and `--format json` (full Merkle manifest).",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R9",
      "title": "R9",
      "description": "CLI Verify \u2014 CLI command `treehash verify <path> <manifest.json>` verifying an existing directory against a manifest (exit code 0 on match, 1 on mismatch).",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R10",
      "title": "R10",
      "description": "Python Library API \u2014 Python library module exporting `compute_tree_hash(path, ...)` and `verify_tree_hash(path, manifest, ...)`.",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R11",
      "title": "R11",
      "description": "Error Handling \u2014 Clean error handling, reporting errors to stderr and exiting with non-zero exit codes on missing paths or errors.",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R12",
      "title": "R12",
      "description": "Unit Test Suite \u2014 Comprehensive deterministic test suite in `tests/` passing 100% under `python3 -m unittest discover -s tests -v`.",
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "R13",
      "title": "Deterministic Unit and Integration Tests",
      "description": "Comprehensive test suite under tests/ verifying all requirements deterministically",
      "provenance": "DERIVED"
    },
    {
      "id": "R14",
      "title": "Clean CLI and Error Handling",
      "description": "Standard error messaging, proper exit codes, and robust argument parsing",
      "provenance": "DERIVED"
    }
  ],
  "created_at": "2026-09-24T10:08:09.334981+00:00"
}

=== RECENT GIT DIFF ===
diff --git a/tests/test_core.py b/tests/test_core.py
index cc600c3..16b7193 100644
--- a/tests/test_core.py
+++ b/tests/test_core.py
@@ -6,6 +6,7 @@ import shutil
 import tempfile
 import unittest
 from pathlib import Path
+from unittest.mock import patch
 
 from treehash import (
     DEFAULT_IGNORE_PATTERNS,
@@ -15,6 +16,7 @@ from treehash import (
     PathNotFoundError,
     SymlinkCycleError,
     TreeHashError,
+    build_merkle_tree,
     compute_file_hash,
     compute_manifest,
     compute_symlink_hash,
@@ -22,6 +24,7 @@ from treehash import (
     verify_tree_hash,
     verify_tree_manifest_detailed,
 )
+from treehash.core import is_ignored, load_ignore_file
 
 
 class TestTreeHashCore(unittest.TestCase):
@@ -299,6 +302,100 @@ class TestTreeHashCore(unittest.TestCase):
             # Missing root_hash and hash fields
             verify_tree_hash(self.test_dir, {"invalid": "manifest"})
 
+    def test_compute_file_hash_missing_file(self):
+        missing = self.test_dir / "missing.txt"
+        with self.assertRaises(PathNotFoundError):
+            compute_file_hash(missing)
+
+    def test_compute_file_hash_oserror(self):
+        existing = self.test_dir / "error.txt"
+        existing.write_text("hello", encoding="utf-8")
+        with patch("builtins.open", side_effect=OSError("Read error")):
+            with self.assertRaises(TreeHashError):
+                compute_file_hash(existing)
+
+    def test_compute_symlink_hash_missing_symlink(self):
+        missing_link = self.test_dir / "nonexistent_symlink"
+        with self.assertRaises(TreeHashError):
+            compute_symlink_hash(missing_link)
+
+    def test_load_ignore_file_missing(self):
+        missing = self.test_dir / ".nonexistent_ignore"
+        self.assertEqual(load_ignore_file(missing), [])
+
+    def test_load_ignore_file_parsing(self):
+        ignore_file = self.test_dir / ".customignore"
+        ignore_file.write_text(
+            "# A comment\n"
+            "\n"
+            "pattern1\n"
+            "  pattern2  \n"
+            "# Another comment\n",
+            encoding="utf-8",
+        )
+        patterns = load_ignore_file(ignore_file)
+        self.assertEqual(patterns, ["pattern1", "pattern2"])
+
+    def test_load_ignore_file_oserror(self):
+        ignore_file = self.test_dir / ".errorignore"
+        ignore_file.write_text("pattern", encoding="utf-8")
+        with patch("builtins.open", side_effect=OSError("Disk failure")):
+            with self.assertRaises(TreeHashError):
+                load_ignore_file(ignore_file)
+
+    def test_is_ignored_rules(self):
+        patterns = ["*.pyc", "build/", "a/b/secret.key", "temp*"]
+        self.assertTrue(is_ignored("test.pyc", "test.pyc", False, patterns))
+        self.assertTrue(is_ignored("build", "build", True, patterns))
+        self.assertFalse(is_ignored("build", "build", False, patterns))  # dir_only pattern on a file
+        self.assertTrue(is_ignored("secret.key", "a/b/secret.key", False, patterns))
+        self.assertTrue(is_ignored("tempfile.txt", "tempfile.txt", False, patterns))
+        self.assertFalse(is_ignored("regular.txt", "regular.txt", False, patterns))
+
+    def test_merkle_node_to_dict_and_get_entries(self):
+        leaf = MerkleNode(name="file.txt", path="sub/file.txt", node_type="file", hash="h1", size=42)
+        sym = MerkleNode(name="link.txt", path="sub/link.txt", node_type="symlink", hash="h2", target="file.txt")
+        sub = MerkleNode(name="sub", path="sub", node_type="directory", hash="h3", children=[leaf, sym])
+        root = MerkleNode(name=".", path=".", node_type="directory", hash="hroot", children=[sub])
+
+        d = root.to_dict()
+        self.assertEqual(d["name"], ".")
+        self.assertEqual(d["path"], ".")
+        self.assertEqual(d["type"], "directory")
+        self.assertEqual(len(d["children"]), 1)
+        sub_dict = d["children"][0]
+        self.assertEqual(sub_dict["name"], "sub")
+        self.assertEqual(len(sub_dict["children"]), 2)
+        self.assertEqual(sub_dict["children"][0]["size"], 42)
+        self.assertEqual(sub_dict["children"][1]["target"], "file.txt")
+
+        entries = root.get_entries()
+        self.assertEqual(entries["sub"], "h3")
+        self.assertEqual(entries["sub/file.txt"], "h1")
+        self.assertEqual(entries["sub/link.txt"], "h2")
+        self.assertNotIn(".", entries)
+
+    def test_build_merkle_tree_root_is_symlink(self):
+        target = self.test_dir / "target.txt"
+        target.write_text("hello", encoding="utf-8")
+        link = self.test_dir / "root_link"
+        link.symlink_to("target.txt")
+
+        node = build_merkle_tree(link, follow_symlinks=False)
+        self.assertEqual(node.node_type, "symlink")
+        self.assertEqual(node.target, "target.txt")
+        self.assertEqual(node.path, ".")
+
+    def test_build_merkle_tree_dir_stat_error(self):
+        with patch("os.stat", side_effect=OSError("Permission denied")):
+            with self.assertRaises(TreeHashError):
+                build_merkle_tree(self.test_dir)
+
+    def test_build_merkle_tree_dir_listdir_error(self):
+        with patch("os.listdir", side_effect=OSError("Read error")):
+            with self.assertRaises(TreeHashError):
+                build_merkle_tree(self.test_dir)
+
 
 if __name__ == "__main__":
     unittest.main()
diff --git a/tests/test_hasher.py b/tests/test_hasher.py
new file mode 100644
index 0000000..2249c96
--- /dev/null
+++ b/tests/test_hasher.py
@@ -0,0 +1,256 @@
+"""Unit tests for treehash.hasher module."""
+
+import hashlib
+import json
+import os
+import tempfile
+import unittest
+from pathlib import Path
+from unittest.mock import mock_open, patch
+
+from treehash.exceptions import (
+    InvalidManifestError,
+    PathNotFoundError,
+    TreeHashError,
+    VerificationError,
+)
+from treehash.hasher import (
+    VerificationResult,
+    compute_manifest,
+    compute_tree_hash,
+    parse_manifest,
+    verify_tree_hash,
+    verify_tree_manifest_detailed,
+)
+
+
+class TestHasher(unittest.TestCase):
+    """Test suite covering high-level hasher APIs and manifest parsing/verification."""
+
+    def setUp(self):
+        self.temp_dir = tempfile.TemporaryDirectory()
+        self.test_dir = Path(self.temp_dir.name)
+
+    def tearDown(self):
+        self.temp_dir.cleanup()
+
+    def test_verification_result_truthiness(self):
+        res_ok = VerificationResult(
+            is_valid=True,
+            expected_hash="a" * 64,
+            computed_hash="a" * 64,
+            mismatched_entries=[],
+            missing_entries=[],
+            extra_entries=[],
+        )
+        self.assertTrue(bool(res_ok))
+
+        res_fail = VerificationResult(
+            is_valid=False,
+            expected_hash="a" * 64,
+            computed_hash="b" * 64,
+            mismatched_entries=["file.txt"],
+            missing_entries=[],
+            extra_entries=[],
+        )
+        self.assertFalse(bool(res_fail))
+
+    def test_parse_manifest_from_dict(self):
+        data = {"root_hash": "a" * 64, "entries": {}}
+        parsed = parse_manifest(data)
+        self.assertEqual(parsed, data)
+
+    def test_parse_manifest_from_json_file(self):
+        manifest_file = self.test_dir / "manifest.json"
+        data = {"root_hash": "b" * 64, "algorithm": "sha256"}
+        manifest_file.write_text(json.dumps(data), encoding="utf-8")
+
+        parsed = parse_manifest(manifest_file)
+        self.assertEqual(parsed["root_hash"], "b" * 64)
+
+    def test_parse_manifest_from_raw_hash_file(self):
+        hash_file = self.test_dir / "root.hash"
+        expected = "c" * 64
+        hash_file.write_text(f"  {expected}\n", encoding="utf-8")
+
+        parsed = parse_manifest(hash_file)
+        self.assertEqual(parsed["root_hash"], expected)
+        self.assertEqual(parsed["hash"], expected)
+
+    def test_parse_manifest_from_json_string_quoted_hash_file(self):
+        manifes

Verify whether all criteria are correctly implemented, cleanly tested, and safe.
Output ONLY a JSON object:
{
  "verdict": "ACCEPTED" | "REMEDIATION_REQUIRED",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "area": "...",
      "evidence": "...",
      "recommendation": "..."
    }
  ]
}

</USER_REQUEST>
<ADDITIONAL_METADATA>
The current local time is: 2026-09-24T12:19:42+02:00.
</ADDITIONAL_METADATA>
<USER_SETTINGS_CHANGE>
The user changed setting `Model Selection` from None to Claude Sonnet 4.6 (Thinking). No need to comment on this change if the user doesn't ask about it. If reporting what model you are, please use a human readable name instead of the exact string.
</USER_SETTINGS_CHANGE>