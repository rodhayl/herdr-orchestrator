"""Static source-contract regressions for core fixes that require the full Factory module.

These complement runtime tests in test_v9_core_hardening.py and deliberately avoid
provider calls. They catch accidental reintroduction of known fail-open patterns.
"""

from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACTORY = ROOT / "tools" / "factory.py"


class CoreSourceContractsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FACTORY.exists():
            raise unittest.SkipTest("requires full repository checkout")
        cls.source = FACTORY.read_text(encoding="utf-8")

    def test_real_only_roles_have_explicit_fail_closed_error(self):
        self.assertIn("class RealProviderRequiredError", self.source)
        for role in ("goal specification planner", "plan compiler", "plan reviewer", "final auditor"):
            self.assertIn(role, self.source.lower())
        self.assertGreaterEqual(self.source.count("raise RealProviderRequiredError"), 4)

    def test_test_verdict_overrides_require_explicit_test_harness(self):
        self.assertIn('if os.environ.get("FACTORY_TEST_HARNESS") == "1" else None', self.source)
        self.assertNotIn('sim_verdict = os.environ.get("PLAN_REVIEW_TEST_VERDICT")\n', self.source)
        self.assertNotIn('test_verdict = os.environ.get("AUDIT_TEST_VERDICT")\n', self.source)

    def test_fresh_goal_resume_mode_is_based_on_preexisting_run_id(self):
        self.assertIn("existing_run_id = self.state.get(\"run_id\")", self.source)
        self.assertIn("resume_mode=has_existing_run(existing_run_id)", self.source)
        self.assertNotIn('resume_mode=(self.state.get("run_id") is not None)', self.source)

    def test_goal_state_persists_real_only_and_validation_uses_shlex(self):
        self.assertIn('self.state["real_only"] = bool(self.real_only)', self.source)
        self.assertIn('"real_only": bool(self.real_only)', self.source)
        self.assertIn('vcmd if isinstance(vcmd, list) else shlex.split(vcmd)', self.source)


    def test_run_manifest_uses_current_engine_version_and_persists_real_only(self):
        self.assertIn('"factory_version": FACTORY_ENGINE_VERSION', self.source)
        self.assertIn('"real_only": bool(self.real_only)', self.source)
        self.assertIn('self.manifest.get("real_only")', self.source)
        self.assertNotIn('"factory_version": "8.0.0"', self.source)

    def test_dirty_git_filter_uses_shared_root_scoped_contract(self):
        self.assertIn("non_runtime_porcelain_lines(status_res.stdout)", self.source)
        self.assertNotIn('".agy-factory" in line_str', self.source)


if __name__ == "__main__":
    unittest.main()
