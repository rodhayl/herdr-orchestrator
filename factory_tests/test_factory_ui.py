"""Provider-free tests for the Factory Control UI read model and HTTP facade."""

from __future__ import annotations

import http.client
import importlib.util
import json
import pathlib
import tempfile
import threading
import time
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "tools" / "factory_ui.py"
spec = importlib.util.spec_from_file_location("factory_ui_under_test", MODULE_PATH)
factory_ui = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(factory_ui)


class FakeActionRunner:
    def __init__(self):
        self.calls = []

    def resume(self, goal_id):
        self.calls.append(goal_id)
        return {"accepted": True, "goal_id": goal_id, "pid": 4242, "log": ".agy-factory/ui/actions/fake.log"}


class FactoryUITestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.temp.name)
        self.factory_root = root / "factory"
        self.project_root = root / "project"
        self.ui_root = self.factory_root / "ui"
        self.vendor_root = self.factory_root / ".tools" / "ui" / "vendor"
        self.factory_root.mkdir()
        self.project_root.mkdir()
        self.ui_root.mkdir()
        self.vendor_root.mkdir(parents=True)
        (self.ui_root / "index.html").write_text("<!doctype html><title>Factory UI</title>", encoding="utf-8")
        (self.ui_root / "app.js").write_text("console.log('factory-ui');", encoding="utf-8")
        (self.vendor_root / "alpine").mkdir()
        (self.vendor_root / "alpine" / "csp.min.js").write_text("/* vendor */", encoding="utf-8")

        self._write_json(self.factory_root / "factory.json", {"version": "9.0.0"})
        self._write_json(self.factory_root / "context_policy.json", {
            "schema_version": "8.0.0",
            "roles": {"task": {"soft_budget_bytes": 4096, "hard_budget_bytes": 12288}},
        })
        self._write_json(self.factory_root / "reasoning_policy.json", {
            "policy_version": "9.0.0", "status": "VALID",
            "escalation_policy": {"max_effort_escalations_per_task": 1},
        })
        self._write_json(self.factory_root / "toolchain.lock.json", {
            "freebuff": {"feasibility_status": "FREEBUFF_HEADLESS_BLOCKED", "notes": "TUI only"},
            "herdr_board": {"compatibility_status": "BLOCKED_EXTERNAL_COMPATIBILITY", "compatibility_notes": "locked baseline"},
        })
        self._write_json(self.factory_root / "harness_profiles.json", {
            "profiles": {
                "agy-backend-medium": {
                    "harness": "agy", "model": "gemini-3.8-flash", "effort": "medium", "enabled": True,
                    "certification": {"status": "REAL_PROVIDER_CERTIFIED"},
                },
                "codex-luna-high": {
                    "harness": "codex", "model": "gpt-5.6-luna", "effort": "high", "enabled": True,
                    "certification": {"status": "AUTH_BLOCKED"},
                },
            }
        })
        self._write_json(self.factory_root / "ui" / "vendor.lock.json", {"schema_version": 1, "packages": []})
        self._write_json(self.project_root / "factory.project.json", {"project_name": "Synthetic Project"})

        runtime = self.project_root / ".agy-factory"
        run_dir = runtime / "runs" / "run-001"
        goal_dir = runtime / "goals" / "goal-001"
        evidence_dir = runtime / "evidence"
        run_dir.mkdir(parents=True)
        goal_dir.mkdir(parents=True)
        evidence_dir.mkdir(parents=True)

        goal_spec_path = goal_dir / "goal-spec.json"
        plan_path = goal_dir / "plan.json"
        self._write_json(goal_spec_path, {
            "goal_id": "goal-001", "title": "Synthetic Goal",
            "acceptance_criteria": [
                {"id": "R1", "title": "Build feature", "description": "Feature works", "provenance": "USER_EXPLICIT"}
            ],
        })
        self._write_json(plan_path, {"plan_id": "plan-001", "tasks": [{"task_id": "task_run"}]})
        self._write_json(goal_dir / "state.json", {
            "goal_id": "goal-001", "phase": "EXECUTING", "run_id": "run-001",
            "raw_goal": "# Synthetic Goal\nBuild a feature.",
            "goal_spec_path": str(goal_spec_path), "approved_plan_path": str(plan_path),
            "plan_revision_count": 0, "remediation_round_count": 0,
            "created_at": "2026-09-26T10:00:00+00:00", "updated_at": "2026-09-26T10:01:00+00:00",
        })

        manifest = {
            "factory_version": "9.0.0", "run_id": "run-001", "goal_id": "goal-001",
            "plan_id": "plan-001", "plan_name": "Synthetic Plan", "run_state": "RUNNING",
            "start_time": "2026-09-26T10:00:00+00:00", "contains_mock_execution": False,
            "tasks": {
                "task_backlog": {"task_id": "task_backlog", "canonical_state": "PENDING", "attempts": []},
                "task_run": {
                    "task_id": "task_run", "name": "Implement feature", "canonical_state": "RUNNING",
                    "profile_id": "agy-backend-medium", "harness": "agy", "model": "gemini-3.8-flash", "effort": "medium",
                    "attempts_count": 1, "current_attempt_id": 1,
                    "attempts": [{
                        "attempt_id": 1, "status": "RUNNING", "state": "RUNNING", "profile_id": "agy-backend-medium",
                        "harness": "agy", "model": "gemini-3.8-flash", "effort": "medium", "execution_mode": "REAL",
                        "start_time": "2026-09-26T10:00:10+00:00", "changed_paths": ["src/app.py"],
                    }],
                },
                "task_done": {
                    "task_id": "task_done", "canonical_state": "INTEGRATED", "status": "SUCCESS",
                    "attempts_count": 1, "attempts": [{"attempt_id": 1, "status": "SUCCESS", "state": "INTEGRATED", "execution_mode": "REAL", "commit_hash": "abc123"}],
                },
            },
        }
        self._write_json(run_dir / "manifest.json", manifest)
        (run_dir / "events.jsonl").write_text(
            json.dumps({"timestamp": "2026-09-26T10:00:11+00:00", "event": "TASK_DISPATCHED", "payload": {"task_id": "task_run"}}) + "\n",
            encoding="utf-8",
        )
        (evidence_dir / "telemetry.jsonl").write_text(
            json.dumps({
                "run_id": "run-001", "task_id": "task_run", "attempt_id": 1,
                "provider_input_tokens": 1000, "provider_cached_input_tokens": 500,
                "provider_reasoning_tokens": 200, "provider_output_tokens": 100,
                "factory_supplied_bytes": 4096, "duration_ms": 1200,
            }) + "\n",
            encoding="utf-8",
        )
        self.action_runner = FakeActionRunner()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")

    def test_read_model_snapshot_projects_canonical_state_without_duplication(self):
        model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        snapshot = model.snapshot()
        self.assertEqual(snapshot["factory"]["version"], "9.0.0")
        self.assertEqual(snapshot["factory"]["project_name"], "Synthetic Project")
        self.assertEqual(snapshot["selected_run_id"], "run-001")
        self.assertEqual(snapshot["board"]["counts"]["BACKLOG"], 1)
        self.assertEqual(snapshot["board"]["counts"]["RUNNING"], 1)
        self.assertEqual(snapshot["board"]["counts"]["DONE"], 1)
        self.assertEqual(snapshot["metrics"]["input_tokens"], 1000)
        self.assertEqual(snapshot["metrics"]["reasoning_tokens"], 200)
        statuses = {item["id"]: item["status"] for item in snapshot["providers"]}
        self.assertEqual(statuses["agy"], "REAL_PROVIDER_CERTIFIED")
        self.assertEqual(statuses["codex"], "AUTH_BLOCKED")
        self.assertEqual(statuses["freebuff"], "FREEBUFF_HEADLESS_BLOCKED")

    def test_snapshot_revision_ignores_generated_at(self):
        model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        first = model.snapshot()
        time.sleep(0.002)
        second = model.snapshot()
        self.assertNotEqual(first["generated_at"], second["generated_at"])
        self.assertEqual(first["revision"], second["revision"])

    def test_detail_views_are_bounded_and_traceable(self):
        model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        goal = model.goal_detail("goal-001")
        self.assertEqual(goal["goal_spec"]["acceptance_criteria"][0]["id"], "R1")
        run = model.run_detail("run-001")
        self.assertEqual(run["run"]["run_id"], "run-001")
        task = model.task_detail("run-001", "task_run")
        self.assertEqual(task["task"]["execution_mode"], "REAL")
        self.assertEqual(task["task"]["changed_paths"], ["src/app.py"])
        self.assertEqual(task["events"][0]["event"], "TASK_DISPATCHED")
        self.assertEqual(task["telemetry"][0]["factory_supplied_bytes"], 4096)

    def _start_server(self):
        server = factory_ui.make_server(
            self.project_root, "127.0.0.1", 0,
            factory_root=self.factory_root,
            ui_root=self.ui_root,
            vendor_root=self.vendor_root,
            action_runner=self.action_runner,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server

    def _request(self, server, method, path, *, body=None, headers=None):
        host, port = server.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), raw
        finally:
            conn.close()

    def test_http_snapshot_etag_security_headers_and_304(self):
        server = self._start_server()
        status, headers, raw = self._request(server, "GET", "/api/v1/snapshot")
        self.assertEqual(status, 200)
        payload = json.loads(raw)
        self.assertEqual(payload["selected_run_id"], "run-001")
        self.assertIn("Content-Security-Policy", headers)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        etag = headers.get("ETag")
        self.assertTrue(etag)

        status2, headers2, raw2 = self._request(server, "GET", "/api/v1/snapshot", headers={"If-None-Match": etag})
        self.assertEqual(status2, 304)
        self.assertEqual(raw2, b"")
        self.assertEqual(headers2.get("ETag"), etag)

    def test_http_static_assets_health_and_traversal_guard(self):
        server = self._start_server()
        self.assertEqual(self._request(server, "GET", "/health")[0], 200)
        self.assertEqual(self._request(server, "GET", "/health", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self._request(server, "GET", "/")[0], 200)
        self.assertEqual(self._request(server, "GET", "/assets/app.js")[0], 200)
        self.assertEqual(self._request(server, "GET", "/vendor/alpine/csp.min.js")[0], 200)
        traversal_status = self._request(server, "GET", "/assets/%2e%2e/factory.json")[0]
        self.assertIn(traversal_status, {403, 404})

    def test_resume_action_requires_same_origin_and_delegates_only_existing_operation(self):
        server = self._start_server()
        host, port = server.server_address[:2]
        common = {"Content-Type": "application/json"}
        bad_headers = dict(common, Origin="https://evil.example")
        self.assertEqual(self._request(server, "POST", "/api/v1/goals/goal-001/resume", body="{}", headers=bad_headers)[0], 403)
        self.assertEqual(self.action_runner.calls, [])

        good_headers = dict(common, Origin=f"http://{host}:{port}")
        status, _, raw = self._request(server, "POST", "/api/v1/goals/goal-001/resume", body="{}", headers=good_headers)
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(raw)["pid"], 4242)
        self.assertEqual(self.action_runner.calls, ["goal-001"])

    def test_loopback_only_policy(self):
        factory_ui._require_loopback("127.0.0.1")
        factory_ui._require_loopback("::1")
        with self.assertRaises(SystemExit):
            factory_ui._require_loopback("0.0.0.0")

    def test_invalid_identifiers_fail_closed(self):
        model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        with self.assertRaises(factory_ui.UIDataError):
            model.run_detail("../secret")
        with self.assertRaises(factory_ui.UIDataError):
            model.goal_detail("goal/../../bad")


if __name__ == "__main__":
    unittest.main()
