#!/usr/bin/env python3
"""
Unit tests for Factory v7.0.0 ProjectContext, Target-Project Support, and Host Isolation.
"""

import os
import shutil
import subprocess
import tempfile
import pathlib
import unittest

from tools.factory import (
    FACTORY_ROOT,
    ProjectContext,
    set_project_context,
    get_project_context
)


class TestV7ProjectContextAndIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="factory-v7-context-test-"))
        self.orig_ctx = get_project_context()

    def tearDown(self):
        set_project_context(self.orig_ctx)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _init_git_repo(self, repo_dir: pathlib.Path):
        subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@factory.local"], cwd=str(repo_dir), check=True)
        subprocess.run(["git", "config", "user.name", "Factory Test"], cwd=str(repo_dir), check=True)
        readme = repo_dir / "README.md"
        readme.write_text("# Test Repo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=str(repo_dir), check=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo_dir), check=True)

    def test_default_context_points_to_factory_root_or_cwd(self):
        ctx = ProjectContext()
        self.assertEqual(ctx.factory_root, FACTORY_ROOT)
        self.assertTrue(ctx.project_root.exists())

    def test_explicit_project_root_context(self):
        target = self.tmp_dir / "my-target-project"
        target.mkdir()
        ctx = ProjectContext(target)
        self.assertEqual(ctx.project_root, target.resolve())
        self.assertEqual(ctx.runtime_root, target.resolve() / ".agy-factory")
        self.assertEqual(ctx.project_policy_path, target.resolve() / "factory.project.json")
        self.assertEqual(ctx.factory_root, FACTORY_ROOT)

    def test_set_and_get_project_context(self):
        target = self.tmp_dir / "target_b"
        target.mkdir()
        ctx = ProjectContext(target)
        set_project_context(ctx)
        curr = get_project_context()
        self.assertEqual(curr.project_root, target.resolve())

    def test_ensure_clean_git_rejects_non_git_repo(self):
        non_git = self.tmp_dir / "not_a_repo"
        non_git.mkdir()
        ctx = ProjectContext(non_git)
        with self.assertRaises(RuntimeError) as cm:
            ctx.ensure_clean_git()
        self.assertIn("not a valid Git repository", str(cm.exception))

    def test_ensure_clean_git_accepts_clean_repo(self):
        repo = self.tmp_dir / "clean_repo"
        repo.mkdir()
        self._init_git_repo(repo)
        ctx = ProjectContext(repo)
        res = ctx.ensure_clean_git()
        self.assertTrue(res["clean"])
        self.assertTrue(len(res["head_commit"]) >= 7)

    def test_ensure_clean_git_rejects_dirty_repo(self):
        repo = self.tmp_dir / "dirty_repo"
        repo.mkdir()
        self._init_git_repo(repo)
        dirty_file = repo / "dirty.txt"
        dirty_file.write_text("uncommitted work", encoding="utf-8")
        ctx = ProjectContext(repo)
        with self.assertRaises(RuntimeError) as cm:
            ctx.ensure_clean_git()
        self.assertIn("is dirty", str(cm.exception))

    def test_ensure_clean_git_ignores_agy_factory_runtime_dir(self):
        repo = self.tmp_dir / "repo_with_runtime"
        repo.mkdir()
        self._init_git_repo(repo)
        runtime_file = repo / ".agy-factory" / "runs" / "test.json"
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_text("{}", encoding="utf-8")
        ctx = ProjectContext(repo)
        res = ctx.ensure_clean_git()
        self.assertTrue(res["clean"])


if __name__ == "__main__":
    unittest.main()
