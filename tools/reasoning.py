#!/usr/bin/env python3
"""Reasoning Efficiency Engine & Deterministic Policy Core (Factory v9.0.0).

Authoritative module governing model-specific reasoning-effort ladders,
deterministic effort resolution, bounded quality-failure escalation,
provenance hashing, and usage telemetry accounting.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple, Union

# Factory Root paths
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
POLICY_PATH = PROJECT_ROOT / "reasoning_policy.json"

REASONING_SCHEMA_VERSION = "9.0.0"
EFFORT_RANKS = {"none": 0, "free": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4, "deep": 4, "max": 5}
_PROVENANCE_FILES = {
    "context_policy_hash": "context_policy.json",
    "toolchain_lock_hash": "toolchain.lock.json",
    "harness_profiles_hash": "harness_profiles.json",
    "calibration_evidence_hash": "certification/v9/calibration-runs.jsonl",
}

# Canonical ordered effort ladders per model family discovered from live runtime probing
CERTIFIED_MODEL_LADDERS: Dict[str, List[str]] = {
    "gemini-3.8-flash": ["low", "medium", "high"],
    "claude-sonnet-4-6": ["high"],
    "qwen3.8-max": ["low", "medium", "xhigh"],
    "gpt-5.6-luna": ["low", "medium", "high", "xhigh"],
    "claude-sonnet-5": ["low", "medium", "high", "xhigh", "max"],
    "openrouter/openrouter/free": ["free"]
}

# Quality failures eligible for bounded effort escalation
ELIGIBLE_FAILURE_CATEGORIES = {
    "INCOMPLETE_RESULT",
    "SCHEMA_VIOLATION",
    "REQUIREMENT_VALIDATION_FAILED",
    "DETERMINISTIC_TEST_FAILED",
    "AUDIT_REQUIRED_REMEDIATION",
    "MISSING_EXPECTED_FILES",
    "WORKER_RESULT_INVALID"
}

# Failures that MUST NEVER trigger effort escalation. This includes infrastructure/auth
# failures and guardrail/scope violations: more reasoning must never be used to bypass
# a deterministic safety boundary such as path validation.
NON_ELIGIBLE_FAILURE_CATEGORIES = {
    "AUTH_BLOCKED",
    "EXECUTABLE_MISSING",
    "BINARY_NOT_FOUND",
    "PROVIDER_UNAVAILABLE",
    "NETWORK_FAILURE",
    "RATE_LIMIT",
    "TIMEOUT",
    "TIMED_OUT",
    "INVALID_MODEL",
    "INVALID_CLI_FLAG",
    "WORKTREE_FAILURE",
    "GIT_CONFLICT",
    "PATH_VALIDATION_FAILED",
    "CONFLICTED",
    "CONTEXT_COMPILATION_FAILED",
    "CONTEXT_ANCHOR_MISSING",
    "CONTEXT_BUDGET_EXCEEDED",
    "CONTEXT_PACKET_STALE",
    "ORPHAN_DERIVED_REQUIREMENT",
    "CANCELLED",
    "UNEXPECTED_COMPILATION_ERROR"
}

# Execution purposes for strict telemetry separation
VALID_EXECUTION_PURPOSES = {
    "PRODUCTION",
    "CALIBRATION",
    "CERTIFICATION",
    "DETERMINISTIC_TEST",
    "LEGACY",
    "UNKNOWN"
}


class ReasoningError(Exception):
    """Base exception for reasoning policy violations."""
    pass


class ReasoningPolicyConflictError(ReasoningError):
    """Raised when project policy restricts effort below certified minimum for deep tasks."""
    pass


class MalformedReasoningPolicyError(ReasoningError):
    """Raised when reasoning policy file or structure violates schema."""
    pass


def sha256_file(path: pathlib.Path) -> Optional[str]:
    """Computes SHA-256 hex digest of a file if it exists."""
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def calculate_policy_provenance_hashes(project_root: pathlib.Path = PROJECT_ROOT) -> Dict[str, str]:
    """Hash actual governance files; an empty value means evidence is missing."""
    return {
        key: sha256_file(pathlib.Path(project_root) / relative_path) or ""
        for key, relative_path in _PROVENANCE_FILES.items()
    }


def verify_policy_provenance(policy_dict: dict, project_root: pathlib.Path = PROJECT_ROOT) -> Tuple[bool, List[str]]:
    """Require every recorded hash and its source file; missing is not verified."""
    prov = policy_dict.get("provenance_hashes") if isinstance(policy_dict, dict) else None
    if not isinstance(prov, dict):
        return False, ["Missing or malformed provenance_hashes object"]
    try:
        current_hashes = calculate_policy_provenance_hashes(project_root)
    except OSError as exc:
        return False, [f"Cannot read provenance evidence: {type(exc).__name__}"]
    reasons = []
    for key, cur_hash in current_hashes.items():
        recorded_hash = prov.get(key)
        if not isinstance(recorded_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", recorded_hash):
            reasons.append(f"Missing or malformed recorded provenance hash: {key}")
        elif not cur_hash:
            reasons.append(f"Missing provenance evidence file: {key}")
        elif recorded_hash != cur_hash:
            reasons.append(f"Provenance drift detected on {key}: recorded={recorded_hash[:12]}, current={cur_hash[:12]}")
    return not reasons, reasons


def _bounded_effort(ladder: List[str], ceiling: str) -> Optional[str]:
    """Resolve an upper bound even when its label is absent from this ladder."""
    if not isinstance(ceiling, str) or ceiling not in EFFORT_RANKS:
        return None
    allowed = [effort for effort in ladder if EFFORT_RANKS[effort] <= EFFORT_RANKS[ceiling]]
    return allowed[-1] if allowed else None


@dataclasses.dataclass
class ReasoningResolution:
    """Outcome of deterministic reasoning effort selection."""
    role: str
    task_type: str
    execution_class: str
    model_family: str
    initial_effort: str
    selected_effort: str
    escalation_ceiling: str
    effort_source: str
    effort_attempt_index: int
    escalated_from_profile: Optional[str] = None
    escalation_reason: Optional[str] = None
    ladder: List[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


class ReasoningPolicy:
    """Encapsulates static deterministic reasoning policy rules, ladders, and escalation bounds."""

    def __init__(self, policy_data: dict, policy_path: Optional[pathlib.Path] = None):
        self.data = copy.deepcopy(policy_data)
        self.policy_path = policy_path
        self._validate()

    @classmethod
    def load(cls, policy_path: Optional[pathlib.Path] = None) -> "ReasoningPolicy":
        path = pathlib.Path(policy_path) if policy_path is not None else POLICY_PATH
        if not path.exists():
            raise MalformedReasoningPolicyError(f"Reasoning policy file not found at {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise MalformedReasoningPolicyError(f"Failed to parse reasoning policy JSON: {e}")
        return cls(data, policy_path=path)

    def _validate(self):
        """Validates loaded policy structure against internal invariants."""
        if not isinstance(self.data, dict):
            raise MalformedReasoningPolicyError("Reasoning policy must be a JSON object")

        if self.data.get("schema_version") != REASONING_SCHEMA_VERSION:
            raise MalformedReasoningPolicyError(
                f"Unsupported schema_version '{self.data.get('schema_version')}'. Expected '{REASONING_SCHEMA_VERSION}'"
            )

        for req in ["policy_version", "model_ladders", "role_policy", "task_policy", "escalation_policy"]:
            if req not in self.data:
                raise MalformedReasoningPolicyError(f"Missing required policy section '{req}'")

        if not isinstance(self.data["policy_version"], str) or not self.data["policy_version"].strip():
            raise MalformedReasoningPolicyError("policy_version must be a non-empty string")
        for section in ("model_ladders", "role_policy", "task_policy", "escalation_policy"):
            if not isinstance(self.data[section], dict):
                raise MalformedReasoningPolicyError(f"Policy section '{section}' must be an object")

        ladders = self.data["model_ladders"]
        if not ladders:
            raise MalformedReasoningPolicyError("model_ladders must not be empty")
        for model, ladder in ladders.items():
            if not isinstance(model, str) or not model.strip():
                raise MalformedReasoningPolicyError("Model family must be a non-empty string")
            if not isinstance(ladder, list) or not ladder or any(
                not isinstance(effort, str) or effort not in EFFORT_RANKS for effort in ladder
            ):
                raise MalformedReasoningPolicyError(f"Model '{model}' has empty or invalid effort ladder")
            ranks = [EFFORT_RANKS[effort] for effort in ladder]
            if any(left >= right for left, right in zip(ranks, ranks[1:])):
                raise MalformedReasoningPolicyError(f"Model '{model}' ladder must be strictly increasing: {ladder}")

        for section in ("role_policy", "task_policy"):
            for name, rules in self.data[section].items():
                if not isinstance(rules, dict):
                    raise MalformedReasoningPolicyError(f"{section}.{name} must be an object")
                for field in ("initial_effort", "escalation_ceiling"):
                    if field in rules and (not isinstance(rules[field], str) or rules[field] not in EFFORT_RANKS):
                        raise MalformedReasoningPolicyError(f"Invalid effort in {section}.{name}.{field}")
                for field in ("initial_effort_by_class", "escalation_ceiling_by_class"):
                    values = rules.get(field, {})
                    if not isinstance(values, dict) or any(
                        key not in {"routine", "standard", "deep"}
                        or not isinstance(value, str) or value not in EFFORT_RANKS
                        for key, value in values.items()
                    ):
                        raise MalformedReasoningPolicyError(f"Invalid effort map in {section}.{name}.{field}")

        esc = self.data["escalation_policy"]
        max_esc = esc.get("max_effort_escalations_per_task", 1)
        if type(max_esc) is not int or not 0 <= max_esc <= 1:
            raise MalformedReasoningPolicyError(f"Invalid max_effort_escalations_per_task '{max_esc}'. Must be 0 or 1.")
        if type(esc.get("enabled", True)) is not bool:
            raise MalformedReasoningPolicyError("escalation_policy.enabled must be a boolean")
        for field in ("eligible_failure_categories", "non_eligible_failure_categories"):
            categories = esc.get(field, [])
            if not isinstance(categories, list) or any(not isinstance(cat, str) or not cat for cat in categories):
                raise MalformedReasoningPolicyError(f"{field} must be an array of non-empty strings")

        prov = self.data.get("provenance_hashes", {})
        if not isinstance(prov, dict):
            raise MalformedReasoningPolicyError("provenance_hashes must be an object")
        for key, value in prov.items():
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise MalformedReasoningPolicyError(f"Provenance hash '{key}' must be a lowercase hex SHA-256 string")

        evidence = self.data.get("calibration_evidence", {})
        if not isinstance(evidence, dict):
            raise MalformedReasoningPolicyError("calibration_evidence must be an object")
        roles = evidence.get("calibrated_roles", [])
        if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
            raise MalformedReasoningPolicyError("calibrated_roles must be an array of strings")
        missing = set(self.data["role_policy"]) - set(roles)
        if roles and missing:
            raise MalformedReasoningPolicyError(f"Declared roles in role_policy missing calibration evidence: {missing}")

    @property
    def version(self) -> str:
        return str(self.data.get("policy_version", "unknown"))

    @property
    def status(self) -> str:
        return str(self.data.get("status", "VALID"))

    def check_staleness(self, project_root: pathlib.Path = PROJECT_ROOT) -> Tuple[bool, List[str]]:
        """Checks whether the policy is stale with respect to local project toolchain."""
        return verify_policy_provenance(self.data, project_root)

    def _model_family(self, model: str) -> str:
        """Prefer exact policy keys; normalize only known provider/suffix forms."""
        if isinstance(model, str):
            for candidate in (model, model.rsplit("/", 1)[-1]):
                if candidate in self.data["model_ladders"]:
                    return candidate
                for suffix in ("-low", "-medium", "-high"):
                    if candidate.endswith(suffix) and candidate[:-len(suffix)] in self.data["model_ladders"]:
                        return candidate[:-len(suffix)]
        raise ReasoningPolicyConflictError(f"REASONING_POLICY_CONFLICT: No configured effort ladder for '{model}'")

    def get_ladder(self, model_family: str) -> List[str]:
        """Return the configured ladder, never an invented fallback for unknown models."""
        return list(self.data["model_ladders"][self._model_family(model_family)])

    def is_failure_escalation_eligible(self, failure_category: str) -> bool:
        """Configured denials and invariant guardrails take precedence over allowlists."""
        if not failure_category:
            return False
        cat = str(failure_category).upper()
        esc = self.data["escalation_policy"]
        denied = NON_ELIGIBLE_FAILURE_CATEGORIES | {cat.upper() for cat in esc.get("non_eligible_failure_categories", [])}
        eligible = {cat.upper() for cat in esc.get("eligible_failure_categories", ELIGIBLE_FAILURE_CATEGORIES)}
        return cat in eligible and cat not in denied

    def resolve_initial_effort(
        self,
        role: str,
        task_type: str,
        execution_class: str,
        model_family: str = "gemini-3.8-flash",
        project_policy: Optional[Any] = None
    ) -> ReasoningResolution:
        """Deterministically resolves the initial reasoning effort for a role/task."""
        execution_class = execution_class if execution_class in {"routine", "standard", "deep"} else "standard"
        clean_model = self._model_family(model_family)
        ladder = self.get_ladder(clean_model)

        initial_effort = "medium"
        escalation_ceiling = ladder[-1] if ladder else "high"

        # 1. Role-specific policy resolution
        role_rules = self.data.get("role_policy", {}).get(role, {})
        if role in {"planner", "plan_reviewer", "final_auditor", "remediation_planner"}:
            initial_effort = role_rules.get("initial_effort", "medium")
            escalation_ceiling = role_rules.get("escalation_ceiling", ladder[-1])
        elif role == "remediation_worker":
            initial_effort = role_rules.get("initial_effort", "high")
            escalation_ceiling = role_rules.get("escalation_ceiling", ladder[-1])
        else:  # worker
            worker_rules = self.data.get("role_policy", {}).get("worker", {})
            by_class = worker_rules.get("initial_effort_by_class", {})
            initial_effort = by_class.get(execution_class, "medium")
            ceilings = worker_rules.get("escalation_ceiling_by_class", {})
            escalation_ceiling = ceilings.get(execution_class, ladder[-1])

            # Task-specific override if explicitly declared in task_policy
            task_policy = self.data.get("task_policy", {})
            task_rules = task_policy.get(task_type) or (task_policy.get("testing") if task_type == "tests" else {})
            if task_rules:
                t_by_class = task_rules.get("initial_effort_by_class", {})
                if execution_class in t_by_class:
                    initial_effort = t_by_class[execution_class]
                t_ceilings = task_rules.get("escalation_ceiling_by_class", {})
                if execution_class in t_ceilings:
                    escalation_ceiling = t_ceilings[execution_class]

        # Ensure effort is in ladder (map to highest available <= requested or closest)
        if initial_effort not in ladder:
            target_rank = EFFORT_RANKS[initial_effort]
            lower_or_equal = [e for e in ladder if EFFORT_RANKS[e] <= target_rank]
            if lower_or_equal:
                initial_effort = lower_or_equal[-1]
            else:
                initial_effort = ladder[0] if ladder else "medium"

        supported_ceiling = _bounded_effort(ladder, escalation_ceiling)
        if supported_ceiling is None or ladder.index(initial_effort) > ladder.index(supported_ceiling):
            raise ReasoningPolicyConflictError(
                f"REASONING_POLICY_CONFLICT: Initial effort '{initial_effort}' exceeds policy ceiling '{escalation_ceiling}'"
            )
        escalation_ceiling = supported_ceiling

        # 2. Project Policy Constraints and Deep Task Safety (Section 56-57)
        if project_policy:
            project_max = getattr(project_policy, "max_effort", None)
            if isinstance(project_policy, dict):
                project_max = project_policy.get("max_effort")

            if project_max is not None:
                supported_max = _bounded_effort(ladder, project_max)
                if supported_max is None:
                    raise ReasoningPolicyConflictError(
                        f"REASONING_POLICY_CONFLICT: No effort for '{clean_model}' satisfies project max_effort '{project_max}'"
                    )
                proj_max_idx = ladder.index(supported_max)
                init_idx = ladder.index(initial_effort)

                # Section 57: Deep Task Safety invariant
                # If required calibrated effort for deep task is higher than project max, fail with REASONING_POLICY_CONFLICT
                if execution_class == "deep" and init_idx > proj_max_idx:
                    raise ReasoningPolicyConflictError(
                        f"REASONING_POLICY_CONFLICT: Deep task '{task_type}' requires calibrated minimum effort "
                        f"'{initial_effort}', but project policy restricts max_effort to '{project_max}'."
                    )

                if init_idx > proj_max_idx:
                    initial_effort = supported_max

                ceil_idx = ladder.index(escalation_ceiling) if escalation_ceiling in ladder else len(ladder) - 1
                if ceil_idx > proj_max_idx:
                    escalation_ceiling = supported_max

        return ReasoningResolution(
            role=role,
            task_type=task_type,
            execution_class=execution_class,
            model_family=clean_model,
            initial_effort=initial_effort,
            selected_effort=initial_effort,
            escalation_ceiling=escalation_ceiling,
            effort_source="reasoning_policy",
            effort_attempt_index=1,
            escalated_from_profile=None,
            escalation_reason=None,
            ladder=ladder,
        )

    def evaluate_escalation(
        self,
        current_effort: str,
        model_family: str,
        failure_category: str,
        attempt_id: int,
        execution_class: str = "standard",
        project_policy: Optional[Any] = None,
        escalation_ceiling: Optional[str] = None
    ) -> Tuple[Optional[str], str]:
        """
        Evaluates whether a failed attempt should escalate reasoning effort.
        Returns: (new_effort or None, decision_reason)
        """
        # 1. Failure eligibility check
        if not self.is_failure_escalation_eligible(failure_category):
            return None, f"FAILURE_NOT_ELIGIBLE: Category '{failure_category}' is non-escalatable"

        # 2. Check policy escalation enabled and attempt limits
        esc_cfg = self.data.get("escalation_policy", {})
        if not esc_cfg.get("enabled", True):
            return None, "ESCALATION_DISABLED_BY_POLICY"

        max_escalations = esc_cfg.get("max_effort_escalations_per_task", 1)
        if project_policy:
            disable_esc = getattr(project_policy, "disable_effort_escalation", False)
            if isinstance(project_policy, dict):
                disable_esc = project_policy.get("disable_effort_escalation", False)
            if disable_esc:
                return None, "ESCALATION_DISABLED_BY_PROJECT_POLICY"

        # Invalid or missing durable attempt evidence never grants another attempt.
        if type(attempt_id) is not int or attempt_id < 1:
            return None, "INVALID_ATTEMPT_ID: expected a positive integer"
        norm_attempt = attempt_id
        limits = project_policy.get("limits", {}) if isinstance(project_policy, dict) else getattr(project_policy, "limits", {})
        if not isinstance(limits, dict):
            return None, "INVALID_PROJECT_ATTEMPT_LIMIT"
        max_attempts = limits.get("max_task_attempts")
        if "max_task_attempts" in limits:
            if type(max_attempts) is not int or max_attempts < 1:
                return None, "INVALID_PROJECT_ATTEMPT_LIMIT"
            if norm_attempt >= max_attempts:
                return None, "PROJECT_ATTEMPT_LIMIT_REACHED"

        # Only allow 1 escalation by default in v9 (e.g. attempt 1 failed -> attempt 2 escalates)
        if norm_attempt > max_escalations:
            return None, f"ESCALATION_LIMIT_REACHED: Attempt {attempt_id} exceeds max_escalations ({max_escalations})"

        # 3. Ladder lookup in same model family
        clean_model = self._model_family(model_family)
        ladder = self.get_ladder(clean_model)
        if current_effort not in ladder:
            return None, f"UNKNOWN_CURRENT_EFFORT: '{current_effort}' not in ladder {ladder}"

        cur_idx = ladder.index(current_effort)
        if cur_idx >= len(ladder) - 1:
            return None, f"ALREADY_AT_CEILING: '{current_effort}' is maximum supported effort"

        next_effort = ladder[cur_idx + 1]

        # 4. Check policy escalation ceiling
        if escalation_ceiling is None:
            worker_ceilings = self.data.get("role_policy", {}).get("worker", {}).get("escalation_ceiling_by_class", {})
            escalation_ceiling = worker_ceilings.get(execution_class, ladder[-1])

        supported_ceiling = _bounded_effort(ladder, escalation_ceiling)
        if supported_ceiling is None or ladder.index(next_effort) > ladder.index(supported_ceiling):
            return None, f"CEILING_REACHED: next effort '{next_effort}' exceeds escalation ceiling '{escalation_ceiling}'"

        # 5. Check project policy ceiling
        if project_policy:
            project_max = getattr(project_policy, "max_effort", None)
            if isinstance(project_policy, dict):
                project_max = project_policy.get("max_effort")
            if project_max is not None:
                supported_max = _bounded_effort(ladder, project_max)
                if supported_max is None or ladder.index(next_effort) > ladder.index(supported_max):
                    return None, f"PROJECT_CEILING_REACHED: next effort '{next_effort}' exceeds project max '{project_max}'"

        return next_effort, f"ESCALATED: Ladder step from '{current_effort}' to '{next_effort}' due to {failure_category}"

    def explain(
        self,
        role: str = "worker",
        task_type: str = "backend",
        execution_class: str = "standard",
        model_family: str = "gemini-3.8-flash",
        project_policy: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Produces a structured explanation of the reasoning effort selection for a role/task."""
        res = self.resolve_initial_effort(
            role=role,
            task_type=task_type,
            execution_class=execution_class,
            model_family=model_family,
            project_policy=project_policy
        )

        escalation_ladder = res.ladder
        next_effort, reason = self.evaluate_escalation(
            current_effort=res.selected_effort,
            model_family=model_family,
            failure_category="DETERMINISTIC_TEST_FAILED",
            attempt_id=1,
            execution_class=execution_class,
            project_policy=project_policy,
            escalation_ceiling=res.escalation_ceiling,
        )

        return {
            "policy_version": self.version,
            "status": self.status,
            "role": role,
            "task_type": task_type,
            "execution_class": execution_class,
            "model_family": model_family,
            "effort_ladder": escalation_ladder,
            "ladder": escalation_ladder,
            "selected_initial_effort": res.selected_effort,
            "selected_effort": res.selected_effort,
            "initial_effort": res.initial_effort,
            "escalation_ceiling": res.escalation_ceiling,
            "escalation_eligible": next_effort is not None,
            "next_escalated_effort": next_effort,
            "escalation_sample_decision": reason,
            "eligible_failures": sorted(
                category for category in self.data["escalation_policy"].get("eligible_failure_categories", ELIGIBLE_FAILURE_CATEGORIES)
                if self.is_failure_escalation_eligible(category)
            ),
            "calibration_evidence_ref": self.data.get("calibration_evidence", {}).get("baseline_ref", "certification/v9/effort-baseline.json")
        }


def _measurement(value: Any, integer: bool = False) -> Optional[Union[int, float]]:
    """Accept finite, nonnegative provider measurements without rounding tokens."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or (integer and not value.is_integer()):
            return None
    return int(value) if integer else value


def summarize_usage_by_dimensions(
    records: List[Dict[str, Any]],
    filter_purpose: Optional[str] = None
) -> Dict[str, Any]:
    """Group measured usage; an incomplete aggregate is null, never a partial total."""
    token_fields = ("provider_input_tokens", "provider_cached_input_tokens", "provider_reasoning_tokens", "provider_output_tokens")
    counters = {"calls": 0, "attempts": 0, "successes": 0, "failures": 0, "escalations": 0}
    counters.update({field: 0 for field in token_fields})
    counters.update(provider_credits_or_units=0.0, total_duration_ms=0.0)
    totals = dict(counters)
    groups: Dict[Tuple, Dict[str, Any]] = {}

    for rec in records:
        purpose = rec.get("execution_purpose") or "LEGACY"
        if filter_purpose and purpose != filter_purpose:
            continue
        dimensions = {
            "model": rec.get("model") or "unknown",
            "effort": rec.get("effort") or rec.get("resolved_effort") or "unknown",
            "role": rec.get("role") or ("worker" if "task_id" in rec else "unknown"),
            "task_type": rec.get("task_type") or "implementation",
            "execution_class": rec.get("execution_class") or "standard",
            "execution_purpose": purpose,
        }
        key = tuple(dimensions.values())
        if key not in groups:
            groups[key] = {**dimensions, **counters}
        group = groups[key]
        status = rec.get("status") or rec.get("state")
        outcome = "successes" if status in {"SUCCESS", "INTEGRATED", "COMPLETED", "ACCEPTED", "COMMITTED", "PATH_VALIDATED"} else "failures"
        for aggregate in (group, totals):
            aggregate["calls"] += 1
            aggregate["attempts"] += 1
            aggregate[outcome] += 1
            if rec.get("effort_source") == "escalation" or rec.get("escalated_from_profile"):
                aggregate["escalations"] += 1

        measured = {field: _measurement(rec.get(field), integer=True) for field in token_fields}
        measured["provider_credits_or_units"] = _measurement(rec.get("provider_credits_or_units"))
        duration = rec.get("duration_ms")
        if duration is None:
            duration = rec.get("total_model_duration_ms")
        measured["total_duration_ms"] = _measurement(duration)
        for field, value in measured.items():
            for aggregate in (group, totals):
                previous = aggregate[field]
                try:
                    total = previous + value if previous is not None and value is not None else None
                except OverflowError:
                    total = None
                aggregate[field] = None if isinstance(total, float) and not math.isfinite(total) else total

    breakdown = list(groups.values())
    for aggregate in [totals, *breakdown]:
        duration = aggregate["total_duration_ms"]
        aggregate["avg_duration_ms"] = None if duration is None else round(duration / max(1, aggregate["calls"]), 2)
    return {"filter_purpose": filter_purpose, "totals": totals, "breakdown": breakdown}
