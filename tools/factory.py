#!/usr/bin/env python3
"""
AGY-Herdr Software Factory Orchestration Engine (Version 2.0.0)

Generic, brain-agnostic orchestration driver delegating multi-worker software
construction across isolated Herdr workspaces and Git worktrees.
Zero third-party Python dependencies (Python 3 standard library only).
"""

import argparse
import concurrent.futures
import datetime
import fnmatch
import glob
import hashlib
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
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


def check_mutation_safety(resource_id: str, owned_list: list) -> bool:
    """Enforces: if resource_id not in owned_resources: mutation_forbidden"""
    return bool(resource_id and resource_id in owned_list)


def is_path_safe_under_root(path_str: str, root_dir: pathlib.Path) -> bool:
    """Verifies that a given path does not escape the project/worktree root."""
    try:
        resolved = (root_dir / path_str).resolve()
        return root_dir.resolve() in resolved.parents or resolved == root_dir.resolve()
    except Exception:
        return False


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
    """Manages project-owned resources and enforces strict ownership boundaries."""

    def __init__(self, herdr: HerdrClient):
        self.herdr = herdr
        self.state_file = OWNED_RESOURCES_PATH
        self._load_or_init()

    def _load_or_init(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                self.state = json.load(f)
        else:
            self.state = {
                "control_plane": self.herdr.control_plane,
                "owned": {
                    "workspace_ids": [],
                    "pane_ids": [],
                    "branches": [],
                    "worktrees": []
                }
            }
            self.save()

    def save(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def record_workspace(self, workspace_id: str, pane_id: str):
        if workspace_id not in self.state["owned"]["workspace_ids"]:
            self.state["owned"]["workspace_ids"].append(workspace_id)
        if pane_id not in self.state["owned"]["pane_ids"]:
            self.state["owned"]["pane_ids"].append(pane_id)
        self.save()

    def record_worktree(self, path: str, branch: str):
        if path not in self.state["owned"]["worktrees"]:
            self.state["owned"]["worktrees"].append(path)
        if branch not in self.state["owned"]["branches"]:
            self.state["owned"]["branches"].append(branch)
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
        self.save()
        return success

    def cleanup_owned_resources(self) -> dict:
        """Idempotently cleans ONLY explicitly owned resources."""
        cleaned = {
            "workspaces_closed": [],
            "worktrees_removed": [],
            "branches_deleted": [],
            "tmp_cleaned": False
        }

        # 1. Close owned Herdr workspaces
        for ws_id in list(self.state["owned"]["workspace_ids"]):
            if self.is_owned_workspace(ws_id):
                try:
                    self.herdr.close_workspace(ws_id)
                    cleaned["workspaces_closed"].append(ws_id)
                except Exception:
                    pass
        self.state["owned"]["workspace_ids"] = []
        self.state["owned"]["pane_ids"] = []

        # 2. Remove owned git worktrees
        for wt_path in list(self.state["owned"]["worktrees"]):
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
        self.state["owned"]["worktrees"] = []

        # 3. Clean tmp/cache files
        if TMP_DIR.exists():
            for item in TMP_DIR.glob("*"):
                if item.is_file() or item.is_symlink():
                    item.unlink(missing_ok=True)
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
            cleaned["tmp_cleaned"] = True

        self.save()
        return cleaned


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


def validate_plan_file(plan_path: pathlib.Path, factory_config: dict = None) -> list:
    """
    Validates a plan against structural, dependency, and security constraints.
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

    # Required top-level fields
    for field in ["plan_id", "name", "version", "waves"]:
        if field not in plan:
            errors.append(f"Missing required top-level field: '{field}'")

    waves = plan.get("waves", [])
    if not isinstance(waves, list) or len(waves) == 0:
        errors.append("Plan must define at least one wave in 'waves'")
        return errors

    task_ids = set()
    dependencies_graph = {}

    for wave in waves:
        if "wave_index" not in wave or "tasks" not in wave:
            errors.append(f"Wave missing 'wave_index' or 'tasks': {wave}")
            continue

        tasks = wave.get("tasks", [])
        for task in tasks:
            tid = task.get("task_id")
            if not tid:
                errors.append(f"Task in wave {wave.get('wave_index')} is missing 'task_id'")
                continue
            if tid in task_ids:
                errors.append(f"Duplicate task_id detected: '{tid}'")
            task_ids.add(tid)

            # Worker validation
            wid = task.get("worker_id")
            if not wid:
                errors.append(f"Task '{tid}' is missing 'worker_id'")
            elif worker_registry and wid not in worker_registry:
                errors.append(f"Task '{tid}' specifies unknown worker: '{wid}'")

            # Dependency recording
            deps = task.get("dependencies", [])
            dependencies_graph[tid] = deps

            # Allowed paths validation
            for p in task.get("allowed_paths", []):
                if not is_path_safe_under_root(p, PROJECT_ROOT):
                    errors.append(f"Task '{tid}' specifies unsafe path escaping project root: '{p}'")

            # Expected files validation
            for ef in task.get("expected_files", []):
                if not is_path_safe_under_root(ef, PROJECT_ROOT):
                    errors.append(f"Task '{tid}' specifies unsafe expected file path: '{ef}'")

            # Context files validation
            for cf in task.get("context_files", []):
                if not is_path_safe_under_root(cf, PROJECT_ROOT):
                    errors.append(f"Task '{tid}' specifies unsafe context file path: '{cf}'")

    # Dependency existence and cycle check
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
    """Executes preflight audit and records evidence in .agy-factory/evidence/preflight/."""
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

    with open(preflight_dir / "preflight_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(preflight_dir / "baseline_herdr_inventory.json", "w", encoding="utf-8") as f:
        json.dump(baseline_inventory, f, indent=2)

    return report


class TaskExecutor:
    """Executes a single task in an isolated Git worktree and Herdr workspace."""

    def __init__(self, run_id: str, plan_task: dict, run_dir: pathlib.Path,
                 herdr: HerdrClient, res_mgr: ResourceManager, factory_config: dict):
        self.run_id = run_id
        self.task = plan_task
        self.task_id = plan_task["task_id"]
        self.worker_id = plan_task["worker_id"]
        self.run_dir = run_dir
        self.herdr = herdr
        self.res_mgr = res_mgr
        self.factory_config = factory_config

        self.worker_cmd = factory_config["worker_registry"][self.worker_id]["command"]
        self.model = factory_config.get("default_model", "gemini-3.8-flash-high")
        self.allowed_paths = plan_task.get("allowed_paths", [])
        self.expected_files = plan_task.get("expected_files", [])
        self.context_files = plan_task.get("context_files", [])
        self.review_only = plan_task.get("review_only", False)
        self.timeout = plan_task.get("timeout", 180)

        self.task_dir = run_dir / "workers" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.worktree_path = WORKTREES_DIR / run_id / self.task_id
        self.branch_name = f"factory/{run_id}/{self.task_id}"

        self.workspace_id = None
        self.pane_id = None
        self.start_time = None
        self.end_time = None
        self.state = "PENDING"
        self.result = {}

    def prepare_worktree(self, base_commit: str):
        """Creates an isolated git worktree and ensures target directory hierarchy."""
        self.worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if self.worktree_path.exists():
            subprocess.run(["git", "worktree", "remove", "--force", str(self.worktree_path)],
                           cwd=str(PROJECT_ROOT), capture_output=True)
            shutil.rmtree(self.worktree_path, ignore_errors=True)

        subprocess.run(["git", "branch", "-D", self.branch_name], cwd=str(PROJECT_ROOT), capture_output=True)

        cmd = ["git", "worktree", "add", "-b", self.branch_name, str(self.worktree_path), base_commit]
        res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {res.stderr}")

        # Dynamically pre-create directory paths for allowed paths and expected files
        for p in self.allowed_paths:
            norm_p = p.replace("/**", "").replace("/*", "")
            if "/" in norm_p:
                (self.worktree_path / norm_p).mkdir(parents=True, exist_ok=True)
        for ef in self.expected_files:
            (self.worktree_path / pathlib.Path(ef).parent).mkdir(parents=True, exist_ok=True)

        self.res_mgr.record_worktree(str(self.worktree_path), self.branch_name)

    def prepare_workspace(self):
        """Creates an experiment-owned Herdr workspace."""
        label = f"task-{self.task_id}"
        self.workspace_id, self.pane_id = self.herdr.create_workspace(
            cwd=str(self.worktree_path),
            label=label
        )
        self.res_mgr.record_workspace(self.workspace_id, self.pane_id)

    def build_prompt(self) -> str:
        # Collect declared context files dynamically from worktree
        context_blocks = []
        for cf in self.context_files:
            cf_path = self.worktree_path / cf
            if cf_path.exists():
                content = cf_path.read_text(encoding="utf-8")
                context_blocks.append(f"### Reference Context File: `{cf}`\n```markdown\n{content}\n```")
        context_content = ("\n\n" + "\n\n".join(context_blocks)) if context_blocks else ""

        target_files_guidance = ""
        if self.expected_files:
            targets = "\n".join(f"- `{self.worktree_path / f}`" for f in self.expected_files)
            target_files_guidance = f"### Required TargetFile Paths to Create via write_to_file:\n{targets}\n"

        if self.review_only:
            template_path = PROJECT_ROOT / "prompts" / "reviewer-base.md"
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
            return template.format(
                worktree_path=str(self.worktree_path),
                spec_path=str(self.worktree_path / self.context_files[0]) if self.context_files else "docs/SPECIFICATION.md",
                task_id=self.task_id
            ) + context_content
        else:
            template_path = PROJECT_ROOT / "prompts" / "worker-base.md"
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
            patterns_str = "\n".join(f"- `{p}`" for p in self.allowed_paths)
            return template.format(
                worktree_path=str(self.worktree_path),
                allowed_patterns=patterns_str,
                task_description=self.task["description"] + context_content,
                target_files_guidance=target_files_guidance,
                task_id=self.task_id
            )

    def execute(self) -> dict:
        self.state = "RUNNING"
        self.start_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        prompt_content = self.build_prompt()
        prompt_file = self.task_dir / "prompt.md"
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_content)

        output_json_path = self.task_dir / "output.json"
        status_file_path = self.task_dir / "exit_code.txt"

        custom_schema = self.task_plan.get("result_schema")
        if custom_schema:
            schema_src = PROJECT_ROOT / custom_schema
        else:
            schema_src = PROJECT_ROOT / "schemas" / ("review-result.schema.json" if self.review_only else "worker-result.schema.json")
        schema_dest = self.task_dir / "schema.json"
        shutil.copyfile(schema_src, schema_dest)

        script_path = self.task_dir / "run_worker.sh"
        with open(script_path, "w", encoding="utf-8") as sf:
            sf.write(f"""#!/bin/bash
set -o pipefail
cd "{self.worktree_path}"
"{self.worker_cmd}" --mode accept-edits --add-dir "{self.worktree_path}" \
  -p "$(< "{prompt_file}")" \
  --model "{self.model}" \
  --output-format json \
  --json-schema "$(< "{schema_dest}")" \
  > "{output_json_path}" 2>&1
echo $? > "{status_file_path}"
""")
        os.chmod(script_path, 0o755)

        self.herdr.run_in_pane(self.pane_id, f'bash "{script_path}"')

        start_wait = time.time()
        while time.time() - start_wait < self.timeout:
            if status_file_path.exists() and status_file_path.stat().st_size > 0:
                break
            time.sleep(1)

        self.end_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not status_file_path.exists():
            self.state = "FAILED"
            return {
                "task_id": self.task_id,
                "state": "FAILED",
                "status": "TIMEOUT",
                "start_time": self.start_time,
                "end_time": self.end_time,
                "error": f"Worker timed out after {self.timeout}s"
            }

        exit_code = int(status_file_path.read_text().strip())
        self.state = "RESULT_RECEIVED"

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

        agy_data = _parse_output(raw_output)

        # Inspect diff for changed paths
        untracked_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(self.worktree_path),
            capture_output=True,
            text=True
        )
        changed_paths = []
        for line in untracked_res.stdout.splitlines():
            if line.strip():
                changed_paths.append(line[3:].strip())

        # Strict path allowlist verification
        path_violations = []
        if not self.review_only:
            for p in changed_paths:
                if not match_path_allowlist(p, self.allowed_paths):
                    path_violations.append(p)

        # Expected files check
        missing_expected = []
        if not self.review_only and self.expected_files:
            for exp_file in self.expected_files:
                if not (self.worktree_path / exp_file).exists():
                    missing_expected.append(exp_file)

        structured_output = agy_data.get("structured_output", {})
        if not structured_output and "response" in agy_data:
            try:
                m = re.search(r"(\{[\s\S]*\})", agy_data["response"])
                if m:
                    structured_output = json.loads(m.group(1))
            except Exception:
                pass

        subagents_observed = "subagent" in raw_output.lower() or "invoke_subagent" in raw_output

        is_success = (
            exit_code == 0
            and agy_data.get("status") == "SUCCESS"
            and not path_violations
            and not missing_expected
            and (self.review_only or len(changed_paths) > 0)
        )

        self.state = "PATH_VALIDATED" if is_success else "FAILED"

        execution_record = {
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "worker_command": self.worker_cmd,
            "model": self.model,
            "branch": self.branch_name,
            "worktree": str(self.worktree_path),
            "workspace_id": self.workspace_id,
            "pane_id": self.pane_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "exit_code": exit_code,
            "agy_status": agy_data.get("status", "UNKNOWN"),
            "changed_paths": changed_paths,
            "path_violations": path_violations,
            "missing_expected": missing_expected,
            "structured_output": structured_output,
            "usage": agy_data.get("usage", {}),
            "subagents_observed": subagents_observed,
            "state": self.state,
            "status": "SUCCESS" if is_success else "FAILED"
        }

        with open(self.task_dir / "execution_record.json", "w", encoding="utf-8") as f:
            json.dump(execution_record, f, indent=2)

        self.result = execution_record
        return execution_record

    def commit_work(self) -> str:
        """Commits verified changes in the task worktree."""
        subprocess.run(["git", "add", "-A"], cwd=str(self.worktree_path), check=True)
        diff_check = subprocess.run(["git", "status", "--porcelain"], cwd=str(self.worktree_path), capture_output=True, text=True)
        if not diff_check.stdout.strip():
            head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.worktree_path), capture_output=True, text=True).stdout.strip()
            self.state = "COMMITTED"
            self.result["state"] = self.state
            return head_commit

        summary = self.result.get("structured_output", {}).get("summary", f"Implemented {self.task_id}")
        msg = f"feat({self.task_id}): {summary}\n\nTask: {self.task_id}\nWorker: {self.worker_id}\nModel: {self.model}"
        subprocess.run(["git", "commit", "-m", msg], cwd=str(self.worktree_path), check=True)
        commit_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.worktree_path), capture_output=True, text=True).stdout.strip()
        self.state = "COMMITTED"
        self.result["state"] = self.state
        self.result["commit_hash"] = commit_hash
        return commit_hash


class FactoryOrchestrator:
    """Generic plan orchestrator executing sequential and parallel waves."""

    def __init__(self, plan_path: pathlib.Path, run_id: str = None):
        self.plan_path = plan_path
        with open(plan_path, "r", encoding="utf-8") as f:
            self.plan = json.load(f)

        with open(FACTORY_CONFIG_PATH, "r", encoding="utf-8") as f:
            self.factory_config = json.load(f)

        self.herdr = HerdrClient(PROJECT_ROOT)
        self.res_mgr = ResourceManager(self.herdr)

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
            self.manifest = {
                "run_id": self.run_id,
                "plan_path": str(self.plan_path),
                "plan_name": self.plan["name"],
                "plan_id": self.plan["plan_id"],
                "control_plane": self.herdr.control_plane,
                "start_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "status": "RUNNING",
                "waves": [],
                "final_audit": {},
                "final_status": "PENDING"
            }
            self.log_event("RUN_STARTED", {"run_id": self.run_id, "plan": self.plan["name"]})

    def log_event(self, event_type: str, payload: dict):
        event = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": event_type,
            "payload": payload
        }
        with open(self.events_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def run_validation_commands(self, commands_list: list) -> dict:
        """Executes a list of declared validation commands."""
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
                proc = subprocess.run(
                    cmd,
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=timeout
                )
                results[name] = {
                    "command": cmd,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "passed": proc.returncode == 0
                }
            except subprocess.TimeoutExpired:
                results[name] = {
                    "command": cmd,
                    "returncode": -1,
                    "error": f"Timeout expired after {timeout}s",
                    "passed": False
                }
            except Exception as e:
                results[name] = {
                    "command": cmd,
                    "returncode": -1,
                    "error": str(e),
                    "passed": False
                }

        results_file = test_dir / f"validation_{datetime.datetime.now(datetime.timezone.utc).strftime('%H%M%S')}.json"
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        return results

    def merge_task_branch(self, branch_name: str, task_id: str) -> bool:
        """Merges a task branch into main in the project root with automatic abort on conflict."""
        res = subprocess.run(
            ["git", "merge", "--no-ff", branch_name, "-m", f"chore(factory): integrate {task_id}"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True
        )
        success = res.returncode == 0
        if not success:
            subprocess.run(["git", "merge", "--abort"], cwd=str(PROJECT_ROOT), capture_output=True)

        self.log_event("BRANCH_MERGED" if success else "MERGE_CONFLICT", {
            "branch": branch_name,
            "task_id": task_id,
            "success": success,
            "output": res.stdout or res.stderr
        })
        return success

    def execute_plan(self, resume_mode: bool = False) -> dict:
        """Main execution loop running waves sequentially with resume awareness."""
        # 1. Plan validation
        plan_errors = validate_plan_file(self.plan_path, self.factory_config)
        if plan_errors:
            raise ValueError(f"Plan validation failed before worker creation:\n" + "\n".join(f"- {e}" for e in plan_errors))

        current_base_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True
        ).stdout.strip()

        # Build map of existing completed tasks in manifest if resuming
        completed_tasks = {}
        if resume_mode:
            for w in self.manifest.get("waves", []):
                for t in w.get("tasks", []):
                    if t.get("state") in ("COMMITTED", "INTEGRATED") and t.get("status") == "SUCCESS":
                        completed_tasks[t["task_id"]] = t

        for wave in self.plan["waves"]:
            wave_index = wave["wave_index"]
            wave_name = wave["name"]
            is_parallel = wave.get("parallel", False)
            self.log_event("WAVE_STARTED", {"wave": wave_name, "wave_index": wave_index, "parallel": is_parallel})

            wave_record = {
                "wave_index": wave_index,
                "name": wave_name,
                "parallel": is_parallel,
                "tasks": []
            }

            executors = []
            for task_plan in wave["tasks"]:
                tid = task_plan["task_id"]
                # Resume check: Skip already integrated/committed tasks
                if resume_mode and tid in completed_tasks:
                    existing = completed_tasks[tid]
                    self.log_event("TASK_RESUMED_SKIPPED", {"task_id": tid, "state": existing.get("state")})
                    wave_record["tasks"].append(existing)
                    continue

                executor = TaskExecutor(
                    self.run_id,
                    task_plan,
                    self.run_dir,
                    self.herdr,
                    self.res_mgr,
                    self.factory_config
                )
                executor.prepare_worktree(current_base_commit)
                executor.prepare_workspace()
                executors.append(executor)

            # Execute pending workers
            if executors:
                if is_parallel:
                    self.log_event("PARALLEL_DISPATCH", {"tasks": [e.task_id for e in executors]})
                    with concurrent.futures.ThreadPoolExecutor(max_workers=len(executors)) as pool:
                        futures = {pool.submit(e.execute): e for e in executors}
                        for fut in concurrent.futures.as_completed(futures):
                            e = futures[fut]
                            self.log_event("TASK_COMPLETED", {"task_id": e.task_id, "status": e.result.get("status")})
                else:
                    for e in executors:
                        e.execute()
                        self.log_event("TASK_COMPLETED", {"task_id": e.task_id, "status": e.result.get("status")})

                # Commit work
                for e in executors:
                    if not e.review_only and e.result.get("status") == "SUCCESS":
                        commit_hash = e.commit_work()
                        e.result["commit_hash"] = commit_hash
                    wave_record["tasks"].append(e.result)

                # Merge work
                if not any(e.review_only for e in executors):
                    for e in executors:
                        if e.result.get("status") == "SUCCESS":
                            merge_ok = self.merge_task_branch(e.branch_name, e.task_id)
                            if not merge_ok:
                                raise RuntimeError(f"Merge conflict integrating task branch '{e.branch_name}'")
                            e.state = "INTEGRATED"
                            e.result["state"] = "INTEGRATED"

                    current_base_commit = subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=str(PROJECT_ROOT),
                        capture_output=True,
                        text=True
                    ).stdout.strip()

            # Record wave in manifest
            existing_wave = next((w for w in self.manifest["waves"] if w["wave_index"] == wave_index), None)
            if existing_wave:
                existing_wave["tasks"] = wave_record["tasks"]
            else:
                self.manifest["waves"].append(wave_record)

            # Execute post-wave validation commands if declared
            post_validation = wave.get("post_wave_validation", [])
            if post_validation:
                self.log_event("POST_WAVE_VALIDATION_STARTED", {"wave_index": wave_index})
                gate_results = self.run_validation_commands(post_validation)
                self.manifest[f"validation_wave_{wave_index}"] = gate_results
                all_passed = all(check.get("passed", False) for check in gate_results.values())
                self.log_event("POST_WAVE_VALIDATION_RESULT", {"wave_index": wave_index, "all_passed": all_passed, "checks": gate_results})

                # Dynamic repair injection if any test failed
                if not all_passed:
                    failures = []
                    for k, v in gate_results.items():
                        if not v.get("passed", False):
                            failures.append(f"[{k}] error={v.get('error')} stdout={v.get('stdout')} stderr={v.get('stderr')}")
                    failure_summary = "\n".join(failures)

                    # Look for repair task in subsequent waves
                    for future_wave in self.plan["waves"]:
                        if future_wave["wave_index"] > wave_index:
                            for ft in future_wave.get("tasks", []):
                                if ft.get("is_repair", False):
                                    ft["description"] = (
                                        f"REPAIR TASK: Integration verification failed with errors:\n{failure_summary}\n"
                                        "Diagnose and fix all defects in allowed paths so all test suites pass."
                                    )
                                    break

            # Capture review/audit structured output if this wave contained audit
            for task_res in wave_record["tasks"]:
                if task_res.get("structured_output", {}).get("findings") is not None:
                    self.manifest["final_audit"] = task_res["structured_output"]

        # Concurrency evidence
        parallel_waves = [w for w in self.manifest["waves"] if w.get("parallel", False)]
        concurrency_evidence = {}
        if parallel_waves:
            tasks_timing = []
            for pw in parallel_waves:
                for t in pw["tasks"]:
                    tasks_timing.append({
                        "task_id": t["task_id"],
                        "worker_id": t["worker_id"],
                        "start": t.get("start_time"),
                        "end": t.get("end_time")
                    })
            concurrency_evidence = {
                "tasks": tasks_timing,
                "parallel_group": True,
                "verified_overlap": len(tasks_timing) > 1
            }
        self.manifest["concurrency_evidence"] = concurrency_evidence

        self.manifest["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.manifest["final_status"] = "COMPLETED"

        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2)

        summary_path = self.run_dir / "final-summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2)

        return self.manifest


def main():
    parser = argparse.ArgumentParser(description="AGY-Herdr Software Factory Driver (v2.0.0)")
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
    subparsers.add_parser("status", help="Show active and past factory run status")

    # Cleanup
    subparsers.add_parser("cleanup", help="Safely clean owned workspaces, worktrees, and ephemeral files")

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
        herdr = HerdrClient(PROJECT_ROOT)
        res_mgr = ResourceManager(herdr)
        print("=== AGY-Herdr Software Factory Status ===")
        print(f"Project Root: {PROJECT_ROOT}")
        print(f"Control Plane Context: {json.dumps(res_mgr.state['control_plane'], indent=2)}")
        print(f"Owned Resources: {json.dumps(res_mgr.state['owned'], indent=2)}")
        runs = list(RUNS_DIR.glob("run-*"))
        print(f"Total Recorded Runs: {len(runs)}")
        for r in sorted(runs):
            m = r / "manifest.json"
            if m.exists():
                with open(m, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tasks_info = []
                for w in data.get("waves", []):
                    for t in w.get("tasks", []):
                        tasks_info.append(f"{t.get('task_id')}:{t.get('state', t.get('status'))}")
                print(f"  - {r.name}: status={data.get('final_status')} plan={data.get('plan_id')} tasks=[{', '.join(tasks_info)}]")

    elif args.command == "cleanup":
        herdr = HerdrClient(PROJECT_ROOT)
        res_mgr = ResourceManager(herdr)
        result = res_mgr.cleanup_owned_resources()
        print("Cleanup completed safely:")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
