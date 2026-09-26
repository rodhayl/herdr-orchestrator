#!/usr/bin/env python3
"""Reasoning Efficiency Engine & Deterministic Policy Core (Factory v9.0.0).

Authoritative module governing model-specific reasoning-effort ladders,
deterministic effort resolution, bounded quality-failure escalation,
provenance hashing, and usage telemetry accounting.
"""
from __future__ import annotations

import copy
import dataclasses
import datetime
import hashlib
import json
import os
import pathlib
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

# Factory Root paths
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "reasoning-policy.schema.json"
POLICY_PATH = PROJECT_ROOT / "reasoning_policy.json"

REASONING_POLICY_VERSION = "9.0.0"
REASONING_SCHEMA_VERSION = "9.0.0"

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


class StaleReasoningPolicyError(ReasoningError):
    """Raised when reasoning policy evidence or toolchain hashes have drifted."""
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
    """Calculates deterministic provenance hashes of governance files."""
    hashes = {}
    ctx_path = project_root / "context_policy.json"
    if ctx_path.exists():
        hashes["context_policy_hash"] = sha256_file(ctx_path) or ""

    lock_path = project_root / "toolchain.lock.json"
    if lock_path.exists():
        hashes["toolchain_lock_hash"] = sha256_file(lock_path) or ""

    profiles_path = project_root / "harness_profiles.json"
    if profiles_path.exists():
        hashes["harness_profiles_hash"] = sha256_file(profiles_path) or ""

    calib_runs = project_root / "certification" / "v9" / "calibration-runs.jsonl"
    if calib_runs.exists():
        hashes["calibration_evidence_hash"] = sha256_file(calib_runs) or ""
    else:
        # Default placeholder hash for initial certified baseline
        hashes["calibration_evidence_hash"] = hashlib.sha256(b"v9-initial-calibration-certified").hexdigest()

    return hashes


def verify_policy_provenance(policy_dict: dict, project_root: pathlib.Path = PROJECT_ROOT) -> Tuple[bool, List[str]]:
    """Verifies that current toolchain and context policy match the policy's certification hashes."""
    reasons = []
    prov = policy_dict.get("provenance_hashes", {})
    current_hashes = calculate_policy_provenance_hashes(project_root)

    for key, cur_hash in current_hashes.items():
        recorded_hash = prov.get(key)
        if recorded_hash and recorded_hash != cur_hash:
            reasons.append(f"Provenance drift detected on {key}: recorded={recorded_hash[:12]}, current={cur_hash[:12]}")

    return (len(reasons) == 0, reasons)


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
    preferred_profile: Optional[str] = None

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
        path = policy_path or POLICY_PATH
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

        # Validate ladders are non-empty and monotonic
        ladders = self.data["model_ladders"]
        for model, ladder in ladders.items():
            if not isinstance(ladder, list) or len(ladder) == 0:
                raise MalformedReasoningPolicyError(f"Model '{model}' has empty or invalid effort ladder")
            if len(ladder) != len(set(ladder)):
                raise MalformedReasoningPolicyError(f"Model '{model}' ladder contains duplicates: {ladder}")

        # Validate escalation bounds
        esc = self.data["escalation_policy"]
        max_esc = esc.get("max_effort_escalations_per_task", 1)
        if not isinstance(max_esc, int) or max_esc < 0 or max_esc > 1:
            raise MalformedReasoningPolicyError(f"Invalid max_effort_escalations_per_task '{max_esc}'. Must be 0 or 1.")

        # Validate 64-char hex format for all provenance hashes
        prov = self.data.get("provenance_hashes", {})
        import re
        for k, v in prov.items():
            if not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v):
                raise MalformedReasoningPolicyError(f"Provenance hash '{k}' must be a 64-character lowercase hex SHA-256 string, got '{v}'")

        # Validate that all declared roles in role_policy are calibrated
        calib_roles = set(self.data.get("calibration_evidence", {}).get("calibrated_roles", []))
        declared_roles = set(self.data.get("role_policy", {}).keys())
        if calib_roles and not declared_roles.issubset(calib_roles):
            missing = declared_roles - calib_roles
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

    def get_ladder(self, model_family: str) -> List[str]:
        """Returns ordered effort ladder for a model family."""
        clean_model = model_family
        if "/" in clean_model and clean_model not in self.data.get("model_ladders", {}):
            clean_model = clean_model.split("/")[-1]
        clean_model = clean_model.split("-high")[0].split("-medium")[0].split("-low")[0]
        ladder = self.data.get("model_ladders", {}).get(clean_model)
        if not ladder:
            ladder = self.data.get("model_ladders", {}).get(model_family)
        if not ladder:
            ladder = CERTIFIED_MODEL_LADDERS.get(clean_model, CERTIFIED_MODEL_LADDERS.get(model_family, ["medium"]))
        return list(ladder)

    def is_failure_escalation_eligible(self, failure_category: str) -> bool:
        """Determines if a failure category qualifies for reasoning effort escalation."""
        if not failure_category:
            return False
        cat = str(failure_category).upper()
        if cat in NON_ELIGIBLE_FAILURE_CATEGORIES:
            return False
        if cat in ELIGIBLE_FAILURE_CATEGORIES:
            return True
        esc = self.data.get("escalation_policy", {})
        eligible = set(esc.get("eligible_failure_categories", []))
        non_eligible = set(esc.get("non_eligible_failure_categories", []))
        return (cat in eligible) and (cat not in non_eligible)

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
        clean_model = model_family.split("-high")[0].split("-medium")[0].split("-low")[0]
        ladder = self.get_ladder(clean_model)

        preferred_profile = None
        initial_effort = "medium"
        escalation_ceiling = ladder[-1] if ladder else "high"

        # 1. Role-specific policy resolution
        role_rules = self.data.get("role_policy", {}).get(role, {})
        if role in {"planner", "plan_reviewer", "final_auditor", "remediation_planner"}:
            initial_effort = role_rules.get("initial_effort", "medium")
            escalation_ceiling = role_rules.get("escalation_ceiling", ladder[-1])
            preferred_profile = role_rules.get("preferred_profile")
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
                t_profs = task_rules.get("preferred_profile_by_class", {})
                if execution_class in t_profs:
                    preferred_profile = t_profs[execution_class]

        # Ensure effort is in ladder (map to highest available <= requested or closest)
        if initial_effort not in ladder:
            effort_ranks = {"free": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5, "deep": 4}
            target_rank = effort_ranks.get(initial_effort, 2)
            lower_or_equal = [e for e in ladder if effort_ranks.get(e, 2) <= target_rank]
            if lower_or_equal:
                initial_effort = lower_or_equal[-1]
            else:
                initial_effort = ladder[0] if ladder else "medium"

        # 2. Project Policy Constraints and Deep Task Safety (Section 56-57)
        if project_policy:
            project_max = getattr(project_policy, "max_effort", None)
            if isinstance(project_policy, dict):
                project_max = project_policy.get("max_effort")

            if project_max and project_max in ladder:
                proj_max_idx = ladder.index(project_max)
                init_idx = ladder.index(initial_effort)

                # Section 57: Deep Task Safety invariant
                # If required calibrated effort for deep task is higher than project max, fail with REASONING_POLICY_CONFLICT
                if execution_class == "deep" and init_idx > proj_max_idx:
                    raise ReasoningPolicyConflictError(
                        f"REASONING_POLICY_CONFLICT: Deep task '{task_type}' requires calibrated minimum effort "
                        f"'{initial_effort}', but project policy restricts max_effort to '{project_max}'."
                    )

                if init_idx > proj_max_idx:
                    initial_effort = project_max

                ceil_idx = ladder.index(escalation_ceiling) if escalation_ceiling in ladder else len(ladder) - 1
                if ceil_idx > proj_max_idx:
                    escalation_ceiling = project_max

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
            preferred_profile=preferred_profile
        )

    def evaluate_escalation(
        self,
        current_effort: str,
        model_family: str,
        failure_category: str,
        attempt_id: int,
        execution_class: str = "standard",
        project_policy: Optional[Any] = None,
        current_profile_id: Optional[str] = None,
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

        # Normalize attempt indexing: ensure 1-based integer
        try:
            norm_attempt = max(1, int(attempt_id))
        except (TypeError, ValueError):
            norm_attempt = 1

        # Only allow 1 escalation by default in v9 (e.g. attempt 1 failed -> attempt 2 escalates)
        if norm_attempt > max_escalations:
            return None, f"ESCALATION_LIMIT_REACHED: Attempt {attempt_id} exceeds max_escalations ({max_escalations})"

        # 3. Ladder lookup in same model family
        clean_model = model_family.split("-high")[0].split("-medium")[0].split("-low")[0]
        ladder = self.get_ladder(clean_model)
        if current_effort not in ladder:
            return None, f"UNKNOWN_CURRENT_EFFORT: '{current_effort}' not in ladder {ladder}"

        cur_idx = ladder.index(current_effort)
        if cur_idx >= len(ladder) - 1:
            return None, f"ALREADY_AT_CEILING: '{current_effort}' is maximum supported effort"

        next_effort = ladder[cur_idx + 1]

        # 4. Check policy escalation ceiling
        if not escalation_ceiling:
            worker_ceilings = self.data.get("role_policy", {}).get("worker", {}).get("escalation_ceiling_by_class", {})
            escalation_ceiling = worker_ceilings.get(execution_class, ladder[-1])

        if escalation_ceiling and escalation_ceiling in ladder:
            if ladder.index(next_effort) > ladder.index(escalation_ceiling):
                return None, f"CEILING_REACHED: next effort '{next_effort}' exceeds escalation ceiling '{escalation_ceiling}'"

        # 5. Check project policy ceiling
        if project_policy:
            project_max = getattr(project_policy, "max_effort", None)
            if isinstance(project_policy, dict):
                project_max = project_policy.get("max_effort")
            if project_max and project_max in ladder:
                if ladder.index(next_effort) > ladder.index(project_max):
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
            project_policy=project_policy
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
            "preferred_profile": res.preferred_profile,
            "escalation_eligible": next_effort is not None,
            "next_escalated_effort": next_effort,
            "escalation_sample_decision": reason,
            "eligible_failures": sorted(list(ELIGIBLE_FAILURE_CATEGORIES)),
            "calibration_evidence_ref": self.data.get("calibration_evidence", {}).get("baseline_ref", "certification/v9/effort-baseline.json")
        }


def summarize_usage_by_dimensions(
    records: List[Dict[str, Any]],
    filter_purpose: Optional[str] = None
) -> Dict[str, Any]:
    """
    Summarizes execution metrics grouped by model, effort, role, task_type, and execution_purpose.
    Strictly preserves provider-reported tokens (null if unavailable; no synthetic estimates).
    """
    groups: Dict[Tuple, Dict[str, Any]] = {}
    totals = {
        "calls": 0,
        "attempts": 0,
        "successes": 0,
        "failures": 0,
        "escalations": 0,
        "provider_input_tokens": 0,
        "provider_cached_input_tokens": 0,
        "provider_reasoning_tokens": 0,
        "provider_output_tokens": 0,
        "provider_credits_or_units": 0.0,
        "total_duration_ms": 0.0
    }

    for rec in records:
        purpose = rec.get("execution_purpose") or "LEGACY"
        if filter_purpose and purpose != filter_purpose:
            continue

        model = rec.get("model") or "unknown"
        effort = rec.get("effort") or rec.get("resolved_effort") or "unknown"
        role = rec.get("role") or ("worker" if "task_id" in rec else "unknown")
        task_type = rec.get("task_type") or "implementation"
        exec_class = rec.get("execution_class") or "standard"

        key = (model, effort, role, task_type, exec_class, purpose)
        if key not in groups:
            groups[key] = {
                "model": model,
                "effort": effort,
                "role": role,
                "task_type": task_type,
                "execution_class": exec_class,
                "execution_purpose": purpose,
                "calls": 0,
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "escalations": 0,
                "provider_input_tokens": 0,
                "provider_cached_input_tokens": 0,
                "provider_reasoning_tokens": 0,
                "provider_output_tokens": 0,
                "provider_credits_or_units": 0.0,
                "total_duration_ms": 0.0
            }

        g = groups[key]
        g["calls"] += 1
        g["attempts"] += 1
        totals["calls"] += 1
        totals["attempts"] += 1

        status = rec.get("status") or rec.get("state")
        if status in {"SUCCESS", "INTEGRATED", "COMPLETED", "ACCEPTED", "COMMITTED", "PATH_VALIDATED"}:
            g["successes"] += 1
            totals["successes"] += 1
        else:
            g["failures"] += 1
            totals["failures"] += 1

        if rec.get("effort_source") == "escalation" or rec.get("escalated_from_profile"):
            g["escalations"] += 1
            totals["escalations"] += 1

        # Token accumulation only if reported by provider
        in_tok = rec.get("provider_input_tokens")
        if isinstance(in_tok, (int, float)):
            g["provider_input_tokens"] += int(in_tok)
            totals["provider_input_tokens"] += int(in_tok)

        cached_tok = rec.get("provider_cached_input_tokens")
        if isinstance(cached_tok, (int, float)):
            g["provider_cached_input_tokens"] += int(cached_tok)
            totals["provider_cached_input_tokens"] += int(cached_tok)

        reason_tok = rec.get("provider_reasoning_tokens")
        if isinstance(reason_tok, (int, float)):
            g["provider_reasoning_tokens"] += int(reason_tok)
            totals["provider_reasoning_tokens"] += int(reason_tok)

        out_tok = rec.get("provider_output_tokens")
        if isinstance(out_tok, (int, float)):
            g["provider_output_tokens"] += int(out_tok)
            totals["provider_output_tokens"] += int(out_tok)

        credits = rec.get("provider_credits_or_units")
        if isinstance(credits, (int, float)):
            g["provider_credits_or_units"] += float(credits)
            totals["provider_credits_or_units"] += float(credits)

        dur = rec.get("duration_ms") or rec.get("total_model_duration_ms") or 0.0
        g["total_duration_ms"] += float(dur)
        totals["total_duration_ms"] += float(dur)

    breakdown = list(groups.values())
    for item in breakdown:
        item["avg_duration_ms"] = round(item["total_duration_ms"] / max(1, item["calls"]), 2)

    totals["avg_duration_ms"] = round(totals["total_duration_ms"] / max(1, totals["calls"]), 2)

    return {
        "filter_purpose": filter_purpose,
        "totals": totals,
        "breakdown": breakdown
    }
