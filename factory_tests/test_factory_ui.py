"""Provider-free tests for the Herdr Orchestrator UI read model and HTTP facade."""

from __future__ import annotations

import contextlib
import http.client
import io
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
                "opencode-free": {
                    "harness": "opencode", "model": "openrouter/free", "effort": "free", "enabled": True,
                    "certification": {"status": "REAL_PROVIDER_CERTIFIED"},
                },
                "opencode-gemini": {
                    "harness": "opencode", "model": "google/gemini-3.8-flash", "effort": "high", "enabled": True,
                    "certification": {"status": "PROFILE_UNAVAILABLE"},
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
                {"id": "R1", "title": "Build feature", "description": "Feature works", "provenance": "USER_EXPLICIT"},
                {"id": "R2", "title": "Test feature", "description": "Feature is validated", "provenance": "USER_EXPLICIT"},
            ],
        })
        self._write_json(plan_path, {
            "plan_id": "plan-001",
            "tasks": [{
                "task_id": "task_run",
                "dependencies": [],
                "satisfies": ["R1", "R2"],
                "allowed_paths": ["src/**", "tests/**"],
                "validations": [["python3", "-m", "unittest", "discover"]],
                "prompt": "SECRET_TASK_PROMPT",
            }],
        })
        self._write_json(goal_dir / "state.json", {
            "goal_id": "goal-001", "phase": "EXECUTING", "run_id": "run-001",
            "raw_goal": "# Synthetic Goal\nBuild a feature.",
            "goal_spec_path": str(goal_spec_path), "approved_plan_path": str(plan_path),
            "plan_revision_count": 0, "remediation_round_count": 0,
            "validation_results": [{"task_id": "task_run", "name": "unit", "command": ["python3", "-m", "unittest", "discover"], "passed": True}],
            "audit_results": [{"verdict": "ACCEPTED", "critical": 0, "major": 0}],
            "created_at": "2026-09-26T10:00:00+00:00", "updated_at": "2026-09-26T10:01:00+00:00",
        })

        manifest = {
            "factory_version": "9.0.0", "run_id": "run-001", "goal_id": "goal-001",
            "plan_id": "plan-001", "plan_name": "Synthetic Plan", "plan_path": str(plan_path), "run_state": "RUNNING",
            "start_time": "2026-09-26T10:00:00+00:00", "contains_mock_execution": False,
            "validation_results": [{"task_id": "task_run", "name": "unit", "command": ["python3", "-m", "unittest", "discover"], "passed": True}],
            "final_audit": {"verdict": "ACCEPTED", "critical": 0, "major": 0},
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
        context_packet = {
            "schema_version": "8.0.0",
            "packet_id": "ctx-task-task_run-att1-test",
            "packet_role": "task",
            "goal_id": "goal-001",
            "run_id": "run-001",
            "task_id": "task_run",
            "attempt_id": 1,
            "requirements": [
                {"id": "R1", "title": "Build feature", "description": "Feature works", "provenance": "USER_EXPLICIT"},
                {"id": "R2", "title": "Test feature", "description": "Feature is validated", "provenance": "USER_EXPLICIT"},
            ],
            "required_anchors": [
                {"anchor_id": "r1", "type": "requirement", "source": "goal", "source_hash": "aaa", "content": "Feature works", "required": True},
                {"anchor_id": "path", "type": "allowed_path", "source": "plan", "source_hash": "bbb", "content": "src/**", "required": True},
            ],
            "included_files": [{"path": "src/app.py", "reason": "implementation target", "byte_count": 99, "source_hash": "ccc", "inline_content": "SECRET_INLINE_CONTENT"}],
            "referenced_files": ["src/app.py", "tests/test_app.py"],
            "handoffs": [{"producer_task_id": "spec"}],
            "validations": [["python3", "-m", "unittest", "discover"]],
            "source_hashes": {"goal-spec.json": "111", "plan.json": "222"},
            "budget": {"soft_budget_bytes": 4096, "hard_budget_bytes": 12288, "original_bytes": 5000, "final_bytes": 3000, "was_pruned": True},
            "packet_bytes": 3000,
            "packet_hash": "packet-hash",
            "compiler_version": "8.0.0",
            "rendered_tail": "SECRET_RENDERED_PROMPT",
        }
        self._write_json(run_dir / "workers" / "task_run" / "att-1" / "context_packet.json", context_packet)

        completed_dir = runtime / "runs" / "run-999"
        completed_dir.mkdir(parents=True)
        self._write_json(completed_dir / "manifest.json", {
            "run_id": "run-999", "run_state": "COMPLETED", "start_time": "2026-09-26T11:00:00+00:00", "end_time": "2026-09-26T11:01:00+00:00", "tasks": {}
        })

        (run_dir / "events.jsonl").write_text(
            json.dumps({"timestamp": "2026-09-26T10:00:11+00:00", "event": "TASK_DISPATCHED", "payload": {"task_id": "task_run", "prompt": "SECRET_EVENT_PAYLOAD"}}) + "\n",
            encoding="utf-8",
        )
        telemetry_rows = [
            {"run_id": f"noise-{index}", "task_id": "noise", "attempt_id": 1, "duration_ms": 1}
            for index in range(650)
        ]
        telemetry_rows.insert(10, {
            "run_id": "run-001", "task_id": "task_run", "attempt_id": 1,
            "provider_input_tokens": 1000, "provider_cached_input_tokens": 500,
            "provider_reasoning_tokens": 200, "provider_output_tokens": 100,
            "duration_ms": 1200, "raw_output": "SECRET_TELEMETRY_PAYLOAD",
        })
        (evidence_dir / "telemetry.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in telemetry_rows), encoding="utf-8"
        )
        (evidence_dir / "context-telemetry.jsonl").write_text(
            json.dumps({
                "run_id": "run-001", "task_id": "task_run", "attempt_id": 1,
                "context_packet_id": "ctx-task-task_run-att1-test",
                "factory_supplied_bytes": 4096, "required_anchor_recall": 1.0,
            }) + "\n", encoding="utf-8"
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
        self.assertEqual(snapshot["metrics"]["context_bytes"], 4096)
        self.assertEqual(snapshot["metrics"]["attempts"], 2)
        statuses = {item["id"]: item["status"] for item in snapshot["providers"]}
        self.assertEqual(statuses["agy"], "REAL_PROVIDER_CERTIFIED")
        self.assertEqual(statuses["codex"], "AUTH_BLOCKED")
        self.assertEqual(statuses["opencode"], "PARTIAL")
        self.assertEqual(statuses["freebuff"], "FREEBUFF_HEADLESS_BLOCKED")

    def test_system_detail_is_allowlisted_and_does_not_expose_profile_commands(self):
        model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        system = model.system_detail()
        serialized = json.dumps(system)
        self.assertNotIn("profile_home", serialized)
        self.assertNotIn("command", serialized)
        self.assertNotIn("notes", serialized)
        self.assertEqual(system["profiles"]["agy-backend-medium"]["model"], "gemini-3.8-flash")
        self.assertEqual(system["reasoning_policy"]["policy_version"], "9.0.0")
        self.assertEqual(system["context_policy"]["roles"]["task"]["soft_budget_bytes"], 4096)

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
        self.assertEqual(run["goal_state"]["remediation_round_count"], 0)
        self.assertEqual(run["plan"]["tasks"][0]["task_id"], "task_run")
        task = model.task_detail("run-001", "task_run")
        self.assertEqual(task["task"]["execution_mode"], "REAL")
        self.assertEqual(task["task"]["changed_paths"], ["src/app.py"])
        self.assertEqual(task["events"][0]["event"], "TASK_DISPATCHED")
        self.assertEqual(task["telemetry"][0]["provider_input_tokens"], 1000)
        self.assertEqual([item["id"] for item in task["requirements"]], ["R1", "R2"])
        self.assertEqual(task["context"]["packet_id"], "ctx-task-task_run-att1-test")
        self.assertEqual(task["context"]["packet_bytes"], 3000)
        self.assertEqual(task["context"]["packet_role"], "task")
        self.assertEqual(task["context"]["compiler_version"], "8.0.0")
        self.assertEqual(task["context"]["budget"]["final_bytes"], 3000)
        self.assertEqual(
            set(task["context"]["budget"]),
            {"soft_budget_bytes", "hard_budget_bytes", "original_bytes", "final_bytes", "was_pruned"},
        )
        self.assertNotIn("validations", task["context"])
        self.assertEqual(task["context"]["included_files"][0]["path"], "src/app.py")
        self.assertNotIn("inline_content", task["context"]["included_files"][0])
        self.assertEqual(task["context"]["required_anchor_recall"], 1.0)
        self.assertEqual(task["context"]["required_anchor_count"], 2)
        self.assertEqual(task["validation"]["commands"][0][:3], ["python3", "-m", "unittest"])
        self.assertTrue(task["validation"]["results"][0]["passed"])
        self.assertEqual(task["git"]["changed_paths"], ["src/app.py"])
        serialized = json.dumps(task)
        self.assertNotIn("SECRET_RENDERED_PROMPT", serialized)
        self.assertNotIn("SECRET_INLINE_CONTENT", serialized)
        self.assertNotIn("SECRET_EVENT_PAYLOAD", serialized)
        self.assertNotIn("SECRET_TELEMETRY_PAYLOAD", serialized)
        self.assertNotIn("source_hashes", serialized)
        self.assertNotIn("source_hash", serialized)
        self.assertNotIn("SECRET_TASK_PROMPT", json.dumps(goal))
        self.assertNotIn("SECRET_TASK_PROMPT", json.dumps(run))
        self.assertEqual(run["traceability"][0]["outcome"], "IN_PROGRESS")
        self.assertEqual(run["final_audit"]["verdict"], "ACCEPTED")

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

    def test_http_rejects_transfer_encoding_and_oversized_bodies(self):
        server = self._start_server()
        host, port = server.server_address[:2]
        origin = f"http://{host}:{port}"

        chunked_headers = {
            "Content-Type": "application/json",
            "Origin": origin,
            "Transfer-Encoding": "chunked",
        }
        status, _, raw = self._request(
            server, "POST", "/api/v1/goals/goal-001/resume", body="{}", headers=chunked_headers
        )
        self.assertEqual(status, 400)
        self.assertIn(b"Transfer-Encoding", raw)
        self.assertEqual(self.action_runner.calls, [])

        oversized_headers = {
            "Content-Type": "application/json",
            "Origin": origin,
            "Content-Length": str(factory_ui.MAX_REQUEST_BODY + 1),
        }
        status, _, raw = self._request(
            server, "POST", "/api/v1/goals/goal-001/resume", body="", headers=oversized_headers
        )
        self.assertEqual(status, 400)
        self.assertIn(b"too large", raw)
        self.assertEqual(self.action_runner.calls, [])

    def test_frontend_expressions_remain_alpine_csp_compatible(self):
        source = factory_ui.FACTORY_ROOT / "ui" / "index.html"
        text = source.read_text(encoding="utf-8")
        # Alpine CSP explicitly rejects arrow functions, template literals, HTML injection,
        # and access to browser globals from inline expressions. Keep complex logic in app.js.
        self.assertNotIn("=>", text)
        self.assertNotIn("x-html", text)
        self.assertNotRegex(text, r'x-[^=]+="[^"]*`')
        for forbidden in ("window.", "document.", "console.", "Math.", "JSON."):
            self.assertNotIn(forbidden, text)

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


    def test_newer_completed_run_does_not_replace_active_run(self):
        model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        snapshot = model.snapshot()
        self.assertEqual(snapshot["runs"][0]["run_id"], "run-999")
        self.assertEqual(snapshot["selected_run_id"], "run-001")
        self.assertTrue(snapshot["factory"]["active"])

    def test_filter_first_telemetry_keeps_older_selected_run_metrics(self):
        model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        rows = model._telemetry("run-001", "task_run", limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider_input_tokens"], 1000)

    def test_duration_fallback_sums_all_task_durations(self):
        model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        result = model._usage_summary("missing-run", [{"duration_ms": 100, "attempts_count": 1}, {"duration_ms": 250, "attempts_count": 2}])
        self.assertEqual(result["duration_ms"], 350.0)
        self.assertEqual(result["attempts"], 3)

    def test_cancelled_goals_are_terminal_and_not_resumable(self):
        model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        summary = model._goal_summary({"goal_id": "goal-cancelled", "phase": "CANCELLED"})
        self.assertFalse(summary["resumable"])

    def test_runtime_symlink_escape_is_skipped_and_direct_access_fails_closed(self):
        outside = pathlib.Path(self.temp.name) / "outside-run"
        outside.mkdir()
        self._write_json(outside / "manifest.json", {"run_id": "run-escape", "run_state": "RUNNING", "tasks": {}})
        link = self.project_root / ".agy-factory" / "runs" / "run-escape"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        self.assertNotIn("run-escape", [item["run_id"] for item in model.snapshot()["runs"]])
        with self.assertRaises(factory_ui.UIDataError):
            model.run_detail("run-escape")

    def test_http_rejects_userinfo_host_https_origin_and_hides_internal_errors(self):
        server = self._start_server()
        host, port = server.server_address[:2]
        self.assertEqual(self._request(server, "GET", "/health", headers={"Host": f"evil@{host}:{port}"})[0], 403)
        bad_origin = {"Content-Type": "application/json", "Origin": f"https://{host}:{port}"}
        self.assertEqual(self._request(server, "POST", "/api/v1/goals/goal-001/resume", body="{}", headers=bad_origin)[0], 403)

        original = server.read_model.snapshot
        def fail_snapshot():
            raise RuntimeError("TOP SECRET /tmp/private")
        server.read_model.snapshot = fail_snapshot
        captured = io.StringIO()
        try:
            with contextlib.redirect_stderr(captured):
                status, _, raw = self._request(server, "GET", "/api/v1/snapshot")
        finally:
            server.read_model.snapshot = original
        self.assertEqual(status, 500)
        self.assertNotIn(b"TOP SECRET", raw)
        self.assertNotIn("TOP SECRET", captured.getvalue())
        self.assertNotIn("/tmp/private", captured.getvalue())
        self.assertIn("RuntimeError", captured.getvalue())
        self.assertEqual(json.loads(raw)["error"], "Internal server error")

    def test_frontend_contains_original_plan_surfaces_without_drag_drop(self):
        index = (self.factory_root / "ui" / "index.html")
        # The synthetic ui_root is intentionally tiny; inspect the real source beside the module instead.
        source = factory_ui.FACTORY_ROOT / "ui" / "index.html"
        text = source.read_text(encoding="utf-8")
        for tab in ("Requirements", "Context", "Validation", "Git", "Events"):
            self.assertIn(f'>{tab}<', text)
        self.assertIn("Requirement traceability", text)
        self.assertIn("Certified toolchain", text)
        for marker in ("RETRY", "ESCALATED", "Dependencies", "Effort source", "GoalSpec criteria", "Remediation rounds", "Included files", "goalAuditVerdict"):
            self.assertIn(marker, text)
        self.assertNotIn("draggable=", text)
        self.assertNotIn("ondrag", text.lower())
        self.assertNotIn("x-html", text)

    def test_usage_summary_preserves_null_for_incomplete_metrics(self):
        read_model = factory_ui.FactoryReadModel(self.project_root, self.factory_root)
        run_id = "test-incomplete-run"
        run_dir = self.project_root / ".agy-factory" / "runs" / run_id
        run_dir.mkdir(parents=True)
        metrics = [
            {"task_id": "t1", "attempt_id": 1, "provider_input_tokens": 100, "provider_cached_input_tokens": 20, "provider_output_tokens": 50, "provider_reasoning_tokens": 30, "duration_ms": 1500.0},
            {"task_id": "t2", "attempt_id": 1, "provider_input_tokens": None, "provider_cached_input_tokens": None, "provider_output_tokens": None, "provider_reasoning_tokens": None, "duration_ms": None}
        ]
        (run_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        tasks = [{"task_id": "t1", "attempts_count": 1}, {"task_id": "t2", "attempts_count": 1}]
        summary = read_model._usage_summary(run_id, tasks)
        self.assertIsNone(summary["input_tokens"])
        self.assertIsNone(summary["cached_input_tokens"])
        self.assertIsNone(summary["reasoning_tokens"])
        self.assertIsNone(summary["output_tokens"])
        self.assertIsNone(summary["duration_ms"])
        self.assertEqual(summary["attempts"], 2)


if __name__ == "__main__":
    unittest.main()
