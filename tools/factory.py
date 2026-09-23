#!/usr/bin/env python3
"""
AGY-Herdr Software Factory Orchestration Engine (Version 3.0.0)

Generic, brain-agnostic orchestration engine delegating arbitrary DAG workflows
across isolated Herdr workspaces, Git worktrees, and worker adapters.
Supports atomic durable state, attempt isolation, reconciliation resume,
failpoint injection, Git conflict abort, concurrent run isolation, and
machine-readable status projections for Kanban integration.

Zero third-party Python dependencies (Python 3 standard library only).
"""

import argparse
import concurrent.futures
import copy
import datetime
import fnmatch
import glob
import hashlib
import inspect
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request

# Base paths
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
FACTORY_DIR = PROJECT_ROOT / ".agy-factory"
STATE_DIR = FACTORY_DIR / "state"
RUNS_DIR = FACTORY_DIR / "runs"
EVIDENCE_DIR = FACTORY_DIR / "evidence"
WORKTREES_DIR = FACTORY_DIR / "worktrees"
TMP_DIR = FACTORY_DIR / "tmp"
CACHE_DIR = FACTORY_DIR / "cache"
LOGS_DIR = FACTORY_DIR / "logs"

OWNED_RESOURCES_PATH = STATE_DIR / "owned-resources.json"
FACTORY_CONFIG_PATH = PROJECT_ROOT / "factory.json"

# Canonical State Definitions
CANONICAL_TASK_STATES = [
    "PENDING",
    "READY",
    "DISPATCHING",
    "RUNNING",
    "RESULT_RECEIVED",
    "PATH_VALIDATING",
    "PATH_VALIDATED",
    "VALIDATING",
    "COMMITTING",
    "COMMITTED",
    "INTEGRATING",
    "INTEGRATED",
    "COMPLETED",
    "BLOCKED",
    "TIMED_OUT",
    "FAILED",
    "CONFLICTED",
    "CANCELLED"
]

CANONICAL_RUN_STATES = [
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED"
]

CANONICAL_TO_DISPLAY_STATE = {
    "PENDING": "BACKLOG",
    "READY": "READY",
    "DISPATCHING": "RUNNING",
    "RUNNING": "RUNNING",
    "RESULT_RECEIVED": "RUNNING",
    "PATH_VALIDATING": "RUNNING",
    "PATH_VALIDATED": "RUNNING",
    "VALIDATING": "RUNNING",
    "COMMITTING": "RUNNING",
    "COMMITTED": "RUNNING",
    "INTEGRATING": "RUNNING",
    "INTEGRATED": "DONE",
    "COMPLETED": "DONE",
    "BLOCKED": "BLOCKED",
    "TIMED_OUT": "FAILED",
    "FAILED": "FAILED",
    "CONFLICTED": "REVIEW",
    "CANCELLED": "FAILED"
}


def atomic_write_json(path: pathlib.Path, data: dict, indent: int = 2):
    """Atomically writes data to a JSON file using a temp file, flush, fsync, and replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".tmp.{path.name}.{os.getpid()}.{time.time()}")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def check_failpoint(point_name: str, run_dir: pathlib.Path = None, details: dict = None):
    """
    Checks if FACTORY_TEST_FAILPOINT environment variable matches point_name.
    If matched, logs failpoint to events.jsonl and exits immediately with code 88.
    """
    target = os.environ.get("FACTORY_TEST_FAILPOINT")
    if target and target.strip() == point_name:
        if run_dir:
            events_file = run_dir / "events.jsonl"
            ev = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "event": "FAILPOINT_TRIGGERED",
                "payload": {"failpoint": point_name, "details": details or {}}
            }
            try:
                with open(events_file, "a", encoding="utf-8") as ef:
                    ef.write(json.dumps(ev) + "\n")
            except Exception:
                pass
        sys.stderr.write(f"[FACTORY FAILPOINT] Triggered failpoint '{point_name}'. Exiting abruptly.\n")
        sys.stderr.flush()
        os._exit(88)


def check_mutation_safety(resource_id: str, owned_list: list) -> bool:
    """Enforces: if resource_id not in owned_resources: mutation_forbidden"""
    return bool(resource_id and resource_id in owned_list)


def is_path_safe_under_root(path_str: str, root_dir: pathlib.Path) -> bool:
    """Verifies that a given relative or absolute path does not escape root_dir."""
    try:
        p = pathlib.Path(path_str)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (root_dir / path_str).resolve()
        root_resolved = root_dir.resolve()
        return root_resolved in resolved.parents or resolved == root_resolved
    except Exception:
        return False


def check_worktree_symlinks(worktree_path: pathlib.Path, project_root: pathlib.Path) -> list:
    """Detects any symlink inside worktree whose target points outside project root."""
    violations = []
    root_resolved = project_root.resolve()
    for item in worktree_path.rglob("*"):
        if item.is_symlink():
            try:
                target = item.resolve()
                if not (root_resolved in target.parents or target == root_resolved):
                    violations.append(f"Symlink '{item.relative_to(worktree_path)}' points outside project root to '{target}'")
            except Exception as e:
                violations.append(f"Unresolvable symlink '{item.name}': {e}")
    return violations


def match_path_allowlist(rel_path: str, allowed_patterns: list) -> bool:
    """
    Checks if a relative path matches any pattern in the task allowlist.
    Handles exact files, directory trees ('dir/**', 'dir/*', 'dir/'), and wildcards.
    Guards against prefix collisions (e.g. 'app' matching 'apple').
    """
    normalized = rel_path.replace("\\", "/").strip("/")
    for pat in allowed_patterns:
        raw_pat = pat.replace("\\", "/").strip()
        if raw_pat.endswith("/**"):
            base_dir = raw_pat[:-3].strip("/")
            if normalized == base_dir or normalized.startswith(base_dir + "/"):
                return True
        elif raw_pat.endswith("/*"):
            base_dir = raw_pat[:-2].strip("/")
            parent = "/".join(normalized.split("/")[:-1])
            if parent == base_dir:
                return True
        elif raw_pat.endswith("/"):
            base_dir = raw_pat.strip("/")
            if normalized == base_dir or normalized.startswith(base_dir + "/"):
                return True
        else:
            pat_norm = raw_pat.strip("/")
            if normalized == pat_norm or normalized.startswith(pat_norm + "/"):
                return True
            if fnmatch.fnmatch(normalized, pat_norm):
                return True
    return False


def collect_file_metadata(path_str: str) -> dict:
    p = pathlib.Path(path_str).expanduser()
    if not p.exists():
        return {"exists": False, "path": str(p)}
    stat = p.stat()
    h = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        digest = h.hexdigest()
    except Exception:
        digest = "unreadable"
    return {
        "exists": True,
        "path": str(p),
        "size_bytes": stat.st_size,
        "mtime": datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat(),
        "sha256": digest
    }


class HerdrClient:
    """Interface to the local Herdr session and socket API."""

    def __init__(self, root_dir: pathlib.Path):
        self.root_dir = root_dir
        self.herdr_bin = os.environ.get("HERDR_BIN_PATH", "/root/.local/bin/herdr")
        self.control_plane = {
            "workspace_id": os.environ.get("HERDR_WORKSPACE_ID", "unknown"),
            "pane_id": os.environ.get("HERDR_PANE_ID", "unknown"),
            "tab_id": os.environ.get("HERDR_TAB_ID", "unknown"),
            "cwd": str(root_dir),
            "herdr_socket": os.environ.get("HERDR_SOCKET_PATH", "/root/.config/herdr/herdr.sock")
        }

    def run_cmd(self, args: list, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
        cmd = [self.herdr_bin] + args
        res = subprocess.run(
            cmd,
            cwd=str(self.root_dir),
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if check and res.returncode != 0:
            raise RuntimeError(f"Herdr command failed ({res.returncode}): {' '.join(cmd)}\nStderr: {res.stderr}\nStdout: {res.stdout}")
        return res

    def get_snapshot(self) -> dict:
        res = self.run_cmd(["api", "snapshot"])
        return json.loads(res.stdout)

    def list_workspaces(self) -> list:
        res = self.run_cmd(["workspace", "list"])
        data = json.loads(res.stdout)
        return data.get("result", {}).get("workspaces", [])

    def list_panes(self) -> list:
        res = self.run_cmd(["pane", "list"])
        data = json.loads(res.stdout)
        return data.get("result", {}).get("panes", [])

    def create_workspace(self, cwd: str, label: str) -> tuple:
        """Creates a dedicated workspace and returns (workspace_id, pane_id)."""
        res = self.run_cmd(["workspace", "create", "--cwd", cwd, "--label", label, "--no-focus"])
        data = json.loads(res.stdout)
        root_pane = data.get("result", {}).get("root_pane", {})
        ws = data.get("result", {}).get("workspace", {})
        workspace_id = ws.get("workspace_id") or root_pane.get("workspace_id")
        pane_id = root_pane.get("pane_id")
        if not workspace_id or not pane_id:
            raise RuntimeError(f"Failed to parse workspace/pane from Herdr response: {res.stdout}")
        return workspace_id, pane_id

    def run_in_pane(self, pane_id: str, command: str) -> None:
        self.run_cmd(["pane", "run", pane_id, command])

    def close_workspace(self, workspace_id: str) -> bool:
        res = self.run_cmd(["workspace", "close", workspace_id], check=False)
        return res.returncode == 0


class ResourceManager:
    """Manages project-owned resources and enforces strict ownership boundaries per run and overall."""

    def __init__(self, herdr: HerdrClient, state_file: pathlib.Path = None):
        self.herdr = herdr
        self.state_file = state_file or OWNED_RESOURCES_PATH
        self._load_or_init()

    def _load_or_init(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
            except Exception:
                self.state = {}
        else:
            self.state = {}

        if "control_plane" not in self.state:
            self.state["control_plane"] = getattr(self.herdr, "control_plane", "wK:p1")
        if "owned" not in self.state:
            self.state["owned"] = {
                "workspace_ids": [],
                "pane_ids": [],
                "branches": [],
                "worktrees": []
            }
        if "runs" not in self.state:
            self.state["runs"] = {}
        self.save()

    def save(self):
        atomic_write_json(self.state_file, self.state)

    def record_workspace(self, workspace_id: str = None, pane_id: str = None, run_id: str = None):
        if workspace_id and workspace_id not in self.state["owned"]["workspace_ids"]:
            self.state["owned"]["workspace_ids"].append(workspace_id)
        if pane_id and pane_id not in self.state["owned"]["pane_ids"]:
            self.state["owned"]["pane_ids"].append(pane_id)

        if run_id:
            if run_id not in self.state["runs"]:
                self.state["runs"][run_id] = {"workspace_ids": [], "pane_ids": [], "branches": [], "worktrees": []}
            if workspace_id and workspace_id not in self.state["runs"][run_id]["workspace_ids"]:
                self.state["runs"][run_id]["workspace_ids"].append(workspace_id)
            if pane_id and pane_id not in self.state["runs"][run_id]["pane_ids"]:
                self.state["runs"][run_id]["pane_ids"].append(pane_id)

        self.save()

    def register_owned_workspace(self, workspace_id: str, run_id: str = None):
        if workspace_id:
            self.record_workspace(workspace_id, None, run_id=run_id)

    def register_owned_pane(self, pane_id: str, run_id: str = None):
        if pane_id:
            self.record_workspace(None, pane_id, run_id=run_id)

    def record_worktree(self, path: str, branch: str, run_id: str = None):
        if path not in self.state["owned"]["worktrees"]:
            self.state["owned"]["worktrees"].append(path)
        if branch not in self.state["owned"]["branches"]:
            self.state["owned"]["branches"].append(branch)

        if run_id:
            if run_id not in self.state["runs"]:
                self.state["runs"][run_id] = {"workspace_ids": [], "pane_ids": [], "branches": [], "worktrees": []}
            if path not in self.state["runs"][run_id]["worktrees"]:
                self.state["runs"][run_id]["worktrees"].append(path)
            if branch not in self.state["runs"][run_id]["branches"]:
                self.state["runs"][run_id]["branches"].append(branch)

        self.save()

    def is_owned_workspace(self, workspace_id: str) -> bool:
        return check_mutation_safety(workspace_id, self.state["owned"]["workspace_ids"])

    def clean_workspace(self, workspace_id: str) -> bool:
        """Safely closes a workspace ONLY if it is registered as project-owned."""
        if not self.is_owned_workspace(workspace_id):
            raise PermissionError(f"Security violation: Workspace '{workspace_id}' is not project-owned. Mutation forbidden.")
        success = self.herdr.close_workspace(workspace_id)
        if workspace_id in self.state["owned"]["workspace_ids"]:
            self.state["owned"]["workspace_ids"].remove(workspace_id)
        for r in self.state.get("runs", {}).values():
            if workspace_id in r.get("workspace_ids", []):
                r["workspace_ids"].remove(workspace_id)
        self.save()
        return success

    def cleanup_owned_resources(self, run_id: str = None) -> dict:
        """
        Idempotently cleans ONLY explicitly registered project-owned resources.
        If run_id is supplied, cleans only resources registered for that specific run.
        """
        cleaned = {
            "run_id": run_id,
            "workspaces_closed": [],
            "worktrees_removed": [],
            "branches_deleted": [],
            "tmp_cleaned": False
        }

        if run_id:
            run_data = self.state.get("runs", {}).get(run_id, {})
            target_ws = list(run_data.get("workspace_ids", []))
            target_wt = list(run_data.get("worktrees", []))
            target_br = list(run_data.get("branches", []))
        else:
            target_ws = list(self.state["owned"]["workspace_ids"])
            target_wt = list(self.state["owned"]["worktrees"])
            target_br = list(self.state["owned"]["branches"])

        # 1. Close owned Herdr workspaces
        for ws_id in target_ws:
            if self.is_owned_workspace(ws_id):
                try:
                    self.herdr.close_workspace(ws_id)
                    cleaned["workspaces_closed"].append(ws_id)
                except Exception:
                    pass
                if ws_id in self.state["owned"]["workspace_ids"]:
                    self.state["owned"]["workspace_ids"].remove(ws_id)

        # 2. Remove owned git worktrees
        for wt_path in target_wt:
            wt = pathlib.Path(wt_path)
            if wt.exists():
                try:
                    subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                                   cwd=str(PROJECT_ROOT), capture_output=True)
                    if wt.exists():
                        shutil.rmtree(wt, ignore_errors=True)
                    cleaned["worktrees_removed"].append(wt_path)
                except Exception:
                    pass
            if wt_path in self.state["owned"]["worktrees"]:
                self.state["owned"]["worktrees"].remove(wt_path)

        if run_id and run_id in self.state.get("runs", {}):
            del self.state["runs"][run_id]
        elif not run_id:
            self.state["owned"]["workspace_ids"] = []
            self.state["owned"]["pane_ids"] = []
            self.state["owned"]["worktrees"] = []
            self.state["runs"] = {}

        # 3. Clean tmp/cache files if doing global cleanup
        if not run_id and TMP_DIR.exists():
            for item in TMP_DIR.glob("*"):
                if item.is_file() or item.is_symlink():
                    item.unlink(missing_ok=True)
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
            cleaned["tmp_cleaned"] = True

        self.save()
        return cleaned


# ==============================================================================
# WorkerAdapter Boundary and Implementations
# ==============================================================================

class WorkerAdapter:
    """Base interface for worker execution adapters."""

    def __init__(self, worker_id: str, worker_config: dict, herdr: HerdrClient, res_mgr: ResourceManager):
        self.worker_id = worker_id
        self.worker_config = worker_config
        self.herdr = herdr
        self.res_mgr = res_mgr

    def prepare_environment(self, run_id: str, task_id: str, attempt_id: int, worktree_path: pathlib.Path) -> dict:
        """Allocates any worker-specific resources (e.g. Herdr workspace/pane) and returns resource dict."""
        raise NotImplementedError

    def execute(self, run_id: str, task_id: str, attempt_id: int, worktree_path: pathlib.Path,
                prompt_file: pathlib.Path, schema_file: pathlib.Path, timeout: int,
                task_attempt_dir: pathlib.Path, env_info: dict, model: str,
                effort: str = None, **kwargs) -> dict:
        """Executes the worker and returns standardized execution result dict."""
        raise NotImplementedError

    def cancel(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> bool:
        """Cancels or terminates a running worker."""
        return True

    def cleanup_attempt(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> None:
        """Cleans up attempt resources (e.g. closing Herdr workspace)."""
        pass


class AgyAdapter(WorkerAdapter):
    """Production adapter executing AGY / Antigravity CLI in isolated Herdr workspaces."""

    def prepare_environment(self, run_id: str, task_id: str, attempt_id: int, worktree_path: pathlib.Path) -> dict:
        label = f"task-{task_id}-a{attempt_id}"
        workspace_id, pane_id = self.herdr.create_workspace(cwd=str(worktree_path), label=label)
        self.res_mgr.record_workspace(workspace_id, pane_id, run_id=run_id)
        return {
            "workspace_id": workspace_id,
            "pane_id": pane_id,
            "worktree_path": str(worktree_path)
        }

    def execute(self, run_id: str, task_id: str, attempt_id: int, worktree_path: pathlib.Path,
                prompt_file: pathlib.Path, schema_file: pathlib.Path, timeout: int,
                task_attempt_dir: pathlib.Path, env_info: dict, model: str,
                effort: str = None, **kwargs) -> dict:
        pane_id = env_info["pane_id"]
        output_json_path = task_attempt_dir / "output.json"
        status_file_path = task_attempt_dir / "exit_code.txt"
        worker_cmd = self.worker_config.get("command", "agy")
        # In AGY CLI, --effort is only supported for reasoning-effort models (e.g. Gemini), not for Claude Sonnet 4.6
        effort_arg = f'--effort "{effort}" \\' if (effort and not model.startswith("claude")) else ""

        # Support test injection in test harness
        test_behavior = os.environ.get("AGY_TEST_BEHAVIOR")
        if os.environ.get("FACTORY_TEST_HARNESS") == "1" and test_behavior:
            return self._handle_test_behavior(
                test_behavior, run_id, task_id, attempt_id, worktree_path,
                output_json_path, status_file_path, timeout, env_info,
                model=model, effort=effort
            )

        script_path = task_attempt_dir / "run_worker.sh"
        with open(script_path, "w", encoding="utf-8") as sf:
            sf.write(f"""#!/bin/bash
set -o pipefail
cd "{worktree_path}"
"{worker_cmd}" --mode accept-edits --dangerously-skip-permissions --add-dir "{worktree_path}" \\
  -p "$(< "{prompt_file}")" \\
  --model "{model}" \\
  {effort_arg}
  --output-format json \\
  --json-schema "$(< "{schema_file}")" \\
  > "{output_json_path}" 2>&1
echo $? > "{status_file_path}"
""")
        os.chmod(script_path, 0o755)

        self.herdr.run_in_pane(pane_id, f'bash "{script_path}"')

        start_wait = time.time()
        while time.time() - start_wait < timeout:
            if status_file_path.exists() and status_file_path.stat().st_size > 0:
                break
            time.sleep(1)

        if not status_file_path.exists() or status_file_path.stat().st_size == 0:
            self.cancel(run_id, task_id, attempt_id, env_info)
            return {
                "exit_code": -1,
                "timed_out": True,
                "error": f"Worker timed out after {timeout}s",
                "raw_output": output_json_path.read_text(encoding="utf-8") if output_json_path.exists() else ""
            }

        try:
            exit_code = int(status_file_path.read_text().strip())
        except Exception:
            exit_code = -1

        raw_output = output_json_path.read_text(encoding="utf-8") if output_json_path.exists() else ""

        def _parse_output(content: str) -> dict:
            content = content.strip()
            try:
                return json.loads(content)
            except Exception:
                pass
            for line in reversed(content.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        d = json.loads(line)
                        if "status" in d or "conversation_id" in d:
                            return d
                    except Exception:
                        pass
            for m in re.finditer(r"(\{[\s\S]*?\n\})", content):
                try:
                    d = json.loads(m.group(1))
                    if "status" in d or "conversation_id" in d:
                        return d
                except Exception:
                    pass
            m = re.search(r"(\{[\s\S]*\})", content)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    pass
            return {}

        parsed_data = _parse_output(raw_output)
        return {
            "exit_code": exit_code,
            "timed_out": False,
            "raw_output": raw_output,
            "data": parsed_data
        }

    def _handle_test_behavior(self, behavior: str, run_id: str, task_id: str, attempt_id: int,
                              worktree_path: pathlib.Path, output_json_path: pathlib.Path,
                              status_file_path: pathlib.Path, timeout: int, env_info: dict,
                              model: str = "gemini-3.8-flash", effort: str = "high") -> dict:
        if behavior == "TIMEOUT":
            self.cancel(run_id, task_id, attempt_id, env_info)
            return {"exit_code": -1, "timed_out": True, "error": f"AGY worker timed out after {timeout}s"}
        elif behavior == "ERROR":
            err_envelope = {"status": "FAILED", "error": "Simulated AGY failure"}
            output_json_path.write_text(json.dumps(err_envelope), encoding="utf-8")
            status_file_path.write_text("1\n")
            return {
                "exit_code": 1,
                "timed_out": False,
                "raw_output": json.dumps(err_envelope),
                "data": err_envelope,
                "provenance": {"model": model, "reasoning_effort": effort}
            }
        else:  # SUCCESS
            inner_data = {
                "run_id": run_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "status": "COMPLETED",
                "summary": f"Successfully finished {task_id} via AGY",
                "changed_files": []
            }
            envelope = {
                "status": "SUCCESS",
                "response": json.dumps(inner_data),
                "structured_output": inner_data
            }
            output_json_path.write_text(json.dumps(envelope), encoding="utf-8")
            status_file_path.write_text("0\n")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": json.dumps(envelope),
                "data": envelope,
                "provenance": {
                    "model": model,
                    "reasoning_effort": effort
                }
            }

    def cancel(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> bool:
        ws_id = env_info.get("workspace_id")
        if ws_id and self.res_mgr.is_owned_workspace(ws_id):
            try:
                return self.herdr.close_workspace(ws_id)
            except Exception:
                return False
        return True

    def cleanup_attempt(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> None:
        ws_id = env_info.get("workspace_id")
        if ws_id and self.res_mgr.is_owned_workspace(ws_id):
            try:
                self.res_mgr.clean_workspace(ws_id)
            except Exception:
                pass
def extract_json_payload(text: str, task_id: str = None):
    """
    Robustly extracts a task result dictionary from arbitrary worker output or markdown.
    Handles fenced ```json ... ``` blocks, bare JSON, nested braces, and greedy regex fallbacks.
    """
    if not text or not isinstance(text, str):
        return None
    cleaned = text.strip()
    # 1. Fenced markdown code block
    m_fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned)
    if m_fence:
        try:
            parsed = json.loads(m_fence.group(1))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    # 2. Direct json string parse
    if (cleaned.startswith("{") and cleaned.endswith("}")) or ("{" in cleaned and "}" in cleaned):
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    # 3. Candidate JSON blocks containing status
    for m in re.finditer(r"(\{[^{}]*\"status\"[^{}]*\})", cleaned):
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict) and "status" in parsed:
                return parsed
        except Exception:
            pass
    # 4. Search curly bracket blocks that have task keys
    for m in re.finditer(r"(\{[\s\S]*?\})", cleaned):
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict) and ("status" in parsed or "summary" in parsed or (task_id and parsed.get("task_id") == task_id)):
                return parsed
        except Exception:
            pass
    # 5. Greedy fallback
    m_greedy = re.search(r"(\{[\s\S]*\})", cleaned)
    if m_greedy:
        try:
            parsed = json.loads(m_greedy.group(1))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return None


class DroidAdapter(WorkerAdapter):
    """Production adapter executing Droid / Factory CLI in isolated Herdr workspaces."""

    def prepare_environment(self, run_id: str, task_id: str, attempt_id: int, worktree_path: pathlib.Path) -> dict:
        label = f"task-{task_id}-a{attempt_id}"
        workspace_id, pane_id = self.herdr.create_workspace(cwd=str(worktree_path), label=label)
        self.res_mgr.record_workspace(workspace_id, pane_id, run_id=run_id)
        return {
            "workspace_id": workspace_id,
            "pane_id": pane_id,
            "worktree_path": str(worktree_path)
        }

    def execute(self, run_id: str, task_id: str, attempt_id: int, worktree_path: pathlib.Path,
                prompt_file: pathlib.Path, schema_file: pathlib.Path, timeout: int,
                task_attempt_dir: pathlib.Path, env_info: dict, model: str,
                effort: str = None, **kwargs) -> dict:
        pane_id = env_info.get("pane_id")
        output_json_path = task_attempt_dir / "output.json"
        status_file_path = task_attempt_dir / "exit_code.txt"
        worker_cmd = self.worker_config.get("command", "droid")
        effort = effort or self.worker_config.get("reasoning_effort", "xhigh")
        autonomy = self.worker_config.get("autonomy", "low")

        # Support test injection in test harness
        test_behavior = os.environ.get("DROID_TEST_BEHAVIOR")
        if os.environ.get("FACTORY_TEST_HARNESS") == "1" and test_behavior:
            return self._handle_test_behavior(
                test_behavior, run_id, task_id, attempt_id, worktree_path,
                output_json_path, status_file_path, timeout, env_info
            )

        script_path = task_attempt_dir / "run_worker.sh"
        with open(script_path, "w", encoding="utf-8") as sf:
            sf.write(f"""#!/bin/bash
set -o pipefail
cd "{worktree_path}"
"{worker_cmd}" exec \\
  --cwd "{worktree_path}" \\
  --auto "{autonomy}" \\
  --model "{model}" \\
  --reasoning-effort "{effort}" \\
  --output-format json \\
  --file "{prompt_file}" \\
  > "{output_json_path}" 2>&1
echo $? > "{status_file_path}"
""")
        os.chmod(script_path, 0o755)

        if pane_id:
            self.herdr.run_in_pane(pane_id, f'bash "{script_path}"')
        else:
            subprocess.Popen(["bash", str(script_path)], cwd=str(worktree_path))

        start_wait = time.time()
        while time.time() - start_wait < timeout:
            if status_file_path.exists() and status_file_path.stat().st_size > 0:
                break
            time.sleep(1)

        if not status_file_path.exists() or status_file_path.stat().st_size == 0:
            self.cancel(run_id, task_id, attempt_id, env_info)
            return {
                "exit_code": -1,
                "timed_out": True,
                "error": f"Droid worker timed out after {timeout}s",
                "raw_output": output_json_path.read_text(encoding="utf-8") if output_json_path.exists() else ""
            }

        try:
            exit_code = int(status_file_path.read_text().strip())
        except Exception:
            exit_code = -1

        raw_output = output_json_path.read_text(encoding="utf-8") if output_json_path.exists() else ""
        parsed = self._parse_droid_output(raw_output, run_id, task_id, attempt_id)

        return {
            "exit_code": exit_code,
            "timed_out": False,
            "raw_output": raw_output,
            "data": parsed.get("task_data", {}),
            "provenance": parsed.get("provenance", {})
        }

    def _parse_droid_output(self, raw_output: str, run_id: str, task_id: str, attempt_id: int) -> dict:
        result = {"task_data": {}, "provenance": {}}
        raw_output = raw_output.strip()
        if not raw_output:
            return result

        droid_envelope = {}
        try:
            droid_envelope = json.loads(raw_output)
        except Exception:
            for line in reversed(raw_output.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        droid_envelope = json.loads(line)
                        break
                    except Exception:
                        pass

        # Capture provenance from envelope
        if isinstance(droid_envelope, dict):
            if "session_id" in droid_envelope:
                result["provenance"]["session_id"] = droid_envelope["session_id"]
            if "duration_ms" in droid_envelope:
                result["provenance"]["duration_ms"] = droid_envelope["duration_ms"]
            if "turns" in droid_envelope:
                result["provenance"]["turns"] = droid_envelope["turns"]
            result["provenance"]["model"] = droid_envelope.get("model", self.worker_config.get("default_model"))
            result["provenance"]["reasoning_effort"] = droid_envelope.get("reasoning_effort", self.worker_config.get("reasoning_effort"))

            # Check if outer envelope indicates error
            if droid_envelope.get("is_error") is True:
                result["task_data"] = {
                    "status": "FAILED",
                    "error": droid_envelope.get("error") or droid_envelope.get("result", "Droid execution error")
                }
                return result

            # Parse inner Factory task JSON
            inner_text = str(droid_envelope.get("result") or raw_output)
            inner_json = extract_json_payload(inner_text, task_id)
            if inner_json:
                if inner_json.get("task_id") and inner_json.get("task_id") != task_id:
                    result["task_data"] = {"status": "FAILED", "error": f"Mismatched task_id: {inner_json.get('task_id')} != {task_id}"}
                    return result
                if inner_json.get("attempt_id") and inner_json.get("attempt_id") != attempt_id:
                    result["task_data"] = {"status": "FAILED", "error": f"Mismatched attempt_id: {inner_json.get('attempt_id')} != {attempt_id}"}
                    return result
                result["task_data"] = inner_json
                return result

        fallback_json = extract_json_payload(raw_output, task_id)
        if fallback_json:
            result["task_data"] = fallback_json
        return result

    def _handle_test_behavior(self, behavior: str, run_id: str, task_id: str, attempt_id: int,
                              worktree_path: pathlib.Path, output_json_path: pathlib.Path,
                              status_file_path: pathlib.Path, timeout: int, env_info: dict) -> dict:
        if behavior == "TIMEOUT":
            self.cancel(run_id, task_id, attempt_id, env_info)
            return {"exit_code": -1, "timed_out": True, "error": f"Worker timed out after {timeout}s"}
        elif behavior == "ERROR":
            err_envelope = {"is_error": True, "error": "Simulated Droid failure", "result": "Execution error"}
            output_json_path.write_text(json.dumps(err_envelope), encoding="utf-8")
            status_file_path.write_text("1\n")
            return {
                "exit_code": 1,
                "timed_out": False,
                "raw_output": json.dumps(err_envelope),
                "data": {"status": "FAILED", "error": "Simulated Droid failure"},
                "provenance": {"session_id": "test-session-err", "model": "qwen3.8-max"}
            }
        elif behavior == "MALFORMED":
            output_json_path.write_text("NOT_JSON_AT_ALL", encoding="utf-8")
            status_file_path.write_text("0\n")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": "NOT_JSON_AT_ALL",
                "data": {},
                "provenance": {}
            }
        elif behavior == "ATTEMPT_MISMATCH":
            envelope = {
                "is_error": False,
                "session_id": "test-session-mismatch",
                "result": json.dumps({
                    "run_id": run_id,
                    "task_id": task_id,
                    "attempt_id": attempt_id + 99,
                    "status": "COMPLETED",
                    "summary": "Mismatched attempt",
                    "changed_files": []
                })
            }
            output_json_path.write_text(json.dumps(envelope), encoding="utf-8")
            status_file_path.write_text("0\n")
            parsed = self._parse_droid_output(json.dumps(envelope), run_id, task_id, attempt_id)
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": json.dumps(envelope),
                "data": parsed.get("task_data", {}),
                "provenance": parsed.get("provenance", {})
            }
        else: # SUCCESS
            inner_data = {
                "run_id": run_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "status": "COMPLETED",
                "summary": f"Successfully finished {task_id} via Droid",
                "changed_files": []
            }
            envelope = {
                "is_error": False,
                "session_id": f"sess-{task_id}-{attempt_id}",
                "duration_ms": 4200,
                "turns": 3,
                "model": "qwen3.8-max",
                "reasoning_effort": "xhigh",
                "result": json.dumps(inner_data)
            }
            output_json_path.write_text(json.dumps(envelope), encoding="utf-8")
            status_file_path.write_text("0\n")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": json.dumps(envelope),
                "data": inner_data,
                "provenance": {
                    "session_id": f"sess-{task_id}-{attempt_id}",
                    "duration_ms": 4200,
                    "turns": 3,
                    "model": "qwen3.8-max",
                    "reasoning_effort": "xhigh"
                }
            }

    def cancel(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> bool:
        ws_id = env_info.get("workspace_id")
        if ws_id and self.res_mgr.is_owned_workspace(ws_id):
            try:
                return self.herdr.close_workspace(ws_id)
            except Exception:
                return False
        return True

    def cleanup_attempt(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> None:
        ws_id = env_info.get("workspace_id")
        if ws_id and self.res_mgr.is_owned_workspace(ws_id):
            try:
                self.res_mgr.clean_workspace(ws_id)
            except Exception:
                pass


class CodexAdapter(WorkerAdapter):
    """
    Worker adapter for OpenAI Codex non-interactive execution.
    Pins execution to gpt-5.6-luna with high reasoning effort.
    Executes in isolated worktree and registered Herdr workspace/pane.
    Flags:
      codex exec \\
        --model gpt-5.6-luna \\
        -c model_reasoning_effort=high \\
        --sandbox workspace-write \\
        --approve-for-me \\
        --ephemeral \\
        --output-schema <schema> \\
        -o <output_json>
    """

    def __init__(self, worker_id: str, worker_config: dict, herdr_client: HerdrClient, resource_manager: ResourceManager):
        super().__init__(worker_id, worker_config, herdr_client, resource_manager)
        self.command = worker_config.get("command", "/usr/local/bin/codex")
        self.profile_home = pathlib.Path(worker_config.get("profile_home", "/root/.codex"))
        self.default_model = worker_config.get("default_model", "gpt-5.6-luna")
        self.reasoning_effort = worker_config.get("reasoning_effort", "high")
        self.native_cfg = worker_config.get("native", {})

    def prepare_environment(self, run_id: str, task_id: str, attempt_id: int, worktree_path: pathlib.Path) -> dict:
        label = f"factory_{task_id}_att_{attempt_id}"
        ws_id, pane_id = self.herdr.create_workspace(cwd=str(worktree_path), label=label)
        self.res_mgr.register_owned_workspace(ws_id)
        self.res_mgr.register_owned_pane(pane_id)
        return {
            "workspace_id": ws_id,
            "pane_id": pane_id,
            "worktree_path": str(worktree_path)
        }

    def execute(self, run_id: str, task_id: str, attempt_id: int,
                worktree_path: pathlib.Path, prompt_file: pathlib.Path,
                schema_file: pathlib.Path, timeout: int,
                task_attempt_dir: pathlib.Path, env_info: dict,
                model: str = None, effort: str = None) -> dict:
        output_json_path = task_attempt_dir / "worker_output.json"
        status_file_path = task_attempt_dir / "worker_status.txt"
        pane_id = env_info.get("pane_id")

        model = model or self.default_model
        effort = effort or self.reasoning_effort
        sandbox = self.native_cfg.get("sandbox", "workspace-write")

        # Deterministic test harness mode
        if os.environ.get("FACTORY_TEST_HARNESS") == "1":
            behavior = os.environ.get("CODEX_TEST_BEHAVIOR", "SUCCESS")
            return self._handle_test_behavior(
                behavior, run_id, task_id, attempt_id, worktree_path,
                output_json_path, status_file_path, timeout, env_info,
                model=model, effort=effort, sandbox=sandbox
            )

        # Live authentication check
        has_auth = bool(os.environ.get("OPENAI_API_KEY"))
        if not has_auth:
            return {
                "exit_code": 1,
                "timed_out": False,
                "error": "Codex authentication missing (no OPENAI_API_KEY environment variable). Set OPENAI_API_KEY to enable live Codex execution.",
                "data": {"status": "FAILED", "error": "AUTH_BLOCKED"},
                "provenance": {"auth_status": "AUTH_BLOCKED", "model": model, "reasoning_effort": effort, "sandbox": sandbox}
            }

        # Build wrapper script for live codex execution
        script_path = task_attempt_dir / "run_codex.sh"
        cmd = [
            f'"{self.command}"',
            "exec",
            f"--model {model}",
            f"-c model_reasoning_effort={effort}",
            f"--sandbox {sandbox}",
            "--approve-for-me",
            "--ephemeral",
            f'--output-schema "{schema_file}"',
            f'-o "{output_json_path}"'
        ]
        script_body = (
            f"#!/usr/bin/env bash\n"
            f"cd \"{worktree_path}\"\n"
            f"{' '.join(cmd)} < \"{prompt_file}\"\n"
            f"echo $? > \"{status_file_path}\"\n"
        )
        script_path.write_text(script_body, encoding="utf-8")
        os.chmod(script_path, 0o755)

        if pane_id:
            self.herdr.run_in_pane(pane_id, f'bash "{script_path}"')
        else:
            subprocess.Popen(["bash", str(script_path)], cwd=str(worktree_path))

        start_wait = time.time()
        while time.time() - start_wait < timeout:
            if status_file_path.exists() and status_file_path.stat().st_size > 0:
                break
            time.sleep(1)

        if not status_file_path.exists() or status_file_path.stat().st_size == 0:
            self.cancel(run_id, task_id, attempt_id, env_info)
            return {
                "exit_code": -1,
                "timed_out": True,
                "error": f"Codex worker timed out after {timeout}s",
                "raw_output": output_json_path.read_text(encoding="utf-8") if output_json_path.exists() else ""
            }

        try:
            exit_code = int(status_file_path.read_text().strip())
        except Exception:
            exit_code = -1

        raw_output = output_json_path.read_text(encoding="utf-8") if output_json_path.exists() else ""
        parsed = self._parse_codex_output(raw_output, run_id, task_id, attempt_id, model=model, effort=effort, sandbox=sandbox)

        return {
            "exit_code": exit_code,
            "timed_out": False,
            "raw_output": raw_output,
            "data": parsed.get("task_data", {}),
            "provenance": parsed.get("provenance", {})
        }

    def _parse_codex_output(self, raw_output: str, run_id: str, task_id: str, attempt_id: int,
                            model: str = "gpt-5.6-luna", effort: str = "high", sandbox: str = "workspace-write") -> dict:
        result = {
            "task_data": {},
            "provenance": {
                "model": model,
                "reasoning_effort": effort,
                "sandbox": sandbox
            }
        }
        raw_output = raw_output.strip()
        if not raw_output:
            return result

        envelope = {}
        try:
            envelope = json.loads(raw_output)
        except Exception:
            for line in reversed(raw_output.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        envelope = json.loads(line)
                        break
                    except Exception:
                        pass

        if isinstance(envelope, dict):
            if "session_id" in envelope:
                result["provenance"]["session_id"] = envelope["session_id"]
            if "duration_ms" in envelope:
                result["provenance"]["duration_ms"] = envelope["duration_ms"]
            if "turns" in envelope:
                result["provenance"]["turns"] = envelope["turns"]
            if "model" in envelope:
                result["provenance"]["model"] = envelope["model"]
            if "reasoning_effort" in envelope:
                result["provenance"]["reasoning_effort"] = envelope["reasoning_effort"]

            if envelope.get("is_error") is True:
                result["task_data"] = {
                    "status": "FAILED",
                    "error": envelope.get("error") or envelope.get("result", "Codex execution error")
                }
                return result

            # Parse inner task result
            inner_text = envelope.get("result")
            inner_json = None
            if isinstance(inner_text, dict):
                inner_json = inner_text
            elif isinstance(inner_text, str):
                inner_json = extract_json_payload(inner_text, task_id)
            elif not inner_text and "status" in envelope:
                inner_json = envelope

            if inner_json:
                if inner_json.get("task_id") and inner_json.get("task_id") != task_id:
                    result["task_data"] = {"status": "FAILED", "error": f"Mismatched task_id: {inner_json.get('task_id')} != {task_id}"}
                    return result
                if inner_json.get("attempt_id") and inner_json.get("attempt_id") != attempt_id:
                    result["task_data"] = {"status": "FAILED", "error": f"Mismatched attempt_id: {inner_json.get('attempt_id')} != {attempt_id}"}
                    return result
                result["task_data"] = inner_json
                return result

        fallback_json = extract_json_payload(raw_output, task_id)
        if fallback_json:
            result["task_data"] = fallback_json
        return result

    def _handle_test_behavior(self, behavior: str, run_id: str, task_id: str, attempt_id: int,
                              worktree_path: pathlib.Path, output_json_path: pathlib.Path,
                              status_file_path: pathlib.Path, timeout: int, env_info: dict,
                              model: str = "gpt-5.6-luna", effort: str = "high", sandbox: str = "workspace-write") -> dict:
        if behavior == "TIMEOUT":
            self.cancel(run_id, task_id, attempt_id, env_info)
            return {"exit_code": -1, "timed_out": True, "error": f"Codex worker timed out after {timeout}s"}
        elif behavior == "ERROR":
            err_envelope = {"is_error": True, "error": "Simulated Codex failure", "result": "Execution error"}
            output_json_path.write_text(json.dumps(err_envelope), encoding="utf-8")
            status_file_path.write_text("1\n")
            return {
                "exit_code": 1,
                "timed_out": False,
                "raw_output": json.dumps(err_envelope),
                "data": {"status": "FAILED", "error": "Simulated Codex failure"},
                "provenance": {
                    "session_id": "codex-test-session-err",
                    "model": model,
                    "reasoning_effort": effort,
                    "sandbox": sandbox
                }
            }
        elif behavior == "MALFORMED":
            output_json_path.write_text("NOT_JSON_AT_ALL", encoding="utf-8")
            status_file_path.write_text("0\n")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": "NOT_JSON_AT_ALL",
                "data": {},
                "provenance": {}
            }
        elif behavior == "ATTEMPT_MISMATCH":
            envelope = {
                "is_error": False,
                "session_id": "codex-test-session-mismatch",
                "result": json.dumps({
                    "run_id": run_id,
                    "task_id": task_id,
                    "attempt_id": attempt_id + 99,
                    "status": "COMPLETED",
                    "summary": "Mismatched attempt",
                    "changed_files": []
                })
            }
            output_json_path.write_text(json.dumps(envelope), encoding="utf-8")
            status_file_path.write_text("0\n")
            parsed = self._parse_codex_output(json.dumps(envelope), run_id, task_id, attempt_id, model=model, effort=effort, sandbox=sandbox)
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": json.dumps(envelope),
                "data": parsed.get("task_data", {}),
                "provenance": parsed.get("provenance", {})
            }
        else:  # SUCCESS
            inner_data = {
                "run_id": run_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "status": "COMPLETED",
                "summary": f"Successfully finished {task_id} via Codex",
                "changed_files": []
            }
            envelope = {
                "is_error": False,
                "session_id": f"codex-sess-{task_id}-{attempt_id}",
                "duration_ms": 3800,
                "turns": 2,
                "model": model,
                "reasoning_effort": effort,
                "result": json.dumps(inner_data)
            }
            output_json_path.write_text(json.dumps(envelope), encoding="utf-8")
            status_file_path.write_text("0\n")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": json.dumps(envelope),
                "data": inner_data,
                "provenance": {
                    "session_id": f"codex-sess-{task_id}-{attempt_id}",
                    "duration_ms": 3800,
                    "turns": 2,
                    "model": model,
                    "reasoning_effort": effort,
                    "sandbox": sandbox
                }
            }

    def cancel(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> bool:
        ws_id = env_info.get("workspace_id")
        if ws_id and self.res_mgr.is_owned_workspace(ws_id):
            try:
                return self.herdr.close_workspace(ws_id)
            except Exception:
                return False
        return True

    def cleanup_attempt(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> None:
        ws_id = env_info.get("workspace_id")
        if ws_id and self.res_mgr.is_owned_workspace(ws_id):
            try:
                self.res_mgr.clean_workspace(ws_id)
            except Exception:
                pass


class ClaudeAdapter(WorkerAdapter):
    """
    Worker adapter for Anthropic Claude Code non-interactive execution.
    Executes in isolated worktree and registered Herdr workspace/pane.
    Flags:
      claude -p "$(< prompt.md)" \\
        --model claude-sonnet-5 \\
        --effort high \\
        --permission-mode acceptEdits \\
        --output-format json \\
        --json-schema "$(< schema.json)" \\
        --no-session-persistence
    """

    def __init__(self, worker_id: str, worker_config: dict, herdr_client: HerdrClient, resource_manager: ResourceManager):
        super().__init__(worker_id, worker_config, herdr_client, resource_manager)
        self.command = worker_config.get("command", "/root/.local/bin/claude")
        self.profile_home = pathlib.Path(worker_config.get("profile_home", "/root/.claude"))
        self.default_model = worker_config.get("default_model", "claude-sonnet-5")
        self.reasoning_effort = worker_config.get("reasoning_effort", "high")
        self.native_cfg = worker_config.get("native", {})

    def prepare_environment(self, run_id: str, task_id: str, attempt_id: int, worktree_path: pathlib.Path) -> dict:
        label = f"factory_{task_id}_att_{attempt_id}"
        ws_id, pane_id = self.herdr.create_workspace(cwd=str(worktree_path), label=label)
        self.res_mgr.register_owned_workspace(ws_id)
        self.res_mgr.register_owned_pane(pane_id)
        return {
            "workspace_id": ws_id,
            "pane_id": pane_id,
            "worktree_path": str(worktree_path)
        }

    def execute(self, run_id: str, task_id: str, attempt_id: int,
                worktree_path: pathlib.Path, prompt_file: pathlib.Path,
                schema_file: pathlib.Path, timeout: int,
                task_attempt_dir: pathlib.Path, env_info: dict,
                model: str = None, effort: str = None) -> dict:
        output_json_path = task_attempt_dir / "worker_output.json"
        status_file_path = task_attempt_dir / "worker_status.txt"
        pane_id = env_info.get("pane_id")

        model = model or self.default_model
        effort = effort or self.reasoning_effort
        perm_mode = self.native_cfg.get("permission_mode", "acceptEdits")

        # Deterministic test harness mode
        if os.environ.get("FACTORY_TEST_HARNESS") == "1":
            behavior = os.environ.get("CLAUDE_TEST_BEHAVIOR", "SUCCESS")
            return self._handle_test_behavior(
                behavior, run_id, task_id, attempt_id, worktree_path,
                output_json_path, status_file_path, timeout, env_info,
                model=model, effort=effort, perm_mode=perm_mode
            )

        # Live authentication check
        has_auth = bool(os.environ.get("CLAUDE_CODE_TOKEN") or os.environ.get("ANTHROPIC_API_KEY"))
        if not has_auth:
            return {
                "exit_code": 1,
                "timed_out": False,
                "error": "Claude authentication missing (no CLAUDE_CODE_TOKEN or ANTHROPIC_API_KEY). Set credentials to enable live Claude execution.",
                "data": {"status": "FAILED", "error": "AUTH_BLOCKED"},
                "provenance": {"auth_status": "AUTH_BLOCKED", "model": model, "reasoning_effort": effort}
            }

        # Build wrapper script for live claude execution
        script_path = task_attempt_dir / "run_claude.sh"
        cmd = [
            f'"{self.command}"',
            "-p \"$(< " + f'"{prompt_file}"' + ")\"",
            f'--model "{model}"',
            f'--effort "{effort}"',
            f'--permission-mode "{perm_mode}"',
            "--output-format json",
            f'--json-schema "$(< "{schema_file}")"',
            "--no-session-persistence"
        ]
        script_body = (
            f"#!/usr/bin/env bash\n"
            f"cd \"{worktree_path}\"\n"
            f"{' '.join(cmd)} > \"{output_json_path}\" 2>&1\n"
            f"echo $? > \"{status_file_path}\"\n"
        )
        script_path.write_text(script_body, encoding="utf-8")
        os.chmod(script_path, 0o755)

        if pane_id:
            self.herdr.run_in_pane(pane_id, f'bash "{script_path}"')
        else:
            subprocess.Popen(["bash", str(script_path)], cwd=str(worktree_path))

        start_wait = time.time()
        while time.time() - start_wait < timeout:
            if status_file_path.exists() and status_file_path.stat().st_size > 0:
                break
            time.sleep(1)

        if not status_file_path.exists() or status_file_path.stat().st_size == 0:
            self.cancel(run_id, task_id, attempt_id, env_info)
            return {
                "exit_code": -1,
                "timed_out": True,
                "error": f"Claude worker timed out after {timeout}s",
                "raw_output": output_json_path.read_text(encoding="utf-8") if output_json_path.exists() else ""
            }

        try:
            exit_code = int(status_file_path.read_text().strip())
        except Exception:
            exit_code = -1

        raw_output = output_json_path.read_text(encoding="utf-8") if output_json_path.exists() else ""
        parsed = self._parse_claude_output(raw_output, run_id, task_id, attempt_id, model=model, effort=effort)

        return {
            "exit_code": exit_code,
            "timed_out": False,
            "raw_output": raw_output,
            "data": parsed.get("task_data", {}),
            "provenance": parsed.get("provenance", {})
        }

    def _parse_claude_output(self, raw_output: str, run_id: str, task_id: str, attempt_id: int,
                             model: str = "claude-sonnet-5", effort: str = "high") -> dict:
        result = {
            "task_data": {},
            "provenance": {
                "model": model,
                "reasoning_effort": effort
            }
        }
        raw_output = raw_output.strip()
        if not raw_output:
            return result

        envelope = {}
        try:
            envelope = json.loads(raw_output)
        except Exception:
            for line in reversed(raw_output.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        envelope = json.loads(line)
                        break
                    except Exception:
                        pass

        if isinstance(envelope, dict):
            if "session_id" in envelope:
                result["provenance"]["session_id"] = envelope["session_id"]
            if "duration_ms" in envelope:
                result["provenance"]["duration_ms"] = envelope["duration_ms"]
            if "turns" in envelope:
                result["provenance"]["turns"] = envelope["turns"]
            if "model" in envelope:
                result["provenance"]["model"] = envelope["model"]
            if "effort" in envelope or "reasoning_effort" in envelope:
                result["provenance"]["reasoning_effort"] = envelope.get("effort") or envelope.get("reasoning_effort")

            if envelope.get("is_error") is True:
                result["task_data"] = {
                    "status": "FAILED",
                    "error": envelope.get("error") or envelope.get("result", "Claude execution error")
                }
                return result

            inner_text = envelope.get("result")
            inner_json = None
            if isinstance(inner_text, dict):
                inner_json = inner_text
            elif isinstance(inner_text, str):
                inner_json = extract_json_payload(inner_text, task_id)
            elif not inner_text and "status" in envelope:
                inner_json = envelope

            if inner_json:
                if inner_json.get("task_id") and inner_json.get("task_id") != task_id:
                    result["task_data"] = {"status": "FAILED", "error": f"Mismatched task_id: {inner_json.get('task_id')} != {task_id}"}
                    return result
                if inner_json.get("attempt_id") and inner_json.get("attempt_id") != attempt_id:
                    result["task_data"] = {"status": "FAILED", "error": f"Mismatched attempt_id: {inner_json.get('attempt_id')} != {attempt_id}"}
                    return result
                result["task_data"] = inner_json
                return result

        fallback_json = extract_json_payload(raw_output, task_id)
        if fallback_json:
            result["task_data"] = fallback_json
        return result

    def _handle_test_behavior(self, behavior: str, run_id: str, task_id: str, attempt_id: int,
                              worktree_path: pathlib.Path, output_json_path: pathlib.Path,
                              status_file_path: pathlib.Path, timeout: int, env_info: dict,
                              model: str = "claude-sonnet-5", effort: str = "high", perm_mode: str = "acceptEdits") -> dict:
        if behavior == "TIMEOUT":
            self.cancel(run_id, task_id, attempt_id, env_info)
            return {"exit_code": -1, "timed_out": True, "error": f"Claude worker timed out after {timeout}s"}
        elif behavior == "ERROR":
            err_envelope = {"is_error": True, "error": "Simulated Claude failure", "result": "Execution error"}
            output_json_path.write_text(json.dumps(err_envelope), encoding="utf-8")
            status_file_path.write_text("1\n")
            return {
                "exit_code": 1,
                "timed_out": False,
                "raw_output": json.dumps(err_envelope),
                "data": {"status": "FAILED", "error": "Simulated Claude failure"},
                "provenance": {
                    "session_id": "claude-test-session-err",
                    "model": model,
                    "reasoning_effort": effort,
                    "permission_mode": perm_mode
                }
            }
        elif behavior == "MALFORMED":
            output_json_path.write_text("NOT_JSON_AT_ALL", encoding="utf-8")
            status_file_path.write_text("0\n")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": "NOT_JSON_AT_ALL",
                "data": {},
                "provenance": {}
            }
        elif behavior == "ATTEMPT_MISMATCH":
            envelope = {
                "is_error": False,
                "session_id": "claude-test-session-mismatch",
                "result": json.dumps({
                    "run_id": run_id,
                    "task_id": task_id,
                    "attempt_id": attempt_id + 99,
                    "status": "COMPLETED",
                    "summary": "Mismatched attempt",
                    "changed_files": []
                })
            }
            output_json_path.write_text(json.dumps(envelope), encoding="utf-8")
            status_file_path.write_text("0\n")
            parsed = self._parse_claude_output(json.dumps(envelope), run_id, task_id, attempt_id, model=model, effort=effort)
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": json.dumps(envelope),
                "data": parsed.get("task_data", {}),
                "provenance": parsed.get("provenance", {})
            }
        else:  # SUCCESS
            inner_data = {
                "run_id": run_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "status": "COMPLETED",
                "summary": f"Successfully finished {task_id} via Claude",
                "changed_files": []
            }
            envelope = {
                "is_error": False,
                "session_id": f"claude-sess-{task_id}-{attempt_id}",
                "duration_ms": 3500,
                "turns": 2,
                "model": model,
                "reasoning_effort": effort,
                "result": json.dumps(inner_data)
            }
            output_json_path.write_text(json.dumps(envelope), encoding="utf-8")
            status_file_path.write_text("0\n")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": json.dumps(envelope),
                "data": inner_data,
                "provenance": {
                    "session_id": f"claude-sess-{task_id}-{attempt_id}",
                    "duration_ms": 3500,
                    "turns": 2,
                    "model": model,
                    "reasoning_effort": effort,
                    "permission_mode": perm_mode
                }
            }

    def cancel(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> bool:
        ws_id = env_info.get("workspace_id")
        if ws_id and self.res_mgr.is_owned_workspace(ws_id):
            try:
                return self.herdr.close_workspace(ws_id)
            except Exception:
                return False
        return True

    def cleanup_attempt(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> None:
        ws_id = env_info.get("workspace_id")
        if ws_id and self.res_mgr.is_owned_workspace(ws_id):
            try:
                self.res_mgr.clean_workspace(ws_id)
            except Exception:
                pass


class OpenCodeAdapter(WorkerAdapter):
    """
    Worker adapter for OpenCode CLI non-interactive execution.
    Executes in isolated worktree and registered Herdr workspace/pane.
    Flags:
      opencode run "$(< prompt.md)" \\
        --dir "<worktree>" \\
        --model "<model>" \\
        --variant "<variant>" \\
        --format json \\
        --auto \\
        --pure
    """

    def __init__(self, worker_id: str, worker_config: dict, herdr_client: HerdrClient, resource_manager: ResourceManager):
        super().__init__(worker_id, worker_config, herdr_client, resource_manager)
        self.command = worker_config.get("command", "/root/.opencode/bin/opencode")
        self.profile_home = pathlib.Path(worker_config.get("profile_home", "/root/.opencode"))
        self.default_model = worker_config.get("default_model", "google/gemini-3.8-flash")
        self.reasoning_effort = worker_config.get("reasoning_effort", "high")
        self.native_cfg = worker_config.get("native", {})

    def prepare_environment(self, run_id: str, task_id: str, attempt_id: int, worktree_path: pathlib.Path) -> dict:
        label = f"factory_{task_id}_att_{attempt_id}"
        ws_id, pane_id = self.herdr.create_workspace(cwd=str(worktree_path), label=label)
        self.res_mgr.register_owned_workspace(ws_id)
        self.res_mgr.register_owned_pane(pane_id)
        return {
            "workspace_id": ws_id,
            "pane_id": pane_id,
            "worktree_path": str(worktree_path)
        }

    def execute(self, run_id: str, task_id: str, attempt_id: int,
                worktree_path: pathlib.Path, prompt_file: pathlib.Path,
                schema_file: pathlib.Path, timeout: int,
                task_attempt_dir: pathlib.Path, env_info: dict,
                model: str = None, effort: str = None) -> dict:
        output_json_path = task_attempt_dir / "worker_output.json"
        status_file_path = task_attempt_dir / "worker_status.txt"
        pane_id = env_info.get("pane_id")

        model = model or self.default_model
        variant = effort or self.reasoning_effort
        pure = "--pure" if self.native_cfg.get("pure", True) else ""
        auto = "--auto" if self.native_cfg.get("auto", True) else ""

        # Deterministic test harness mode
        if os.environ.get("FACTORY_TEST_HARNESS") == "1":
            behavior = os.environ.get("OPENCODE_TEST_BEHAVIOR", "SUCCESS")
            return self._handle_test_behavior(
                behavior, run_id, task_id, attempt_id, worktree_path,
                output_json_path, status_file_path, timeout, env_info,
                model=model, variant=variant
            )

        # Live authentication check
        has_auth = bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENCODE_API_KEY"))
        if not has_auth:
            return {
                "exit_code": 1,
                "timed_out": False,
                "error": "OpenCode authentication missing (no OPENROUTER_API_KEY or OPENCODE_API_KEY).",
                "data": {"status": "FAILED", "error": "AUTH_BLOCKED"},
                "provenance": {"auth_status": "AUTH_BLOCKED", "model": model, "reasoning_effort": variant}
            }

        # Build wrapper script for live opencode execution
        script_path = task_attempt_dir / "run_opencode.sh"
        cmd = [
            f'"{self.command}"',
            "run",
            f'"$(< \"{prompt_file}\")"',
            f'--dir "{worktree_path}"',
            f'--model "{model}"',
            f'--variant "{variant}"',
            "--format json",
            auto,
            pure
        ]
        script_body = (
            f"#!/usr/bin/env bash\n"
            f"cd \"{worktree_path}\"\n"
            f"{' '.join([c for c in cmd if c])} > \"{output_json_path}\" 2>&1\n"
            f"echo $? > \"{status_file_path}\"\n"
        )
        script_path.write_text(script_body, encoding="utf-8")
        os.chmod(script_path, 0o755)

        if pane_id:
            self.herdr.run_in_pane(pane_id, f'bash "{script_path}"')
        else:
            subprocess.Popen(["bash", str(script_path)], cwd=str(worktree_path))

        start_wait = time.time()
        while time.time() - start_wait < timeout:
            if status_file_path.exists() and status_file_path.stat().st_size > 0:
                break
            time.sleep(1)

        if not status_file_path.exists() or status_file_path.stat().st_size == 0:
            self.cancel(run_id, task_id, attempt_id, env_info)
            return {
                "exit_code": -1,
                "timed_out": True,
                "error": f"OpenCode worker timed out after {timeout}s",
                "raw_output": output_json_path.read_text(encoding="utf-8") if output_json_path.exists() else ""
            }

        try:
            exit_code = int(status_file_path.read_text().strip())
        except Exception:
            exit_code = -1

        raw_output = output_json_path.read_text(encoding="utf-8") if output_json_path.exists() else ""
        parsed = self._parse_opencode_output(raw_output, run_id, task_id, attempt_id, model=model, variant=variant)

        return {
            "exit_code": exit_code,
            "timed_out": False,
            "raw_output": raw_output,
            "data": parsed.get("task_data", {}),
            "provenance": parsed.get("provenance", {})
        }

    def _parse_opencode_output(self, raw_output: str, run_id: str, task_id: str, attempt_id: int,
                              model: str = "google/gemini-3.8-flash", variant: str = "high") -> dict:
        result = {
            "task_data": {},
            "provenance": {
                "model": model,
                "reasoning_effort": variant
            }
        }
        raw_output = raw_output.strip()
        if not raw_output:
            return result

        envelope = {}
        try:
            envelope = json.loads(raw_output)
        except Exception:
            for line in reversed(raw_output.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        envelope = json.loads(line)
                        break
                    except Exception:
                        pass

        if isinstance(envelope, dict):
            if "session_id" in envelope:
                result["provenance"]["session_id"] = envelope["session_id"]
            if "duration_ms" in envelope:
                result["provenance"]["duration_ms"] = envelope["duration_ms"]
            if "turns" in envelope:
                result["provenance"]["turns"] = envelope["turns"]
            if "model" in envelope:
                result["provenance"]["model"] = envelope["model"]
            if "variant" in envelope:
                result["provenance"]["reasoning_effort"] = envelope["variant"]

            if envelope.get("is_error") is True:
                result["task_data"] = {
                    "status": "FAILED",
                    "error": envelope.get("error") or envelope.get("result", "OpenCode execution error")
                }
                return result

            inner_text = envelope.get("result")
            inner_json = None
            if isinstance(inner_text, dict):
                inner_json = inner_text
            elif isinstance(inner_text, str):
                inner_json = extract_json_payload(inner_text, task_id)
            elif not inner_text and "status" in envelope:
                inner_json = envelope

            if inner_json:
                if inner_json.get("task_id") and inner_json.get("task_id") != task_id:
                    result["task_data"] = {"status": "FAILED", "error": f"Mismatched task_id: {inner_json.get('task_id')} != {task_id}"}
                    return result
                if inner_json.get("attempt_id") and inner_json.get("attempt_id") != attempt_id:
                    result["task_data"] = {"status": "FAILED", "error": f"Mismatched attempt_id: {inner_json.get('attempt_id')} != {attempt_id}"}
                    return result
                result["task_data"] = inner_json
                return result

        fallback_json = extract_json_payload(raw_output, task_id)
        if fallback_json:
            result["task_data"] = fallback_json
        return result

    def _handle_test_behavior(self, behavior: str, run_id: str, task_id: str, attempt_id: int,
                              worktree_path: pathlib.Path, output_json_path: pathlib.Path,
                              status_file_path: pathlib.Path, timeout: int, env_info: dict,
                              model: str = "google/gemini-3.8-flash", variant: str = "high") -> dict:
        if behavior == "TIMEOUT":
            self.cancel(run_id, task_id, attempt_id, env_info)
            return {"exit_code": -1, "timed_out": True, "error": f"OpenCode worker timed out after {timeout}s"}
        elif behavior == "ERROR":
            err_envelope = {"is_error": True, "error": "Simulated OpenCode failure", "result": "Execution error"}
            output_json_path.write_text(json.dumps(err_envelope), encoding="utf-8")
            status_file_path.write_text("1\n")
            return {
                "exit_code": 1,
                "timed_out": False,
                "raw_output": json.dumps(err_envelope),
                "data": {"status": "FAILED", "error": "Simulated OpenCode failure"},
                "provenance": {
                    "session_id": "opencode-test-session-err",
                    "model": model,
                    "reasoning_effort": variant
                }
            }
        elif behavior == "MALFORMED":
            output_json_path.write_text("NOT_JSON_AT_ALL", encoding="utf-8")
            status_file_path.write_text("0\n")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": "NOT_JSON_AT_ALL",
                "data": {},
                "provenance": {}
            }
        elif behavior == "ATTEMPT_MISMATCH":
            envelope = {
                "is_error": False,
                "session_id": "opencode-test-session-mismatch",
                "result": json.dumps({
                    "run_id": run_id,
                    "task_id": task_id,
                    "attempt_id": attempt_id + 99,
                    "status": "COMPLETED",
                    "summary": "Mismatched attempt",
                    "changed_files": []
                })
            }
            output_json_path.write_text(json.dumps(envelope), encoding="utf-8")
            status_file_path.write_text("0\n")
            parsed = self._parse_opencode_output(json.dumps(envelope), run_id, task_id, attempt_id, model=model, variant=variant)
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": json.dumps(envelope),
                "data": parsed.get("task_data", {}),
                "provenance": parsed.get("provenance", {})
            }
        else:  # SUCCESS
            inner_data = {
                "run_id": run_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "status": "COMPLETED",
                "summary": f"Successfully finished {task_id} via OpenCode",
                "changed_files": []
            }
            envelope = {
                "is_error": False,
                "session_id": f"opencode-sess-{task_id}-{attempt_id}",
                "duration_ms": 2900,
                "turns": 2,
                "model": model,
                "variant": variant,
                "result": json.dumps(inner_data)
            }
            output_json_path.write_text(json.dumps(envelope), encoding="utf-8")
            status_file_path.write_text("0\n")
            return {
                "exit_code": 0,
                "timed_out": False,
                "raw_output": json.dumps(envelope),
                "data": inner_data,
                "provenance": {
                    "session_id": f"opencode-sess-{task_id}-{attempt_id}",
                    "duration_ms": 2900,
                    "turns": 2,
                    "model": model,
                    "reasoning_effort": variant
                }
            }

    def cancel(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> bool:
        ws_id = env_info.get("workspace_id")
        if ws_id and self.res_mgr.is_owned_workspace(ws_id):
            try:
                return self.herdr.close_workspace(ws_id)
            except Exception:
                return False
        return True

    def cleanup_attempt(self, run_id: str, task_id: str, attempt_id: int, env_info: dict) -> None:
        ws_id = env_info.get("workspace_id")
        if ws_id and self.res_mgr.is_owned_workspace(ws_id):
            try:
                self.res_mgr.clean_workspace(ws_id)
            except Exception:
                pass


ADAPTER_REGISTRY = {
    "agy": AgyAdapter,
    "antigravity_cli": AgyAdapter,
    "droid": DroidAdapter,
    "droid_cli": DroidAdapter,
    "factory_cli": DroidAdapter,
    "codex": CodexAdapter,
    "codex_cli": CodexAdapter,
    "claude": ClaudeAdapter,
    "claude_cli": ClaudeAdapter,
    "opencode": OpenCodeAdapter,
    "opencode_cli": OpenCodeAdapter
}


def register_adapter(name: str, adapter_cls: type):
    ADAPTER_REGISTRY[name] = adapter_cls


def get_adapter(worker_id: str, worker_config: dict, herdr: HerdrClient, res_mgr: ResourceManager) -> WorkerAdapter:
    adapter_name = worker_config.get("adapter") or worker_config.get("invocation_adapter", "agy")
    if adapter_name not in ADAPTER_REGISTRY:
        if os.environ.get("FACTORY_TEST_HARNESS") == "1":
            try:
                from factory_tests.test_v3_capabilities import FakeWorkerAdapter
                register_adapter("fake_worker", FakeWorkerAdapter)
            except Exception:
                pass
    if adapter_name not in ADAPTER_REGISTRY:
        raise ValueError(f"Unknown worker adapter '{adapter_name}' declared for worker '{worker_id}'")
    cls = ADAPTER_REGISTRY[adapter_name]
    return cls(worker_id, worker_config, herdr, res_mgr)


# ==============================================================================
# Harness Profiles Data Model, Validation & Execution Profile Routing
# ==============================================================================

HARNESS_PROFILES_PATH = PROJECT_ROOT / "harness_profiles.json"

SUPPORTED_HARNESS_EFFORTS = {
    "agy": {"low", "medium", "high"},
    "droid": {"none", "low", "medium", "high", "xhigh"},
    "codex": {"low", "medium", "high", "xhigh"},
    "claude": {"low", "medium", "high", "xhigh", "max"},
    "opencode": {"default", "fast", "medium", "high", "deep", "free"}
}

ALLOWED_CODEX_SANDBOXES = {"read-only", "workspace-write", "danger-full-access"}

def derive_execution_class(task_type: str, explicit_class: str = None) -> str:
    """Deterministically derives routine, standard, or deep execution class."""
    if explicit_class in {"routine", "standard", "deep"}:
        return explicit_class
    if task_type in {"mechanical_change", "testing", "fixture", "support"}:
        return "routine"
    if task_type in {"debugging", "conflict_resolution", "audit"}:
        return "deep"
    return "standard"

ROUTING_PRIORITY_MATRIX = {
    ("specification", "routine"): ["agy-spec-high", "claude-sonnet5-medium", "claude-sonnet5-high"],
    ("specification", "standard"): ["agy-spec-high", "claude-sonnet5-high"],
    ("specification", "deep"): ["agy-spec-high", "claude-sonnet5-high"],
    ("planning", "standard"): ["agy-spec-high", "claude-sonnet5-high"],
    ("backend", "routine"): ["droid-backend-medium", "agy-backend-medium", "droid-backend-xhigh", "agy-backend-high", "droid-backend-deep"],
    ("backend", "standard"): ["droid-backend-xhigh", "agy-backend-high", "droid-backend-medium", "agy-backend-medium", "droid-backend-deep"],
    ("backend", "deep"): ["droid-backend-xhigh", "agy-backend-high", "droid-backend-deep"],
    ("frontend", "routine"): ["codex-luna-medium", "agy-frontend-medium", "codex-luna-high", "agy-frontend-high", "codex-frontend-high"],
    ("frontend", "standard"): ["codex-luna-high", "agy-frontend-high", "codex-luna-medium", "agy-frontend-medium", "codex-frontend-high"],
    ("frontend", "deep"): ["codex-luna-xhigh", "codex-luna-high", "agy-frontend-high", "codex-frontend-high"],
    ("testing", "routine"): ["claude-sonnet5-high", "agy-tests-medium", "claude-sonnet5-medium", "opencode-gemini-high", "opencode-mimo-free", "agy-backend-high"],
    ("testing", "standard"): ["claude-sonnet5-high", "agy-tests-medium", "opencode-gemini-high", "agy-backend-high"],
    ("testing", "deep"): ["claude-sonnet5-high", "agy-tests-medium", "agy-backend-high"],
    ("fixture", "routine"): ["opencode-gemini-high", "opencode-mimo-free", "agy-tests-medium"],
    ("support", "routine"): ["opencode-gemini-high", "opencode-mimo-free", "agy-tests-medium"],
    ("coding", "routine"): ["opencode-gemini-high", "opencode-mimo-free", "agy-tests-medium", "agy-backend-medium"],
    ("mechanical_change", "routine"): ["droid-backend-medium", "opencode-gemini-high", "droid-backend-xhigh", "droid-backend-deep"],
    ("mechanical_change", "standard"): ["droid-backend-xhigh", "droid-backend-medium", "opencode-gemini-high", "droid-backend-deep"],
    ("integration", "routine"): ["agy-integration-high", "agy-backend-medium"],
    ("integration", "standard"): ["agy-integration-high", "agy-backend-high"],
    ("integration", "deep"): ["agy-integration-high", "agy-backend-high"],
    ("debugging", "deep"): ["droid-backend-xhigh", "agy-integration-high", "agy-backend-high", "droid-backend-deep"],
    ("conflict_resolution", "deep"): ["agy-integration-high"],
    ("review", "routine"): ["agy-audit-high", "claude-sonnet5-medium"],
    ("review", "standard"): ["agy-audit-high", "claude-sonnet5-high"],
    ("review", "deep"): ["agy-audit-high", "claude-sonnet5-high"],
    ("audit", "deep"): ["agy-audit-high", "claude-sonnet5-high"],
    ("audit", "standard"): ["agy-audit-high", "claude-sonnet5-high"]
}

PROFILE_TASK_TYPE_PREFERENCES = {
    "specification": ["agy-spec-high", "claude-sonnet5-high"],
    "planning": ["agy-spec-high", "claude-sonnet5-high"],
    "backend": ["droid-backend-deep", "agy-backend-high", "droid-backend-xhigh", "droid-backend-medium"],
    "frontend": ["codex-frontend-high", "agy-frontend-high", "codex-luna-high", "codex-luna-medium", "codex-luna-xhigh"],
    "testing": ["agy-tests-medium", "claude-sonnet5-high", "opencode-gemini-high", "opencode-mimo-free", "agy-backend-high"],
    "fixture": ["opencode-gemini-high", "opencode-mimo-free", "agy-tests-medium"],
    "support": ["opencode-gemini-high", "opencode-mimo-free", "agy-tests-medium"],
    "debugging": ["droid-backend-deep", "droid-backend-xhigh", "agy-backend-high", "agy-integration-high"],
    "mechanical_change": ["droid-backend-medium", "opencode-gemini-high", "droid-backend-xhigh", "droid-backend-deep"],
    "integration": ["agy-integration-high", "agy-backend-high"],
    "conflict_resolution": ["agy-integration-high"],
    "review": ["agy-audit-high", "claude-sonnet5-high"],
    "audit": ["agy-audit-high", "claude-sonnet5-high"]
}

WORKER_CAPABILITIES = {
    "agy": {"implementation", "review", "planning", "testing"},
    "agy2": {"planning", "specification", "review"},
    "agy3": {"coding", "backend", "debugging"},
    "agy4": {"coding", "frontend"},
    "agy5": {"coding", "testing"},
    "agy6": {"integration", "debugging", "conflict_resolution"},
    "agy7": {"review", "audit"},
    "droid": {"coding", "backend", "testing", "debugging", "mechanical_change"},
    "codex": {"coding", "frontend", "debugging", "testing", "review"},
    "claude": {"coding", "testing", "specification", "review"},
    "opencode": {"coding", "testing", "support", "fixture", "mechanical_change"}
}

TASK_TYPE_PREFERENCES = {
    "specification": ["agy2", "claude"],
    "planning": ["agy2", "claude"],
    "backend": ["droid", "agy3"],
    "frontend": ["codex", "agy4"],
    "testing": ["claude", "agy5", "opencode", "droid"],
    "fixture": ["opencode", "agy5"],
    "support": ["opencode", "agy5"],
    "debugging": ["droid", "agy3", "agy6"],
    "mechanical_change": ["droid", "opencode"],
    "integration": ["agy6", "droid"],
    "conflict_resolution": ["agy6", "droid"],
    "review": ["agy7", "claude"],
    "audit": ["agy7", "claude"]
}


def load_harness_profiles(profiles_path: pathlib.Path = None) -> dict:
    path = profiles_path or HARNESS_PROFILES_PATH
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("profiles", {})
    except Exception:
        return {}


def validate_profile(profile_id: str, profile: dict) -> list:
    errors = []
    if not re.match(r"^[a-z0-9][a-z0-9._-]*$", profile_id):
        errors.append(f"Profile ID '{profile_id}' violates naming pattern: must start with alphanumeric and contain only [a-z0-9._-]")

    if profile.get("id") != profile_id:
        errors.append(f"Profile 'id' field '{profile.get('id')}' does not match key '{profile_id}'")

    adapter = profile.get("adapter")
    if adapter not in ADAPTER_REGISTRY:
        errors.append(f"Profile '{profile_id}' references unknown adapter '{adapter}'")

    harness = profile.get("harness")
    effort = profile.get("effort")
    if harness in SUPPORTED_HARNESS_EFFORTS:
        allowed_efforts = SUPPORTED_HARNESS_EFFORTS[harness]
        if effort not in allowed_efforts:
            errors.append(f"Profile '{profile_id}' has invalid effort '{effort}' for harness '{harness}' (allowed: {allowed_efforts})")
    elif harness is not None:
        errors.append(f"Profile '{profile_id}' references unknown harness '{harness}'")

    if harness == "codex":
        native = profile.get("native", {})
        sandbox = native.get("sandbox")
        if sandbox and sandbox not in ALLOWED_CODEX_SANDBOXES:
            errors.append(f"Profile '{profile_id}' declares invalid Codex sandbox '{sandbox}' (allowed: {ALLOWED_CODEX_SANDBOXES})")

    if "model" not in profile or not profile["model"]:
        errors.append(f"Profile '{profile_id}' must specify a non-empty 'model'")

    if "capabilities" not in profile or not isinstance(profile["capabilities"], list):
        errors.append(f"Profile '{profile_id}' must define 'capabilities' list")

    return errors


def validate_all_profiles(profiles_path: pathlib.Path = None) -> dict:
    profiles = load_harness_profiles(profiles_path)
    results = {}
    for pid, pdata in profiles.items():
        results[pid] = validate_profile(pid, pdata)
    return results


def resolve_task_worker(task_id: str, task_def: dict, factory_config: dict,
                        busy_workers: set = None, busy_profiles: set = None,
                        profiles_path: pathlib.Path = None) -> tuple:
    """
    Deterministically routes a task to an eligible worker based on execution profiles and capabilities.
    Section 20 priority order:
      specification: agy-spec-high
      backend:       droid-backend-deep -> agy-backend-high
      frontend:      codex-frontend-high -> agy-frontend-high
      testing:       agy-tests-medium -> agy-backend-high
      review:        agy-review-high -> agy-audit-high
      audit:         agy-audit-high
      integration:   agy-integration-high -> agy-backend-high

    Returns: (worker_id, routing_metadata, status)
      where status is 'ROUTED', 'BUSY', or 'BLOCKED'
    """
    busy_workers = set(busy_workers or set())
    busy_profiles = set(busy_profiles or set())
    worker_registry = factory_config.get("worker_registry", {})
    profiles = load_harness_profiles(profiles_path)

    # 1. Explicit worker assignment (legacy and backward-compatibility mode)
    explicit_wid = task_def.get("worker_id") or task_def.get("worker")
    if explicit_wid:
        if explicit_wid in worker_registry:
            w_cfg = worker_registry[explicit_wid]
            adapter = w_cfg.get("adapter", "agy")
            concurrency_allowed = w_cfg.get("concurrency_eligibility", False)
            is_busy = (explicit_wid in busy_workers) and (not concurrency_allowed)
            metadata = {
                "routing_mode": "explicit",
                "task_type": task_def.get("task_type", "explicit"),
                "required_capabilities": task_def.get("requires", []),
                "requirements": task_def.get("requires", []),
                "eligible_candidates": [explicit_wid],
                "busy_candidates": [explicit_wid] if is_busy else [],
                "selected_worker": explicit_wid,
                "selected_adapter": adapter,
                "selection_reason": f"Explicit worker assignment to '{explicit_wid}'"
            }
            if is_busy:
                return explicit_wid, metadata, "BUSY"
            return explicit_wid, metadata, "ROUTED"
        else:
            metadata = {
                "routing_mode": "explicit",
                "error": f"Unknown explicit worker: {explicit_wid}"
            }
            return None, metadata, "BLOCKED"

    # 2. Execution Profile Routing (v5 and v6 mode if profiles loaded)
    task_type = task_def.get("task_type", "implementation")
    explicit_class = task_def.get("execution_class")
    execution_class = derive_execution_class(task_type, explicit_class)
    requires = set(task_def.get("requires", []))

    if profiles:
        if explicit_class:
            priority_pids = ROUTING_PRIORITY_MATRIX.get((task_type, execution_class)) or PROFILE_TASK_TYPE_PREFERENCES.get(task_type, [])
        else:
            priority_pids = PROFILE_TASK_TYPE_PREFERENCES.get(task_type) or ROUTING_PRIORITY_MATRIX.get((task_type, execution_class), [])
        all_pids = list(profiles.keys())
        ordered_pids = [p for p in priority_pids if p in all_pids]
        for p in all_pids:
            if p not in ordered_pids:
                ordered_pids.append(p)

        invalid_profiles = []
        auth_blocked_profiles = []
        capability_matched_profiles = []

        is_test_harness = os.environ.get("FACTORY_TEST_HARNESS") == "1"

        for pid in ordered_pids:
            p = profiles[pid]
            if not p.get("enabled", True):
                continue

            # Validation check (exclude drifted profiles)
            errs = validate_profile(pid, p)
            if errs:
                invalid_profiles.append({"profile_id": pid, "errors": errs})
                continue

            # Capabilities check
            p_caps = set(p.get("capabilities", []))
            if not requires.issubset(p_caps):
                continue

            capability_matched_profiles.append(pid)

            # Auth check
            harness = p.get("harness")
            if not is_test_harness:
                if harness == "droid" and not os.environ.get("FACTORY_API_KEY"):
                    auth_blocked_profiles.append(pid)
                    continue
                if harness == "codex":
                    has_auth = bool(os.environ.get("OPENAI_API_KEY"))
                    if not has_auth:
                        auth_blocked_profiles.append(pid)
                        continue
                if harness == "claude":
                    has_auth = bool(os.environ.get("CLAUDE_CODE_TOKEN") or os.environ.get("ANTHROPIC_API_KEY"))
                    if not has_auth:
                        auth_blocked_profiles.append(pid)
                        continue
                if harness == "opencode":
                    has_auth = bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENCODE_API_KEY"))
                    if not has_auth:
                        auth_blocked_profiles.append(pid)
                        continue
                    if pid == "opencode-gemini-high" and not os.environ.get("OPENCODE_API_KEY"):
                        # Gemini on openrouter restricted unless authenticated direct
                        auth_blocked_profiles.append(pid)
                        continue

        if not capability_matched_profiles:
            metadata = {
                "routing_mode": "execution_profile",
                "task_type": task_type,
                "execution_class": execution_class,
                "required_capabilities": list(requires),
                "requirements": list(requires),
                "eligible_candidates": [],
                "eligible_profiles": [],
                "busy_candidates": [],
                "busy_profiles": [],
                "invalid_profiles": invalid_profiles,
                "auth_blocked_profiles": auth_blocked_profiles,
                "selected_worker": None,
                "selected_adapter": None,
                "selection_reason": f"No worker satisfies required capabilities: {list(requires)}"
            }
            return None, metadata, "BLOCKED"

        # Eligible profiles that are valid and authenticated
        eligible_profiles = [p for p in capability_matched_profiles if p not in auth_blocked_profiles]

        if not eligible_profiles:
            metadata = {
                "routing_mode": "execution_profile",
                "task_type": task_type,
                "execution_class": execution_class,
                "required_capabilities": list(requires),
                "requirements": list(requires),
                "eligible_candidates": [],
                "eligible_profiles": [],
                "busy_candidates": [],
                "busy_profiles": [],
                "invalid_profiles": invalid_profiles,
                "auth_blocked_profiles": auth_blocked_profiles,
                "selected_worker": None,
                "selected_adapter": None,
                "selection_reason": f"All capable profiles ({', '.join(capability_matched_profiles)}) are blocked by authentication"
            }
            return None, metadata, "BLOCKED"

        # Candidate lists for compatibility with v4/v5
        eligible_candidates = []
        for pid in eligible_profiles:
            wid = profiles[pid].get("worker_identity", pid)
            if wid not in eligible_candidates:
                eligible_candidates.append(wid)

        available_profiles = []
        busy_candidates_list = []
        busy_profiles_list = []
        for pid in eligible_profiles:
            p = profiles[pid]
            wid = p.get("worker_identity", pid)
            is_busy = (pid in busy_profiles) or (wid in busy_workers)
            if is_busy:
                if wid not in busy_candidates_list:
                    busy_candidates_list.append(wid)
                if pid not in busy_profiles_list:
                    busy_profiles_list.append(pid)
            else:
                available_profiles.append(pid)

        if not available_profiles:
            metadata = {
                "routing_mode": "execution_profile",
                "task_type": task_type,
                "execution_class": execution_class,
                "required_capabilities": list(requires),
                "requirements": list(requires),
                "eligible_candidates": eligible_candidates,
                "eligible_profiles": eligible_profiles,
                "busy_candidates": busy_candidates_list,
                "busy_profiles": busy_profiles_list or list(busy_profiles),
                "invalid_profiles": invalid_profiles,
                "auth_blocked_profiles": auth_blocked_profiles,
                "selected_worker": None,
                "selected_adapter": None,
                "selection_reason": f"All eligible candidates ({', '.join(eligible_profiles)}) are busy"
            }
            return None, metadata, "BUSY"

        selected_pid = available_profiles[0]
        sp = profiles[selected_pid]
        wid = sp.get("worker_identity", selected_pid)
        adapter = sp.get("adapter", "agy")
        model = sp.get("model")
        effort = sp.get("effort")

        metadata = {
            "routing_mode": "execution_profile",
            "task_type": task_type,
            "execution_class": execution_class,
            "required_capabilities": list(requires),
            "requirements": list(requires),
            "eligible_candidates": eligible_candidates,
            "eligible_profiles": eligible_profiles,
            "busy_candidates": busy_candidates_list,
            "busy_profiles": list(busy_profiles),
            "invalid_profiles": invalid_profiles,
            "auth_blocked_profiles": auth_blocked_profiles,
            "selected_profile_id": selected_pid,
            "selected_worker": wid,
            "worker_identity": wid,
            "selected_adapter": adapter,
            "harness": sp.get("harness", adapter),
            "model": model,
            "effort": effort,
            "native": sp.get("native", {}),
            "selection_reason": f"Selected preferred available profile '{selected_pid}' from eligible pool {eligible_profiles}"
        }
        return wid, metadata, "ROUTED"

    # Fallback to legacy v4 routing if no profiles available
    priority_order = TASK_TYPE_PREFERENCES.get(task_type, [])
    all_workers = list(worker_registry.keys())

    ordered_candidates = [w for w in priority_order if w in all_workers]
    for w in all_workers:
        if w not in ordered_candidates:
            ordered_candidates.append(w)

    eligible = []
    for wid in ordered_candidates:
        w_cfg = worker_registry.get(wid, {})
        if not w_cfg.get("enabled", True):
            continue
        if wid == "droid" and not os.environ.get("FACTORY_API_KEY") and os.environ.get("FACTORY_TEST_HARNESS") != "1":
            continue
        w_caps = set(WORKER_CAPABILITIES.get(wid, w_cfg.get("capabilities", [])))
        if requires.issubset(w_caps):
            eligible.append(wid)

    if not eligible:
        metadata = {
            "routing_mode": "deterministic_capability",
            "task_type": task_type,
            "required_capabilities": list(requires),
            "requirements": list(requires),
            "eligible_candidates": [],
            "busy_candidates": [],
            "selected_worker": None,
            "selected_adapter": None,
            "selection_reason": f"No worker satisfies required capabilities: {list(requires)}"
        }
        return None, metadata, "BLOCKED"

    busy_candidates = [w for w in eligible if w in busy_workers]
    available_candidates = [w for w in eligible if w not in busy_workers]

    if not available_candidates:
        metadata = {
            "routing_mode": "deterministic_capability",
            "task_type": task_type,
            "required_capabilities": list(requires),
            "requirements": list(requires),
            "eligible_candidates": eligible,
            "busy_candidates": busy_candidates,
            "selected_worker": None,
            "selected_adapter": None,
            "selection_reason": f"All eligible candidates ({', '.join(eligible)}) are busy"
        }
        return None, metadata, "BUSY"

    selected = available_candidates[0]
    adapter = worker_registry[selected].get("adapter", "agy")
    metadata = {
        "routing_mode": "deterministic_capability",
        "task_type": task_type,
        "required_capabilities": list(requires),
        "requirements": list(requires),
        "eligible_candidates": eligible,
        "busy_candidates": busy_candidates,
        "selected_worker": selected,
        "worker_identity": selected,
        "selected_adapter": adapter,
        "selection_reason": f"Selected preferred available candidate '{selected}' from eligible pool {eligible}"
    }
    return selected, metadata, "ROUTED"


def explain_task_routing(plan_file_or_data, task_id: str, profiles_path: pathlib.Path = None, run_id: str = None) -> dict:
    """
    Non-mutating routing evaluation engine. Explains deterministic candidate ranking,
    capability matching, authentication status, busy state, and final profile decision.
    """
    if isinstance(plan_file_or_data, (str, pathlib.Path)):
        with open(plan_file_or_data, "r", encoding="utf-8") as f:
            plan_data = json.load(f)
    else:
        plan_data = plan_file_or_data

    target_task = None
    for t in plan_data.get("tasks", []):
        if t.get("task_id") == task_id:
            target_task = t
            break

    if not target_task:
        raise ValueError(f"Task '{task_id}' not found in plan")

    task_type = target_task.get("task_type", "implementation")
    explicit_class = target_task.get("execution_class")
    execution_class = derive_execution_class(task_type, explicit_class)
    requires = target_task.get("requires", [])
    requires_set = set(requires)

    profiles = load_harness_profiles(profiles_path)
    factory_config = {}
    if FACTORY_CONFIG_PATH.exists():
        try:
            with open(FACTORY_CONFIG_PATH, "r", encoding="utf-8") as f:
                factory_config = json.load(f)
        except Exception:
            pass

    # Determine busy state if run_id provided
    busy_workers = set()
    busy_profiles = set()
    if run_id:
        run_manifest = RUNS_DIR / run_id / "manifest.json"
        if run_manifest.exists():
            try:
                with open(run_manifest, "r", encoding="utf-8") as f:
                    mdata = json.load(f)
                for tid, trec in mdata.get("tasks", {}).items():
                    if trec.get("canonical_state") in ("DISPATCHING", "RUNNING", "PATH_VALIDATING", "VALIDATING", "COMMITTING", "COMMITTED", "INTEGRATING"):
                        if trec.get("worker_id"):
                            busy_workers.add(trec["worker_id"])
                        if trec.get("profile_id"):
                            busy_profiles.add(trec["profile_id"])
            except Exception:
                pass

    if explicit_class:
        pref_list = ROUTING_PRIORITY_MATRIX.get((task_type, execution_class)) or PROFILE_TASK_TYPE_PREFERENCES.get(task_type, [])
    else:
        pref_list = PROFILE_TASK_TYPE_PREFERENCES.get(task_type) or ROUTING_PRIORITY_MATRIX.get((task_type, execution_class), [])
    ordered_pids = [p for p in pref_list if p in profiles]
    for p in profiles:
        if p not in ordered_pids:
            ordered_pids.append(p)

    profile_evaluations = []
    eligible_pool = []

    for rank, pid in enumerate(ordered_pids, start=1):
        p = profiles[pid]
        p_caps = set(p.get("capabilities", []))
        caps_match = requires_set.issubset(p_caps)
        missing_caps = list(requires_set - p_caps)

        harness = p.get("harness")
        is_test_harness = os.environ.get("FACTORY_TEST_HARNESS") == "1"
        if is_test_harness:
            auth_status = "HARNESS_OVERRIDE"
        elif harness == "droid":
            auth_status = "AVAILABLE" if os.environ.get("FACTORY_API_KEY") else "AUTH_BLOCKED"
        elif harness == "codex":
            auth_status = "AVAILABLE" if os.environ.get("OPENAI_API_KEY") else "AUTH_BLOCKED"
        elif harness == "claude":
            auth_status = "AVAILABLE" if (os.environ.get("CLAUDE_CODE_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")) else "AUTH_BLOCKED"
        elif harness == "opencode":
            has_auth = bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENCODE_API_KEY"))
            if not has_auth:
                auth_status = "AUTH_BLOCKED"
            elif pid == "opencode-gemini-high" and not os.environ.get("OPENCODE_API_KEY"):
                auth_status = "AUTH_BLOCKED"
            else:
                auth_status = "AVAILABLE"
        else:
            auth_status = "AVAILABLE"

        errs = validate_profile(pid, p)
        is_valid = len(errs) == 0

        wid = p.get("worker_identity", pid)
        is_busy = (pid in busy_profiles) or (wid in busy_workers)
        busy_status = "BUSY" if is_busy else "IDLE"

        if not is_valid:
            eligibility = "INVALID"
            reason = f"Profile failed validation: {'; '.join(errs)}"
        elif not caps_match:
            eligibility = "CAPABILITY_MISMATCH"
            reason = f"Missing capabilities: {missing_caps}"
        elif auth_status == "AUTH_BLOCKED":
            eligibility = "AUTH_BLOCKED"
            reason = f"Authentication missing for harness '{harness}'"
        elif is_busy:
            eligibility = "BUSY"
            reason = f"Worker '{wid}' or profile '{pid}' is currently busy"
        else:
            eligibility = "ELIGIBLE"
            reason = "Matches all required capabilities, valid, authenticated, and idle"
            eligible_pool.append(pid)

        profile_evaluations.append({
            "priority_rank": rank,
            "profile_id": pid,
            "name": p.get("name", pid),
            "harness": harness,
            "adapter": p.get("adapter"),
            "model": p.get("model"),
            "effort": p.get("effort"),
            "capability_match": caps_match,
            "missing_capabilities": missing_caps,
            "auth_status": auth_status,
            "busy_status": busy_status,
            "eligibility": eligibility,
            "eligibility_reason": reason
        })

    wid, meta, status = resolve_task_worker(
        task_id, target_task, factory_config,
        busy_workers=busy_workers, busy_profiles=busy_profiles,
        profiles_path=profiles_path
    )

    final_decision = {
        "status": status,
        "selected_profile": meta.get("selected_profile_id"),
        "selected_worker": wid,
        "selected_adapter": meta.get("selected_adapter"),
        "reason": meta.get("selection_reason", "")
    }

    return {
        "task_id": task_id,
        "task_type": task_type,
        "execution_class": execution_class,
        "required_capabilities": requires,
        "profiles": profile_evaluations,
        "final_decision": final_decision
    }


# ==============================================================================
# One-Way Kanban Board Projector
# ==============================================================================

class HerdrBoardProjector:
    """
    One-way Kanban projection engine translating Factory state into herdr-board cards.
    Enforces strict one-way authority: Factory is the single source of truth.
    Maintains .agy-factory/board/mapping.json and cards.json.
    Ensures idempotency, self-correction upon manual move, and offline recovery.
    """
    COLUMNS = ["Backlog", "Ready", "Running", "Blocked", "Review", "Done", "Failed"]

    STATE_TO_COLUMN = {
        "PENDING": "Backlog",
        "READY": "Ready",
        "DISPATCHING": "Running",
        "RUNNING": "Running",
        "RESULT_RECEIVED": "Running",
        "PATH_VALIDATING": "Running",
        "VALIDATING": "Running",
        "COMMITTING": "Running",
        "COMMITTED": "Running",
        "INTEGRATING": "Running",
        "BLOCKED": "Blocked",
        "INTEGRATED": "Review",
        "COMPLETED": "Done",
        "FAILED": "Failed",
        "TIMED_OUT": "Failed",
        "CONFLICTED": "Failed",
        "CANCELLED": "Failed"
    }

    def __init__(self, root_dir: pathlib.Path = None):
        self.root_dir = root_dir or PROJECT_ROOT
        self.runs_dir = self.root_dir / ".agy-factory" / "runs"
        self.board_dir = self.root_dir / ".agy-factory" / "board"
        self.board_dir.mkdir(parents=True, exist_ok=True)
        self.mapping_file = self.board_dir / "mapping.json"
        self.cards_file = self.board_dir / "cards.json"
        self.mapping = self._load_json(self.mapping_file, default={})
        self.cards = self._load_json(self.cards_file, default={})

    def _load_json(self, path: pathlib.Path, default=None):
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return default if default is not None else {}
        return default if default is not None else {}

    def _save(self):
        atomic_write_json(self.mapping_file, self.mapping)
        atomic_write_json(self.cards_file, self.cards)

    def sync(self, run_id: str = None) -> dict:
        """
        Synchronizes Factory state to herdr-board cards.
        Idempotent: running repeatedly produces zero duplicate cards.
        Self-correcting: restores any manually moved card to its canonical column.
        """
        runs_to_sync = []
        if run_id:
            runs_to_sync = [self.runs_dir / run_id]
        else:
            if self.runs_dir.exists():
                runs_to_sync = sorted(list(self.runs_dir.glob("run-*")))

        synced_cards = []
        for r_dir in runs_to_sync:
            m_file = r_dir / "manifest.json"
            if not m_file.exists():
                continue
            try:
                with open(m_file, "r", encoding="utf-8") as f:
                    m_data = json.load(f)
            except Exception:
                continue

            r_id = m_data.get("run_id", r_dir.name)
            for tid, tinfo in m_data.get("tasks", {}).items():
                key = f"{r_id}:{tid}"
                if key not in self.mapping:
                    self.mapping[key] = f"card-{len(self.mapping) + 1:04d}"
                card_id = self.mapping[key]

                canonical_state = tinfo.get("canonical_state", tinfo.get("status", "PENDING"))
                target_col = self.STATE_TO_COLUMN.get(canonical_state, "Backlog")

                profile_id = tinfo.get("profile_id") or tinfo.get("profile") or tinfo.get("worker_id")
                harness = tinfo.get("harness") or tinfo.get("adapter", "agy")
                model = tinfo.get("model", "unknown")
                effort = tinfo.get("effort", "standard")

                card = {
                    "card_id": card_id,
                    "run_id": r_id,
                    "task_id": tid,
                    "column": target_col,
                    "canonical_state": canonical_state,
                    "worker_id": tinfo.get("worker_id"),
                    "profile": profile_id,
                    "harness": harness,
                    "model": model,
                    "effort": effort,
                    "adapter": tinfo.get("adapter"),
                    "attempt_id": tinfo.get("current_attempt_id", 0),
                    "task_type": tinfo.get("task_type"),
                    "dependencies": tinfo.get("dependencies", []),
                    "branch": tinfo.get("branch"),
                    "commit": tinfo.get("commit_hash"),
                    "reason": tinfo.get("error") or tinfo.get("block_reason"),
                    "description": f"Task: {tid}\nProfile: {profile_id}\nHarness: {harness}\nModel: {model} ({effort})\nState: {canonical_state}",
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                }
                self.cards[card_id] = card
                synced_cards.append(card_id)

        self._save()

        # Record board snapshot history
        try:
            history_file = self.board_dir / "history.jsonl"
            history_entry = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "run_id": run_id,
                "columns": {col: [c["task_id"] for c in self.cards.values() if c.get("column") == col] for col in self.COLUMNS}
            }
            with open(history_file, "a", encoding="utf-8") as hf:
                hf.write(json.dumps(history_entry) + "\n")
        except Exception:
            pass

        # Check if actual board CLI is installed locally and daemon running
        board_bin = self.root_dir / ".tools" / "bin" / "board"
        if board_bin.exists() and os.access(board_bin, os.X_OK):
            try:
                subprocess.run([str(board_bin), "card", "sync"], cwd=str(self.root_dir), capture_output=True, timeout=5)
            except Exception:
                pass

        return {
            "status": "OK",
            "synced_cards_count": len(synced_cards),
            "total_cards": len(self.cards),
            "run_id": run_id
        }

    def get_status(self) -> dict:
        board_bin = self.root_dir / ".tools" / "bin" / "board"
        has_bin = board_bin.exists() and os.access(board_bin, os.X_OK)

        columns_view = {col: [] for col in self.COLUMNS}
        for card_id, card in self.cards.items():
            col = card.get("column", "Backlog")
            if col in columns_view:
                columns_view[col].append(card)

        return {
            "authority": "factory (one-way)",
            "columns": self.COLUMNS,
            "columns_view": columns_view,
            "total_cards": len(self.cards),
            "mapping_count": len(self.mapping),
            "board_binary_present": has_bin,
            "compatibility_status": "BLOCKED_EXTERNAL_COMPATIBILITY" if not has_bin else "OK",
            "auto_dispatch": False
        }



# ==============================================================================
# Preflight and Plan Validation
# ==============================================================================

def validate_plan_file(plan_path: pathlib.Path, factory_config: dict = None) -> list:
    """
    Validates a plan against structural, dependency, and security constraints.
    Supports arbitrary DAG dependencies.
    Returns a list of error strings (empty list indicates a valid plan).
    """
    errors = []
    if not plan_path.exists():
        return [f"Plan file does not exist: {plan_path}"]

    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)
    except Exception as e:
        return [f"Malformed plan JSON: {e}"]

    if factory_config is None and FACTORY_CONFIG_PATH.exists():
        with open(FACTORY_CONFIG_PATH, "r", encoding="utf-8") as f:
            factory_config = json.load(f)

    worker_registry = factory_config.get("worker_registry", {}) if factory_config else {}

    for field in ["plan_id", "name", "version"]:
        if field not in plan:
            errors.append(f"Missing required top-level field: '{field}'")

    has_waves = "waves" in plan and isinstance(plan.get("waves"), list)
    has_tasks = "tasks" in plan and isinstance(plan.get("tasks"), list)
    if not has_waves and not has_tasks:
        errors.append("Missing required top-level field: 'waves'")
        return errors

    task_defs = []
    if has_waves:
        for wave in plan["waves"]:
            if "wave_index" not in wave or "tasks" not in wave:
                errors.append(f"Wave missing 'wave_index' or 'tasks': {wave}")
                continue
            task_defs.extend(wave.get("tasks", []))
    if has_tasks:
        task_defs.extend(plan["tasks"])

    task_ids = set()
    dependencies_graph = {}

    for task in task_defs:
        tid = task.get("task_id")
        if not tid:
            errors.append("Task definition is missing 'task_id'")
            continue
        if tid in task_ids:
            errors.append(f"Duplicate task_id detected: '{tid}'")
        task_ids.add(tid)

        wid = task.get("worker_id") or task.get("worker")
        ttype = task.get("task_type")
        if not wid and not ttype:
            errors.append(f"Task '{tid}' must specify either 'worker_id' or 'task_type'")
        elif wid and worker_registry and wid not in worker_registry:
            errors.append(f"Task '{tid}' specifies unknown worker: '{wid}'")

        deps = task.get("dependencies", [])
        dependencies_graph[tid] = deps

        for p in task.get("allowed_paths", []):
            if not is_path_safe_under_root(p, PROJECT_ROOT):
                errors.append(f"Task '{tid}' specifies unsafe path escaping project root: '{p}'")

        for ef in task.get("expected_files", []):
            if not is_path_safe_under_root(ef, PROJECT_ROOT):
                errors.append(f"Task '{tid}' specifies unsafe expected file path: '{ef}'")

        for cf in task.get("context_files", []):
            if not is_path_safe_under_root(cf, PROJECT_ROOT):
                errors.append(f"Task '{tid}' specifies unsafe context file path: '{cf}'")

    # Dependency resolution check
    for tid, deps in dependencies_graph.items():
        for d in deps:
            if d not in task_ids:
                errors.append(f"Task '{tid}' references nonexistent dependency '{d}'")

    # Cycle detection via DFS
    visited = {}
    def has_cycle(node, path):
        visited[node] = True
        path.add(node)
        for dep in dependencies_graph.get(node, []):
            if dep not in visited:
                if has_cycle(dep, path):
                    return True
            elif dep in path:
                return True
        path.remove(node)
        return False

    for tid in task_ids:
        if tid not in visited:
            if has_cycle(tid, set()):
                errors.append(f"Dependency cycle detected involving task '{tid}'")
                break

    return errors


def run_preflight() -> dict:
    """Executes environment preflight inspection and records baseline evidence."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    preflight_dir = EVIDENCE_DIR / "preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)

    herdr = HerdrClient(PROJECT_ROOT)
    git_ver = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    python_ver = sys.version.replace("\n", " ")
    os_info = subprocess.run(["uname", "-a"], capture_output=True, text=True).stdout.strip()

    herdr_ver = herdr.run_cmd(["--version"], check=False).stdout.strip()
    snapshot = herdr.get_snapshot()

    result_data = snapshot.get("result", {}).get("snapshot", {})
    baseline_inventory = {
        "workspaces": result_data.get("workspaces", []),
        "panes": result_data.get("panes", []),
        "control_plane": herdr.control_plane
    }

    integrations_raw = herdr.run_cmd(["integration", "status"], check=False).stdout.strip()

    worker_check = {}
    for cmd_name in ["agy", "agy2", "agy3", "agy4", "agy5", "agy6", "agy7"]:
        res_which = subprocess.run(["which", cmd_name], capture_output=True, text=True)
        res_type = subprocess.run(["bash", "-c", f"type {cmd_name}"], capture_output=True, text=True)
        res_ver = subprocess.run([cmd_name, "--version"], capture_output=True, text=True)
        worker_check[cmd_name] = {
            "resolved_path": res_which.stdout.strip(),
            "shell_type": res_type.stdout.strip(),
            "version": res_ver.stdout.strip(),
            "status": "available" if res_which.returncode == 0 else "missing"
        }

    models_res = subprocess.run(["agy", "models"], capture_output=True, text=True)
    has_target_model = "gemini-3.8-flash-high" in models_res.stdout
    installed_model = "gemini-3.8-flash-high" if has_target_model else "gemini-3.8-flash-medium"

    config_metadata = [
        collect_file_metadata("/root/.config/herdr/config.toml"),
        collect_file_metadata("/root/.gemini/antigravity-cli/settings.json"),
        collect_file_metadata("/root/.agy7_home/.gemini/antigravity-cli/settings.json"),
        collect_file_metadata("/root/.config/agy7/herdr/config.toml")
    ]

    report = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "project_root": str(PROJECT_ROOT),
        "os": os_info,
        "user": os.environ.get("USER", "root"),
        "git_version": git_ver,
        "python_version": python_ver,
        "venv_active": bool(os.environ.get("VIRTUAL_ENV")),
        "herdr_version": herdr_ver,
        "herdr_context": herdr.control_plane,
        "worker_commands": worker_check,
        "model_verified": installed_model,
        "config_files": config_metadata,
        "existing_workspaces_count": len(baseline_inventory["workspaces"]),
        "existing_panes_count": len(baseline_inventory["panes"]),
        "integrations_status": integrations_raw
    }

    atomic_write_json(preflight_dir / "preflight_report.json", report)
    atomic_write_json(preflight_dir / "baseline_herdr_inventory.json", baseline_inventory)
    return report


# ==============================================================================
# TaskExecutor: Manages Attempt Lifecycle, Worktrees, and Adapters
# ==============================================================================

class TaskExecutor:
    """Executes a task across explicit attempts in isolated Git worktrees."""

    def __init__(self, run_id: str, plan_task: dict, run_dir: pathlib.Path,
                 herdr: HerdrClient, res_mgr: ResourceManager, factory_config: dict):
        self.run_id = run_id
        self.task = plan_task
        self.task_id = plan_task["task_id"]
        self.worker_id = plan_task.get("worker_id") or plan_task.get("worker")
        self.routing_provenance = plan_task.get("routing_provenance", {})
        self.run_dir = run_dir
        self.herdr = herdr
        self.res_mgr = res_mgr
        self.factory_config = factory_config

        if not self.worker_id:
            raise ValueError(f"Task '{self.task_id}' cannot be executed without an assigned worker_id")

        self.worker_config = copy.deepcopy(factory_config.get("worker_registry", {}).get(self.worker_id, {}))
        self.adapter = get_adapter(self.worker_id, self.worker_config, herdr, res_mgr)
        self.profile_id = self.task.get("profile_id") or self.routing_provenance.get("selected_profile_id")
        self.harness = self.task.get("harness") or self.routing_provenance.get("harness") or self.worker_config.get("adapter", "agy")
        self.model = self.task.get("model") or self.routing_provenance.get("model") or self.worker_config.get("default_model") or factory_config.get("default_model", "gemini-3.8-flash-high")
        self.effort = self.task.get("effort") or self.routing_provenance.get("effort") or self.worker_config.get("reasoning_effort", "high")

        self.allowed_paths = plan_task.get("allowed_paths", [])
        self.expected_files = plan_task.get("expected_files", [])
        self.context_files = plan_task.get("context_files", [])
        self.review_only = plan_task.get("review_only", False)
        self.is_repair = plan_task.get("is_repair", False)
        self.timeout = plan_task.get("timeout", 180)
        self.max_retries = plan_task.get("max_retries", 0)

        self.task_root_dir = run_dir / "workers" / self.task_id
        self.task_root_dir.mkdir(parents=True, exist_ok=True)
        self.state = "PENDING"
        self.current_attempt_id = 0
        self.attempts = []
        self.latest_result = {}

    def prepare_attempt_worktree(self, attempt_id: int, base_commit: str) -> tuple[pathlib.Path, str]:
        """Creates an isolated git worktree for this specific attempt."""
        attempt_branch = f"factory/{self.run_id}/{self.task_id}/att-{attempt_id}"
        worktree_path = WORKTREES_DIR / self.run_id / self.task_id / f"att-{attempt_id}"
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        if worktree_path.exists():
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree_path)],
                           cwd=str(PROJECT_ROOT), capture_output=True)
            shutil.rmtree(worktree_path, ignore_errors=True)

        subprocess.run(["git", "branch", "-D", attempt_branch], cwd=str(PROJECT_ROOT), capture_output=True)

        cmd = ["git", "worktree", "add", "-b", attempt_branch, str(worktree_path), base_commit]
        res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {res.stderr}")

        # Pre-create directory paths for allowed paths and expected files
        for p in self.allowed_paths:
            norm_p = p.replace("/**", "").replace("/*", "").rstrip("/")
            if norm_p:
                target = worktree_path / norm_p
                if target.suffix:
                    target.parent.mkdir(parents=True, exist_ok=True)
                else:
                    target.mkdir(parents=True, exist_ok=True)
        for ef in self.expected_files:
            (worktree_path / pathlib.Path(ef).parent).mkdir(parents=True, exist_ok=True)

        self.res_mgr.record_worktree(str(worktree_path), attempt_branch, run_id=self.run_id)
        return worktree_path, attempt_branch

    def build_prompt(self, worktree_path: pathlib.Path) -> str:
        context_blocks = []
        for cf in self.context_files:
            cf_path = worktree_path / cf
            if cf_path.exists():
                content = cf_path.read_text(encoding="utf-8")
                context_blocks.append(f"### Reference Context File: `{cf}`\n```markdown\n{content}\n```")
        context_content = ("\n\n" + "\n\n".join(context_blocks)) if context_blocks else ""

        target_files_guidance = ""
        if self.expected_files:
            targets = "\n".join(f"- `{worktree_path / f}`" for f in self.expected_files)
            target_files_guidance = f"### Required TargetFile Paths to Create via write_to_file:\n{targets}\n"

        if self.review_only:
            template_path = PROJECT_ROOT / "prompts" / "reviewer-base.md"
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
            return template.format(
                worktree_path=str(worktree_path),
                spec_path=str(worktree_path / self.context_files[0]) if self.context_files else "docs/SPECIFICATION.md",
                task_id=self.task_id
            ) + context_content
        else:
            template_path = PROJECT_ROOT / "prompts" / "worker-base.md"
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
            patterns_str = "\n".join(f"- `{p}`" for p in self.allowed_paths)
            task_desc = self.task.get("description", f"Implement task {self.task_id}")
            return template.format(
                worktree_path=str(worktree_path),
                allowed_patterns=patterns_str,
                task_description=task_desc + context_content,
                target_files_guidance=target_files_guidance,
                task_id=self.task_id
            )

    def execute_attempt(self, attempt_id: int, base_commit: str) -> dict:
        """Executes a single attempt through the adapter, validating paths and outputs."""
        self.current_attempt_id = attempt_id
        attempt_dir = self.task_root_dir / f"att-{attempt_id}"
        attempt_dir.mkdir(parents=True, exist_ok=True)

        start_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.state = "DISPATCHING"

        worktree_path, attempt_branch = self.prepare_attempt_worktree(attempt_id, base_commit)
        env_info = self.adapter.prepare_environment(self.run_id, self.task_id, attempt_id, worktree_path)

        prompt_file = attempt_dir / "prompt.md"
        prompt_content = self.build_prompt(worktree_path)
        prompt_file.write_text(prompt_content, encoding="utf-8")

        custom_schema = self.task.get("result_schema")
        if custom_schema:
            schema_src = PROJECT_ROOT / custom_schema
        else:
            schema_src = PROJECT_ROOT / "schemas" / ("review-result.schema.json" if self.review_only else "worker-result.schema.json")
        schema_file = attempt_dir / "schema.json"
        shutil.copyfile(schema_src, schema_file)

        self.state = "RUNNING"
        sig = inspect.signature(self.adapter.execute)
        exec_kwargs = {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "attempt_id": attempt_id,
            "worktree_path": worktree_path,
            "prompt_file": prompt_file,
            "schema_file": schema_file,
            "timeout": self.timeout,
            "task_attempt_dir": attempt_dir,
            "env_info": env_info,
            "model": self.model
        }
        if "effort" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            exec_kwargs["effort"] = self.effort

        raw_res = self.adapter.execute(**exec_kwargs)

        end_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Failpoint test check: right after worker process execution
        check_failpoint("FAIL_AFTER_RUNNING", self.run_dir, {"task_id": self.task_id, "attempt_id": attempt_id})

        # Stale result rejection guard
        if attempt_id != self.current_attempt_id:
            return {
                "attempt_id": attempt_id,
                "task_id": self.task_id,
                "state": "CANCELLED",
                "status": "STALE_REJECTED",
                "error": "Result arrived after attempt superseded"
            }

        if raw_res.get("timed_out"):
            self.state = "TIMED_OUT"
            attempt_record = {
                "attempt_id": attempt_id,
                "task_id": self.task_id,
                "worker_id": self.worker_id,
                "profile_id": self.profile_id,
                "harness": self.harness,
                "model": self.model,
                "effort": self.effort,
                "adapter": self.worker_config.get("adapter", "agy"),
                "routing_provenance": self.routing_provenance,
                "branch": attempt_branch,
                "worktree": str(worktree_path),
                "start_time": start_time,
                "end_time": end_time,
                "exit_code": -1,
                "timed_out": True,
                "state": "TIMED_OUT",
                "status": "TIMEOUT",
                "error": raw_res.get("error", "Worker timed out")
            }
            self._record_telemetry(attempt_record, raw_res, base_commit, worktree_path, start_time, end_time, -1)
            self.attempts.append(attempt_record)
            self.latest_result = attempt_record
            atomic_write_json(attempt_dir / "attempt_record.json", attempt_record)
            return attempt_record

        self.state = "RESULT_RECEIVED"
        exit_code = raw_res.get("exit_code", -1)
        agy_data = raw_res.get("data", {})

        # Path validation
        self.state = "PATH_VALIDATING"
        untracked_res = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True
        )
        changed_paths = []
        for line in untracked_res.stdout.splitlines():
            if line.strip():
                changed_paths.append(line[3:].strip().strip('"'))

        path_violations = []
        if not self.review_only:
            for p in changed_paths:
                if not match_path_allowlist(p, self.allowed_paths):
                    path_violations.append(p)

        # Symlink security check
        symlink_violations = check_worktree_symlinks(worktree_path, PROJECT_ROOT)
        path_violations.extend(symlink_violations)

        missing_expected = []
        if not self.review_only and self.expected_files:
            for exp_file in self.expected_files:
                if not (worktree_path / exp_file).exists():
                    missing_expected.append(exp_file)

        structured_output = agy_data.get("structured_output", {})
        if not structured_output and "response" in agy_data:
            try:
                m = re.search(r"(\{[\s\S]*\})", agy_data["response"])
                if m:
                    structured_output = json.loads(m.group(1))
            except Exception:
                pass
        if not structured_output and agy_data.get("status") in ("SUCCESS", "COMPLETED"):
            structured_output = agy_data

        is_success = (
            exit_code == 0
            and agy_data.get("status") in ("SUCCESS", "COMPLETED")
            and not path_violations
            and not missing_expected
            and (self.review_only or self.is_repair or len(changed_paths) > 0 or (self.expected_files and not missing_expected) or self.task_type in ("support", "fixture"))
        )

        self.state = "PATH_VALIDATED" if is_success else "FAILED"

        attempt_record = {
            "attempt_id": attempt_id,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "profile_id": self.profile_id,
            "harness": self.harness,
            "model": self.model,
            "effort": self.effort,
            "adapter": self.worker_config.get("adapter", "agy"),
            "routing_provenance": self.routing_provenance,
            "provenance": raw_res.get("provenance", {}),
            "branch": attempt_branch,
            "worktree": str(worktree_path),
            "env_info": env_info,
            "start_time": start_time,
            "end_time": end_time,
            "exit_code": exit_code,
            "agy_status": agy_data.get("status", "UNKNOWN"),
            "changed_paths": changed_paths,
            "path_violations": path_violations,
            "missing_expected": missing_expected,
            "structured_output": structured_output,
            "state": self.state,
            "status": "SUCCESS" if is_success else "FAILED"
        }

        self._record_telemetry(attempt_record, raw_res, base_commit, worktree_path, start_time, end_time, exit_code)
        atomic_write_json(attempt_dir / "attempt_record.json", attempt_record)
        self.attempts.append(attempt_record)
        self.latest_result = attempt_record

        # Check failpoint before commit
        check_failpoint("FAIL_BEFORE_COMMIT", self.run_dir, {"task_id": self.task_id, "attempt_id": attempt_id})

        return attempt_record

    def _record_telemetry(self, attempt_record: dict, raw_res: dict, base_commit: str,
                          worktree_path: pathlib.Path, start_time: str, end_time: str, exit_code: int):
        churn = {"lines_added": 0, "lines_deleted": 0, "files_changed": 0}
        try:
            diff_res = subprocess.run(
                ["git", "diff", "--numstat", base_commit],
                cwd=str(worktree_path),
                capture_output=True,
                text=True
            )
            if diff_res.returncode == 0:
                for line in diff_res.stdout.splitlines():
                    parts = line.strip().split("\t")
                    if len(parts) >= 3:
                        try:
                            added = int(parts[0]) if parts[0] != "-" else 0
                            deleted = int(parts[1]) if parts[1] != "-" else 0
                            churn["lines_added"] += added
                            churn["lines_deleted"] += deleted
                            churn["files_changed"] += 1
                        except Exception:
                            pass
        except Exception:
            pass

        try:
            dt_start = datetime.datetime.fromisoformat(start_time)
            dt_end = datetime.datetime.fromisoformat(end_time)
            duration_ms = max(0.0, round((dt_end - dt_start).total_seconds() * 1000, 2))
        except Exception:
            duration_ms = 0.0

        exec_class = (
            self.task.get("execution_class")
            or self.routing_provenance.get("execution_class")
            or derive_execution_class(self.task.get("task_type", "implementation"))
        )

        telemetry = {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "attempt_id": attempt_record.get("attempt_id", 1),
            "profile_id": self.profile_id or "unknown",
            "harness": self.harness,
            "adapter": self.worker_config.get("adapter", "agy"),
            "model": self.model,
            "effort": self.effort,
            "execution_class": exec_class,
            "task_type": self.task.get("task_type", "implementation"),
            "start_time": start_time,
            "end_time": end_time,
            "duration_ms": duration_ms,
            "status": attempt_record.get("state", self.state),
            "exit_code": exit_code,
            "churn": churn
        }
        prov = raw_res.get("provenance", {})
        if prov.get("turns"):
            telemetry["turns"] = prov["turns"]
        if prov.get("session_id"):
            telemetry["session_id"] = prov["session_id"]

        attempt_record["telemetry"] = telemetry

        # Run-local metrics.json
        try:
            metrics_file = self.run_dir / "metrics.json"
            run_metrics = []
            if metrics_file.exists():
                try:
                    with open(metrics_file, "r", encoding="utf-8") as mf:
                        run_metrics = json.load(mf)
                except Exception:
                    run_metrics = []
            run_metrics.append(telemetry)
            atomic_write_json(metrics_file, run_metrics)
        except Exception:
            pass

        # Global evidence telemetry
        try:
            global_telemetry = EVIDENCE_DIR / "telemetry.jsonl"
            global_telemetry.parent.mkdir(parents=True, exist_ok=True)
            with open(global_telemetry, "a", encoding="utf-8") as gtf:
                gtf.write(json.dumps(telemetry) + "\n")
        except Exception:
            pass

    def commit_work(self, attempt_id: int) -> str:
        """Commits verified changes in the attempt worktree."""
        self.state = "COMMITTING"
        worktree_path = WORKTREES_DIR / self.run_id / self.task_id / f"att-{attempt_id}"
        subprocess.run(["git", "add", "-A"], cwd=str(worktree_path), check=True)
        diff_check = subprocess.run(["git", "status", "--porcelain"], cwd=str(worktree_path), capture_output=True, text=True)
        if not diff_check.stdout.strip():
            head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(worktree_path), capture_output=True, text=True).stdout.strip()
            self.state = "COMMITTED"
            self.latest_result["state"] = self.state
            self.latest_result["commit_hash"] = head_commit
            return head_commit

        summary = self.latest_result.get("structured_output", {}).get("summary", f"Implemented {self.task_id}")
        msg = f"feat({self.task_id}): {summary}\n\nTask: {self.task_id}\nAttempt: {attempt_id}\nProfile: {self.profile_id}\nWorker: {self.worker_id}\nHarness: {self.harness}\nModel: {self.model}\nEffort: {self.effort}"
        subprocess.run(["git", "commit", "-m", msg], cwd=str(worktree_path), check=True)
        commit_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(worktree_path), capture_output=True, text=True).stdout.strip()
        self.state = "COMMITTED"
        self.latest_result["state"] = self.state
        self.latest_result["commit_hash"] = commit_hash
        return commit_hash


# ==============================================================================
# FactoryOrchestrator: DAG Scheduler, Reconciliation Resume, and Conflict Handling
# ==============================================================================

class FactoryOrchestrator:
    """Dependency-driven arbitrary DAG scheduler and state machine engine."""

    def __init__(self, plan_path: pathlib.Path, run_id: str = None):
        self.plan_path = plan_path
        with open(plan_path, "r", encoding="utf-8") as f:
            self.plan = json.load(f)

        with open(FACTORY_CONFIG_PATH, "r", encoding="utf-8") as f:
            self.factory_config = json.load(f)

        self.herdr = HerdrClient(PROJECT_ROOT)
        self.res_mgr = ResourceManager(self.herdr)
        self.merge_lock = threading.Lock()
        self.board_projector = HerdrBoardProjector(PROJECT_ROOT)

        # Build task lookup and dependency graph
        self._build_task_graph()

        if run_id:
            self.run_id = run_id
            self.run_dir = RUNS_DIR / self.run_id
            self.manifest_path = self.run_dir / "manifest.json"
            self.events_log = self.run_dir / "events.jsonl"
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                self.manifest = json.load(f)
        else:
            self.run_id = f"run-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            self.run_dir = RUNS_DIR / self.run_id
            self.run_dir.mkdir(parents=True, exist_ok=True)
            (self.run_dir / "workers").mkdir(exist_ok=True)
            (self.run_dir / "tests").mkdir(exist_ok=True)
            (self.run_dir / "merges").mkdir(exist_ok=True)
            (self.run_dir / "prompts").mkdir(exist_ok=True)

            self.events_log = self.run_dir / "events.jsonl"
            self.manifest_path = self.run_dir / "manifest.json"

            initial_tasks = {}
            for tid, tdef in self.tasks_def.items():
                wid = tdef.get("worker_id") or tdef.get("worker")
                adapter = self.factory_config.get("worker_registry", {}).get(wid, {}).get("adapter") if wid else None
                initial_tasks[tid] = {
                    "task_id": tid,
                    "worker_id": wid,
                    "task_type": tdef.get("task_type"),
                    "adapter": adapter,
                    "dependencies": tdef.get("dependencies", []),
                    "canonical_state": "PENDING",
                    "display_state": "BACKLOG",
                    "current_attempt_id": 0,
                    "attempts_count": 0,
                    "attempts": [],
                    "latest_result": {},
                    "status": "PENDING"
                }

            self.manifest = {
                "factory_version": "5.0.0",
                "run_id": self.run_id,
                "plan_path": str(self.plan_path),
                "plan_name": self.plan.get("name") or self.plan.get("plan_id", "unnamed_plan"),
                "plan_id": self.plan.get("plan_id") or self.plan.get("name", "unnamed_plan"),
                "control_plane": self.herdr.control_plane,
                "start_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "end_time": None,
                "run_state": "PENDING",
                "tasks": initial_tasks,
                "waves": [],  # Backward compatibility
                "final_audit": {},
                "final_status": "PENDING"
            }
            self.save_manifest()
            self.log_event("RUN_INITIALIZED", {"run_id": self.run_id, "plan": self.manifest["plan_name"]})

    def _build_task_graph(self):
        """Constructs unified task definition map from either 'waves' or 'tasks'."""
        self.tasks_def = {}
        if "waves" in self.plan:
            prev_wave_tasks = []
            for wave in self.plan["waves"]:
                wave_tasks = []
                for task in wave.get("tasks", []):
                    tid = task["task_id"]
                    # If task doesn't have explicit dependencies and wave > 0, default to prior wave tasks
                    deps = list(task.get("dependencies", []))
                    if not deps and prev_wave_tasks:
                        deps = list(prev_wave_tasks)
                    t_copy = dict(task)
                    t_copy["dependencies"] = deps
                    t_copy["wave_index"] = wave.get("wave_index", 0)
                    self.tasks_def[tid] = t_copy
                    wave_tasks.append(tid)
                prev_wave_tasks = wave_tasks
        elif "tasks" in self.plan:
            for task in self.plan["tasks"]:
                self.tasks_def[task["task_id"]] = dict(task)

    def log_event(self, event_type: str, payload: dict):
        event = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": event_type,
            "payload": payload
        }
        with open(self.events_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def save_manifest(self):
        # Update display states and wave projection
        for tid, tinfo in self.manifest["tasks"].items():
            state = tinfo.get("canonical_state", "PENDING")
            tinfo["display_state"] = CANONICAL_TO_DISPLAY_STATE.get(state, "RUNNING")
            tinfo["state"] = state  # Backward compatibility

        # Generate wave projection for backward compatibility
        wave_map = {}
        for tid, tdef in self.tasks_def.items():
            w_idx = tdef.get("wave_index", 0)
            if w_idx not in wave_map:
                wave_map[w_idx] = {
                    "wave_index": w_idx,
                    "name": f"Wave {w_idx}",
                    "tasks": []
                }
            t_record = self.manifest["tasks"].get(tid, {})
            # Merge latest_result into task record for legacy consumers
            merged_task = dict(t_record)
            if t_record.get("latest_result"):
                merged_task.update(t_record["latest_result"])
            wave_map[w_idx]["tasks"].append(merged_task)

        self.manifest["waves"] = [wave_map[k] for k in sorted(wave_map.keys())]
        atomic_write_json(self.manifest_path, self.manifest)
        try:
            self.board_projector.sync(self.run_id)
        except Exception:
            pass

    def run_validation_commands(self, commands_list: list) -> dict:
        """Executes declared verification commands."""
        test_dir = self.run_dir / "tests"
        test_dir.mkdir(parents=True, exist_ok=True)
        results = {}

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        for gate in commands_list:
            name = gate.get("name", "gate")
            cmd = gate.get("command", [])
            timeout = gate.get("timeout", 60)
            try:
                proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, env=env, timeout=timeout)
                results[name] = {
                    "command": cmd,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "passed": proc.returncode == 0
                }
            except subprocess.TimeoutExpired:
                results[name] = {"command": cmd, "returncode": -1, "error": f"Timeout expired after {timeout}s", "passed": False}
            except Exception as e:
                results[name] = {"command": cmd, "returncode": -1, "error": str(e), "passed": False}

        results_file = test_dir / f"validation_{datetime.datetime.now(datetime.timezone.utc).strftime('%H%M%S')}.json"
        atomic_write_json(results_file, results)
        return results

    def merge_task_branch(self, branch_name: str, task_id: str) -> tuple[bool, list]:
        """Merges an attempt branch into main under a thread lock with automatic abort on conflict."""
        check_failpoint("FAIL_BEFORE_MERGE", self.run_dir, {"branch": branch_name, "task_id": task_id})

        with self.merge_lock:
            res = subprocess.run(
                ["git", "merge", "--no-ff", branch_name, "-m", f"chore(factory): integrate {task_id}"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True
            )
            success = (res.returncode == 0)
            conflicted_files = []

            if not success:
                # Capture conflicting files
                diff_res = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=U"],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True
                )
                conflicted_files = [line.strip() for line in diff_res.stdout.splitlines() if line.strip()]
                # Abort merge cleanly
                subprocess.run(["git", "merge", "--abort"], cwd=str(PROJECT_ROOT), capture_output=True)

            self.log_event("BRANCH_MERGED" if success else "MERGE_CONFLICT", {
                "branch": branch_name,
                "task_id": task_id,
                "success": success,
                "conflicted_files": conflicted_files,
                "output": res.stdout or res.stderr
            })

            if success:
                check_failpoint("FAIL_AFTER_MERGE", self.run_dir, {"branch": branch_name, "task_id": task_id})

            return success, conflicted_files

    def reconcile_state(self):
        """Reconciles durable state across cases A through F when resuming an interrupted run."""
        self.log_event("RECONCILIATION_STARTED", {"run_id": self.run_id})

        for tid, tinfo in self.manifest["tasks"].items():
            if tinfo.get("worker_id"):
                self.tasks_def[tid]["worker_id"] = tinfo["worker_id"]
                self.tasks_def[tid]["routing_provenance"] = tinfo.get("routing_provenance", {})
            state = tinfo.get("canonical_state", "PENDING")
            att_id = tinfo.get("current_attempt_id", 0)

            # Case A: Task already integrated/completed
            if state in ("INTEGRATED", "COMPLETED"):
                self.log_event("RECONCILE_CASE_A", {"task_id": tid, "state": state})
                continue

            # Case B: COMMITTED but not merged
            if state == "COMMITTING" or state == "COMMITTED":
                branch = f"factory/{self.run_id}/{tid}/att-{att_id}"
                # Verify if branch exists
                br_check = subprocess.run(["git", "rev-parse", "--verify", branch], cwd=str(PROJECT_ROOT), capture_output=True)
                if br_check.returncode == 0:
                    self.log_event("RECONCILE_CASE_B_ATTEMPT_MERGE", {"task_id": tid, "branch": branch})
                    merge_ok, conflicts = self.merge_task_branch(branch, tid)
                    if merge_ok:
                        tinfo["canonical_state"] = "INTEGRATED"
                        tinfo["status"] = "SUCCESS"
                        if tinfo.get("latest_result"):
                            tinfo["latest_result"]["state"] = "INTEGRATED"
                            tinfo["latest_result"]["status"] = "SUCCESS"
                    else:
                        tinfo["canonical_state"] = "CONFLICTED"
                        tinfo["status"] = "FAILED"
                        tinfo["conflicted_files"] = conflicts
                    continue

            # Case C: PATH_VALIDATED or VALIDATING
            if state in ("PATH_VALIDATED", "VALIDATING"):
                worktree_path = WORKTREES_DIR / self.run_id / tid / f"att-{att_id}"
                if worktree_path.exists():
                    self.log_event("RECONCILE_CASE_C_COMMIT", {"task_id": tid, "worktree": str(worktree_path)})
                    executor = TaskExecutor(self.run_id, self.tasks_def[tid], self.run_dir, self.herdr, self.res_mgr, self.factory_config)
                    executor.current_attempt_id = att_id
                    executor.latest_result = tinfo.get("latest_result", {})
                    commit_hash = executor.commit_work(att_id)
                    branch = f"factory/{self.run_id}/{tid}/att-{att_id}"
                    merge_ok, conflicts = self.merge_task_branch(branch, tid)
                    if merge_ok:
                        tinfo["canonical_state"] = "INTEGRATED"
                        tinfo["status"] = "SUCCESS"
                        tinfo["latest_result"] = executor.latest_result
                    else:
                        tinfo["canonical_state"] = "CONFLICTED"
                        tinfo["status"] = "FAILED"
                        tinfo["conflicted_files"] = conflicts
                    continue

            # Case D: RUNNING or DISPATCHING when process died
            if state in ("DISPATCHING", "RUNNING", "RESULT_RECEIVED"):
                attempt_dir = self.run_dir / "workers" / tid / f"att-{att_id}"
                status_file = attempt_dir / "exit_code.txt"
                if status_file.exists() and status_file.stat().st_size > 0:
                    self.log_event("RECONCILE_CASE_D_WORKER_COMPLETED", {"task_id": tid, "attempt_id": att_id})
                    # Re-run attempt evaluation
                    executor = TaskExecutor(self.run_id, self.tasks_def[tid], self.run_dir, self.herdr, self.res_mgr, self.factory_config)
                    current_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT), capture_output=True, text=True).stdout.strip()
                    res = executor.execute_attempt(att_id, current_head)
                    if res.get("status") == "SUCCESS":
                        if executor.review_only:
                            tinfo["canonical_state"] = "COMPLETED"
                            tinfo["status"] = "SUCCESS"
                        else:
                            executor.commit_work(att_id)
                            merge_ok, conflicts = self.merge_task_branch(res["branch"], tid)
                            if merge_ok:
                                tinfo["canonical_state"] = "INTEGRATED"
                                tinfo["status"] = "SUCCESS"
                            else:
                                tinfo["canonical_state"] = "CONFLICTED"
                                tinfo["status"] = "FAILED"
                                tinfo["conflicted_files"] = conflicts
                        tinfo["latest_result"] = executor.latest_result
                        continue
                # If worker didn't finish, reset to READY for re-dispatch
                self.log_event("RECONCILE_CASE_D_RESET_TO_READY", {"task_id": tid, "attempt_id": att_id})
                tinfo["canonical_state"] = "READY"
                continue

            # Case E: PENDING / READY
            if state in ("PENDING", "READY"):
                self.log_event("RECONCILE_CASE_E", {"task_id": tid})
                continue

            # Case F: BLOCKED, FAILED, TIMED_OUT, CONFLICTED
            if state in ("TIMED_OUT", "FAILED"):
                self.log_event("RECONCILE_CASE_F_RETRY", {"task_id": tid, "previous_state": state})
                tinfo["canonical_state"] = "PENDING"
                tinfo["status"] = "PENDING"
            elif state == "BLOCKED":
                self.log_event("RECONCILE_CASE_F_RESET_BLOCKED", {"task_id": tid})
                tinfo["canonical_state"] = "PENDING"
                tinfo["status"] = "PENDING"
            else:
                self.log_event("RECONCILE_CASE_F", {"task_id": tid, "state": state})

        self.save_manifest()
        self.log_event("RECONCILIATION_COMPLETED", {"run_id": self.run_id})

    def execute_plan(self, resume_mode: bool = False) -> dict:
        """Main execution engine running arbitrary DAG scheduler."""
        plan_errors = validate_plan_file(self.plan_path, self.factory_config)
        if plan_errors:
            raise ValueError(f"Plan validation failed before execution:\n" + "\n".join(f"- {e}" for e in plan_errors))

        self.manifest["run_state"] = "RUNNING"
        self.save_manifest()

        if resume_mode:
            self.reconcile_state()

        max_concurrency = self.plan.get("max_concurrency", 4)
        active_executors = {}  # {future: (tid, executor, attempt_id)}
        current_base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT), capture_output=True, text=True).stdout.strip()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            while True:
                # 1. Evaluate task dependencies and state transitions
                all_terminal = True
                ready_tasks = []

                for tid, tinfo in self.manifest["tasks"].items():
                    c_state = tinfo.get("canonical_state", "PENDING")

                    if c_state in ("PENDING", "READY", "BLOCKED"):
                        deps = tinfo.get("dependencies", [])
                        deps_states = [self.manifest["tasks"][d].get("canonical_state") for d in deps if d in self.manifest["tasks"]]

                        # If any dependency failed or blocked, transition to BLOCKED
                        if any(s in ("FAILED", "TIMED_OUT", "BLOCKED", "CONFLICTED", "CANCELLED") for s in deps_states):
                            if c_state != "BLOCKED":
                                tinfo["canonical_state"] = "BLOCKED"
                                tinfo["status"] = "BLOCKED"
                                self.log_event("TASK_BLOCKED", {"task_id": tid, "failed_deps": deps})
                            continue

                        # If all dependencies integrated or completed, task is READY
                        if all(s in ("INTEGRATED", "COMPLETED") for s in deps_states):
                            if c_state != "READY":
                                tinfo["canonical_state"] = "READY"
                                tinfo["status"] = "PENDING"
                                self.log_event("TASK_READY", {"task_id": tid})
                            ready_tasks.append(tid)
                            all_terminal = False
                        else:
                            if c_state == "BLOCKED":
                                tinfo["canonical_state"] = "PENDING"
                                tinfo["status"] = "PENDING"
                            all_terminal = False

                    elif c_state in ("DISPATCHING", "RUNNING", "RESULT_RECEIVED", "PATH_VALIDATING", "VALIDATING", "COMMITTING", "INTEGRATING"):
                        all_terminal = False

                # 2. Dispatch ready tasks up to available concurrency slots
                if ready_tasks and len(active_executors) < max_concurrency:
                    current_base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT), capture_output=True, text=True).stdout.strip()
                    busy_workers = {ex.worker_id for _, (t, ex, a) in active_executors.items()}
                    busy_profiles = {getattr(ex, "profile_id", None) for _, (t, ex, a) in active_executors.items() if getattr(ex, "profile_id", None)}

                    for tid in ready_tasks:
                        if len(active_executors) >= max_concurrency:
                            break

                        tinfo = self.manifest["tasks"][tid]
                        tdef = self.tasks_def[tid]

                        # Deterministic capability routing
                        wid, route_meta, route_status = resolve_task_worker(
                            tid,
                            tdef,
                            self.factory_config,
                            busy_workers=busy_workers,
                            busy_profiles=busy_profiles
                        )

                        if route_status == "BLOCKED":
                            tinfo["canonical_state"] = "BLOCKED"
                            tinfo["status"] = "BLOCKED"
                            tinfo["block_reason"] = route_meta.get("selection_reason")
                            self.log_event("TASK_ROUTING_BLOCKED", {"task_id": tid, "metadata": route_meta})
                            continue
                        elif route_status == "BUSY":
                            self.log_event("TASK_WAITING_BUSY_WORKER", {"task_id": tid, "metadata": route_meta})
                            continue

                        # Successfully routed
                        tinfo["worker_id"] = wid
                        tinfo["profile_id"] = route_meta.get("selected_profile_id")
                        tinfo["profile"] = route_meta.get("selected_profile_id")
                        tinfo["harness"] = route_meta.get("harness")
                        tinfo["model"] = route_meta.get("model")
                        tinfo["effort"] = route_meta.get("effort")
                        tinfo["adapter"] = route_meta.get("selected_adapter")
                        tinfo["routing_provenance"] = route_meta

                        tdef["worker_id"] = wid
                        tdef["profile_id"] = route_meta.get("selected_profile_id")
                        tdef["profile"] = route_meta.get("selected_profile_id")
                        tdef["harness"] = route_meta.get("harness")
                        tdef["model"] = route_meta.get("model")
                        tdef["effort"] = route_meta.get("effort")
                        tdef["routing_provenance"] = route_meta

                        busy_workers.add(wid)
                        if route_meta.get("selected_profile_id"):
                            busy_profiles.add(route_meta.get("selected_profile_id"))

                        tinfo["canonical_state"] = "DISPATCHING"
                        tinfo["attempts_count"] = tinfo.get("attempts_count", 0) + 1
                        att_id = tinfo["attempts_count"]
                        tinfo["current_attempt_id"] = att_id

                        executor = TaskExecutor(
                            self.run_id,
                            tdef,
                            self.run_dir,
                            self.herdr,
                            self.res_mgr,
                            self.factory_config
                        )
                        fut = pool.submit(executor.execute_attempt, att_id, current_base_commit)
                        active_executors[fut] = (tid, executor, att_id)
                        self.log_event("TASK_DISPATCHED", {
                            "task_id": tid,
                            "attempt_id": att_id,
                            "worker_id": wid,
                            "adapter": tinfo["adapter"],
                            "routing": route_meta
                        })

                    self.save_manifest()

                # 3. If nothing is running and no ready tasks, we are done
                if not active_executors:
                    if all_terminal:
                        break
                    time.sleep(0.5)
                    continue

                # 4. Wait for at least one running executor to finish
                done_futures, _ = concurrent.futures.wait(
                    active_executors.keys(),
                    return_when=concurrent.futures.FIRST_COMPLETED
                )

                for fut in done_futures:
                    tid, executor, att_id = active_executors.pop(fut)
                    tinfo = self.manifest["tasks"][tid]

                    try:
                        res = fut.result()
                    except Exception as exc:
                        res = {
                            "attempt_id": att_id,
                            "task_id": tid,
                            "state": "FAILED",
                            "status": "FAILED",
                            "error": str(exc)
                        }

                    tinfo["attempts"].append(res)
                    tinfo["latest_result"] = res
                    status = res.get("status")

                    if status == "SUCCESS":
                        if executor.review_only:
                            tinfo["canonical_state"] = "COMPLETED"
                            tinfo["status"] = "SUCCESS"
                            self.manifest["final_audit"] = res.get("structured_output", {})
                            self.log_event("REVIEW_TASK_COMPLETED", {"task_id": tid, "audit": self.manifest["final_audit"]})
                        else:
                            # Commit verified changes
                            commit_hash = executor.commit_work(att_id)
                            res["commit_hash"] = commit_hash
                            tinfo["canonical_state"] = "COMMITTED"
                            self.save_manifest()
                            check_failpoint("FAIL_AFTER_COMMIT", self.run_dir, {"task_id": tid, "attempt_id": att_id, "commit": commit_hash})

                            tinfo["canonical_state"] = "INTEGRATING"
                            self.save_manifest()

                            # Merge into main branch
                            merge_ok, conflicts = self.merge_task_branch(res["branch"], tid)
                            if merge_ok:
                                tinfo["canonical_state"] = "INTEGRATED"
                                tinfo["status"] = "SUCCESS"
                                res["state"] = "INTEGRATED"
                                current_base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT), capture_output=True, text=True).stdout.strip()
                                self.log_event("TASK_INTEGRATED", {"task_id": tid, "commit": commit_hash, "base_commit": current_base_commit})
                            else:
                                tinfo["canonical_state"] = "CONFLICTED"
                                tinfo["status"] = "FAILED"
                                tinfo["conflicted_files"] = conflicts
                                res["state"] = "CONFLICTED"
                                self.log_event("TASK_CONFLICTED", {"task_id": tid, "conflicts": conflicts})

                    elif res.get("timed_out"):
                        tinfo["canonical_state"] = "TIMED_OUT"
                        tinfo["status"] = "TIMEOUT"
                        self.log_event("TASK_TIMED_OUT", {"task_id": tid, "attempt_id": att_id})
                    else:
                        tinfo["canonical_state"] = "FAILED"
                        tinfo["status"] = "FAILED"
                        self.log_event("TASK_FAILED", {"task_id": tid, "attempt_id": att_id, "error": res.get("error")})

                    self.save_manifest()

        # 5. Check Concurrency Evidence
        tasks_timing = []
        for tid, tinfo in self.manifest["tasks"].items():
            for att in tinfo.get("attempts", []):
                tasks_timing.append({
                    "task_id": tid,
                    "attempt_id": att.get("attempt_id"),
                    "worker_id": att.get("worker_id"),
                    "start": att.get("start_time"),
                    "end": att.get("end_time")
                })
        self.manifest["concurrency_evidence"] = {
            "attempts": tasks_timing,
            "recorded_attempts_count": len(tasks_timing)
        }

        # 6. Post-Run / Final Validation Gates
        check_failpoint("FAIL_BEFORE_POST_VALIDATION", self.run_dir, {"run_id": self.run_id})

        validation_gates = self.plan.get("post_validation") or self.plan.get("final_validation") or []
        for w in self.plan.get("waves", []):
            validation_gates.extend(w.get("post_wave_validation", []))

        validation_passed = True
        if validation_gates:
            self.log_event("POST_RUN_VALIDATION_STARTED", {"gates_count": len(validation_gates)})
            val_results = self.run_validation_commands(validation_gates)
            self.manifest["validation_results"] = val_results
            validation_passed = all(g.get("passed", False) for g in val_results.values())
            self.log_event("POST_RUN_VALIDATION_RESULT", {"all_passed": validation_passed, "checks": val_results})

        # 7. Audit Verification
        audit_approved = True
        final_audit = self.manifest.get("final_audit", {})
        if final_audit:
            findings = final_audit.get("findings", [])
            has_blocking = any(f.get("severity") in ("CRITICAL", "MAJOR") for f in findings)
            audit_approved = (not has_blocking) and final_audit.get("status") in ("APPROVED", "COMPLETED")

        all_tasks_successful = all(
            tinfo.get("canonical_state") in ("INTEGRATED", "COMPLETED") and tinfo.get("status") == "SUCCESS"
            for tinfo in self.manifest["tasks"].values()
        )

        self.manifest["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if all_tasks_successful and validation_passed and audit_approved:
            self.manifest["run_state"] = "COMPLETED"
            self.manifest["final_status"] = "COMPLETED"
        else:
            self.manifest["run_state"] = "FAILED"
            self.manifest["final_status"] = "FAILED"

        self.save_manifest()
        atomic_write_json(self.run_dir / "final-summary.json", self.manifest)
        self.log_event("RUN_FINISHED", {"run_id": self.run_id, "final_status": self.manifest["final_status"]})
        return self.manifest


# ==============================================================================
# Status and CLI Commands
# ==============================================================================

def generate_status_projection(run_id: str = None) -> dict:
    """Generates machine-readable status projection for Kanban / API consumers."""
    herdr = HerdrClient(PROJECT_ROOT)
    res_mgr = ResourceManager(herdr)

    run_dirs = sorted(list(RUNS_DIR.glob("run-*")), reverse=True)
    if run_id:
        target_dir = RUNS_DIR / run_id
        run_dirs = [target_dir] if target_dir.exists() else []

    runs_data = []
    for r in run_dirs:
        m_file = r / "manifest.json"
        if not m_file.exists():
            continue
        try:
            with open(m_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        tasks_proj = []
        raw_tasks = data.get("tasks", {})
        if not raw_tasks and "waves" in data:
            raw_tasks = {}
            for w in data.get("waves", []):
                for t in w.get("tasks", []):
                    tid = t.get("task_id")
                    if tid:
                        raw_tasks[tid] = t

        for tid, tinfo in raw_tasks.items():
            c_state = tinfo.get("canonical_state") or tinfo.get("state") or tinfo.get("status") or "PENDING"
            d_state = tinfo.get("display_state") or CANONICAL_TO_DISPLAY_STATE.get(c_state, "RUNNING")
            tasks_proj.append({
                "task_id": tid,
                "canonical_state": c_state,
                "display_state": d_state,
                "worker_id": tinfo.get("worker_id"),
                "adapter": tinfo.get("adapter", "agy"),
                "current_attempt_id": tinfo.get("current_attempt_id", 0),
                "attempts_count": tinfo.get("attempts_count", len(tinfo.get("attempts", []))),
                "dependencies": tinfo.get("dependencies", []),
                "status": tinfo.get("status", "PENDING")
            })

        run_summary = {
            "run_id": data.get("run_id", r.name),
            "plan_id": data.get("plan_id"),
            "plan_name": data.get("plan_name"),
            "run_state": data.get("run_state", data.get("final_status", "UNKNOWN")),
            "start_time": data.get("start_time"),
            "end_time": data.get("end_time"),
            "tasks": tasks_proj
        }

        if run_id:
            # Include events if specific run requested
            events_file = r / "events.jsonl"
            events_list = []
            if events_file.exists():
                try:
                    with open(events_file, "r", encoding="utf-8") as ef:
                        for line in ef:
                            if line.strip():
                                events_list.append(json.loads(line.strip()))
                except Exception:
                    pass
            run_summary["events"] = events_list
            run_summary["concurrency_evidence"] = data.get("concurrency_evidence", {})
            run_summary["final_audit"] = data.get("final_audit", {})

        runs_data.append(run_summary)

    projection = {
        "status": "OK",
        "factory_version": "6.0.0",
        "control_plane": res_mgr.state["control_plane"],
        "owned_resources": res_mgr.state["owned"],
        "runs": runs_data
    }
    if run_id and runs_data:
        projection["run"] = runs_data[0]
    return projection


def summarize_execution_metrics(run_id: str = None, profile_id: str = None, telemetry_file: pathlib.Path = None) -> dict:
    """
    Summarizes execution telemetry across runs or for a specific run/profile.
    Strictly observational: metrics do not influence routing decisions.
    """
    records = []
    if telemetry_file and pathlib.Path(telemetry_file).exists():
        tf = pathlib.Path(telemetry_file)
        try:
            with open(tf, "r", encoding="utf-8") as f:
                if tf.suffix == ".json":
                    records = json.load(f)
                else:
                    for line in f:
                        if line.strip():
                            records.append(json.loads(line.strip()))
        except Exception:
            pass
    elif run_id:
        rf = RUNS_DIR / run_id / "metrics.json"
        if rf.exists():
            try:
                with open(rf, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except Exception:
                pass
    else:
        gt = EVIDENCE_DIR / "telemetry.jsonl"
        if gt.exists():
            try:
                with open(gt, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            records.append(json.loads(line.strip()))
            except Exception:
                pass
        if not records:
            for rf in RUNS_DIR.glob("*/metrics.json"):
                try:
                    with open(rf, "r", encoding="utf-8") as f:
                        records.extend(json.load(f))
                except Exception:
                    pass

    if profile_id:
        records = [r for r in records if r.get("profile_id") == profile_id]

    total_attempts = len(records)
    successful = sum(1 for r in records if r.get("status") in ("COMPLETED", "COMMITTED", "PATH_VALIDATED", "INTEGRATED"))
    failed = total_attempts - successful
    success_rate = (successful / total_attempts * 100) if total_attempts > 0 else 0.0

    durations = [r.get("duration_ms", 0.0) for r in records if "duration_ms" in r]
    avg_duration = (sum(durations) / len(durations)) if durations else 0.0

    total_lines_added = sum(r.get("churn", {}).get("lines_added", 0) for r in records)
    total_lines_deleted = sum(r.get("churn", {}).get("lines_deleted", 0) for r in records)
    total_files_changed = sum(r.get("churn", {}).get("files_changed", 0) for r in records)

    by_profile = {}
    by_harness = {}
    by_class = {}

    for r in records:
        pid = r.get("profile_id", "unknown")
        by_profile.setdefault(pid, {"total": 0, "success": 0, "failed": 0, "duration_ms": 0.0, "lines_added": 0, "lines_deleted": 0})
        by_profile[pid]["total"] += 1
        if r.get("status") in ("COMPLETED", "COMMITTED", "PATH_VALIDATED", "INTEGRATED"):
            by_profile[pid]["success"] += 1
        else:
            by_profile[pid]["failed"] += 1
        by_profile[pid]["duration_ms"] += r.get("duration_ms", 0.0)
        by_profile[pid]["lines_added"] += r.get("churn", {}).get("lines_added", 0)
        by_profile[pid]["lines_deleted"] += r.get("churn", {}).get("lines_deleted", 0)

        h = r.get("harness", "unknown")
        by_harness.setdefault(h, {"total": 0, "success": 0, "failed": 0, "duration_ms": 0.0})
        by_harness[h]["total"] += 1
        if r.get("status") in ("COMPLETED", "COMMITTED", "PATH_VALIDATED", "INTEGRATED"):
            by_harness[h]["success"] += 1
        else:
            by_harness[h]["failed"] += 1
        by_harness[h]["duration_ms"] += r.get("duration_ms", 0.0)

        ec = r.get("execution_class", "standard")
        by_class.setdefault(ec, {"total": 0, "success": 0, "failed": 0, "duration_ms": 0.0})
        by_class[ec]["total"] += 1
        if r.get("status") in ("COMPLETED", "COMMITTED", "PATH_VALIDATED", "INTEGRATED"):
            by_class[ec]["success"] += 1
        else:
            by_class[ec]["failed"] += 1
        by_class[ec]["duration_ms"] += r.get("duration_ms", 0.0)

    for p in by_profile.values():
        if p["total"] > 0:
            p["avg_duration_ms"] = round(p["duration_ms"] / p["total"], 2)
    for h in by_harness.values():
        if h["total"] > 0:
            h["avg_duration_ms"] = round(h["duration_ms"] / h["total"], 2)
    for c in by_class.values():
        if c["total"] > 0:
            c["avg_duration_ms"] = round(c["duration_ms"] / c["total"], 2)

    return {
        "run_filter": run_id,
        "profile_filter": profile_id,
        "total_attempts": total_attempts,
        "successful_attempts": successful,
        "failed_attempts": failed,
        "success_rate_pct": round(success_rate, 2),
        "avg_duration_ms": round(avg_duration, 2),
        "total_churn": {
            "lines_added": total_lines_added,
            "lines_deleted": total_lines_deleted,
            "files_changed": total_files_changed
        },
        "by_profile": by_profile,
        "by_harness": by_harness,
        "by_execution_class": by_class
    }


def main():
    parser = argparse.ArgumentParser(description="AGY-Herdr Software Factory Engine (v6.0.0)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Preflight
    subparsers.add_parser("preflight", help="Run environment preflight inspection")

    # Validate Plan
    val_parser = subparsers.add_parser("validate-plan", help="Validate a declarative plan before execution")
    val_parser.add_argument("plan", type=str, help="Path to plan JSON file (e.g. plans/demo.json)")

    # Run
    run_parser = subparsers.add_parser("run", help="Execute an orchestration plan")
    run_parser.add_argument("plan", type=str, help="Path to plan JSON (e.g. plans/demo.json)")

    # Resume
    res_parser = subparsers.add_parser("resume", help="Resume an interrupted or partial factory run")
    res_parser.add_argument("run_id", type=str, help="Run ID to resume (e.g. run-20260922-223926)")

    # Status
    st_parser = subparsers.add_parser("status", help="Show active and past factory run status")
    st_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON status")
    st_parser.add_argument("--run", type=str, help="Filter status to a specific run ID")

    # Board
    board_parser = subparsers.add_parser("board", help="Manage one-way Kanban board projection")
    board_sub = board_parser.add_subparsers(dest="board_action", required=True)
    board_sync = board_sub.add_parser("sync", help="Synchronize factory state to Kanban board")
    board_sync.add_argument("--run", type=str, help="Specific run ID to sync")
    board_status = board_sub.add_parser("status", help="Get Kanban board projection status")

    # Profile
    profile_parser = subparsers.add_parser("profile", help="Inspect and validate execution profiles")
    profile_sub = profile_parser.add_subparsers(dest="profile_action", required=True)
    profile_sub.add_parser("list", help="List all execution profiles")
    p_show = profile_sub.add_parser("show", help="Show details for a specific profile")
    p_show.add_argument("profile_id", type=str, help="Profile ID to inspect")
    p_val = profile_sub.add_parser("validate", help="Validate profiles against schema and rules")
    p_val.add_argument("profile_id", nargs="?", default=None, help="Optional profile ID to validate")

    # Route
    route_parser = subparsers.add_parser("route", help="Inspect and explain deterministic routing")
    route_sub = route_parser.add_subparsers(dest="route_action", required=True)
    r_exp = route_sub.add_parser("explain", help="Explain routing decision for a task")
    r_exp.add_argument("plan", type=str, help="Path to plan JSON")
    r_exp.add_argument("task", type=str, help="Task ID to explain")
    r_exp.add_argument("--json", action="store_true", help="Output JSON explanation")
    r_exp.add_argument("--run", type=str, default=None, help="Optional run ID for live busy state context")

    # Metrics
    metrics_parser = subparsers.add_parser("metrics", help="Execution telemetry and performance metrics")
    metrics_sub = metrics_parser.add_subparsers(dest="metrics_action", required=True)
    m_sum = metrics_sub.add_parser("summarize", help="Summarize execution telemetry")
    m_sum.add_argument("--json", action="store_true", help="Output summary in JSON format")
    m_sum.add_argument("--run", type=str, default=None, help="Filter summary to specific run ID")
    m_sum.add_argument("--profile", type=str, default=None, help="Filter summary to specific profile ID")

    # Cleanup
    cl_parser = subparsers.add_parser("cleanup", help="Safely clean owned workspaces, worktrees, and ephemeral files")
    cl_parser.add_argument("--run", type=str, help="Scope cleanup to a specific run ID")

    args = parser.parse_args()

    if args.command == "preflight":
        report = run_preflight()
        print(json.dumps(report, indent=2))

    elif args.command == "validate-plan":
        plan_file = pathlib.Path(args.plan)
        if not plan_file.is_absolute():
            plan_file = PROJECT_ROOT / plan_file
        errors = validate_plan_file(plan_file)
        if errors:
            print(f"Plan validation FAILED for {plan_file}:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"Plan {plan_file} is VALID.")

    elif args.command == "run":
        plan_file = pathlib.Path(args.plan)
        if not plan_file.is_absolute():
            plan_file = PROJECT_ROOT / plan_file
        if not plan_file.exists():
            print(f"Error: Plan file {plan_file} does not exist", file=sys.stderr)
            sys.exit(1)

        orch = FactoryOrchestrator(plan_file)
        manifest = orch.execute_plan()
        print(f"Run {manifest['run_id']} completed with status: {manifest['final_status']}")
        print(f"Manifest written to: {orch.manifest_path}")

    elif args.command == "resume":
        run_dir = RUNS_DIR / args.run_id
        if not run_dir.exists():
            print(f"Error: Run directory {run_dir} does not exist", file=sys.stderr)
            sys.exit(1)
        manifest_file = run_dir / "manifest.json"
        if not manifest_file.exists():
            print(f"Error: Run manifest {manifest_file} not found", file=sys.stderr)
            sys.exit(1)

        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
        plan_file = pathlib.Path(manifest_data.get("plan_path", ""))
        if not plan_file.exists():
            print(f"Error: Recorded plan file {plan_file} not found", file=sys.stderr)
            sys.exit(1)

        orch = FactoryOrchestrator(plan_file, run_id=args.run_id)
        res_manifest = orch.execute_plan(resume_mode=True)
        print(f"Resumed run {res_manifest['run_id']} completed with status: {res_manifest['final_status']}")

    elif args.command == "status":
        if args.json:
            proj = generate_status_projection(run_id=args.run)
            print(json.dumps(proj, indent=2))
        else:
            herdr = HerdrClient(PROJECT_ROOT)
            res_mgr = ResourceManager(herdr)
            print("=== AGY-Herdr Software Factory Status (v4.0.0) ===")
            print(f"Project Root: {PROJECT_ROOT}")
            print(f"Control Plane Context: {json.dumps(res_mgr.state['control_plane'], indent=2)}")
            print(f"Owned Resources: {json.dumps(res_mgr.state['owned'], indent=2)}")
            runs = sorted(list(RUNS_DIR.glob("run-*")))
            print(f"Total Recorded Runs: {len(runs)}")
            for r in runs:
                m = r / "manifest.json"
                if m.exists():
                    try:
                        with open(m, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        tasks_info = []
                        for tid, t in data.get("tasks", {}).items():
                            tasks_info.append(f"{tid}:{t.get('canonical_state', t.get('status'))}")
                        print(f"  - {r.name}: state={data.get('run_state', data.get('final_status'))} plan={data.get('plan_id')} tasks=[{', '.join(tasks_info)}]")
                    except Exception:
                        pass

    elif args.command == "board":
        projector = HerdrBoardProjector()
        if args.board_action == "sync":
            res = projector.sync(run_id=args.run)
            print(json.dumps(res, indent=2))
        elif args.board_action == "status":
            res = projector.get_status()
            print(json.dumps(res, indent=2))

    elif args.command == "profile":
        if args.profile_action == "list":
            profiles = load_harness_profiles()
            print(f"{'Profile ID':<24} {'Harness':<10} {'Adapter':<10} {'Model':<20} {'Effort':<8} {'Status':<12}")
            print("-" * 90)
            for pid, p in profiles.items():
                cert = p.get("certification", {})
                status = cert.get("status", "UNCERTIFIED")
                print(f"{pid:<24} {p.get('harness', ''):<10} {p.get('adapter', ''):<10} {p.get('model', ''):<20} {p.get('effort', ''):<8} {status:<12}")
        elif args.profile_action == "show":
            profiles = load_harness_profiles()
            if args.profile_id not in profiles:
                print(f"Error: Unknown profile '{args.profile_id}'", file=sys.stderr)
                sys.exit(1)
            print(json.dumps(profiles[args.profile_id], indent=2))
        elif args.profile_action == "validate":
            results = validate_all_profiles()
            if args.profile_id:
                if args.profile_id not in results:
                    print(f"Error: Unknown profile '{args.profile_id}'", file=sys.stderr)
                    sys.exit(1)
                errs = results[args.profile_id]
                if errs:
                    print(f"Validation FAILED for profile '{args.profile_id}':", file=sys.stderr)
                    for e in errs:
                        print(f"  - {e}", file=sys.stderr)
                    sys.exit(1)
                else:
                    print(f"Profile '{args.profile_id}' is VALID.")
            else:
                any_err = False
                for pid, errs in results.items():
                    if errs:
                        any_err = True
                        print(f"FAILED: {pid}: {', '.join(errs)}", file=sys.stderr)
                    else:
                        print(f"OK:     {pid}")
                if any_err:
                    sys.exit(1)

    elif args.command == "route":
        if args.route_action == "explain":
            plan_path = pathlib.Path(args.plan)
            if not plan_path.is_absolute():
                plan_path = PROJECT_ROOT / plan_path
            if not plan_path.exists():
                print(f"Error: Plan file {plan_path} does not exist", file=sys.stderr)
                sys.exit(1)
            explanation = explain_task_routing(plan_path, args.task, run_id=args.run)
            if args.json:
                print(json.dumps(explanation, indent=2))
            else:
                print(f"Routing Explanation for Task: {explanation['task_id']} (Type: {explanation['task_type']})")
                print(f"Required Capabilities: {', '.join(explanation['required_capabilities'])}")
                print("\nCandidate Profiles Evaluation:")
                print(f"{'Rank':<5} {'Profile ID':<24} {'Harness':<10} {'Caps Match':<12} {'Auth':<14} {'Busy':<8} {'Eligibility':<16}")
                print("-" * 95)
                for p in explanation["profiles"]:
                    cm = "YES" if p["capability_match"] else "NO"
                    print(f"{p['priority_rank']:<5} {p['profile_id']:<24} {p['harness']:<10} {cm:<12} {p['auth_status']:<14} {p['busy_status']:<8} {p['eligibility']:<16}")
                print(f"\nFinal Decision: {explanation['final_decision']['status']}")
                print(f"Selected Profile: {explanation['final_decision']['selected_profile']}")
                print(f"Selected Worker:  {explanation['final_decision']['selected_worker']}")
                print(f"Reason: {explanation['final_decision']['reason']}")

    elif args.command == "cleanup":
        herdr = HerdrClient(PROJECT_ROOT)
        res_mgr = ResourceManager(herdr)
        result = res_mgr.cleanup_owned_resources(run_id=args.run)
        print("Cleanup completed safely:")
        print(json.dumps(result, indent=2))

    elif args.command == "metrics":
        if args.metrics_action == "summarize":
            summary = summarize_execution_metrics(run_id=args.run, profile_id=args.profile)
            if args.json:
                print(json.dumps(summary, indent=2))
            else:
                print("================================================================================")
                print("AGY-Herdr Software Factory — Execution Telemetry Summary")
                print("================================================================================")
                if summary["run_filter"]:
                    print(f"Run Filter:     {summary['run_filter']}")
                if summary["profile_filter"]:
                    print(f"Profile Filter: {summary['profile_filter']}")
                print(f"Total Attempts: {summary['total_attempts']}")
                print(f"Successful:     {summary['successful_attempts']} ({summary['success_rate_pct']}%)")
                print(f"Failed:         {summary['failed_attempts']}")
                print(f"Avg Duration:   {summary['avg_duration_ms']} ms")
                churn = summary["total_churn"]
                print(f"Git Churn:      +{churn['lines_added']} / -{churn['lines_deleted']} across {churn['files_changed']} files")
                print("-" * 80)
                print(f"{'Profile ID':<24} {'Total':<8} {'Success':<9} {'Failed':<8} {'Avg Duration':<14} {'Churn'}")
                print("-" * 80)
                for pid, pdata in summary["by_profile"].items():
                    ch_str = f"+{pdata.get('lines_added', 0)} / -{pdata.get('lines_deleted', 0)}"
                    print(f"{pid:<24} {pdata['total']:<8} {pdata['success']:<9} {pdata['failed']:<8} {pdata.get('avg_duration_ms', 0.0):<14} {ch_str}")
                print("-" * 80)
                print(f"{'Harness':<15} {'Total':<8} {'Success':<9} {'Failed':<8} {'Avg Duration'}")
                print("-" * 80)
                for h, hdata in summary["by_harness"].items():
                    print(f"{h:<15} {hdata['total']:<8} {hdata['success']:<9} {hdata['failed']:<8} {hdata.get('avg_duration_ms', 0.0)}")
                print("-" * 80)
                print(f"{'Execution Class':<18} {'Total':<8} {'Success':<9} {'Failed':<8} {'Avg Duration'}")
                print("-" * 80)
                for ec, ecdata in summary["by_execution_class"].items():
                    print(f"{ec:<18} {ecdata['total']:<8} {ecdata['success']:<9} {ecdata['failed']:<8} {ecdata.get('avg_duration_ms', 0.0)}")
                print("================================================================================")


if __name__ == "__main__":
    main()
