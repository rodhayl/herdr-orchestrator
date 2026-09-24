#!/usr/bin/env python3
"""
Unit tests for Factory v7.0.0 ProjectPolicy and project diagnostics.
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from tools.factory import (
    ProjectPolicy,
    run_project_doctor
)


class TestV7ProjectPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="factory-v7-policy-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _init_git(self, repo_dir: pathlib.Path):
        subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(repo_dir), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo_dir), check=True)
        (repo_dir / "init.txt").write_text("init\n", encoding="utf-8")
        subprocess.run(["git", "add", "init.txt"], cwd=str(repo_dir), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo_dir), check=True)

    def test_init_starter_creates_valid_policy(self):
        policy_file = ProjectPolicy.init_starter(self.tmp_dir, "CustomProject")
        self.assertTrue(policy_file.exists())
        with open(policy_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["project_name"], "CustomProject")
        self.assertEqual(data["version"], "7.0.0")
        self.assertIn("limits", data)
        self.assertIn("execution_policy", data)
        self.assertIn("routing_overrides", data)

    def test_load_and_validate_policy(self):
        policy_file = ProjectPolicy.init_starter(self.tmp_dir, "ValidProject")
        policy = ProjectPolicy.load(policy_file)
        errs = policy.validate()
        self.assertEqual(errs, [])
        self.assertEqual(policy.limits["max_tasks"], 12)
        self.assertEqual(policy.execution_policy["mode"], "real_only")

    def test_validate_rejects_negative_limits(self):
        bad_policy = {
            "project_name": "BadProject",
            "version": "7.0.0",
            "limits": {"max_tasks": -5}
        }
        policy = ProjectPolicy(bad_policy, self.tmp_dir)
        errs = policy.validate()
        self.assertTrue(any("max_tasks" in e for e in errs))

    def test_path_permission_checks(self):
        data = {
            "project_name": "PathProject",
            "version": "7.0.0",
            "allowed_paths": ["src/**", "tests/**"],
            "forbidden_paths": [".git/**", "secrets/**"]
        }
        policy = ProjectPolicy(data, self.tmp_dir)
        self.assertTrue(policy.is_path_permitted("src/main.py"))
        self.assertTrue(policy.is_path_permitted("tests/test_main.py"))
        self.assertFalse(policy.is_path_permitted(".git/config"))
        self.assertFalse(policy.is_path_permitted("secrets/key.pem"))
        self.assertFalse(policy.is_path_permitted("other/file.py"))

    def test_run_project_doctor(self):
        self._init_git(self.tmp_dir)
        # Doctor before init should fail
        doc1 = run_project_doctor(self.tmp_dir)
        self.assertFalse(doc1["valid"])
        self.assertFalse(doc1["policy_valid"])

        # Doctor after init should pass
        ProjectPolicy.init_starter(self.tmp_dir)
        # Commit policy file so git is clean
        subprocess.run(["git", "add", "factory.project.json"], cwd=str(self.tmp_dir), check=True)
        subprocess.run(["git", "commit", "-m", "add policy"], cwd=str(self.tmp_dir), check=True)

        doc2 = run_project_doctor(self.tmp_dir)
        self.assertTrue(doc2["valid"])
        self.assertTrue(doc2["policy_valid"])
        self.assertTrue(doc2["git_status"]["clean"])


if __name__ == "__main__":
    unittest.main()
