#!/usr/bin/env python3
"""Factory Control UI: local browser projection over durable Factory state.

The server is intentionally thin. It owns no orchestration state, database,
routing policy, retry semantics, or provider client. Read paths project durable
Factory artifacts; the only mutable v1 action delegates to the public
``factory.py goal resume`` command.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
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
from typing import Any, Callable, Iterable, Optional

try:
    from tools.factory_contracts import (
        DISPLAY_STATES,
        TERMINAL_GOAL_PHASES,
        TERMINAL_RUN_STATES,
        display_state,
        run_state,
    )
except ImportError:  # Direct execution from tools/.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from factory_contracts import (  # type: ignore
        DISPLAY_STATES,
        TERMINAL_GOAL_PHASES,
        TERMINAL_RUN_STATES,
        display_state,
        run_state,
    )

FACTORY_ROOT = pathlib.Path(__file__).resolve().parent.parent
UI_ROOT = FACTORY_ROOT / "ui"
DEFAULT_VENDOR_ROOT = FACTORY_ROOT / ".tools" / "ui" / "vendor"
API_PREFIX = "/api/v1"
MAX_REQUEST_BODY = 64 * 1024
MAX_RUNS = 50
MAX_GOALS = 50
MAX_EVENTS = 300
MAX_TELEMETRY = 500
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")


class UIDataError(RuntimeError):
    """Invalid or unavailable user-visible Factory data."""


class ActionConflict(RuntimeError):
    """A requested bounded UI action is already in progress."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _safe_text(value: Any, max_chars: int = 1200) -> str:
    text = "" if value is None else str(value).replace("\x00", "")
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _safe_id(value: Any, label: str = "id") -> str:
    candidate = str(value or "")
    if not ID_RE.fullmatch(candidate):
        raise UIDataError(f"Invalid {label}")
    return candidate


def _first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _duration_ms(start: Any, end: Any) -> Optional[float]:
    if not start or not end:
        return None
    try:
        left = dt.datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        right = dt.datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return round((right - left).total_seconds() * 1000.0, 2)
    except (TypeError, ValueError):
        return None


def _is_under(root: pathlib.Path, candidate: pathlib.Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _safe_child_dir(root: pathlib.Path, name: Any, label: str) -> pathlib.Path:
    safe_name = _safe_id(name, label)
    candidate = root / safe_name
    if not _is_under(root, candidate):
        raise UIDataError(f"Invalid {label} path")
    return candidate


def _read_json(path: pathlib.Path, default: Any = None, *, root: Optional[pathlib.Path] = None) -> Any:
    if root is not None and not _is_under(root, path):
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _read_jsonl_tail(
    path: pathlib.Path,
    limit: int,
    predicate: Optional[Callable[[dict], bool]] = None,
    *,
    root: Optional[pathlib.Path] = None,
) -> list[dict]:
    """Read the last matching JSON objects, filtering before the bounded tail.

    Filtering after truncating a global telemetry file caused older selected runs
    to appear to have no metrics. This scans sequentially but retains only the
    bounded matching tail in memory.
    """

    if limit <= 0 or (root is not None and not _is_under(root, path)):
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
                if isinstance(item, dict) and (predicate is None or predicate(item)):
                    rows.append(item)
    except OSError:
        return []
    return list(rows)


def _referenced_json(project_root: pathlib.Path, value: Any) -> Optional[dict]:
    if not value:
        return None
    path = pathlib.Path(str(value))
    if not path.is_absolute():
        path = project_root / path
    data = _read_json(path, None, root=project_root)
    return data if isinstance(data, dict) else None


def _task_display(task: dict) -> str:
    canonical = task.get("canonical_state") or task.get("state") or task.get("status") or "PENDING"
    return display_state(canonical, task.get("display_state"))


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
        "branch": attempt.get("branch") or attempt.get("branch_name"),
        "start_time": attempt.get("start_time"),
        "end_time": attempt.get("end_time"),
        "duration_ms": _first_not_none(
            attempt.get("duration_ms"),
            _duration_ms(attempt.get("start_time"), attempt.get("end_time")),
        ),
        "commit_hash": attempt.get("commit_hash") or attempt.get("commit"),
        "changed_paths": list(attempt.get("changed_paths") or []),
        "path_violations": list(attempt.get("path_violations") or []),
        "missing_expected": list(attempt.get("missing_expected") or []),
        "error": _safe_text(attempt.get("error"), 1600) if attempt.get("error") else None,
        "usage": {
            "input_tokens": _first_not_none(usage.get("input_tokens"), attempt.get("provider_input_tokens")),
            "cached_input_tokens": _first_not_none(usage.get("cache_read_tokens"), attempt.get("provider_cached_input_tokens")),
            "reasoning_tokens": _first_not_none(usage.get("thinking_tokens"), usage.get("reasoning_tokens"), attempt.get("provider_reasoning_tokens")),
            "output_tokens": _first_not_none(usage.get("output_tokens"), attempt.get("provider_output_tokens")),
        },
    }


def _compact_task(task_id: str, task: dict, run_id: str) -> dict:
    attempts = task.get("attempts") if isinstance(task.get("attempts"), list) else []
    latest_result = task.get("latest_result") if isinstance(task.get("latest_result"), dict) else None
    source_attempt = latest_result if latest_result else (attempts[-1] if attempts else {})
    latest = _compact_attempt(source_attempt)
    return {
        "run_id": run_id,
        "task_id": task_id,
        "name": task.get("name") or task.get("title") or task_id,
        "task_type": task.get("task_type"),
        "execution_class": task.get("execution_class"),
        "display_state": _task_display(task),
        "canonical_state": task.get("canonical_state") or task.get("state"),
        "status": task.get("status") or latest.get("status"),
        "worker_id": task.get("worker_id") or latest.get("worker_id"),
        "profile_id": task.get("profile_id") or task.get("profile") or latest.get("profile_id"),
        "harness": task.get("harness") or latest.get("harness") or latest.get("adapter"),
        "model": task.get("model") or latest.get("model"),
        "effort": task.get("effort") or latest.get("effort"),
        "effort_source": task.get("effort_source"),
        "escalated_from_profile": task.get("escalated_from_profile"),
        "escalation_reason": _safe_text(task.get("escalation_reason"), 500) if task.get("escalation_reason") else None,
        "execution_mode": latest.get("execution_mode"),
        "retried": len(attempts) > 1,
        "escalated": bool(task.get("escalated_from_profile") or task.get("escalation_reason")),
        "attempts_count": task.get("attempts_count") if task.get("attempts_count") is not None else len(attempts),
        "current_attempt_id": task.get("current_attempt_id") or latest.get("attempt_id"),
        "dependencies": list(task.get("dependencies") or []),
        "commit_hash": latest.get("commit_hash"),
        "branch": latest.get("branch"),
        "start_time": latest.get("start_time"),
        "end_time": latest.get("end_time"),
        "duration_ms": latest.get("duration_ms"),
        "changed_paths": latest.get("changed_paths") or [],
        "error": latest.get("error"),
    }


def _compact_run(manifest: dict) -> dict:
    tasks = manifest.get("tasks") if isinstance(manifest.get("tasks"), dict) else {}
    counts = {column: 0 for column in DISPLAY_STATES}
    for task in tasks.values():
        counts[_task_display(task)] += 1
    return {
        "run_id": manifest.get("run_id"),
        "goal_id": manifest.get("goal_id"),
        "plan_id": manifest.get("plan_id"),
        "plan_name": manifest.get("plan_name") or manifest.get("name"),
        "run_state": run_state(manifest),
        "certification_level": manifest.get("certification_level"),
        "contains_mock_execution": bool(manifest.get("contains_mock_execution", False)),
        "start_time": manifest.get("start_time"),
        "end_time": manifest.get("end_time"),
        "task_count": len(tasks),
        "counts": counts,
    }


def _plan_tasks(plan: Any) -> list[dict]:
    if not isinstance(plan, dict):
        return []
    tasks = plan.get("tasks")
    if isinstance(tasks, list):
        return [task for task in tasks if isinstance(task, dict)]
    result: list[dict] = []
    for wave in plan.get("waves", []) if isinstance(plan.get("waves"), list) else []:
        if isinstance(wave, dict):
            result.extend(task for task in wave.get("tasks", []) if isinstance(task, dict))
    return result


def _compact_goal_spec(goal_spec: Any) -> Optional[dict]:
    """Return only GoalSpec fields the browser needs for traceability."""
    if not isinstance(goal_spec, dict):
        return None
    criteria = []
    for item in goal_spec.get("acceptance_criteria", []) if isinstance(goal_spec.get("acceptance_criteria"), list) else []:
        if not isinstance(item, dict):
            continue
        criteria.append({
            "id": item.get("id"),
            "title": _safe_text(item.get("title"), 320),
            "description": _safe_text(item.get("description"), 1600),
            "provenance": item.get("provenance"),
            "derived_from": list(item.get("derived_from") or []),
            "rationale": _safe_text(item.get("rationale"), 800) if item.get("rationale") else None,
        })
    return {
        "goal_id": goal_spec.get("goal_id"),
        "title": _safe_text(goal_spec.get("title"), 320),
        "acceptance_criteria": criteria,
        "constraints": [_safe_text(item, 800) for item in (goal_spec.get("constraints") or []) if item is not None][:100],
        "non_goals": [_safe_text(item, 800) for item in (goal_spec.get("non_goals") or []) if item is not None][:100],
    }


def _compact_plan(plan: Any) -> Optional[dict]:
    """Project plan structure without worker prompts or other raw semantic payloads."""
    if not isinstance(plan, dict):
        return None
    tasks = []
    for item in _plan_tasks(plan):
        tasks.append({
            "task_id": item.get("task_id"),
            "name": _safe_text(item.get("name") or item.get("title"), 320),
            "task_type": item.get("task_type"),
            "execution_class": item.get("execution_class"),
            "dependencies": list(item.get("dependencies") or []),
            "allowed_paths": list(item.get("allowed_paths") or []),
            "expected_files": list(item.get("expected_files") or []),
            "context_files": list(item.get("context_files") or []),
            "satisfies": list(item.get("satisfies") or []),
            "validations": list(item.get("validations") or []),
            "requires": list(item.get("requires") or []),
            "profile": item.get("profile") or item.get("profile_id"),
            "worker": item.get("worker") or item.get("worker_id"),
        })
    traceability = plan.get("requirements_traceability")
    if not isinstance(traceability, dict):
        traceability = {}
    return {
        "plan_id": plan.get("plan_id"),
        "version": plan.get("version"),
        "name": _safe_text(plan.get("name"), 320),
        "goal_id": plan.get("goal_id"),
        "requirements_traceability": {str(key): list(value) for key, value in traceability.items() if isinstance(value, list)},
        "tasks": tasks,
    }


def _compact_validation_result(item: dict, name: Any = None) -> dict:
    """Project only validation evidence needed by the UI; never expose raw stdout/stderr."""

    command = item.get("command")
    if isinstance(command, list):
        command = [str(part) for part in command[:64]]
    elif command is not None:
        command = _safe_text(command, 1200)
    return {
        "name": _safe_text(item.get("name") or name, 240) if (item.get("name") or name) else None,
        "task_id": item.get("task_id"),
        "command": command,
        "returncode": item.get("returncode"),
        "passed": bool(item.get("passed")) if item.get("passed") is not None else None,
        "error": _safe_text(item.get("error"), 500) if item.get("error") else None,
    }


def _normalize_validation_results(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        return [_compact_validation_result(item) for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [_compact_validation_result(item, name) for name, item in raw.items() if isinstance(item, dict)]
    return []


def _safe_context_summary(packet: Any, metrics: list[dict]) -> Optional[dict]:
    if not isinstance(packet, dict):
        return None
    anchors = [item for item in packet.get("required_anchors", []) if isinstance(item, dict)]
    required_anchors = [item for item in anchors if item.get("required") is not False]
    anchor_types: dict[str, int] = collections.Counter(str(item.get("type") or item.get("anchor_type") or "unknown") for item in required_anchors)
    metric = next((item for item in reversed(metrics) if item.get("context_packet_id") == packet.get("packet_id")), metrics[-1] if metrics else {})
    included_files = []
    for item in packet.get("included_files", []) if isinstance(packet.get("included_files"), list) else []:
        if isinstance(item, dict):
            included_files.append({
                "path": item.get("path"),
                "reason": _safe_text(item.get("reason"), 240),
                "byte_count": item.get("byte_count"),
            })
    requirements = []
    for item in packet.get("requirements", []) if isinstance(packet.get("requirements"), list) else []:
        if isinstance(item, dict):
            requirements.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "description": _safe_text(item.get("description") or item.get("text"), 1200),
                "provenance": item.get("provenance"),
            })
    return {
        "packet_id": packet.get("packet_id"),
        "packet_role": packet.get("packet_role"),
        "packet_hash": packet.get("packet_hash"),
        "packet_bytes": packet.get("packet_bytes"),
        "compiler_version": packet.get("compiler_version"),
        "attempt_id": packet.get("attempt_id"),
        "budget": packet.get("budget") if isinstance(packet.get("budget"), dict) else {},
        "required_anchor_count": len(required_anchors),
        "required_anchor_recall": metric.get("required_anchor_recall"),
        "anchor_types": dict(sorted(anchor_types.items())),
        "handoff_count": len(packet.get("handoffs", [])) if isinstance(packet.get("handoffs"), list) else 0,
        "referenced_files": list(packet.get("referenced_files") or []),
        "included_files": included_files,
        "requirements": requirements,
        "validations": list(packet.get("validations") or []),
    }


def _build_traceability(goal_spec: Any, plan: Any, tasks_by_id: dict[str, dict], validation_results: list[dict]) -> list[dict]:
    if not isinstance(goal_spec, dict):
        return []
    criteria = [item for item in goal_spec.get("acceptance_criteria", []) if isinstance(item, dict)]
    plan_tasks = _plan_tasks(plan)
    mapping: dict[str, list[str]] = collections.defaultdict(list)
    explicit = plan.get("requirements_traceability") if isinstance(plan, dict) else None
    if isinstance(explicit, dict):
        for criterion_id, task_ids in explicit.items():
            for task_id in task_ids if isinstance(task_ids, list) else []:
                if str(task_id) not in mapping[str(criterion_id)]:
                    mapping[str(criterion_id)].append(str(task_id))
    for task in plan_tasks:
        task_id = str(task.get("task_id") or "")
        for criterion_id in task.get("satisfies", []) if isinstance(task.get("satisfies"), list) else []:
            if task_id and task_id not in mapping[str(criterion_id)]:
                mapping[str(criterion_id)].append(task_id)

    validations_by_task: dict[str, list[dict]] = collections.defaultdict(list)
    for item in validation_results:
        task_id = str(item.get("task_id") or "")
        if task_id:
            validations_by_task[task_id].append(item)

    result = []
    for criterion in criteria:
        criterion_id = str(criterion.get("id") or "")
        task_ids = mapping.get(criterion_id, [])
        states = [tasks_by_id[task_id].get("display_state") for task_id in task_ids if task_id in tasks_by_id]
        validations = [item for task_id in task_ids for item in validations_by_task.get(task_id, [])]
        if not task_ids:
            outcome = "UNMAPPED"
        elif any(state in {"FAILED", "BLOCKED"} for state in states):
            outcome = "FAILED"
        elif validations and all(bool(item.get("passed")) for item in validations) and states and all(state == "DONE" for state in states):
            outcome = "PASS"
        elif states and all(state == "DONE" for state in states):
            outcome = "DONE"
        else:
            outcome = "IN_PROGRESS"
        result.append({
            "criterion_id": criterion_id,
            "title": criterion.get("title") or criterion_id,
            "description": _safe_text(criterion.get("description") or criterion.get("text"), 1200),
            "provenance": criterion.get("provenance") or "USER_EXPLICIT",
            "tasks": task_ids,
            "validation_count": len(validations),
            "outcome": outcome,
        })
    return result


def _compact_telemetry(row: dict) -> dict:
    """Allowlist telemetry fields useful for observability without leaking provider payloads."""

    allowed = (
        "run_id", "task_id", "attempt_id", "profile_id", "worker_id", "harness", "model", "effort",
        "execution_mode", "start_time", "end_time", "duration_ms", "tool_calls",
        "provider_input_tokens", "provider_cached_input_tokens", "provider_reasoning_tokens",
        "provider_output_tokens", "factory_supplied_bytes", "required_anchor_recall",
        "context_packet_id", "context_packet_hash", "session_mode", "session_reused",
        "native_compaction_used",
    )
    return {key: row.get(key) for key in allowed if key in row}


def _compact_event(row: dict) -> dict:
    """Expose event identity/timing only; raw payloads can contain prompts, paths or errors."""

    return {
        "timestamp": row.get("timestamp"),
        "event": row.get("event") or row.get("type") or row.get("name"),
        "task_id": row.get("task_id") or ((row.get("payload") or {}).get("task_id") if isinstance(row.get("payload"), dict) else None),
        "attempt_id": row.get("attempt_id") or ((row.get("payload") or {}).get("attempt_id") if isinstance(row.get("payload"), dict) else None),
    }


def _compact_goal_state(state: dict) -> dict:
    allowed = (
        "goal_id", "phase", "run_id", "plan_revision_count", "remediation_round_count",
        "created_at", "updated_at", "completed_at", "real_only", "failpoint_hit",
    )
    compact = {key: state.get(key) for key in allowed if key in state}
    compact["raw_goal"] = _safe_text(state.get("raw_goal"), 4000)
    if state.get("error"):
        compact["error"] = _safe_text(state.get("error"), 500)
    return compact


def _compact_audit(audit: Any) -> Optional[dict]:
    if not isinstance(audit, dict):
        return None
    findings = []
    for finding in audit.get("findings", []) if isinstance(audit.get("findings"), list) else []:
        if not isinstance(finding, dict):
            continue
        findings.append({
            "id": finding.get("id"),
            "severity": finding.get("severity"),
            "area": finding.get("area") or finding.get("category"),
            "criterion_id": finding.get("criterion_id") or finding.get("criterion"),
            "description": _safe_text(finding.get("description") or finding.get("evidence"), 1000),
            "required_change": _safe_text(finding.get("required_change") or finding.get("recommendation") or finding.get("suggested_action"), 1000),
        })
    return {
        "verdict": audit.get("verdict") or audit.get("status"),
        "findings": findings,
    }


class FactoryReadModel:
    """Read-only projection over Factory's durable, versioned project artifacts."""

    def __init__(self, project_root: pathlib.Path, factory_root: pathlib.Path = FACTORY_ROOT):
        self.project_root = pathlib.Path(project_root).resolve()
        self.factory_root = pathlib.Path(factory_root).resolve()
        self.runtime_root = self.project_root / ".agy-factory"
        if self.runtime_root.exists() and not _is_under(self.project_root, self.runtime_root):
            raise UIDataError("Factory runtime root escapes project")
        self.runs_dir = self.runtime_root / "runs"
        self.goals_dir = self.runtime_root / "goals"
        self.evidence_dir = self.runtime_root / "evidence"

    def _load_factory_config(self, filename: str, default: Any) -> Any:
        return _read_json(self.factory_root / filename, default, root=self.factory_root)

    def _run_dir(self, run_id: Any) -> pathlib.Path:
        return _safe_child_dir(self.runs_dir, run_id, "run id")

    def _goal_dir(self, goal_id: Any) -> pathlib.Path:
        return _safe_child_dir(self.goals_dir, goal_id, "goal id")

    def _list_run_manifests(self) -> list[dict]:
        results: list[dict] = []
        if not self.runs_dir.is_dir() or not _is_under(self.project_root, self.runs_dir):
            return results
        for run_dir in sorted(self.runs_dir.glob("run-*"), reverse=True):
            if len(results) >= MAX_RUNS or not run_dir.is_dir() or not _is_under(self.runs_dir, run_dir):
                continue
            data = _read_json(run_dir / "manifest.json", None, root=self.runs_dir)
            if isinstance(data, dict):
                data.setdefault("run_id", run_dir.name)
                results.append(data)
        results.sort(key=lambda item: str(item.get("start_time") or item.get("run_id") or ""), reverse=True)
        return results

    def _list_goal_states(self) -> list[dict]:
        results: list[dict] = []
        if not self.goals_dir.is_dir() or not _is_under(self.project_root, self.goals_dir):
            return results
        for goal_dir in sorted(self.goals_dir.glob("goal-*"), reverse=True):
            if len(results) >= MAX_GOALS or not goal_dir.is_dir() or not _is_under(self.goals_dir, goal_dir):
                continue
            state = _read_json(goal_dir / "state.json", None, root=self.goals_dir)
            if isinstance(state, dict):
                state.setdefault("goal_id", goal_dir.name)
                results.append(state)
        results.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or item.get("goal_id") or ""), reverse=True)
        return results

    def _telemetry(self, run_id: Optional[str] = None, task_id: Optional[str] = None, limit: int = MAX_TELEMETRY) -> list[dict]:
        def matches(row: dict) -> bool:
            return (not run_id or row.get("run_id") == run_id) and (not task_id or row.get("task_id") == task_id)
        return [_compact_telemetry(row) for row in _read_jsonl_tail(self.evidence_dir / "telemetry.jsonl", limit, matches, root=self.evidence_dir)]

    def _context_telemetry(self, run_id: Optional[str] = None, task_id: Optional[str] = None, limit: int = 200) -> list[dict]:
        def matches(row: dict) -> bool:
            return (not run_id or row.get("run_id") == run_id) and (not task_id or row.get("task_id") == task_id)
        return [_compact_telemetry(row) for row in _read_jsonl_tail(self.evidence_dir / "context-telemetry.jsonl", limit, matches, root=self.evidence_dir)]

    def _events(self, run_id: str, task_id: Optional[str] = None, limit: int = MAX_EVENTS) -> list[dict]:
        def matches(row: dict) -> bool:
            if not task_id:
                return True
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            return payload.get("task_id") == task_id or row.get("task_id") == task_id
        return [_compact_event(row) for row in _read_jsonl_tail(self._run_dir(run_id) / "events.jsonl", limit, matches, root=self.runs_dir)]

    def _provider_summary(self) -> list[dict]:
        raw = self._load_factory_config("harness_profiles.json", {})
        profiles = raw.get("profiles") if isinstance(raw, dict) and isinstance(raw.get("profiles"), dict) else {}
        grouped: dict[str, list[dict]] = collections.defaultdict(list)
        for profile_id, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            certification = profile.get("certification") if isinstance(profile.get("certification"), dict) else {}
            grouped[str(profile.get("harness") or profile.get("adapter") or "unknown")].append({
                "profile_id": profile_id,
                "model": profile.get("model"),
                "effort": profile.get("effort"),
                "status": certification.get("status") or "UNKNOWN",
                "enabled": bool(profile.get("enabled", True)),
            })

        result = []
        for harness in sorted(grouped):
            entries = grouped[harness]
            enabled = [item for item in entries if item["enabled"]]
            statuses = [str(item["status"]) for item in enabled]
            distinct = sorted(set(statuses))
            aggregate = distinct[0] if len(distinct) == 1 else ("PARTIAL" if distinct else "DISABLED")
            counts = dict(sorted(collections.Counter(statuses).items()))
            models = sorted({str(item["model"]) for item in entries if item.get("model")})
            detail_parts = [", ".join(models[:3])] if models else []
            if counts:
                detail_parts.append(", ".join(f"{count} {status.lower()}" for status, count in counts.items()))
            result.append({
                "id": harness,
                "harness": harness,
                "label": "AGY" if harness == "agy" else harness.replace("-", " ").title(),
                "status": aggregate,
                "status_counts": counts,
                "profile_count": len(entries),
                "enabled_profile_count": len(enabled),
                "detail": "; ".join(detail_parts),
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
                        "status_counts": {},
                        "profile_count": 0,
                        "enabled_profile_count": 0,
                        "detail": _safe_text(item.get("compatibility_notes") or item.get("notes"), 240),
                        "profiles": [],
                    })
        return result

    def _goal_summary(self, state: dict) -> dict:
        raw_goal = _safe_text(state.get("raw_goal"), 500)
        first_line = next((line.strip("# ") for line in raw_goal.splitlines() if line.strip()), state.get("goal_id"))
        phase = str(state.get("phase") or "UNKNOWN").upper()
        return {
            "goal_id": state.get("goal_id"),
            "title": state.get("title") or first_line or state.get("goal_id"),
            "raw_goal_excerpt": raw_goal,
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
        rows = self._telemetry(run_id=run_id)
        fields = ("provider_input_tokens", "provider_cached_input_tokens", "provider_reasoning_tokens", "provider_output_tokens")
        totals = {field: 0 for field in fields}
        observed = {field: False for field in fields}
        duration_ms = 0.0
        duration_observed = False
        tool_calls = 0
        for row in rows:
            for field in fields:
                value = row.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    totals[field] += value
                    observed[field] = True
            value = row.get("duration_ms")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                duration_ms += float(value)
                duration_observed = True
            tc = row.get("tool_calls")
            if isinstance(tc, int) and not isinstance(tc, bool):
                tool_calls += tc
        task_list = list(tasks)
        if not duration_observed:
            duration_ms = sum(float(task.get("duration_ms") or 0) for task in task_list)

        context_rows = self._context_telemetry(run_id=run_id)
        context_bytes = sum(float(row.get("factory_supplied_bytes") or 0) for row in context_rows if isinstance(row.get("factory_supplied_bytes"), (int, float)))
        if not context_bytes:
            context_bytes = sum(float(row.get("factory_supplied_bytes") or 0) for row in rows if isinstance(row.get("factory_supplied_bytes"), (int, float)))
        attempts = sum(int(task.get("attempts_count") or 0) for task in task_list)
        return {
            "input_tokens": totals["provider_input_tokens"] if observed["provider_input_tokens"] else None,
            "cached_input_tokens": totals["provider_cached_input_tokens"] if observed["provider_cached_input_tokens"] else None,
            "reasoning_tokens": totals["provider_reasoning_tokens"] if observed["provider_reasoning_tokens"] else None,
            "output_tokens": totals["provider_output_tokens"] if observed["provider_output_tokens"] else None,
            "context_bytes": round(context_bytes) if context_bytes else None,
            "duration_ms": round(duration_ms, 2) if duration_ms else None,
            "tool_calls": tool_calls or None,
            "attempts": attempts,
        }

    def _goal_state_for_run(self, manifest: dict) -> Optional[dict]:
        goal_id = manifest.get("goal_id")
        if not goal_id:
            return None
        state = _read_json(self._goal_dir(goal_id) / "state.json", None, root=self.goals_dir)
        return state if isinstance(state, dict) else None

    def _resolve_plan(self, manifest: dict, run_dir: pathlib.Path) -> Optional[dict]:
        plan = _referenced_json(self.project_root, manifest.get("plan_path"))
        if plan:
            return plan
        direct = _read_json(run_dir / "plan.json", None, root=self.runs_dir)
        if isinstance(direct, dict):
            return direct
        goal_state = self._goal_state_for_run(manifest)
        if goal_state:
            return _referenced_json(self.project_root, goal_state.get("approved_plan_path") or goal_state.get("current_plan_path"))
        return None

    def _resolve_goal_spec(self, manifest: dict) -> Optional[dict]:
        goal_state = self._goal_state_for_run(manifest)
        if not goal_state:
            return None
        spec = _referenced_json(self.project_root, goal_state.get("goal_spec_path"))
        if spec:
            return spec
        goal_id = goal_state.get("goal_id")
        candidate = _read_json(self._goal_dir(goal_id) / "goal-spec.json", None, root=self.goals_dir)
        return candidate if isinstance(candidate, dict) else None

    def _find_context_packet(self, run_id: str, task_id: str, attempt_id: Any) -> Optional[dict]:
        run_dir = self._run_dir(run_id)
        candidates: list[pathlib.Path] = []
        if attempt_id is not None:
            candidates.append(run_dir / "workers" / task_id / f"att-{attempt_id}" / "context_packet.json")
        packet_dir = run_dir / "context" / "packets"
        if packet_dir.is_dir() and _is_under(run_dir, packet_dir):
            candidates.extend(sorted(packet_dir.glob("*.json"), reverse=True))
        for candidate in candidates:
            packet = _read_json(candidate, None, root=run_dir)
            if isinstance(packet, dict) and (not packet.get("task_id") or packet.get("task_id") == task_id):
                return packet
        return None

    def snapshot(self) -> dict:
        manifests = self._list_run_manifests()
        goals_raw = self._list_goal_states()
        runs = [_compact_run(item) for item in manifests]
        goals = [self._goal_summary(item) for item in goals_raw]

        active_manifest = next((item for item in manifests if run_state(item) not in TERMINAL_RUN_STATES), None)
        selected_manifest = active_manifest or (manifests[0] if manifests else None)
        selected_run_id = selected_manifest.get("run_id") if selected_manifest else None
        tasks_raw = selected_manifest.get("tasks", {}) if isinstance(selected_manifest, dict) and isinstance(selected_manifest.get("tasks"), dict) else {}
        tasks = [_compact_task(task_id, task, str(selected_run_id or "")) for task_id, task in tasks_raw.items()]
        tasks.sort(key=lambda item: (DISPLAY_STATES.index(item["display_state"]), str(item["task_id"])))
        columns = [{"id": name, "label": name.title(), "tasks": [task for task in tasks if task["display_state"] == name]} for name in DISPLAY_STATES]

        project_policy = _read_json(self.project_root / "factory.project.json", {}, root=self.project_root)
        factory_cfg = self._load_factory_config("factory.json", {})
        project_name = project_policy.get("project_name") or project_policy.get("project_id") if isinstance(project_policy, dict) else None
        project_name = project_name or self.project_root.name
        active_goal = next((goal for goal in goals if goal.get("phase") not in TERMINAL_GOAL_PHASES), None)
        counts = {column: sum(1 for task in tasks if task["display_state"] == column) for column in DISPLAY_STATES}

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
            "metrics": self._usage_summary(selected_run_id, tasks),
        }
        data["revision"] = _sha256_json({key: value for key, value in data.items() if key != "generated_at"})
        return data

    def goal_detail(self, goal_id: str) -> dict:
        goal_dir = self._goal_dir(goal_id)
        state = _read_json(goal_dir / "state.json", None, root=self.goals_dir)
        if not isinstance(state, dict):
            raise UIDataError("Goal not found")
        goal_spec = _referenced_json(self.project_root, state.get("goal_spec_path")) or _read_json(goal_dir / "goal-spec.json", None, root=self.goals_dir)
        plan = _referenced_json(self.project_root, state.get("approved_plan_path") or state.get("current_plan_path"))
        manifest = None
        tasks_by_id: dict[str, dict] = {}
        if state.get("run_id"):
            manifest = _read_json(self._run_dir(state["run_id"]) / "manifest.json", None, root=self.runs_dir)
            if isinstance(manifest, dict):
                tasks_by_id = {task_id: _compact_task(task_id, task, str(state["run_id"])) for task_id, task in (manifest.get("tasks") or {}).items() if isinstance(task, dict)}
        validations = _normalize_validation_results(state.get("validation_results") or (manifest.get("validation_results") if isinstance(manifest, dict) else None))
        return {
            "summary": self._goal_summary(state),
            "state": _compact_goal_state(state),
            "goal_spec": _compact_goal_spec(goal_spec),
            "plan": _compact_plan(plan),
            "traceability": _build_traceability(goal_spec, plan, tasks_by_id, validations),
            "validation_results": validations,
            "final_audit": _compact_audit((state.get("audit_results") or [])[-1]) if isinstance(state.get("audit_results"), list) and state.get("audit_results") else None,
        }

    def run_detail(self, run_id: str) -> dict:
        run_dir = self._run_dir(run_id)
        manifest = _read_json(run_dir / "manifest.json", None, root=self.runs_dir)
        if not isinstance(manifest, dict):
            raise UIDataError("Run not found")
        tasks_raw = manifest.get("tasks") if isinstance(manifest.get("tasks"), dict) else {}
        tasks = [_compact_task(task_id, task, run_id) for task_id, task in tasks_raw.items() if isinstance(task, dict)]
        plan = self._resolve_plan(manifest, run_dir)
        goal_spec = self._resolve_goal_spec(manifest)
        goal_state = self._goal_state_for_run(manifest)
        validations = _normalize_validation_results(
            manifest.get("validation_results") or (goal_state.get("validation_results") if isinstance(goal_state, dict) else None)
        )
        compact = _compact_run(manifest)
        return {
            "run": compact,
            "goal_state": _compact_goal_state(goal_state) if isinstance(goal_state, dict) else {},
            "tasks": tasks,
            "traceability": _build_traceability(goal_spec, plan, {task["task_id"]: task for task in tasks}, validations),
            "validation_results": validations,
            "final_audit": _compact_audit(manifest.get("final_audit") or ((goal_state.get("audit_results") or [])[-1] if isinstance(goal_state, dict) and isinstance(goal_state.get("audit_results"), list) and goal_state.get("audit_results") else None)),
            "concurrency_evidence": manifest.get("concurrency_evidence") or {},
            "plan": _compact_plan(plan),
            "events": self._events(run_id, limit=150),
            "metrics": self._usage_summary(run_id, tasks),
        }

    def task_detail(self, run_id: str, task_id: str) -> dict:
        run_dir = self._run_dir(run_id)
        task_id = _safe_id(task_id, "task id")
        manifest = _read_json(run_dir / "manifest.json", None, root=self.runs_dir)
        if not isinstance(manifest, dict):
            raise UIDataError("Run not found")
        tasks = manifest.get("tasks") if isinstance(manifest.get("tasks"), dict) else {}
        task = tasks.get(task_id)
        if not isinstance(task, dict):
            raise UIDataError("Task not found")
        attempts = [item for item in (task.get("attempts") or []) if isinstance(item, dict)]
        compact_attempts = [_compact_attempt(item) for item in attempts]
        compact_task = _compact_task(task_id, task, run_id)
        plan = self._resolve_plan(manifest, run_dir)
        definition = next((item for item in _plan_tasks(plan) if item.get("task_id") == task_id), {})
        context_metrics = self._context_telemetry(run_id, task_id)
        packet = self._find_context_packet(run_id, task_id, compact_task.get("current_attempt_id"))
        context_summary = _safe_context_summary(packet, context_metrics)
        goal_spec = self._resolve_goal_spec(manifest)
        criteria_map = {str(item.get("id")): item for item in (goal_spec.get("acceptance_criteria", []) if isinstance(goal_spec, dict) else []) if isinstance(item, dict)}
        requirement_ids = list(definition.get("satisfies") or []) if isinstance(definition, dict) else []
        requirements = context_summary.get("requirements", []) if context_summary else []
        if not requirements:
            requirements = [{
                "id": criterion_id,
                "title": criteria_map.get(str(criterion_id), {}).get("title") or criterion_id,
                "description": _safe_text(criteria_map.get(str(criterion_id), {}).get("description") or criteria_map.get(str(criterion_id), {}).get("text"), 1200),
                "provenance": criteria_map.get(str(criterion_id), {}).get("provenance"),
            } for criterion_id in requirement_ids]

        goal_state = self._goal_state_for_run(manifest)
        validation_results = _normalize_validation_results(
            manifest.get("validation_results") or (goal_state.get("validation_results") if isinstance(goal_state, dict) else None)
        )
        validation_results = [item for item in validation_results if not item.get("task_id") or item.get("task_id") == task_id]
        validations = list(definition.get("validations") or []) if isinstance(definition, dict) else []
        if not validations and context_summary:
            validations = context_summary.get("validations", [])
        changed_paths = sorted({path for attempt in compact_attempts for path in attempt.get("changed_paths", [])} | set(compact_task.get("changed_paths") or []))
        commits = [
            {"attempt_id": attempt.get("attempt_id"), "commit_hash": attempt.get("commit_hash"), "branch": attempt.get("branch")}
            for attempt in compact_attempts if attempt.get("commit_hash") or attempt.get("branch")
        ]
        return {
            "task": compact_task,
            "definition": {
                "satisfies": requirement_ids,
                "validations": validations,
                "allowed_paths": list(definition.get("allowed_paths") or []) if isinstance(definition, dict) else [],
                "dependencies": list(definition.get("dependencies") or compact_task.get("dependencies") or []) if isinstance(definition, dict) else list(compact_task.get("dependencies") or []),
            },
            "requirements": requirements,
            "context": context_summary,
            "validation": {
                "commands": validations,
                "results": validation_results,
                "path_violations": sorted({path for attempt in compact_attempts for path in attempt.get("path_violations", [])}),
                "missing_expected": sorted({path for attempt in compact_attempts for path in attempt.get("missing_expected", [])}),
            },
            "git": {"commits": commits, "changed_paths": changed_paths, "current_commit": compact_task.get("commit_hash")},
            "attempts": compact_attempts,
            "retry_info": task.get("retry_info") if isinstance(task.get("retry_info"), dict) else None,
            "routing_provenance": task.get("routing_provenance") if isinstance(task.get("routing_provenance"), dict) else None,
            "events": self._events(run_id, task_id, 100),
            "telemetry": self._telemetry(run_id, task_id, 50),
        }

    def system_detail(self) -> dict:
        raw_profiles = self._load_factory_config("harness_profiles.json", {})
        profiles = raw_profiles.get("profiles", {}) if isinstance(raw_profiles, dict) else {}
        compact_profiles = {}
        for profile_id, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            certification = profile.get("certification") if isinstance(profile.get("certification"), dict) else {}
            compact_profiles[profile_id] = {
                "harness": profile.get("harness"),
                "adapter": profile.get("adapter"),
                "model": profile.get("model"),
                "effort": profile.get("effort"),
                "enabled": bool(profile.get("enabled", True)),
                "certification": {
                    "status": certification.get("status") or "UNKNOWN",
                    "last_certified_timestamp": certification.get("last_certified_timestamp"),
                },
            }

        raw_context = self._load_factory_config("context_policy.json", {})
        roles = raw_context.get("roles", {}) if isinstance(raw_context, dict) else {}
        compact_roles = {
            role: {
                "soft_budget_bytes": config.get("soft_budget_bytes"),
                "hard_budget_bytes": config.get("hard_budget_bytes"),
            }
            for role, config in roles.items() if isinstance(config, dict)
        }

        raw_reasoning = self._load_factory_config("reasoning_policy.json", {})
        escalation = raw_reasoning.get("escalation_policy", {}) if isinstance(raw_reasoning, dict) else {}
        compact_reasoning = {
            "policy_version": raw_reasoning.get("policy_version") if isinstance(raw_reasoning, dict) else None,
            "status": raw_reasoning.get("status") if isinstance(raw_reasoning, dict) else None,
            "escalation_policy": {
                "max_effort_escalations_per_task": escalation.get("max_effort_escalations_per_task") if isinstance(escalation, dict) else None,
            },
        }

        raw_toolchain = self._load_factory_config("toolchain.lock.json", {})
        compact_toolchain = {}
        if isinstance(raw_toolchain, dict):
            allowed = (
                "version", "installed_version", "certified_version", "status",
                "compatibility_status", "feasibility_status", "protocol", "schema_version",
            )
            for key, value in raw_toolchain.items():
                if isinstance(value, dict):
                    projected = {field: value.get(field) for field in allowed if field in value}
                    compact_toolchain[key] = projected or "configured"
                elif isinstance(value, (str, int, float, bool)) or value is None:
                    compact_toolchain[key] = value

        raw_vendor = self._load_factory_config("ui/vendor.lock.json", {})
        vendor_packages = []
        if isinstance(raw_vendor, dict):
            for package in raw_vendor.get("packages", []) if isinstance(raw_vendor.get("packages"), list) else []:
                if isinstance(package, dict):
                    vendor_packages.append({"name": package.get("name"), "version": package.get("version")})

        return {
            "providers": self._provider_summary(),
            "profiles": compact_profiles,
            "context_policy": {
                "schema_version": raw_context.get("schema_version") if isinstance(raw_context, dict) else None,
                "roles": compact_roles,
            },
            "reasoning_policy": compact_reasoning,
            "toolchain": compact_toolchain,
            "ui_vendor_lock": {"packages": vendor_packages},
        }


class GoalActionRunner:
    """Delegate stable public Factory actions without owning scheduler state."""

    def __init__(self, project_root: pathlib.Path, factory_root: pathlib.Path = FACTORY_ROOT):
        self.project_root = pathlib.Path(project_root).resolve()
        self.factory_root = pathlib.Path(factory_root).resolve()
        self._lock = threading.Lock()
        self._active: dict[str, subprocess.Popen] = {}

    def resume(self, goal_id: str) -> dict:
        goal_id = _safe_id(goal_id, "goal id")
        goals_root = self.project_root / ".agy-factory" / "goals"
        goal_dir = _safe_child_dir(goals_root, goal_id, "goal id")
        state = _read_json(goal_dir / "state.json", None, root=goals_root)
        if not isinstance(state, dict):
            raise UIDataError("Goal not found")
        if str(state.get("phase") or "").upper() in TERMINAL_GOAL_PHASES:
            raise UIDataError("Goal is terminal and cannot be resumed")

        with self._lock:
            existing = self._active.get(goal_id)
            if existing is not None and existing.poll() is None:
                raise ActionConflict("Goal resume is already running")

            actions_dir = self.project_root / ".agy-factory" / "ui" / "actions"
            if not _is_under(self.project_root, actions_dir):
                raise UIDataError("UI action log path escapes project")
            actions_dir.mkdir(parents=True, exist_ok=True)
            if not _is_under(self.project_root, actions_dir):
                raise UIDataError("UI action log path escapes project")
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            log_path = actions_dir / f"{stamp}-resume-{goal_id}.log"
            log_handle = log_path.open("xb")
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

            def watch() -> None:
                try:
                    proc.wait()
                finally:
                    log_handle.close()
                    with self._lock:
                        if self._active.get(goal_id) is proc:
                            self._active.pop(goal_id, None)

            threading.Thread(target=watch, name=f"factory-ui-resume-{goal_id}", daemon=True).start()
            return {"accepted": True, "goal_id": goal_id, "pid": proc.pid, "log": str(log_path.relative_to(self.project_root))}


class FactoryUIServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_cls, *, read_model: FactoryReadModel, action_runner: GoalActionRunner,
                 ui_root: pathlib.Path = UI_ROOT, vendor_root: pathlib.Path = DEFAULT_VENDOR_ROOT):
        super().__init__(server_address, handler_cls)
        self.read_model = read_model
        self.action_runner = action_runner
        self.ui_root = pathlib.Path(ui_root).resolve()
        self.vendor_root = pathlib.Path(vendor_root).resolve()


class FactoryUIHandler(http.server.BaseHTTPRequestHandler):
    server_version = "FactoryControlUI/1.1"
    protocol_version = "HTTP/1.1"
    CSP = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[factory-ui] %s - %s\n" % (self.address_string(), fmt % args))

    def _log_exception(self, context: str, exc: BaseException) -> None:
        # Exception messages may contain target paths, provider output or secrets.
        sys.stderr.write(f"[factory-ui] {context}: {type(exc).__name__}\n")

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
        if not relative or ".." in pathlib.PurePosixPath(relative).parts:
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
        if (content_type.startswith("text/") or path.suffix in {".js", ".css", ".json"}) and "charset=" not in content_type:
            content_type += "; charset=utf-8"
        etag = hashlib.sha256(content).hexdigest()
        if self.headers.get("If-None-Match") == f'"{etag}"':
            self._send_empty(304, etag=etag)
            return
        self.send_response(200)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
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
        except ValueError:
            return False
        if parsed.username is not None or parsed.password is not None or not parsed.hostname:
            return False
        if parsed.hostname.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(parsed.hostname).is_loopback
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
        return parsed.scheme == "http" and parsed.netloc == self.headers.get("Host", "") and not parsed.username and not parsed.password

    def _read_json_body(self) -> dict:
        if self.headers.get("Transfer-Encoding"):
            raise UIDataError("Transfer-Encoding is not supported")
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
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
        path = urllib.parse.urlparse(self.path).path
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
            self._send_json(404, {"error": "Not Found"})
        except UIDataError as exc:
            self._send_json(404, {"error": str(exc)})
        except Exception as exc:
            self._log_exception("GET failed", exc)
            self._send_json(500, {"error": "Internal server error"})

    def do_POST(self) -> None:
        if not self._host_allowed():
            self.close_connection = True
            self._send_json(403, {"error": "Host rejected"})
            return
        path = urllib.parse.urlparse(self.path).path
        if not self._origin_allowed():
            self.close_connection = True
            self._send_json(403, {"error": "Origin rejected"})
            return
        try:
            self._read_json_body()
            segments = [segment for segment in path.split("/") if segment]
            if len(segments) == 5 and segments[:3] == ["api", "v1", "goals"] and segments[4] == "resume":
                self._send_json(202, self.server.action_runner.resume(segments[3]))
                return
            self._send_json(404, {"error": "Not Found"})
        except ActionConflict as exc:
            self._send_json(409, {"error": str(exc)})
        except UIDataError as exc:
            self.close_connection = True
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:
            self._log_exception("POST failed", exc)
            self._send_json(500, {"error": "Action failed"})


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


def main(argv: Optional[list[str]] = None) -> int:
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
