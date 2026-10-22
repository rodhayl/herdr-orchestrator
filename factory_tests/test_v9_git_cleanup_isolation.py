#!/usr/bin/env python3
"""
Acceptance and regression tests for ownership-aware Git state cleanup and isolation.

Validates that:
A. Pre-existing worktree survives cleanup byte-for-byte.
B. Test-created worktree inside expected worktree root is removed.
C. Pre-existing factory/run-* branch survives cleanup.
D. Newly created test branch is removed.
E. Pre-existing tracked file modifications survive cleanup (restores exact pre-test state, not HEAD).
"""

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from factory_tests.git_isolation import GitStateSnapshot


class TestGitCleanupIsolation(unittest.TestCase):
    """Deterministic regression suite proving ownership-aware cleanup."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="git-isolation-test-")
        self.repo_dir = pathlib.Path(self.temp_dir.name) / "test_repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.worktree_root = self.repo_dir / ".agy-factory" / "worktrees"
        self.worktree_root.mkdir(parents=True, exist_ok=True)

        # Initialize test repository
        subprocess.run(["git", "init", "-b", "main"], cwd=str(self.repo_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@git-isolation.local"], cwd=str(self.repo_dir), check=True)
        subprocess.run(["git", "config", "user.name", "Isolation Test"], cwd=str(self.repo_dir), check=True)

        # Initial commit
        readme = self.repo_dir / "README.md"
        readme.write_text("# Test Repo\n", encoding="utf-8")
        tracked_file = self.repo_dir / ".agy-factory" / "state" / "owned-resources.json"
        tracked_file.parent.mkdir(parents=True, exist_ok=True)
        tracked_file.write_text('{"committed_head": "initial"}\n', encoding="utf-8")

        subprocess.run(["git", "add", "-A"], cwd=str(self.repo_dir), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(self.repo_dir), check=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_a_preexisting_worktree_survives(self):
        """A. Pre-existing worktree survives cleanup byte-for-byte."""
        sentinel_wt = self.repo_dir / "external_feature_worktree"
        sentinel_branch = "feature/pre-existing-work"
        subprocess.run(
            ["git", "worktree", "add", str(sentinel_wt), "-b", sentinel_branch],
            cwd=str(self.repo_dir),
            check=True,
            capture_output=True,
        )
        sentinel_file = sentinel_wt / "sentinel.txt"
        sentinel_file.write_text("precious user content that must never be deleted\n", encoding="utf-8")

        # Snapshot taken AFTER sentinel worktree exists
        snapshot = GitStateSnapshot(
            self.repo_dir,
            worktree_root=self.worktree_root,
        )

        # Run cleanup
        snapshot.cleanup()

        # Assert worktree, branch, and file still exist with identical content
        self.assertTrue(sentinel_wt.exists(), "Pre-existing worktree was unexpectedly deleted!")
        self.assertTrue(sentinel_file.exists(), "Pre-existing sentinel file was deleted!")
        self.assertEqual(
            sentinel_file.read_text(encoding="utf-8"),
            "precious user content that must never be deleted\n",
        )
        proc = subprocess.run(
            ["git", "branch", "--list", sentinel_branch],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
        )
        self.assertIn(sentinel_branch, proc.stdout, "Pre-existing worktree branch was deleted!")

    def test_b_test_created_worktree_is_removed(self):
        """B. Test-created worktree inside expected worktree root is removed."""
        # Snapshot taken BEFORE test worktree is created
        snapshot = GitStateSnapshot(
            self.repo_dir,
            worktree_root=self.worktree_root,
        )

        test_wt = self.worktree_root / "run-test-001" / "task_1" / "att-1"
        test_branch = "factory/run-test-001/task_1/att-1"
        subprocess.run(
            ["git", "worktree", "add", str(test_wt), "-b", test_branch],
            cwd=str(self.repo_dir),
            check=True,
            capture_output=True,
        )
        self.assertTrue(test_wt.exists())

        # Run cleanup
        snapshot.cleanup()

        # Assert test worktree is removed
        self.assertFalse(test_wt.exists(), "Test-created worktree was not removed!")
        proc = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
        )
        self.assertNotIn(str(test_wt), proc.stdout)

    def test_c_preexisting_factory_branch_survives(self):
        """C. Pre-existing factory/run-* branch survives cleanup."""
        preexisting_branch = "factory/run-legacy-incident-retained"
        subprocess.run(
            ["git", "branch", preexisting_branch],
            cwd=str(self.repo_dir),
            check=True,
            capture_output=True,
        )

        # Snapshot taken AFTER branch exists
        snapshot = GitStateSnapshot(
            self.repo_dir,
            worktree_root=self.worktree_root,
        )

        # Run cleanup
        snapshot.cleanup()

        # Assert branch still exists
        proc = subprocess.run(
            ["git", "branch", "--list", preexisting_branch],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
        )
        self.assertIn(preexisting_branch, proc.stdout, "Pre-existing factory/run-* branch was deleted!")

    def test_d_newly_created_test_branch_is_removed(self):
        """D. Newly created test branch is removed."""
        # Snapshot taken BEFORE test branch is created
        snapshot = GitStateSnapshot(
            self.repo_dir,
            worktree_root=self.worktree_root,
        )

        test_branch = "factory/run-20260928-new-task-branch"
        subprocess.run(
            ["git", "branch", test_branch],
            cwd=str(self.repo_dir),
            check=True,
            capture_output=True,
        )

        # Run cleanup
        snapshot.cleanup()

        # Assert branch is removed
        proc = subprocess.run(
            ["git", "branch", "--list", test_branch],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
        )
        self.assertNotIn(test_branch, proc.stdout, "Newly created test branch was not removed!")

    def test_e_preexisting_tracked_runtime_modification_survives(self):
        """E. Pre-existing tracked runtime modification survives cleanup (restores pre-test state, not HEAD)."""
        tracked_file = self.repo_dir / ".agy-factory" / "state" / "owned-resources.json"
        uncommitted_pre_test_content = '{"user_uncommitted_work": "must_preserve_123"}\n'
        tracked_file.write_text(uncommitted_pre_test_content, encoding="utf-8")

        nonexistent_before = self.repo_dir / ".agy-factory" / "logs" / "temp.log"

        # Snapshot taken when tracked_file has pre-existing uncommitted modifications
        # and nonexistent_before does not exist yet.
        snapshot = GitStateSnapshot(
            self.repo_dir,
            tracked_files=[tracked_file, nonexistent_before],
            worktree_root=self.worktree_root,
        )

        # Test modifies tracked_file further
        tracked_file.write_text('{"modified_by_test": "transient_data"}\n', encoding="utf-8")

        # Test creates nonexistent_before
        nonexistent_before.parent.mkdir(parents=True, exist_ok=True)
        nonexistent_before.write_text("created during test\n", encoding="utf-8")

        # Run cleanup
        snapshot.cleanup()

        # Assert:
        # 1. tracked_file was restored to uncommitted_pre_test_content, NOT HEAD!
        self.assertEqual(
            tracked_file.read_text(encoding="utf-8"),
            uncommitted_pre_test_content,
            "Cleanup failed to restore exact pre-test user modifications!",
        )
        # 2. nonexistent_before was removed
        self.assertFalse(
            nonexistent_before.exists(),
            "File created during test was not removed!",
        )

    def test_f_failed_worktree_snapshot_fails_closed(self):
        """F. Failed initial worktree discovery fails closed and raises immediately."""
        non_git_dir = pathlib.Path(self.temp_dir.name) / "non_git_dir"
        non_git_dir.mkdir(parents=True, exist_ok=True)
        # 1. Non-git directory fails closed on init
        with self.assertRaises(subprocess.CalledProcessError):
            GitStateSnapshot(non_git_dir)

        # 2. Simulated git failure inside valid repo also raises and never proceeds with empty snapshot
        orig_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0:3] == ["git", "worktree", "list"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="simulated git worktree list failure")
            return orig_run(cmd, *args, **kwargs)

        with mock.patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(subprocess.CalledProcessError):
                GitStateSnapshot(self.repo_dir, worktree_root=self.worktree_root)

    def test_g_failed_branch_snapshot_fails_closed(self):
        """G. Failed branch discovery fails closed on init and during cleanup."""
        orig_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0:3] == ["git", "branch", "--list"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="simulated git branch list failure")
            return orig_run(cmd, *args, **kwargs)

        # 1. Fails closed during initial snapshot
        with mock.patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(subprocess.CalledProcessError):
                GitStateSnapshot(self.repo_dir, worktree_root=self.worktree_root)

        # 2. Fails closed during cleanup discovery (never deletes blindly from unknown state)
        snapshot = GitStateSnapshot(self.repo_dir, worktree_root=self.worktree_root)
        with mock.patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(subprocess.CalledProcessError):
                snapshot.cleanup_branches()

    def test_h_no_global_prune_of_preexisting_stale_worktree_metadata(self):
        """H. Pre-existing stale worktree metadata is preserved and never pruned by cleanup()."""
        stale_wt = pathlib.Path(self.temp_dir.name) / "stale_external_worktree"
        stale_branch = "feature/stale-external-work"
        subprocess.run(
            ["git", "worktree", "add", str(stale_wt), "-b", stale_branch],
            cwd=str(self.repo_dir),
            check=True,
            capture_output=True,
        )
        # Simulate stale worktree by removing directory on disk without git worktree remove
        shutil.rmtree(stale_wt)
        self.assertFalse(stale_wt.exists())

        # Verify git worktree list still tracks the stale worktree entry
        proc_before = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(self.repo_dir),
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn(str(stale_wt), proc_before.stdout)

        # Take snapshot (stale_wt is in orig_worktrees)
        snapshot = GitStateSnapshot(self.repo_dir, worktree_root=self.worktree_root)
        self.assertIn(stale_wt, snapshot.orig_worktrees)

        # Create a test worktree inside worktree_root
        test_wt = self.worktree_root / "run-test-002" / "task_1" / "att-1"
        test_branch = "factory/run-test-002/task_1/att-1"
        subprocess.run(
            ["git", "worktree", "add", str(test_wt), "-b", test_branch],
            cwd=str(self.repo_dir),
            check=True,
            capture_output=True,
        )
        self.assertTrue(test_wt.exists())

        # Run cleanup
        snapshot.cleanup()

        # Test worktree should be removed
        self.assertFalse(test_wt.exists())

        # Assert pre-existing stale worktree was NOT pruned by global prune
        proc_after = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(self.repo_dir),
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn(
            str(stale_wt),
            proc_after.stdout,
            "Pre-existing stale worktree metadata was deleted by global prune!",
        )


if __name__ == "__main__":
    unittest.main()
