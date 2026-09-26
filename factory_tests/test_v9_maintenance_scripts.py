"""Provider-free source contracts for active v9 maintenance scripts."""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class MaintenanceScriptContractsTests(unittest.TestCase):
    def _source(self, relpath: str) -> str:
        path = ROOT / relpath
        if not path.exists():
            raise unittest.SkipTest("requires full repository checkout")
        return path.read_text(encoding="utf-8")

    def test_active_scripts_do_not_advertise_stale_factory_release(self):
        for relpath in (
            "scripts/doctor.sh",
            "scripts/portable-smoke.sh",
            "scripts/verify-real.sh",
            "scripts/update-package.sh",
        ):
            source = self._source(relpath)
            self.assertNotIn("Factory (v7.0.0)", source, relpath)
            self.assertNotIn("Factory v6.1.0", source, relpath)
            self.assertNotIn("to v6.1.0 successfully", source, relpath)

    def test_verify_real_does_not_hardcode_provider_auth_outcomes(self):
        source = self._source("scripts/verify-real.sh")
        self.assertNotIn("Droid:  AUTH_BLOCKED", source)
        self.assertNotIn("Codex:  AUTH_BLOCKED", source)
        self.assertNotIn("Claude: AUTH_BLOCKED", source)
        self.assertNotIn("Genuine providers: AGY, OpenCode", source)
        self.assertIn("auth probe", source)

    def test_update_package_apply_preserves_existing_extension_keys_and_freebuff(self):
        source = self._source("scripts/update-package.sh")
        self.assertIn("new_lock = dict(prev_lock)", source)
        self.assertIn('"freebuff": {', source)
        self.assertIn('"feasibility_status": "FREEBUFF_HEADLESS_BLOCKED"', source)
        self.assertIn('"version": factory_ver', source)
        self.assertIn('upstream_board = "v0.18.0"', source)
        self.assertIn('d7a67470309c378778e388982bda67eee6dc1a58', source)
        self.assertNotIn("future v6", source)

    def test_verify_real_does_not_hide_real_smoke_failures(self):
        source = self._source("scripts/verify-real.sh")
        self.assertNotIn('2>/dev/null || true', source)
        self.assertNotIn('2>&1 || true', source)
        self.assertIn('SMOKE_RC=$?', source)
        self.assertIn('OPENCODE_RC=$?', source)


if __name__ == "__main__":
    unittest.main()
