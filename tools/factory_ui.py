#!/usr/bin/env python3
"""Factory Control UI — local, read-mostly browser surface for Factory v9.

The UI intentionally reads Factory's durable project artifacts rather than
maintaining a second database or scheduler. The only mutable action currently
exposed is the already-supported public `goal resume` command.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import http.server
import ipaddress
import json
import mimetypes
import os
import pathlib
import re
import subprocess
import sys
import threading
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional, Tuple

FACTORY_ROOT = pathlib.Path(__file__).resolve().parent.parent
UI_ROOT = FACTORY_ROOT / "ui"
DEFAULT_VENDOR_ROOT = FACTORY_ROOT / ".tools" / "ui" / "vendor"
API_PREFIX = "/api/v1"
MAX_REQUEST_BODY = 64 * 1024
MAX_JSONL_LINES = 500
MAX_RUNS = 50
MAX_GOALS = 50
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")

BOARD_COLUMNS = ("BACKLOG", "READY", "RUNNING", "BLOCKED", "REVIEW", "DONE", "FAILED")
TERMINAL_RUN_STATES = {"COMPLETED", "FAILED", "CANCELLED"}
TERMINAL_GOAL_PHASES = {"COMPLETE", "FAILED", "BLOCKED"}

CANONICAL_TO_DISPLAY = {
    "PENDING": "BACKLOG",
    "CREATED": "BACKLOG",
    "READY": "READY",
    "DISPATCHING": "RUNNING",
    "RUNNING": "RUNNING",
    "EXECUTING": "RUNNING",
    "BLOCKED": "BLOCKED",
    "VALIDATING": "REVIEW",
    "PATH_VALIDATED": "REVIEW",
    "VALIDATED": "REVIEW",
    "COMMITTING": "REVIEW",
    "COMMITTED": "REVIEW",
    "INTEGRATING": "REVIEW",
    "REVIEW": "REVIEW",
    "INTEGRATED": "DONE",
    "COMPLETED": "DONE",
    "SUCCESS": "DONE",
    "FAILED": "FAILED",
    "TIMED_OUT": "FAILED",
    "CONFLICTED": "FAILED",
    "CANCELLED": "FAILED",
}


class UIDataError(RuntimeError):
    """Raised when an API detail request targets invalid or unavailable data."""


class ActionConflict(RuntimeError):
    """Raised when a requested mutable action is already running."""


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _read_json(path: pathlib.Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _read_jsonl_tail(path: pathlib.Path, limit: int = MAX_JSONL_LINES) -> List[dict]:
    if limit <= 0:
        return []
    rows: collections.deque[dict] = collections.deque(maxlen=limit)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except OSError:
        return []
    return list(rows)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _safe_text(value: Any, max_chars: int = 1200) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\x00", "")
    if len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def _safe_id(value: str, label: str = "id") -> str:
    value = str(value or "")
    if not ID_RE.fullmatch(value):
        raise UIDataError(f"Invalid {label}")
    return value


def _duration_ms(start: Optional[str], end: Optional[str]) -> Optional[float]:
    if not start or not end:
        return None
    try:
        a = _dt.datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = _dt.datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return round((b - a).total_seconds() * 1000.0, 2)
    except (TypeError, ValueError):
        return None


def _is_under(root: pathlib.Path, candidate: pathlib.Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _referenced_json(project_root: pathlib.Path, value: Any) -> Optional[dict]:
    if not value:
        return None
    path = pathlib.Path(str(value))
    if not path.is_absolute():
        path = project_root / path
    if not _is_under(project_root, path):
        return None
    data = _read_json(path, None)
    return data if isinstance(data, dict) else None


def _display_state(task: dict) -> str:
    display = str(task.get("display_state") or "").upper()
    if display in BOARD_COLUMNS:
        return display
    canonical = str(task.get("canonical_state") or task.get("state") or task.get("status") or "PENDING").upper()
    return CANONICAL_TO_DISPLAY.get(canonical, "FAILED" if canonical.endswith("FAILED") else "BACKLOG")


def _compact_attempt(attempt: dict) -> dict:
    usage = attempt.get("usage") if isinstance(attempt.get("usage"), dict) else {}
    return {
        "attempt_id": attempt.get("attempt_id"),
        "state": attempt.get("state"),
        "status": attempt.get("status") or attempt.get("agy_status"),
        "profile_id": attempt.get("profile_id") or attempt.get("profile"),
        "worker_id": attempt.get("worker_id"),
        "harness": attempt.get("harness"),
        "adapter": attempt.get("adapter"),
        "model": attempt.get("model"),
        "effort": attempt.get("effort"),
        "execution_mode": attempt.get("execution_mode") or attempt.get("mode"),
        "start_time": attempt.get("start_time"),
        "end_time": attempt.get("end_time"),
        "duration_ms": attempt.get("duration_ms") or _duration_ms(attempt.get("start_time"), attempt.get("end_time")),
        "commit_hash": attempt.get("commit_hash"),
        "changed_paths": list(attempt.get("changed_paths") or []),
        "path_violations": list(attempt.get("path_violations") or []),
        "missing_expected": list(attempt.get("missing_expected") or []),
        "error": _safe_text(attempt.get("error"), 1600) if attempt.get("error") else None,
        "usage": {
            "input_tokens": usage.get("input_tokens") or attempt.get("provider_input_tokens"),
            "cached_input_tokens": usage.get("cache_read_tokens") or attempt.get("provider_cached_input_tokens"),
            "reasoning_tokens": usage.get("thinking_tokens") or usage.get("reasoning_tokens") or attempt.get("provider_reasoning_tokens"),
            "output_tokens": usage.get("output_tokens") or attempt.get("provider_output_tokens"),
        },
    }


def _compact_task(task_id: str, task: dict, run_id: str) -> dict:
    attempts = task.get("attempts") if isinstance(task.get("attempts"), list) else []
    latest = task.get("latest_result") if isinstance(task.get("latest_result"), dict) else (attempts[-1] if attempts else {})
    compact_latest = _compact_attempt(latest)
    return {
        "run_id": run_id,
        "task_id": task_id,
        "name": task.get("name") or task.get("title") or task_id,
        "task_type": task.get("task_type"),
        "execution_class": task.get("execution_class"),
        "display_state": _display_state(task),
        "canonical_state": task.get("canonical_state") or task.get("state"),
        "status": task.get("status") or compact_latest.get("status"),
        "worker_id": task.get("worker_id") or compact_latest.get("worker_id"),
        "profile_id": task.get("profile_id") or task.get("profile") or compact_latest.get("profile_id"),
        "harness": task.get("harness") or compact_latest.get("harness") or compact_latest.get("adapter"),
        "model": task.get("model") or compact_latest.get("model"),
        "effort": task.get("effort") or compact_latest.get("effort"),
        "execution_mode": compact_latest.get("execution_mode"),
        "attempts_count": task.get("attempts_count") if task.get("attempts_count") is not None else len(attempts),
        "current_attempt_id": task.get("current_attempt_id") or compact_latest.get("attempt_id"),
        "dependencies": list(task.get("dependencies") or []),
        "commit_hash": compact_latest.get("commit_hash"),
        "start_time": compact_latest.get("start_time"),
        "end_time": compact_latest.get("end_time"),
        "duration_ms": compact_latest.get("duration_ms"),
        "changed_paths": compact_latest.get("changed_paths") or [],
        "error": compact_latest.get("error"),
    }


def _compact_run(manifest: dict) -> dict:
    tasks = manifest.get("tasks") if isinstance(manifest.get("tasks"), dict) else {}
    counts = {column: 0 for column in BOARD_COLUMNS}
    for task_id, task in tasks.items():
        counts[_display_state(task)] += 1
    return {
        "run_id": manifest.get("run_id"),
        "goal_id": manifest.get("goal_id"),
        "plan_id": manifest.get("plan_id"),
        "plan_name": manifest.get("plan_name") or manifest.get("name"),
        "run_state": manifest.get("run_state") or manifest.get("final_status") or "UNKNOWN",
        "certification_level": manifest.get("certification_level"),
        "contains_mock_execution": bool(manifest.get("contains_mock_execution", False)),
        "start_time": manifest.get("start_time"),
        "end_time": manifest.get("end_time"),
        "task_count": len(tasks),
        "counts": counts,
    }


class FactoryReadModel:
    """Read-only projection over Factory's durable, versioned project artifacts."""

    def __init__(self, project_root: pathlib.Path, factory_root: pathlib.Path = FACTORY_ROOT):
        self.project_root = pathlib.Path(project_root).resolve()
        self.factory_root = pathlib.Path(factory_root).resolve()
        self.runtime_root = self.project_root / ".agy-factory"
        self.runs_dir = self.runtime_root / "runs"
        self.goals_dir = self.runtime_root / "goals"
        self.evidence_dir = self.runtime_root / "evidence"

    def _load_factory_config(self, filename: str, default: Any) -> Any:
        return _read_json(self.factory_root / filename, default)

    def _list_run_manifests(self) -> List[dict]:
        results: List[dict] = []
        if not self.runs_dir.is_dir():
            return results
        for run_dir in sorted(self.runs_dir.glob("run-*"), reverse=True)[:MAX_RUNS]:
            data = _read_json(run_dir / "manifest.json", None)
            if isinstance(data, dict):
                data.setdefault("run_id", run_dir.name)
                results.append(data)
        results.sort(key=lambda item: str(item.get("start_time") or item.get("run_id") or ""), reverse=True)
        return results

    def _list_goal_states(self) -> List[dict]:
        results: List[dict] = []
        if not self.goals_dir.is_dir():
            return results
        for goal_dir in sorted(self.goals_dir.glob("goal-*"), reverse=True)[:MAX_GOALS]:
            state = _read_json(goal_dir / "state.json", None)
            if isinstance(state, dict):
                state.setdefault("goal_id", goal_dir.name)
                results.append(state)
        results.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or item.get("goal_id") or ""), reverse=True)
        return results

    def _telemetry(self, run_id: Optional[str] = None, task_id: Optional[str] = None) -> List[dict]:
        rows = _read_jsonl_tail(self.evidence_dir / "telemetry.jsonl", MAX_JSONL_LINES)
        if run_id:
            rows = [row for row in rows if row.get("run_id") == run_id]
        if task_id:
            rows = [row for row in rows if row.get("task_id") == task_id]
        return rows

    def _events(self, run_id: str, task_id: Optional[str] = None) -> List[dict]:
        rows = _read_jsonl_tail(self.runs_dir / run_id / "events.jsonl", 300)
        if task_id:
            filtered = []
            for row in rows:
                payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                if payload.get("task_id") == task_id or row.get("task_id") == task_id:
                    filtered.append(row)
            rows = filtered
        return rows

    def _provider_summary(self) -> List[dict]:
        raw = self._load_factory_config("harness_profiles.json", {})
        profiles = raw.get("profiles") if isinstance(raw, dict) and isinstance(raw.get("profiles"), dict) else {}
        grouped: Dict[str, List[dict]] = collections.defaultdict(list)
        for profile_id, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            harness = str(profile.get("harness") or profile.get("adapter") or "unknown")
            certification = profile.get("certification") if isinstance(profile.get("certification"), dict) else {}
            grouped[harness].append({
                "profile_id": profile_id,
                "model": profile.get("model"),
                "effort": profile.get("effort"),
                "status": certification.get("status") or "UNKNOWN",
                "enabled": bool(profile.get("enabled", True)),
            })
        precedence = {
            "REAL_PROVIDER_CERTIFIED": 100,
            "AVAILABLE": 90,
            "TRANSPORT_CERTIFIED": 80,
            "DETERMINISTIC_CERTIFIED": 70,
            "AUTH_BLOCKED": 40,
            "PROFILE_UNAVAILABLE": 30,
            "PROFILE_INVALID": 20,
            "PROFILE_DRIFT": 10,
            "UNKNOWN": 0,
        }
        result = []
        for harness in sorted(grouped):
            entries = grouped[harness]
            status = max((entry["status"] for entry in entries), key=lambda item: precedence.get(str(item), 0), default="UNKNOWN")
            models = sorted({str(entry.get("model")) for entry in entries if entry.get("model")})
            result.append({
                "id": harness,
                "harness": harness,
                "label": harness.upper() if harness in {"agy"} else harness.replace("-", " ").title(),
                "status": status,
                "profile_count": len(entries),
                "detail": ", ".join(models[:3]) if models else f"{len(entries)} profile(s)",
                "profiles": entries,
            })
        lock = self._load_factory_config("toolchain.lock.json", {})
        if isinstance(lock, dict):
            for key, status_key in (("freebuff", "feasibility_status"), ("herdr_board", "compatibility_status")):
                item = lock.get(key)
                if isinstance(item, dict):
                    identifier = key.replace("_", "-")
                    result.append({
                        "id": identifier,
                        "harness": identifier,
                        "label": "herdr-board" if key == "herdr_board" else "Freebuff",
                        "status": item.get(status_key) or "UNKNOWN",
                        "profile_count": 0,
                        "detail": _safe_text(item.get("compatibility_notes") or item.get("notes"), 240),
                        "profiles": [],
                    })
        return result

    def _goal_summary(self, state: dict) -> dict:
        raw_goal = _safe_text(state.get("raw_goal"), 220)
        first_line = next((line.strip("# ") for line in raw_goal.splitlines() if line.strip()), state.get("goal_id"))
        phase = str(state.get("phase") or "UNKNOWN")
        return {
            "goal_id": state.get("goal_id"),
            "title": first_line or state.get("goal_id"),
            "phase": phase,
            "run_id": state.get("run_id"),
            "updated_at": state.get("updated_at"),
            "created_at": state.get("created_at"),
            "completed_at": state.get("completed_at"),
            "plan_revision_count": state.get("plan_revision_count", 0),
            "remediation_round_count": state.get("remediation_round_count", 0),
            "resumable": phase not in TERMINAL_GOAL_PHASES,
            "error": _safe_text(state.get("error"), 500) if state.get("error") else None,
        }

    def _usage_summary(self, run_id: Optional[str], tasks: Iterable[dict]) -> dict:
        fields = ("provider_input_tokens", "provider_cached_input_tokens", "provider_reasoning_tokens", "provider_output_tokens")
        totals = {field: 0 for field in fields}
        observed = {field: False for field in fields}
        duration_ms = 0.0
        tool_calls = 0
        for row in self._telemetry(run_id=run_id):
            for field in fields:
                value = row.get(field)
                if isinstance(value, (int, float)):
                    totals[field] += value
                    observed[field] = True
            value = row.get("duration_ms")
            if isinstance(value, (int, float)):
                duration_ms += float(value)
            tc = row.get("tool_calls")
            if isinstance(tc, int):
                tool_calls += tc
        for task in tasks:
            if task.get("duration_ms") and not duration_ms:
                duration_ms += float(task["duration_ms"] or 0)
        return {
            "input_tokens": totals["provider_input_tokens"] if observed["provider_input_tokens"] else None,
            "cached_input_tokens": totals["provider_cached_input_tokens"] if observed["provider_cached_input_tokens"] else None,
            "reasoning_tokens": totals["provider_reasoning_tokens"] if observed["provider_reasoning_tokens"] else None,
            "output_tokens": totals["provider_output_tokens"] if observed["provider_output_tokens"] else None,
            "duration_ms": round(duration_ms, 2) if duration_ms else None,
            "tool_calls": tool_calls or None,
        }

    def snapshot(self) -> dict:
        manifests = self._list_run_manifests()
        goals_raw = self._list_goal_states()
        runs = [_compact_run(item) for item in manifests]
        goals = [self._goal_summary(item) for item in goals_raw]

        active_manifest = next((item for item in manifests if str(item.get("run_state") or "").upper() not in TERMINAL_RUN_STATES), None)
        selected_manifest = active_manifest or (manifests[0] if manifests else None)
        selected_run_id = selected_manifest.get("run_id") if selected_manifest else None
        tasks_raw = selected_manifest.get("tasks", {}) if isinstance(selected_manifest, dict) and isinstance(selected_manifest.get("tasks"), dict) else {}
        tasks = [_compact_task(task_id, task, str(selected_run_id or "")) for task_id, task in tasks_raw.items()]
        tasks.sort(key=lambda item: (BOARD_COLUMNS.index(item["display_state"]), str(item["task_id"])))

        columns = []
        for name in BOARD_COLUMNS:
            columns.append({"id": name, "label": name.title(), "tasks": [task for task in tasks if task["display_state"] == name]})

        project_policy = _read_json(self.project_root / "factory.project.json", {})
        factory_cfg = self._load_factory_config("factory.json", {})
        project_name = None
        if isinstance(project_policy, dict):
            project_name = project_policy.get("project_name") or project_policy.get("project_id")
        project_name = project_name or self.project_root.name

        active_goal = next((goal for goal in goals if goal.get("phase") not in TERMINAL_GOAL_PHASES), None)
        counts = {column: sum(1 for task in tasks if task["display_state"] == column) for column in BOARD_COLUMNS}
        usage = self._usage_summary(selected_run_id, tasks)

        data = {
            "api_version": "1",
            "generated_at": _utc_now(),
            "factory": {
                "version": factory_cfg.get("version") if isinstance(factory_cfg, dict) else None,
                "project_name": project_name,
                "project_root": str(self.project_root),
                "active": bool(active_manifest or active_goal),
            },
            "active_goal": active_goal,
            "selected_run_id": selected_run_id,
            "goals": goals[:20],
            "runs": runs[:20],
            "board": {"columns": columns, "counts": counts, "task_count": len(tasks)},
            "providers": self._provider_summary(),
            "metrics": usage,
        }
        # Keep the revision stable when canonical Factory state is unchanged.
        # generated_at is response metadata, not state, so it must not defeat ETag/304 caching.
        revision_basis = {k: v for k, v in data.items() if k != "generated_at"}
        data["revision"] = _sha256_json(revision_basis)
        return data

    def goal_detail(self, goal_id: str) -> dict:
        goal_id = _safe_id(goal_id, "goal id")
        goal_dir = self.goals_dir / goal_id
        if not _is_under(self.goals_dir, goal_dir):
            raise UIDataError("Invalid goal path")
        state = _read_json(goal_dir / "state.json", None)
        if not isinstance(state, dict):
            raise UIDataError("Goal not found")
        goal_spec = _referenced_json(self.project_root, state.get("goal_spec_path")) or _read_json(goal_dir / "goal-spec.json", None)
        plan = _referenced_json(self.project_root, state.get("approved_plan_path") or state.get("current_plan_path"))
        return {
            "summary": self._goal_summary(state),
            "state": state,
            "goal_spec": goal_spec if isinstance(goal_spec, dict) else None,
            "plan": plan if isinstance(plan, dict) else None,
        }

    def run_detail(self, run_id: str) -> dict:
        run_id = _safe_id(run_id, "run id")
        run_dir = self.runs_dir / run_id
        manifest = _read_json(run_dir / "manifest.json", None)
        if not isinstance(manifest, dict):
            raise UIDataError("Run not found")
        tasks_raw = manifest.get("tasks") if isinstance(manifest.get("tasks"), dict) else {}
        tasks = [_compact_task(task_id, task, run_id) for task_id, task in tasks_raw.items()]
        plan = _referenced_json(self.project_root, manifest.get("plan_path"))
        compact_run = _compact_run(manifest)
        return {
            "run": compact_run,
            "summary": compact_run,
            "tasks": tasks,
            "validation_results": manifest.get("validation_results") or {},
            "final_audit": manifest.get("final_audit") or {},
            "concurrency_evidence": manifest.get("concurrency_evidence") or {},
            "plan": plan,
            "events": self._events(run_id)[-150:],
            "metrics": self._usage_summary(run_id, tasks),
        }

    def task_detail(self, run_id: str, task_id: str) -> dict:
        run_id = _safe_id(run_id, "run id")
        task_id = _safe_id(task_id, "task id")
        manifest = _read_json(self.runs_dir / run_id / "manifest.json", None)
        if not isinstance(manifest, dict):
            raise UIDataError("Run not found")
        tasks = manifest.get("tasks") if isinstance(manifest.get("tasks"), dict) else {}
        task = tasks.get(task_id)
        if not isinstance(task, dict):
            raise UIDataError("Task not found")
        attempts = task.get("attempts") if isinstance(task.get("attempts"), list) else []
        return {
            "task": _compact_task(task_id, task, run_id),
            "attempts": [_compact_attempt(item) for item in attempts if isinstance(item, dict)],
            "retry_info": task.get("retry_info") if isinstance(task.get("retry_info"), dict) else None,
            "routing_provenance": task.get("routing_provenance") if isinstance(task.get("routing_provenance"), dict) else None,
            "events": self._events(run_id, task_id)[-100:],
            "telemetry": self._telemetry(run_id, task_id)[-50:],
        }

    def system_detail(self) -> dict:
        profiles = self._load_factory_config("harness_profiles.json", {})
        return {
            "providers": self._provider_summary(),
            "profiles": profiles.get("profiles", {}) if isinstance(profiles, dict) else {},
            "context_policy": self._load_factory_config("context_policy.json", {}),
            "reasoning_policy": self._load_factory_config("reasoning_policy.json", {}),
            "toolchain": self._load_factory_config("toolchain.lock.json", {}),
            "ui_vendor_lock": self._load_factory_config("ui/vendor.lock.json", {}),
        }


class GoalActionRunner:
    """Runs only existing public Factory actions; it owns no scheduler state."""

    def __init__(self, project_root: pathlib.Path, factory_root: pathlib.Path = FACTORY_ROOT):
        self.project_root = pathlib.Path(project_root).resolve()
        self.factory_root = pathlib.Path(factory_root).resolve()
        self._lock = threading.Lock()
        self._active: Dict[str, subprocess.Popen] = {}

    def resume(self, goal_id: str) -> dict:
        goal_id = _safe_id(goal_id, "goal id")
        state_path = self.project_root / ".agy-factory" / "goals" / goal_id / "state.json"
        state = _read_json(state_path, None)
        if not isinstance(state, dict):
            raise UIDataError("Goal not found")
        if str(state.get("phase") or "") in TERMINAL_GOAL_PHASES:
            raise UIDataError("Goal is terminal and cannot be resumed")

        with self._lock:
            existing = self._active.get(goal_id)
            if existing is not None and existing.poll() is None:
                raise ActionConflict("Goal resume is already running")

            actions_dir = self.project_root / ".agy-factory" / "ui" / "actions"
            actions_dir.mkdir(parents=True, exist_ok=True)
            stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            log_path = actions_dir / f"{stamp}-resume-{goal_id}.log"
            log_handle = log_path.open("ab")
            cmd = [
                sys.executable,
                str(self.factory_root / "tools" / "factory.py"),
                "--project-root",
                str(self.project_root),
                "goal",
                "resume",
                "--goal-id",
                goal_id,
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.factory_root),
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
            except Exception:
                log_handle.close()
                raise
            self._active[goal_id] = proc

            def _watch() -> None:
                try:
                    proc.wait()
                finally:
                    log_handle.close()
                    with self._lock:
                        if self._active.get(goal_id) is proc:
                            self._active.pop(goal_id, None)

            threading.Thread(target=_watch, name=f"factory-ui-resume-{goal_id}", daemon=True).start()
            return {
                "accepted": True,
                "goal_id": goal_id,
                "pid": proc.pid,
                "log": str(log_path.relative_to(self.project_root)),
            }


class FactoryUIServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: Tuple[str, int], handler_cls, *, read_model: FactoryReadModel,
                 action_runner: GoalActionRunner, ui_root: pathlib.Path = UI_ROOT,
                 vendor_root: pathlib.Path = DEFAULT_VENDOR_ROOT):
        super().__init__(server_address, handler_cls)
        self.read_model = read_model
        self.action_runner = action_runner
        self.ui_root = pathlib.Path(ui_root).resolve()
        self.vendor_root = pathlib.Path(vendor_root).resolve()


class FactoryUIHandler(http.server.BaseHTTPRequestHandler):
    server_version = "FactoryControlUI/1.0"
    protocol_version = "HTTP/1.1"

    CSP = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[factory-ui] %s - %s\n" % (self.address_string(), fmt % args))

    def _security_headers(self) -> None:
        self.send_header("Content-Security-Policy", self.CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")

    def _send_json(self, status: int, payload: Any, *, etag: Optional[str] = None) -> None:
        data = _canonical_json_bytes(payload)
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if etag:
            self.send_header("ETag", f'"{etag}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _send_empty(self, status: int, *, etag: Optional[str] = None) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Cache-Control", "no-store")
        if etag:
            self.send_header("ETag", f'"{etag}"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_file(self, base: pathlib.Path, relative: str) -> None:
        relative = urllib.parse.unquote(relative).lstrip("/")
        parts = pathlib.PurePosixPath(relative).parts
        if not relative or ".." in parts:
            self._send_json(403, {"error": "Forbidden"})
            return
        path = (base / relative).resolve(strict=False)
        if not _is_under(base, path) or not path.is_file():
            self._send_json(404, {"error": "Not Found"})
            return
        try:
            content = path.read_bytes()
        except OSError:
            self._send_json(404, {"error": "Not Found"})
            return
        content_type, _ = mimetypes.guess_type(str(path))
        content_type = content_type or "application/octet-stream"
        if content_type.startswith("text/") or path.suffix in {".js", ".css", ".json", ".svg"}:
            if "charset=" not in content_type and path.suffix != ".svg":
                content_type += "; charset=utf-8"
        etag = hashlib.sha256(content).hexdigest()
        if self.headers.get("If-None-Match") == f'"{etag}"':
            self._send_empty(304, etag=etag)
            return
        self.send_response(200)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("ETag", f'"{etag}"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def _host_allowed(self) -> bool:
        host_header = self.headers.get("Host", "").strip()
        if not host_header:
            return False
        try:
            parsed = urllib.parse.urlsplit(f"//{host_header}", allow_fragments=False)
            hostname = parsed.hostname
        except ValueError:
            return False
        if not hostname:
            return False
        if hostname.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            return False

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            parsed = urllib.parse.urlparse(origin)
        except ValueError:
            return False
        host = self.headers.get("Host", "")
        return parsed.scheme in {"http", "https"} and parsed.netloc == host

    def _read_json_body(self) -> dict:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            raise UIDataError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise UIDataError("Invalid Content-Length") from exc
        if length < 0 or length > MAX_REQUEST_BODY:
            raise UIDataError("Request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UIDataError("Invalid JSON body") from exc
        if not isinstance(value, dict):
            raise UIDataError("JSON body must be an object")
        return value

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._host_allowed():
            self.close_connection = True
            self._send_json(403, {"error": "Host rejected"})
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/health":
                self._send_json(200, {"status": "ok", "api_version": "1"})
                return
            if path == f"{API_PREFIX}/snapshot":
                payload = self.server.read_model.snapshot()
                etag = str(payload.get("revision") or _sha256_json(payload))
                if self.headers.get("If-None-Match") == f'"{etag}"':
                    self._send_empty(304, etag=etag)
                else:
                    self._send_json(200, payload, etag=etag)
                return
            if path == f"{API_PREFIX}/system":
                self._send_json(200, self.server.read_model.system_detail())
                return

            segments = [segment for segment in path.split("/") if segment]
            if len(segments) == 4 and segments[:3] == ["api", "v1", "goals"]:
                self._send_json(200, self.server.read_model.goal_detail(segments[3]))
                return
            if len(segments) == 4 and segments[:3] == ["api", "v1", "runs"]:
                self._send_json(200, self.server.read_model.run_detail(segments[3]))
                return
            if len(segments) == 6 and segments[:3] == ["api", "v1", "runs"] and segments[4] == "tasks":
                self._send_json(200, self.server.read_model.task_detail(segments[3], segments[5]))
                return

            if path in {"/", "/index.html"}:
                self._serve_file(self.server.ui_root, "index.html")
                return
            if path.startswith("/assets/"):
                self._serve_file(self.server.ui_root, path[len("/assets/"):])
                return
            if path.startswith("/vendor/"):
                self._serve_file(self.server.vendor_root, path[len("/vendor/"):])
                return
            if path.startswith("/api/"):
                self._send_json(404, {"error": "Not Found"})
                return
            self._send_json(404, {"error": "Not Found"})
        except UIDataError as exc:
            self._send_json(404, {"error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": "Internal server error", "detail": _safe_text(exc, 300)})

    def do_POST(self) -> None:
        if not self._host_allowed():
            self.close_connection = True
            self._send_json(403, {"error": "Host rejected"})
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self._origin_allowed():
            # Do not leave an unread request body on an HTTP/1.1 keep-alive connection.
            self.close_connection = True
            self._send_json(403, {"error": "Origin rejected"})
            return
        try:
            self._read_json_body()
            segments = [segment for segment in path.split("/") if segment]
            if len(segments) == 5 and segments[:3] == ["api", "v1", "goals"] and segments[4] == "resume":
                result = self.server.action_runner.resume(segments[3])
                self._send_json(202, result)
                return
            self._send_json(404, {"error": "Not Found"})
        except ActionConflict as exc:
            self._send_json(409, {"error": str(exc)})
        except UIDataError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": "Action failed", "detail": _safe_text(exc, 300)})


def make_server(project_root: pathlib.Path, host: str = "127.0.0.1", port: int = 8765, *,
                factory_root: pathlib.Path = FACTORY_ROOT, ui_root: pathlib.Path = UI_ROOT,
                vendor_root: pathlib.Path = DEFAULT_VENDOR_ROOT,
                action_runner: Optional[GoalActionRunner] = None) -> FactoryUIServer:
    read_model = FactoryReadModel(project_root, factory_root)
    runner = action_runner or GoalActionRunner(project_root, factory_root)
    return FactoryUIServer((host, port), FactoryUIHandler, read_model=read_model,
                           action_runner=runner, ui_root=ui_root, vendor_root=vendor_root)


def _require_loopback(host: str) -> None:
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise SystemExit("Factory Control UI v1 binds to loopback only. Use an SSH tunnel or trusted reverse proxy for remote access.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Factory Control UI (local, read-mostly)")
    parser.add_argument("--project-root", default=os.getcwd(), help="Target Factory project root (default: cwd)")
    parser.add_argument("--host", default="127.0.0.1", help="Loopback bind address")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765; use 0 for ephemeral)")
    parser.add_argument("--vendor-root", default=str(DEFAULT_VENDOR_ROOT), help="Self-hosted frontend vendor directory")
    args = parser.parse_args(argv)

    _require_loopback(args.host)
    project_root = pathlib.Path(args.project_root).resolve()
    if not project_root.is_dir():
        parser.error(f"Project root does not exist: {project_root}")
    if args.port < 0 or args.port > 65535:
        parser.error("Port must be between 0 and 65535")

    server = make_server(project_root, args.host, args.port, vendor_root=pathlib.Path(args.vendor_root))
    bound_host, bound_port = server.server_address[:2]
    print(f"Factory Control UI: http://{bound_host}:{bound_port}")
    print(f"Project root: {project_root}")
    print("Press Ctrl+C to stop. Factory/provider execution is not started by the UI itself.")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping Factory Control UI...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
