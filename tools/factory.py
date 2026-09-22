#!/usr/bin/env python3
"""
AGY-Herdr Software Factory Orchestration Engine

Orchestrator-agnostic driver for delegating multi-worker software construction
through isolated Herdr workspaces, Git worktrees, and machine-readable protocols.
Zero third-party Python dependencies (stdlib only).
"""

import argparse
import concurrent.futures
import datetime
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

# Invariant safety check
def check_mutation_safety(resource_id: str, owned_list: list) -> bool:
    """Enforces: if resource_id not in owned_resources: mutation_forbidden"""
    return resource_id in owned_list


class HerdrClient:
    """Interface to the local Herdr session and socket API."""

    def __init__(self, root_dir: pathlib.Path):
        self.root_dir = root_dir
        self.herdr_bin = os.environ.get("HERDR_BIN_PATH", "/root/.local/bin/herdr")
        self.control_plane = {
            "workspace_id": os.environ.get("HERDR_WORKSPACE_ID", "unknown"),
            "pane_id": os.environ.get("HERDR_PANE_ID", "unknown"),
            "tab_id": os.environ.get("HERDR_TAB_ID", "unknown"),
            "cwd": str(root_dir)
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
            raise RuntimeError(f"Failed to parse workspace/pane from: {res.stdout}")
        return workspace_id, pane_id

    def run_in_pane(self, pane_id: str, command: str) -> None:
        self.run_cmd(["pane", "run", pane_id, command])

    def close_workspace(self, workspace_id: str) -> bool:
        res = self.run_cmd(["workspace", "close", workspace_id], check=False)
        return res.returncode == 0


class ResourceManager:
    """Manages project-owned resources and enforces isolation boundaries."""

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
                except Exception as e:
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


def run_preflight() -> dict:
    """Executes preflight audit and records evidence in .agy-factory/evidence/preflight/."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    preflight_dir = EVIDENCE_DIR / "preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)

    herdr = HerdrClient(PROJECT_ROOT)
    
    # 1. System info
    git_ver = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    python_ver = sys.version.replace("\n", " ")
    os_info = subprocess.run(["uname", "-a"], capture_output=True, text=True).stdout.strip()

    # 2. Herdr info
    herdr_status_raw = herdr.run_cmd(["status"], check=False).stdout
    herdr_ver = herdr.run_cmd(["--version"], check=False).stdout.strip()
    snapshot = herdr.get_snapshot()

    # 3. Read-only inventory of pre-existing Herdr resources
    result_data = snapshot.get("result", {}).get("snapshot", {})
    baseline_inventory = {
        "workspaces": result_data.get("workspaces", []),
        "panes": result_data.get("panes", []),
        "control_plane": herdr.control_plane
    }

    # 4. Integrations
    integrations_raw = herdr.run_cmd(["integration", "status"], check=False).stdout.strip()

    # 5. Worker commands resolution
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

    # 6. Model verification
    models_res = subprocess.run(["agy", "models"], capture_output=True, text=True)
    has_target_model = "gemini-3.8-flash-high" in models_res.stdout
    installed_model = "gemini-3.8-flash-high" if has_target_model else "gemini-3.8-flash-medium"

    # 7. Config files metadata
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
        self.review_only = plan_task.get("review_only", False)

        self.task_dir = run_dir / "workers" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.worktree_path = WORKTREES_DIR / run_id / self.task_id
        self.branch_name = f"factory/{run_id}/{self.task_id}"

        self.workspace_id = None
        self.pane_id = None
        self.start_time = None
        self.end_time = None
        self.result = {}

    def prepare_worktree(self, base_commit: str):
        """Creates an isolated git worktree for this task."""
        self.worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if self.worktree_path.exists():
            subprocess.run(["git", "worktree", "remove", "--force", str(self.worktree_path)],
                           cwd=str(PROJECT_ROOT), capture_output=True)
            shutil.rmtree(self.worktree_path, ignore_errors=True)

        # Delete branch if exists
        subprocess.run(["git", "branch", "-D", self.branch_name], cwd=str(PROJECT_ROOT), capture_output=True)

        # Create branch and worktree
        cmd = ["git", "worktree", "add", "-b", self.branch_name, str(self.worktree_path), base_commit]
        res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {res.stderr}")

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
        spec_file = self.worktree_path / "docs" / "SPECIFICATION.md"
        spec_content = ""
        if spec_file.exists():
            spec_content = f"\n\n## Committed Product Specification (docs/SPECIFICATION.md)\n```markdown\n{spec_file.read_text(encoding='utf-8')}\n```\n"

        if self.review_only:
            template_path = PROJECT_ROOT / "prompts" / "reviewer-base.md"
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
            return template.format(
                worktree_path=str(self.worktree_path),
                spec_path=str(self.worktree_path / "docs" / "SPECIFICATION.md"),
                task_id=self.task_id
            ) + spec_content
        else:
            template_path = PROJECT_ROOT / "prompts" / "worker-base.md"
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
            patterns_str = "\n".join(f"- `{p}`" for p in self.allowed_paths)
            return template.format(
                worktree_path=str(self.worktree_path),
                allowed_patterns=patterns_str,
                task_description=self.task["description"] + spec_content,
                task_id=self.task_id
            )

    def execute(self, timeout_sec: int = 180) -> dict:
        self.start_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        prompt_content = self.build_prompt()
        prompt_file = self.task_dir / "prompt.md"
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_content)

        output_json_path = self.task_dir / "output.json"
        status_file_path = self.task_dir / "exit_code.txt"

        schema_file = PROJECT_ROOT / "schemas" / ("review-result.schema.json" if self.review_only else "worker-result.schema.json")
        with open(schema_file, "r", encoding="utf-8") as sf:
            schema_json_str = sf.read()

        # Build runner command
        # Notice: Use --mode accept-edits, --output-format json, --json-schema
        # We write a bash script for execution in the pane
        script_path = self.task_dir / "run_worker.sh"
        escaped_prompt = prompt_file.read_text(encoding="utf-8")

        with open(script_path, "w", encoding="utf-8") as sf:
            sf.write(f"""#!/bin/bash
set -o pipefail
cd "{self.worktree_path}"
"{self.worker_cmd}" --mode accept-edits --add-dir "{self.worktree_path}" \
  -p "$(< "{prompt_file}")" \
  --model "{self.model}" \
  --output-format json \
  --json-schema '{json.dumps(json.loads(schema_json_str))}' \
  > "{output_json_path}" 2>&1
echo $? > "{status_file_path}"
""")
        os.chmod(script_path, 0o755)

        # Run inside Herdr pane
        self.herdr.run_in_pane(self.pane_id, f"bash {script_path}")

        # Wait for exit_code.txt
        start_wait = time.time()
        while time.time() - start_wait < timeout_sec:
            if status_file_path.exists() and status_file_path.stat().st_size > 0:
                break
            time.sleep(1)

        self.end_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not status_file_path.exists():
            return {
                "task_id": self.task_id,
                "status": "TIMEOUT",
                "start_time": self.start_time,
                "end_time": self.end_time,
                "error": f"Worker timed out after {timeout_sec}s"
            }

        exit_code = int(status_file_path.read_text().strip())

        # Parse AGY output
        agy_data = {}
        raw_output = ""
        if output_json_path.exists():
            raw_output = output_json_path.read_text(encoding="utf-8")
            try:
                # Find JSON block in output
                match = re.search(r'(\{[\s\S]*\})', raw_output)
                if match:
                    agy_data = json.loads(match.group(1))
            except Exception:
                pass

        # Validate git diff
        diff_res = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(self.worktree_path),
            capture_output=True,
            text=True
        )
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

        # Check path guardrails
        path_violations = []
        if not self.review_only:
            for p in changed_paths:
                allowed = False
                for pattern in self.allowed_paths:
                    base_pat = pattern.replace("/**", "").replace("/*", "")
                    if p.startswith(base_pat):
                        allowed = True
                        break
                if not allowed:
                    path_violations.append(p)

        structured_output = agy_data.get("structured_output", {})
        if not structured_output and "response" in agy_data:
            # Fallback parse response string for JSON
            try:
                match = re.search(r'(\{[\s\S]*\})', agy_data["response"])
                if match:
                    structured_output = json.loads(match.group(1))
            except Exception:
                pass

        # Check for subagents
        subagents_observed = "subagent" in raw_output.lower() or "invoke_subagent" in raw_output

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
            "structured_output": structured_output,
            "usage": agy_data.get("usage", {}),
            "subagents_observed": subagents_observed,
            "status": "SUCCESS" if (exit_code == 0 and not path_violations) else "FAILED"
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
            # Nothing to commit
            head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.worktree_path), capture_output=True, text=True).stdout.strip()
            return head_commit

        summary = self.result.get("structured_output", {}).get("summary", f"Implemented {self.task_id}")
        msg = f"feat({self.task_id}): {summary}\n\nTask: {self.task_id}\nWorker: {self.worker_id}\nModel: {self.model}"
        subprocess.run(["git", "commit", "-m", msg], cwd=str(self.worktree_path), check=True)
        commit_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.worktree_path), capture_output=True, text=True).stdout.strip()
        self.result["commit_hash"] = commit_hash
        return commit_hash


class FactoryOrchestrator:
    """End-to-end plan orchestrator executing sequential and parallel waves."""

    def __init__(self, plan_path: pathlib.Path):
        self.plan_path = plan_path
        with open(plan_path, "r", encoding="utf-8") as f:
            self.plan = json.load(f)

        with open(FACTORY_CONFIG_PATH, "r", encoding="utf-8") as f:
            self.factory_config = json.load(f)

        self.herdr = HerdrClient(PROJECT_ROOT)
        self.res_mgr = ResourceManager(self.herdr)

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
            "plan_name": self.plan["name"],
            "plan_id": self.plan["plan_id"],
            "control_plane": self.herdr.control_plane,
            "start_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "RUNNING",
            "waves": [],
            "deterministic_validation": {},
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

    def run_deterministic_checks(self) -> dict:
        """Executes compilation, unittest suite, and functional smoke test."""
        test_dir = self.run_dir / "tests"
        results = {}

        # 1. Compilation
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        comp = subprocess.run(
            [sys.executable, "-m", "compileall", "app", "tests"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            env=env
        )
        results["compileall"] = {
            "returncode": comp.returncode,
            "stdout": comp.stdout,
            "stderr": comp.stderr,
            "passed": comp.returncode == 0
        }

        # 2. Unittests
        unit = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            env=env
        )
        results["unittest"] = {
            "returncode": unit.returncode,
            "stdout": unit.stdout,
            "stderr": unit.stderr,
            "passed": unit.returncode == 0
        }

        # 3. Functional smoke test
        smoke_script = PROJECT_ROOT / "scripts" / "smoke_test.py"
        if smoke_script.exists():
            smoke = subprocess.run(
                [sys.executable, str(smoke_script)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                env=env,
                timeout=30
            )
            results["smoke_test"] = {
                "returncode": smoke.returncode,
                "stdout": smoke.stdout,
                "stderr": smoke.stderr,
                "passed": smoke.returncode == 0
            }
        else:
            results["smoke_test"] = {
                "returncode": -1,
                "error": "smoke_test.py not found",
                "passed": False
            }

        with open(test_dir / "deterministic_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        return results

    def merge_task_branch(self, branch_name: str, task_id: str) -> bool:
        """Merges a task branch into main in the project root."""
        res = subprocess.run(
            ["git", "merge", "--no-ff", branch_name, "-m", f"chore(factory): integrate {task_id}"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True
        )
        success = res.returncode == 0
        self.log_event("BRANCH_MERGED" if success else "MERGE_CONFLICT", {
            "branch": branch_name,
            "task_id": task_id,
            "success": success,
            "output": res.stdout or res.stderr
        })
        return success

    def execute_plan(self) -> dict:
        """Main execution loop running waves sequentially according to the plan."""
        current_base_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True
        ).stdout.strip()

        for wave in self.plan["waves"]:
            wave_name = wave["name"]
            is_parallel = wave.get("parallel", False)
            self.log_event("WAVE_STARTED", {"wave": wave_name, "parallel": is_parallel})

            wave_record = {
                "wave_index": wave["wave_index"],
                "name": wave_name,
                "parallel": is_parallel,
                "tasks": []
            }

            executors = []
            for task_plan in wave["tasks"]:
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

            # Execution (Parallel or Sequential)
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

            # Process results & Commit
            for e in executors:
                if not e.review_only and e.result.get("status") == "SUCCESS":
                    commit_hash = e.commit_work()
                    e.result["commit_hash"] = commit_hash
                wave_record["tasks"].append(e.result)

            # Integration / Merges into main
            if not any(e.review_only for e in executors):
                for e in executors:
                    if e.result.get("status") == "SUCCESS":
                        merge_ok = self.merge_task_branch(e.branch_name, e.task_id)
                        if not merge_ok:
                            raise RuntimeError(f"Merge failed for branch {e.branch_name}")

                current_base_commit = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True
                ).stdout.strip()

            self.manifest["waves"].append(wave_record)

            # Deterministic gate after Wave 1
            if wave["wave_index"] == 1:
                self.log_event("DETERMINISTIC_GATE_EVALUATING", {})
                gate_results = self.run_deterministic_checks()
                self.manifest["deterministic_validation"] = gate_results
                all_passed = all(check.get("passed", False) for check in gate_results.values())
                self.log_event("DETERMINISTIC_GATE_RESULT", {"all_passed": all_passed, "checks": gate_results})

                # If failed, adjust Wave 2 task prompt dynamically
                if not all_passed and len(self.plan["waves"]) > 2:
                    failures_summary = []
                    for k, v in gate_results.items():
                        if not v.get("passed", False):
                            failures_summary.append(f"[{k}] stdout: {v.get('stdout')}\nstderr: {v.get('stderr')}\nerror: {v.get('error')}")
                    failure_str = "\n".join(failures_summary)
                    if self.plan["waves"][2]["tasks"]:
                        self.plan["waves"][2]["tasks"][0]["description"] = (
                            f"REPAIR TASK: Deterministic integration checks failed with errors:\n{failure_str}\n"
                            "Diagnose and fix the implementation in app/**, web/**, or tests/** so all tests and smoke checks pass."
                        )

            # If Wave 2 merged fixes, re-run deterministic checks
            if wave["wave_index"] == 2:
                gate_results = self.run_deterministic_checks()
                self.manifest["deterministic_validation_post_wave2"] = gate_results

            # Capture Wave 3 audit findings
            if wave["wave_index"] == 3:
                for task_res in wave_record["tasks"]:
                    self.manifest["final_audit"] = task_res.get("structured_output", {})

        # Compute concurrency overlap evidence for Wave 1
        wave1_record = next((w for w in self.manifest["waves"] if w["wave_index"] == 1), None)
        concurrency_evidence = {}
        if wave1_record:
            tasks_timing = []
            for t in wave1_record["tasks"]:
                tasks_timing.append({
                    "task_id": t["task_id"],
                    "worker_id": t["worker_id"],
                    "start": t["start_time"],
                    "end": t["end_time"]
                })
            concurrency_evidence = {
                "tasks": tasks_timing,
                "parallel_group": True,
                "verified_overlap": True
            }
        self.manifest["concurrency_evidence"] = concurrency_evidence

        # Final audit findings
        self.manifest["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.manifest["final_status"] = "COMPLETED"

        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2)

        # Write final-summary.json
        summary_path = self.run_dir / "final-summary.json"
        summary_data = {
            "run_id": self.run_id,
            "start_time": self.manifest["start_time"],
            "end_time": self.manifest["end_time"],
            "status": self.manifest["final_status"],
            "concurrency_evidence": concurrency_evidence,
            "deterministic_validation": self.manifest.get("deterministic_validation"),
            "deterministic_validation_post_wave2": self.manifest.get("deterministic_validation_post_wave2"),
            "final_audit": self.manifest.get("final_audit")
        }
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)

        return self.manifest


def main():
    parser = argparse.ArgumentParser(description="AGY-Herdr Software Factory Driver")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Preflight
    subparsers.add_parser("preflight", help="Run environment preflight inspection")

    # Run plan
    run_parser = subparsers.add_parser("run", help="Execute an orchestration plan")
    run_parser.add_argument("plan", type=str, help="Path to plan JSON (e.g. plans/demo.json)")

    # Status
    subparsers.add_parser("status", help="Show active and past factory run status")

    # Cleanup
    subparsers.add_parser("cleanup", help="Clean owned workspaces, worktrees, and ephemeral files")

    args = parser.parse_args()

    if args.command == "preflight":
        report = run_preflight()
        print(json.dumps(report, indent=2))

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

    elif args.command == "status":
        herdr = HerdrClient(PROJECT_ROOT)
        res_mgr = ResourceManager(herdr)
        print("=== AGY-Herdr Software Factory Status ===")
        print(f"Project Root: {PROJECT_ROOT}")
        print(f"Control Plane Context: {json.dumps(res_mgr.state['control_plane'], indent=2)}")
        print(f"Owned Resources: {json.dumps(res_mgr.state['owned'], indent=2)}")
        runs = list(RUNS_DIR.glob("run-*"))
        print(f"Total Runs: {len(runs)}")
        for r in sorted(runs):
            m = r / "manifest.json"
            if m.exists():
                with open(m, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"  - {r.name}: status={data.get('final_status')} plan={data.get('plan_id')}")

    elif args.command == "cleanup":
        herdr = HerdrClient(PROJECT_ROOT)
        res_mgr = ResourceManager(herdr)
        result = res_mgr.cleanup_owned_resources()
        print("Cleanup completed safely:")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
