#!/usr/bin/env python3
"""
Reusable Git state isolation and non-destructive cleanup helper for Factory tests.

Ensures that tests clean up only test-created worktrees, branches, and files,
preserving pre-existing worktrees, branches, and tracked modifications.
Never runs repository-wide git reset --hard or git checkout -- .
"""

import os
import pathlib
import shutil
import subprocess
from typing import Dict, List, Optional, Set


class GitStateSnapshot:
    """
    Snapshots existing worktrees, branches, and designated files before a test,
    and cleans up only test-created worktrees and branches while restoring
    the exact pre-test state of designated files.
    """

    def __init__(
        self,
        repo_root: pathlib.Path,
        tracked_files: Optional[List[pathlib.Path]] = None,
        worktree_root: Optional[pathlib.Path] = None,
        branch_pattern: str = "factory/run-*",
    ):
        self.repo_root = pathlib.Path(repo_root).resolve()
        self.worktree_root = pathlib.Path(
            worktree_root or (self.repo_root / ".agy-factory" / "worktrees")
        ).resolve()
        self.branch_pattern = branch_pattern

        # 1. Snapshot pre-existing worktrees (canonical resolved paths)
        self.orig_worktrees: Set[pathlib.Path] = self._get_worktrees()

        # 2. Snapshot pre-existing branches matching pattern
        self.orig_branches: Set[str] = self._get_branches(self.branch_pattern)

        # 3. Snapshot exact pre-test existence & bytes of designated files
        self.file_snapshots: Dict[pathlib.Path, Optional[bytes]] = {}
        for f in tracked_files or []:
            p = pathlib.Path(f).resolve()
            if p.exists() and p.is_file():
                self.file_snapshots[p] = p.read_bytes()
            else:
                self.file_snapshots[p] = None

    def _run_git(self, cmd: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=True,
        )

    def _get_worktrees(self) -> Set[pathlib.Path]:
        proc = self._run_git(["git", "worktree", "list", "--porcelain"])
        worktrees: Set[pathlib.Path] = set()
        for line in proc.stdout.splitlines():
            if line.startswith("worktree "):
                wt_str = line.split(" ", 1)[1].strip()
                try:
                    worktrees.add(pathlib.Path(wt_str).resolve())
                except Exception:
                    pass
        return worktrees

    def _get_branches(self, pattern: str) -> Set[str]:
        proc = self._run_git(["git", "branch", "--list", "--format=%(refname:short)", pattern])
        branches: Set[str] = set()
        for line in proc.stdout.splitlines():
            b = line.strip()
            if b:
                branches.add(b)
        return branches

    def cleanup_worktrees(self) -> None:
        """
        Removes only worktrees created after the snapshot that reside within worktree_root
        or a Factory runtime worktrees directory (.agy-factory/worktrees).
        Never removes the primary repo or pre-existing worktrees.
        Does NOT execute global git worktree prune.
        """
        current_worktrees = self._get_worktrees()
        for wt_path in current_worktrees:
            # Invariant: never delete repo root
            if wt_path == self.repo_root:
                continue
            # Invariant: never delete pre-existing worktrees
            if wt_path in self.orig_worktrees:
                continue
            # Invariant: must reside inside designated worktree_root OR be a test Factory runtime worktree
            is_in_worktree_root = False
            try:
                wt_path.relative_to(self.worktree_root)
                is_in_worktree_root = True
            except ValueError:
                pass
            is_factory_runtime_wt = ".agy-factory/worktrees" in wt_path.as_posix()

            if not (is_in_worktree_root or is_factory_runtime_wt):
                continue

            # Test-created worktree -> safely remove with git worktree remove
            self._run_git(["git", "worktree", "remove", "--force", str(wt_path)])

    def cleanup_branches(self) -> None:
        """
        Removes only branches matching branch_pattern created after snapshot.
        Never removes pre-existing branches.
        """
        current_branches = self._get_branches(self.branch_pattern)
        for b in current_branches:
            if b not in self.orig_branches:
                self._run_git(["git", "branch", "-D", b])

    def restore_files(self) -> None:
        """
        Restores designated files to their exact pre-test state.
        - Existing pre-test: restores original bytes (preserving pre-test user edits).
        - Nonexistent pre-test: removes file if created by test.
        Never performs repository-wide git checkout or restore.
        """
        for path, orig_bytes in self.file_snapshots.items():
            if orig_bytes is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists() or path.read_bytes() != orig_bytes:
                    path.write_bytes(orig_bytes)
            else:
                if path.exists():
                    if path.is_file():
                        path.unlink(missing_ok=True)
                    elif path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)

    def cleanup(self) -> None:
        """Executes full safe cleanup in strictly non-destructive order."""
        self.cleanup_worktrees()
        self.cleanup_branches()
        self.restore_files()
