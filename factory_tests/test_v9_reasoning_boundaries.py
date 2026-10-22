"""Provider-free behavioral regressions for reasoning boundaries and usage truth."""

import copy
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from tools.reasoning import (
    CERTIFIED_MODEL_LADDERS,
    MalformedReasoningPolicyError,
    ReasoningPolicy,
    ReasoningPolicyConflictError,
    calculate_policy_provenance_hashes,
    summarize_usage_by_dimensions,
    verify_policy_provenance,
)


def policy_data():
    return {
        "schema_version": "9.0.0",
        "policy_version": "9.0.0",
        "model_ladders": copy.deepcopy(CERTIFIED_MODEL_LADDERS),
        "role_policy": {
            "worker": {
                "initial_effort_by_class": {"routine": "low", "standard": "medium", "deep": "high"},
                "escalation_ceiling_by_class": {"routine": "medium", "standard": "high", "deep": "high"},
            },
            "planner": {"initial_effort": "medium", "escalation_ceiling": "high"},
        },
        "task_policy": {},
        "escalation_policy": {"enabled": True, "max_effort_escalations_per_task": 1},
    }


class ProvenanceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.paths = {
            "context_policy_hash": "context_policy.json",
            "toolchain_lock_hash": "toolchain.lock.json",
            "harness_profiles_hash": "harness_profiles.json",
            "calibration_evidence_hash": "certification/v9/calibration-runs.jsonl",
        }
        for path in self.paths.values():
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("{}\n", encoding="utf-8")
        self.policy = {"provenance_hashes": calculate_policy_provenance_hashes(self.root)}

    def test_matching_files_pass(self):
        self.assertEqual(verify_policy_provenance(self.policy, self.root), (True, []))

    def test_each_missing_recorded_hash_fails(self):
        for key in self.paths:
            with self.subTest(key=key):
                data = copy.deepcopy(self.policy)
                del data["provenance_hashes"][key]
                valid, reasons = verify_policy_provenance(data, self.root)
                self.assertFalse(valid)
                self.assertTrue(any(key in reason for reason in reasons))

    def test_each_missing_file_fails(self):
        for key, path in self.paths.items():
            with self.subTest(key=key):
                file = self.root / path
                file.unlink()
                try:
                    valid, reasons = verify_policy_provenance(self.policy, self.root)
                    self.assertFalse(valid)
                    self.assertTrue(any(key in reason for reason in reasons))
                finally:
                    file.write_text("{}\n", encoding="utf-8")

    def test_missing_calibration_is_not_synthetic_evidence(self):
        (self.root / self.paths["calibration_evidence_hash"]).unlink()
        self.assertFalse(calculate_policy_provenance_hashes(self.root).get("calibration_evidence_hash"))

    def test_missing_or_malformed_provenance_fails(self):
        for data in ({}, {"provenance_hashes": {}}, {"provenance_hashes": None}, {"provenance_hashes": []}):
            with self.subTest(data=data):
                self.assertFalse(verify_policy_provenance(data, self.root)[0])

    def test_unreadable_evidence_fails_closed(self):
        with mock.patch("tools.reasoning.sha256_file", side_effect=PermissionError("unreadable")):
            valid, reasons = verify_policy_provenance(self.policy, self.root)
        self.assertFalse(valid)
        self.assertTrue(reasons)

    def test_malformed_recorded_hash_fails(self):
        for value in (None, False, 12, "", "x" * 64, "0" * 32):
            with self.subTest(value=value):
                data = copy.deepcopy(self.policy)
                data["provenance_hashes"]["context_policy_hash"] = value
                self.assertFalse(verify_policy_provenance(data, self.root)[0])


class ReasoningBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.data = policy_data()
        self.policy = ReasoningPolicy(self.data)

    def escalate(self, **kwargs):
        args = dict(current_effort="low", model_family="gemini-3.8-flash",
                    failure_category="DETERMINISTIC_TEST_FAILED", attempt_id=1)
        args.update(kwargs)
        return self.policy.evaluate_escalation(**args)

    def test_valid_initial_resolution_and_escalation_still_work(self):
        for execution_class, effort in (("routine", "low"), ("standard", "medium"), ("deep", "high")):
            with self.subTest(execution_class=execution_class):
                self.assertEqual(self.policy.resolve_initial_effort("worker", "backend", execution_class).selected_effort, effort)
        self.assertEqual(self.escalate()[0], "medium")
        self.assertIsNone(self.escalate(attempt_id=2)[0])

    def test_configured_deny_wins_over_default_eligibility(self):
        self.data["escalation_policy"]["non_eligible_failure_categories"] = ["DETERMINISTIC_TEST_FAILED"]
        policy = ReasoningPolicy(self.data)
        self.assertFalse(policy.is_failure_escalation_eligible("DETERMINISTIC_TEST_FAILED"))
        self.assertNotIn("DETERMINISTIC_TEST_FAILED", policy.explain()["eligible_failures"])

    def test_configured_category_case_is_normalized(self):
        self.data["escalation_policy"]["non_eligible_failure_categories"] = ["deterministic_test_failed"]
        self.assertFalse(ReasoningPolicy(self.data).is_failure_escalation_eligible("DETERMINISTIC_TEST_FAILED"))

    def test_invalid_project_attempt_limits_never_grant_escalation(self):
        for limit in (None, True, 0, -1, "2", 1.5):
            with self.subTest(limit=limit):
                self.assertIsNone(self.escalate(project_policy={"limits": {"max_task_attempts": limit}})[0])
        self.assertIsNone(self.escalate(escalation_ceiling="")[0])

    def test_explicit_empty_allowlist_disables_escalation_categories(self):
        self.data["escalation_policy"]["eligible_failure_categories"] = []
        self.assertFalse(ReasoningPolicy(self.data).is_failure_escalation_eligible("DETERMINISTIC_TEST_FAILED"))

    def test_guardrails_cannot_be_enabled_by_configuration(self):
        self.data["escalation_policy"]["eligible_failure_categories"] = ["PATH_VALIDATION_FAILED", "AUTH_BLOCKED"]
        policy = ReasoningPolicy(self.data)
        for category in self.data["escalation_policy"]["eligible_failure_categories"]:
            self.assertFalse(policy.is_failure_escalation_eligible(category))

    def test_malformed_attempts_never_grant_escalation(self):
        for attempt in (None, False, True, 0, -1, 1.5, "1", "bad", float("inf"), float("nan")):
            with self.subTest(attempt=attempt):
                self.assertIsNone(self.escalate(attempt_id=attempt)[0])

    def test_project_attempt_limit_is_honored(self):
        for project in ({"limits": {"max_task_attempts": 1}}, SimpleNamespace(limits={"max_task_attempts": 1})):
            with self.subTest(project=project):
                self.assertIsNone(self.escalate(project_policy=project)[0])
        self.assertEqual(self.escalate(project_policy={"limits": {"max_task_attempts": 2}})[0], "medium")

    def test_policy_ceiling_absent_from_ladder_is_not_ignored(self):
        result, reason = self.escalate(current_effort="medium", model_family="qwen3.8-max", escalation_ceiling="high")
        self.assertIsNone(result)
        self.assertIn("CEILING", reason)

    def test_project_ceiling_absent_from_ladder_is_not_ignored(self):
        result, reason = self.escalate(current_effort="medium", model_family="qwen3.8-max",
                                      escalation_ceiling="xhigh", project_policy={"max_effort": "high"})
        self.assertIsNone(result)
        self.assertIn("PROJECT_CEILING", reason)

    def test_single_rung_model_cannot_exceed_project_cap(self):
        with self.assertRaises(ReasoningPolicyConflictError):
            self.policy.resolve_initial_effort("worker", "backend", "deep", "claude-sonnet-4-6", {"max_effort": "medium"})

    def test_unknown_project_cap_fails_closed(self):
        with self.assertRaises(ReasoningPolicyConflictError):
            self.policy.resolve_initial_effort("worker", "backend", "standard", project_policy={"max_effort": "typo"})
        self.assertIsNone(self.escalate(project_policy={"max_effort": "typo"})[0])

    def test_resolved_ceiling_is_a_supported_rung(self):
        result = self.policy.resolve_initial_effort("worker", "backend", "standard", "qwen3.8-max")
        self.assertIn(result.escalation_ceiling, result.ladder)
        self.assertEqual(result.escalation_ceiling, "medium")

    def test_explanation_uses_the_resolved_role_ceiling(self):
        self.data["role_policy"]["planner"] = {"initial_effort": "low", "escalation_ceiling": "low"}
        result = ReasoningPolicy(self.data).explain(role="planner")
        self.assertEqual(result["escalation_ceiling"], "low")
        self.assertFalse(result["escalation_eligible"])

    def test_unknown_model_has_no_fabricated_ladder(self):
        with self.assertRaises(ReasoningPolicyConflictError):
            self.policy.get_ladder("not-configured")

    def test_known_model_spellings_and_exact_names(self):
        for name in ("gemini-3.8-flash", "google/gemini-3.8-flash", "gemini-3.8-flash-high"):
            self.assertEqual(self.policy.get_ladder(name), ["low", "medium", "high"])
        self.data["model_ladders"]["custom-low-latency"] = ["low", "high"]
        policy = ReasoningPolicy(self.data)
        self.assertEqual(policy.get_ladder("custom-low-latency"), ["low", "high"])
        self.assertEqual(policy.resolve_initial_effort("worker", "backend", "routine", "custom-low-latency").model_family,
                         "custom-low-latency")

    def test_invalid_ladders_raise_policy_error(self):
        for ladder in ([], ["high", "low"], ["low", "low"], ["low", {}], [True], ["unknown"]):
            with self.subTest(ladder=ladder):
                data = policy_data()
                data["model_ladders"]["gemini-3.8-flash"] = ladder
                with self.assertRaises(MalformedReasoningPolicyError):
                    ReasoningPolicy(data)

    def test_invalid_policy_sections_raise_policy_error(self):
        for key in ("model_ladders", "role_policy", "task_policy", "escalation_policy"):
            for value in (None, [], "invalid"):
                with self.subTest(key=key, value=value):
                    data = policy_data()
                    data[key] = value
                    with self.assertRaises(MalformedReasoningPolicyError):
                        ReasoningPolicy(data)

    def test_invalid_escalation_config_is_not_coerced(self):
        for key, value in (("enabled", "false"), ("max_effort_escalations_per_task", True),
                           ("eligible_failure_categories", "DETERMINISTIC_TEST_FAILED"),
                           ("non_eligible_failure_categories", [None])):
            with self.subTest(key=key, value=value):
                data = policy_data()
                data["escalation_policy"][key] = value
                with self.assertRaises(MalformedReasoningPolicyError):
                    ReasoningPolicy(data)


class UsageTruthTests(unittest.TestCase):
    token_fields = ("provider_input_tokens", "provider_cached_input_tokens", "provider_reasoning_tokens", "provider_output_tokens")

    def test_missing_metrics_remain_unknown(self):
        summary = summarize_usage_by_dimensions([{"status": "FAILED"}])
        for aggregate in (summary["totals"], summary["breakdown"][0]):
            for field in (*self.token_fields, "provider_credits_or_units", "total_duration_ms", "avg_duration_ms"):
                with self.subTest(field=field):
                    self.assertIsNone(aggregate[field])

    def test_partial_measurements_are_not_complete_totals(self):
        for values in ((7, None), (None, 7)):
            with self.subTest(values=values):
                records = [{"model": str(index), "provider_input_tokens": value} for index, value in enumerate(values)]
                summary = summarize_usage_by_dimensions(records)
                self.assertIsNone(summary["totals"]["provider_input_tokens"])
                self.assertEqual([g["provider_input_tokens"] for g in summary["breakdown"]], list(values))

    def test_reported_zero_is_preserved(self):
        record = {field: 0 for field in self.token_fields}
        record.update(provider_credits_or_units=0, duration_ms=0, total_model_duration_ms=99)
        summary = summarize_usage_by_dimensions([record])
        for field in (*self.token_fields, "provider_credits_or_units", "total_duration_ms", "avg_duration_ms"):
            self.assertEqual(summary["totals"][field], 0, field)

    def test_invalid_tokens_are_unknown_not_truncated_or_crashing(self):
        for value in (-1, True, False, 1.5, "2", float("nan"), float("inf")):
            for field in self.token_fields:
                with self.subTest(value=value, field=field):
                    summary = summarize_usage_by_dimensions([{field: value}])
                    self.assertIsNone(summary["totals"][field])
                    json.dumps(summary, allow_nan=False)

    def test_duration_and_credit_validation(self):
        for value in (-1, True, "bad", float("nan"), float("inf")):
            with self.subTest(value=value):
                summary = summarize_usage_by_dimensions([{"duration_ms": value, "provider_credits_or_units": value}])
                self.assertIsNone(summary["totals"]["total_duration_ms"])
                self.assertIsNone(summary["totals"]["provider_credits_or_units"])
                json.dumps(summary, allow_nan=False)

    def test_complete_measurements_keep_exact_totals_and_filtering(self):
        records = [
            {"execution_purpose": "PRODUCTION", "provider_input_tokens": 4, "provider_credits_or_units": 0.5, "duration_ms": 2},
            {"execution_purpose": "PRODUCTION", "provider_input_tokens": 6, "provider_credits_or_units": 0.25, "total_model_duration_ms": 4},
            {"execution_purpose": "CALIBRATION", "provider_input_tokens": None},
        ]
        summary = summarize_usage_by_dimensions(records, filter_purpose="PRODUCTION")
        self.assertEqual(summary["totals"]["provider_input_tokens"], 10)
        self.assertEqual(summary["totals"]["provider_credits_or_units"], 0.75)
        self.assertEqual(summary["totals"]["avg_duration_ms"], 3)
        self.assertEqual(summary["totals"]["calls"], 2)

    def test_measurement_overflow_stays_json_safe(self):
        summary = summarize_usage_by_dimensions([{"duration_ms": 1e308}, {"duration_ms": 1e308}])
        self.assertIsNone(summary["totals"]["total_duration_ms"])
        json.dumps(summary, allow_nan=False)

    def test_inputs_are_not_mutated(self):
        records = [{"duration_ms": 1, "provider_output_tokens": None}]
        original = copy.deepcopy(records)
        summarize_usage_by_dimensions(records)
        self.assertEqual(records, original)


if __name__ == "__main__":
    unittest.main()
