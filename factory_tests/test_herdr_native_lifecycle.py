#!/usr/bin/env python3
"""
factory_tests/test_herdr_native_lifecycle.py

Deterministic contract and regression tests for Herdr native agent lifecycle:
1. Identity and state sequence ordering (session < working < idle/terminal < release, stale sequence rejection)
2. Native waits (immediate done match, timeout, missing pane fail-closed)
3. Lifecycle authority release on all exit paths (normal, non-zero, timeout, blocked, error, cancel)
4. Portable HERDR_BIN_PATH resolution and shell quoting (custom path, spaces, fail-closed)
5. Fail-closed exit evidence verification across adapters (missing, empty, malformed, 0, non-zero)
6. Foreign resource preservation (foreign panes/workspaces never mutated or released)
7. Live host integration with installed Herdr binary
"""

import json
import os
import pathlib
import shlex
import tempfile
import unittest

from tools.factory import (
    HerdrClient,
    ResourceManager,
    AgyAdapter,
    DroidAdapter,
    CodexAdapter,
    ClaudeAdapter,
    OpenCodeAdapter,
    _read_durable_exit_code,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


class FakeHerdrNativeClient:
    """Deterministic in-memory test harness simulating Herdr native agent lifecycle."""

    def __init__(self):
        self.control_plane = {
            "workspace_id": "fake_ws_cp",
            "pane_id": "fake_ws_cp:p1",
            "tab_id": "fake_ws_cp:t1",
            "cwd": "/fake/cwd",
            "herdr_socket": "/fake/herdr.sock"
        }
        self.workspaces = {}
        self.agents = {}
        self.counter = 0
        self.release_calls = []
        self.release_mutations = []
        self.seq_records = {}  # (pane_id, source) -> last_seq

    def create_workspace(self, cwd: str, label: str = None) -> tuple:
        self.counter += 1
        ws_id = f"w_fake_{self.counter}"
        pane_id = f"{ws_id}:p1"
        self.workspaces[ws_id] = {
            "workspace_id": ws_id,
            "root_pane": {"pane_id": pane_id, "workspace_id": ws_id},
            "cwd": cwd,
            "label": label,
            "closed": False
        }
        return ws_id, pane_id

    def close_workspace(self, ws_id: str) -> bool:
        if ws_id in self.workspaces:
            self.workspaces[ws_id]["closed"] = True
            pane_id = self.workspaces[ws_id]["root_pane"]["pane_id"]
            if pane_id in self.agents:
                del self.agents[pane_id]
            return True
        return False

    def run_in_pane(self, pane_id: str, command: str) -> bool:
        auto_state = getattr(self, "auto_transition_on_run", None)
        if auto_state:
            agent_name = self.agents.get(pane_id, {}).get("agent", "agy")
            self.report_agent(pane_id, agent_name, state=auto_state, seq=3)
        return True

    def report_agent(self, pane_id: str, agent: str, state: str, source: str = "factory",
                     seq: int = None, message: str = None, session_id: str = None, session_path: str = None) -> bool:
        ws_id = pane_id.split(":")[0] if ":" in pane_id else ""
        if ws_id not in self.workspaces and pane_id != self.control_plane.get("pane_id"):
            return False

        # Sequence ordering enforcement: stale or equal reports are accepted by CLI but ignored
        key = (pane_id, source)
        if seq is not None:
            last_seq = self.seq_records.get(key)
            if last_seq is not None and seq <= last_seq:
                return True  # Accepted but ignored
            self.seq_records[key] = seq

        herdr_status = "done" if state == "idle" else state
        prev_rev = self.agents.get(pane_id, {}).get("revision", 0)
        prev_session = self.agents.get(pane_id, {}).get("agent_session")

        sess_info = prev_session
        if session_id:
            sess_info = {
                "source": source,
                "agent": agent,
                "kind": "id",
                "value": session_id
            }

        self.agents[pane_id] = {
            "agent": agent,
            "source": source,
            "agent_status": herdr_status,
            "pane_id": pane_id,
            "revision": prev_rev + 1,
            "state_change_seq": seq or (prev_rev + 1),
            "agent_session": sess_info,
            "message": message,
            "workspace_id": ws_id or "unknown"
        }
        return True

    def report_agent_session(self, pane_id: str, agent: str, session_id: str = None, session_path: str = None,
                             source: str = "factory", seq: int = None) -> bool:
        ws_id = pane_id.split(":")[0] if ":" in pane_id else ""
        if ws_id not in self.workspaces and pane_id != self.control_plane.get("pane_id"):
            return False

        key = (pane_id, source)
        if seq is not None:
            last_seq = self.seq_records.get(key)
            if last_seq is not None and seq <= last_seq:
                return True
            self.seq_records[key] = seq

        ag = self.agents.setdefault(pane_id, {
            "agent": agent,
            "source": source,
            "agent_status": "unknown",
            "pane_id": pane_id,
            "revision": 0,
            "state_change_seq": seq or 0
        })
        ag["agent"] = agent
        ag["source"] = source
        ag["agent_session"] = {
            "source": source,
            "agent": agent,
            "kind": "id",
            "value": session_id or ""
        }
        if seq is not None:
            ag["state_change_seq"] = seq
        return True

    def release_agent(self, pane_id: str, agent: str, source: str = "factory", seq: int = None) -> bool:
        call = {"pane_id": pane_id, "agent": agent, "source": source, "seq": seq}
        self.release_calls.append(call)
        current = self.agents.get(pane_id)
        if not current or current.get("agent") != agent or current.get("source") != source:
            return True

        key = (pane_id, source)
        last_seq = self.seq_records.get(key)
        if seq is None:
            if last_seq is not None:
                return True
        elif last_seq is not None and seq <= last_seq:
            return True
        else:
            self.seq_records[key] = seq

        del self.agents[pane_id]
        self.release_mutations.append(call)
        return True

    def agent_wait(self, target: str, until: list = None, timeout_ms: int = None) -> dict:
        if target not in self.agents:
            return {"matched": False, "status": "not_found", "error": f"agent target {target} not found"}

        ag = self.agents[target]
        status = ag.get("agent_status", "unknown")
        until_set = set(until) if until else {"idle", "done", "blocked"}

        if status in until_set:
            return {
                "matched": True,
                "status": status,
                "agent": dict(ag)
            }

        if timeout_ms and timeout_ms > 0:
            return {"matched": False, "status": "timeout", "error": "timed out waiting for agent status"}

        return {"matched": False, "status": status, "agent": dict(ag)}


class TestHerdrNativeLifecycleContracts(unittest.TestCase):
    """Deterministic contract tests for Herdr native agent lifecycle sequencing and waits."""

    def setUp(self):
        self.client = FakeHerdrNativeClient()
        self.ws_id, self.pane_id = self.client.create_workspace(cwd="/fake/cwd", label="test-pane")

    def test_monotonic_state_sequence_and_stale_rejection(self):
        """
        Verifies:
        session registration (seq=1) < working (seq=2) < idle/done (seq=3) < release (seq=4)
        and proves that stale/equal sequence updates are accepted by CLI but ignored.
        """
        # 1. Session registration at seq=1
        ok = self.client.report_agent_session(self.pane_id, "agy", session_id="sess-1", seq=1)
        self.assertTrue(ok)
        self.assertEqual(self.client.agents[self.pane_id]["state_change_seq"], 1)

        # 2. Transition to working at seq=2
        ok = self.client.report_agent(self.pane_id, "agy", state="working", seq=2)
        self.assertTrue(ok)
        self.assertEqual(self.client.agents[self.pane_id]["agent_status"], "working")
        self.assertEqual(self.client.agents[self.pane_id]["state_change_seq"], 2)

        # 3. Stale sequence reports (seq=2 duplicate, seq=1 older) must be ignored
        ok = self.client.report_agent(self.pane_id, "agy", state="idle", seq=2)
        self.assertTrue(ok)  # Accepted by protocol
        self.assertEqual(self.client.agents[self.pane_id]["agent_status"], "working")  # Ignored

        ok = self.client.report_agent(self.pane_id, "agy", state="idle", seq=1)
        self.assertTrue(ok)
        self.assertEqual(self.client.agents[self.pane_id]["agent_status"], "working")  # Ignored

        # 4. Strictly increasing seq=3 transitions state to idle (done)
        ok = self.client.report_agent(self.pane_id, "agy", state="idle", seq=3)
        self.assertTrue(ok)
        self.assertEqual(self.client.agents[self.pane_id]["agent_status"], "done")
        self.assertEqual(self.client.agents[self.pane_id]["state_change_seq"], 3)

        # 5. seq=4 releases authority
        ok = self.client.release_agent(self.pane_id, "agy", seq=4)
        self.assertTrue(ok)
        self.assertNotIn(self.pane_id, self.client.agents)

    def test_wait_immediate_done_matching(self):
        """Verifies wait matches done immediately when already in terminal state."""
        self.client.report_agent(self.pane_id, "agy", state="idle", seq=1)
        res = self.client.agent_wait(self.pane_id, timeout_ms=5000)
        self.assertTrue(res["matched"])
        self.assertEqual(res["status"], "done")

    def test_wait_timeout_behavior(self):
        """Verifies wait reports timeout when condition is not satisfied."""
        self.client.report_agent(self.pane_id, "agy", state="working", seq=1)
        res = self.client.agent_wait(self.pane_id, until=["idle", "done"], timeout_ms=100)
        self.assertFalse(res["matched"])
        self.assertEqual(res["status"], "timeout")

    def test_wait_missing_agent_fails_closed(self):
        """Verifies wait fails closed on non-existent pane."""
        res = self.client.agent_wait("nonexistent:p99", timeout_ms=100)
        self.assertFalse(res["matched"])
        self.assertEqual(res["status"], "not_found")


class TestHerdrBinPathPortability(unittest.TestCase):
    """Verifies that HERDR_BIN_PATH is portably resolved, shell-quoted, and fails closed."""

    def setUp(self):
        self.orig_env = os.environ.get("HERDR_BIN_PATH")

    def tearDown(self):
        if self.orig_env is not None:
            os.environ["HERDR_BIN_PATH"] = self.orig_env
        else:
            os.environ.pop("HERDR_BIN_PATH", None)

    def test_custom_herdr_bin_path_honored(self):
        """Proves custom HERDR_BIN_PATH is honored by HerdrClient."""
        os.environ["HERDR_BIN_PATH"] = "/opt/custom/herdr"
        client = HerdrClient(PROJECT_ROOT)
        self.assertEqual(client.herdr_bin, "/opt/custom/herdr")

    def test_herdr_bin_path_with_spaces_quoted_safely(self):
        """Proves paths containing spaces are safely quoted for runner shell execution."""
        os.environ["HERDR_BIN_PATH"] = "/opt/custom tools/herdr bin/herdr"
        client = HerdrClient(PROJECT_ROOT)
        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_res_mgr = ResourceManager(client, state_file=pathlib.Path(tmp_dir) / "test_owned.json")
            adapter = AgyAdapter("agy", {"command": "agy", "adapter": "agy"}, client, fake_res_mgr)
            herdr_cmd = adapter._get_herdr_bin_cmd()
            self.assertEqual(herdr_cmd, shlex.quote("/opt/custom tools/herdr bin/herdr"))
            self.assertIn(" ", shlex.split(herdr_cmd)[0])

    def test_missing_unusable_binary_fails_closed(self):
        """Proves an invalid or missing HERDR_BIN_PATH fails closed without falling back to PATH."""
        os.environ["HERDR_BIN_PATH"] = "/opt/nonexistent_bin_dir/herdr_missing_binary"
        client = HerdrClient(PROJECT_ROOT)
        with self.assertRaises(Exception):
            client.run_cmd(["--version"], check=True)


class TestAdapterExitEvidenceFailClosed(unittest.TestCase):
    """
    Verifies that missing, empty, or malformed durable exit evidence fails closed
    across all adapter implementations, and never defaults to exit code 0.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_root = pathlib.Path(self.temp_dir.name)
        self.status_file = self.test_root / "exit_code.txt"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_read_durable_exit_code_missing(self):
        """Proves missing exit_code.txt fails closed with code -1."""
        if self.status_file.exists():
            self.status_file.unlink()
        code, err = _read_durable_exit_code(self.status_file)
        self.assertEqual(code, -1)
        self.assertIn("Missing durable exit evidence", err)

    def test_read_durable_exit_code_empty(self):
        """Proves empty exit_code.txt fails closed with code -1."""
        self.status_file.write_text("   \n", encoding="utf-8")
        code, err = _read_durable_exit_code(self.status_file)
        self.assertEqual(code, -1)
        self.assertIn("Empty durable exit evidence", err)

    def test_read_durable_exit_code_malformed(self):
        """Proves unparseable exit_code.txt fails closed with code -1."""
        self.status_file.write_text("not_an_integer\n", encoding="utf-8")
        code, err = _read_durable_exit_code(self.status_file)
        self.assertEqual(code, -1)
        self.assertIn("Malformed durable exit evidence", err)

    def test_read_durable_exit_code_success(self):
        """Proves valid exit code 0 is parsed correctly."""
        self.status_file.write_text("0\n", encoding="utf-8")
        code, err = _read_durable_exit_code(self.status_file)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_read_durable_exit_code_nonzero(self):
        """Proves non-zero exit code 42 is parsed correctly."""
        self.status_file.write_text("42\n", encoding="utf-8")
        code, err = _read_durable_exit_code(self.status_file)
        self.assertEqual(code, 42)
        self.assertEqual(err, "")

    def test_all_five_adapters_fail_closed_on_missing_exit_evidence(self):
        """
        Exercises the lifecycle execution path across all 5 production adapters:
        AgyAdapter, DroidAdapter, CodexAdapter, ClaudeAdapter, OpenCodeAdapter.
        Proves missing exit evidence yields exit_code -1 and an evidence failure error.
        """
        from unittest.mock import patch

        fake_herdr = FakeHerdrNativeClient()
        fake_herdr.auto_transition_on_run = "idle"
        res_mgr = ResourceManager(fake_herdr, state_file=self.test_root / "res.json")

        adapter_specs = [
            (AgyAdapter, "agy", {"command": "agy", "adapter": "agy"}),
            (DroidAdapter, "droid", {"command": "droid", "adapter": "droid"}),
            (CodexAdapter, "codex", {"command": "codex", "adapter": "codex"}),
            (ClaudeAdapter, "claude", {"command": "claude", "adapter": "claude"}),
            (OpenCodeAdapter, "opencode", {"command": "opencode", "adapter": "opencode"}),
        ]

        worktree = self.test_root / "worktree"
        worktree.mkdir(parents=True, exist_ok=True)
        schema_file = self.test_root / "schema.json"
        schema_file.write_text("{}", encoding="utf-8")

        with patch("tools.factory.probe_harness_auth", return_value={"authenticated": True, "auth_source": "test", "evidence": "mock"}):
            for adapter_cls, name, cfg in adapter_specs:
                adapter = adapter_cls(name, cfg, fake_herdr, res_mgr)
                attempt_dir = self.test_root / f"attempt_{name}"
                attempt_dir.mkdir(parents=True, exist_ok=True)
                prompt_file = attempt_dir / "prompt.md"
                prompt_file.write_text("test task", encoding="utf-8")

                output_file = attempt_dir / "output.json"
                output_file.write_text(json.dumps({"status": "SUCCESS"}), encoding="utf-8")

                # Intentionally omit exit_code.txt
                env_info = adapter.prepare_environment(f"run-{name}", f"task-{name}", 1, worktree)

                res = adapter.execute(
                    run_id=f"run-{name}",
                    task_id=f"task-{name}",
                    attempt_id=1,
                    worktree_path=worktree,
                    prompt_file=prompt_file,
                    schema_file=schema_file,
                    timeout=5,
                    task_attempt_dir=attempt_dir,
                    env_info=env_info,
                    model="test-model"
                )

                self.assertEqual(res["exit_code"], -1, f"Adapter {name} did not fail closed on missing exit evidence")
                self.assertFalse(res["timed_out"])
                self.assertIn("Missing durable exit evidence", res.get("error", ""))



class TestLifecycleAuthorityRelease(unittest.TestCase):
    """
    Verifies that WorkerAdapter releases Herdr lifecycle authority across all exit paths:
    normal completion, non-zero exit, timeout, blocked, error, and explicit cancel.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_root = pathlib.Path(self.temp_dir.name)
        self.worktree = self.test_root / "worktree"
        self.worktree.mkdir(parents=True, exist_ok=True)
        self.attempt_dir = self.test_root / "attempt"
        self.attempt_dir.mkdir(parents=True, exist_ok=True)
        self.fake_herdr = FakeHerdrNativeClient()
        self.res_mgr = ResourceManager(self.fake_herdr, state_file=self.test_root / "res.json")
        self.adapter = AgyAdapter("agy2", {"command": "agy", "adapter": "agy"}, self.fake_herdr, self.res_mgr)

    def _assert_release_accepted(self, pane_id: str):
        calls = [call for call in self.fake_herdr.release_mutations if call["pane_id"] == pane_id]
        self.assertTrue(calls, f"No accepted lifecycle release for {pane_id}")
        self.assertEqual(calls[-1]["agent"], "agy")
        self.assertEqual(calls[-1]["source"], "factory")
        self.assertEqual(calls[-1]["seq"], 4)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _setup_files(self):
        prompt_file = self.attempt_dir / "prompt.md"
        prompt_file.write_text("test prompt", encoding="utf-8")
        schema_file = self.test_root / "schema.json"
        schema_file.write_text("{}", encoding="utf-8")
        output_file = self.attempt_dir / "output.json"
        output_file.write_text(json.dumps({"status": "SUCCESS"}), encoding="utf-8")
        return prompt_file, schema_file

    def test_release_on_normal_completion(self):
        """Proves release_agent is called on normal completion (exit code 0)."""
        prompt_file, schema_file = self._setup_files()
        (self.attempt_dir / "exit_code.txt").write_text("0\n")
        self.fake_herdr.auto_transition_on_run = "idle"
        env_info = self.adapter.prepare_environment("run-1", "task-1", 1, self.worktree)

        res = self.adapter.execute(
            run_id="run-1", task_id="task-1", attempt_id=1, worktree_path=self.worktree,
            prompt_file=prompt_file, schema_file=schema_file, timeout=5,
            task_attempt_dir=self.attempt_dir, env_info=env_info, model="test"
        )
        self.assertEqual(res["exit_code"], 0)
        self._assert_release_accepted(env_info["pane_id"])
        self.assertNotIn(env_info["pane_id"], self.fake_herdr.agents)

    def test_release_on_nonzero_completion(self):
        """Proves release_agent is called on non-zero exit."""
        prompt_file, schema_file = self._setup_files()
        (self.attempt_dir / "exit_code.txt").write_text("42\n")
        self.fake_herdr.auto_transition_on_run = "idle"
        env_info = self.adapter.prepare_environment("run-2", "task-2", 1, self.worktree)

        res = self.adapter.execute(
            run_id="run-2", task_id="task-2", attempt_id=1, worktree_path=self.worktree,
            prompt_file=prompt_file, schema_file=schema_file, timeout=5,
            task_attempt_dir=self.attempt_dir, env_info=env_info, model="test"
        )
        self.assertEqual(res["exit_code"], 42)
        self._assert_release_accepted(env_info["pane_id"])
        self.assertNotIn(env_info["pane_id"], self.fake_herdr.agents)

    def test_release_on_timeout(self):
        """Proves release_agent is called when worker times out."""
        prompt_file, schema_file = self._setup_files()
        self.fake_herdr.auto_transition_on_run = "working"  # Stays working
        env_info = self.adapter.prepare_environment("run-3", "task-3", 1, self.worktree)

        res = self.adapter.execute(
            run_id="run-3", task_id="task-3", attempt_id=1, worktree_path=self.worktree,
            prompt_file=prompt_file, schema_file=schema_file, timeout=1,
            task_attempt_dir=self.attempt_dir, env_info=env_info, model="test"
        )
        self.assertEqual(res["exit_code"], -1)
        self.assertTrue(res["timed_out"])
        self._assert_release_accepted(env_info["pane_id"])
        self.assertNotIn(env_info["pane_id"], self.fake_herdr.agents)

    def test_release_on_blocked(self):
        """Proves release_agent is called when worker reaches blocked state."""
        prompt_file, schema_file = self._setup_files()
        self.fake_herdr.auto_transition_on_run = "blocked"
        env_info = self.adapter.prepare_environment("run-4", "task-4", 1, self.worktree)

        res = self.adapter.execute(
            run_id="run-4", task_id="task-4", attempt_id=1, worktree_path=self.worktree,
            prompt_file=prompt_file, schema_file=schema_file, timeout=5,
            task_attempt_dir=self.attempt_dir, env_info=env_info, model="test"
        )
        self.assertEqual(res["exit_code"], -1)
        self.assertTrue(res.get("blocked"))
        self._assert_release_accepted(env_info["pane_id"])
        self.assertNotIn(env_info["pane_id"], self.fake_herdr.agents)

    def test_release_on_explicit_cancel(self):
        """Proves cancel() releases agent authority cleanly."""
        env_info = self.adapter.prepare_environment("run-5", "task-5", 1, self.worktree)
        self.fake_herdr.report_agent_session(env_info["pane_id"], "agy", session_id="cancel-session", seq=1)
        self.fake_herdr.report_agent(env_info["pane_id"], "agy", state="working", seq=2)
        self.assertIn(env_info["pane_id"], self.fake_herdr.agents)

        ok = self.adapter.cancel("run-5", "task-5", 1, env_info)
        self.assertTrue(ok)
        self._assert_release_accepted(env_info["pane_id"])
        self.assertNotIn(env_info["pane_id"], self.fake_herdr.agents)

    def test_release_on_internal_error(self):
        """Proves lifecycle authority is released even when the native wait raises."""
        prompt_file, schema_file = self._setup_files()
        env_info = self.adapter.prepare_environment("run-6", "task-6", 1, self.worktree)

        def raise_wait(*args, **kwargs):
            raise RuntimeError("simulated wait failure")

        self.fake_herdr.agent_wait = raise_wait
        with self.assertRaisesRegex(RuntimeError, "simulated wait failure"):
            self.adapter.execute(
                run_id="run-6", task_id="task-6", attempt_id=1, worktree_path=self.worktree,
                prompt_file=prompt_file, schema_file=schema_file, timeout=5,
                task_attempt_dir=self.attempt_dir, env_info=env_info, model="test"
            )
        self._assert_release_accepted(env_info["pane_id"])

    def test_cancel_preserves_foreign_resources(self):
        """Explicit cancel must not release or close a pane/workspace Factory does not own."""
        foreign_ws, foreign_pane = self.fake_herdr.create_workspace(cwd="/foreign", label="foreign")
        self.fake_herdr.report_agent_session(foreign_pane, "agy", session_id="foreign-session", seq=1)
        self.fake_herdr.report_agent(foreign_pane, "agy", state="working", seq=2)

        ok = self.adapter.cancel(
            "run-foreign", "task-foreign", 1,
            {"workspace_id": foreign_ws, "pane_id": foreign_pane}
        )
        self.assertTrue(ok)
        self.assertIn(foreign_pane, self.fake_herdr.agents)
        self.assertFalse(self.fake_herdr.workspaces[foreign_ws]["closed"])
        self.assertFalse(any(call["pane_id"] == foreign_pane for call in self.fake_herdr.release_calls))


class TestHerdrNativeLiveHostContracts(unittest.TestCase):
    """
    Live host integration tests executing against installed Herdr binary
    strictly within dedicated isolated test workspaces, proving foreign isolation.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = HerdrClient(PROJECT_ROOT)
        try:
            res = cls.client.run_cmd(["--version"], check=False)
            cls.has_herdr = (res.returncode == 0)
        except Exception:
            cls.has_herdr = False

        if cls.has_herdr:
            res = cls.client.run_cmd(["agent", "list"], check=False)
            if res.returncode == 0:
                data = json.loads(res.stdout).get("result", {}).get("agents", [])
                cls.initial_foreign_panes = {a["pane_id"] for a in data}
            else:
                cls.initial_foreign_panes = set()
        else:
            cls.initial_foreign_panes = set()

    def setUp(self):
        if not self.has_herdr:
            self.skipTest("Live Herdr CLI is not available on host")
        self.ws_id, self.pane_id = self.client.create_workspace(cwd=str(PROJECT_ROOT), label="test-herdr-live")

    def tearDown(self):
        if hasattr(self, "ws_id") and self.ws_id:
            self.client.close_workspace(self.ws_id)
        # Foreign isolation: foreign panes must still exist and be completely untouched
        res = self.client.run_cmd(["agent", "list"], check=False)
        if res.returncode == 0:
            current_agents = json.loads(res.stdout).get("result", {}).get("agents", [])
            current_panes = {a["pane_id"] for a in current_agents}
            for p in self.initial_foreign_panes:
                self.assertIn(p, current_panes, f"Foreign pane {p} was mutated or killed by test!")

    def test_live_agent_monotonic_lifecycle_and_release(self):
        """Verifies session (seq=1) -> working (seq=2) -> stale rejection -> idle (seq=3) -> release (seq=4)."""
        # 1. Report session (seq=1)
        ok = self.client.report_agent_session(self.pane_id, "test-live", session_id="live-sess-1", seq=1)
        self.assertTrue(ok)

        # 2. Report working (seq=2)
        ok = self.client.report_agent(self.pane_id, "test-live", state="working", seq=2)
        self.assertTrue(ok)

        # 3. Send stale sequence (seq=1) attempting to change state: Herdr accepts but ignores
        res_stale = self.client.run_cmd(
            ["pane", "report-agent", self.pane_id, "--source", "factory", "--agent", "test-live", "--state", "idle", "--seq", "1"],
            check=False
        )
        self.assertEqual(res_stale.returncode, 0)
        # State must remain working
        r_list = self.client.run_cmd(["agent", "list"], check=False)
        agent_data = next((a for a in json.loads(r_list.stdout)["result"]["agents"] if a["pane_id"] == self.pane_id), None)
        self.assertIsNotNone(agent_data)
        self.assertEqual(agent_data["agent_status"], "working")

        # 4. Monotonic seq=3 transitions to idle (maps to done)
        ok = self.client.report_agent(self.pane_id, "test-live", state="idle", seq=3)
        self.assertTrue(ok)
        wait_res = self.client.agent_wait(self.pane_id, until=["idle", "done"], timeout_ms=3000)
        self.assertTrue(wait_res["matched"])
        self.assertEqual(wait_res["status"], "done")

        # 5. seq=4 releases authority: agent disappears from agent list
        ok = self.client.release_agent(self.pane_id, "test-live", seq=4)
        self.assertTrue(ok)
        r_list2 = self.client.run_cmd(["agent", "list"], check=False)
        active_panes = [a["pane_id"] for a in json.loads(r_list2.stdout)["result"]["agents"]]
        self.assertNotIn(self.pane_id, active_panes)


if __name__ == "__main__":
    unittest.main()
