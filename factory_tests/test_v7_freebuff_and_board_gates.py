#!/usr/bin/env python3
"""
Unit tests for Factory v7.0.0 Freebuff Headless Feasibility Gate and herdr-board Compatibility Gate.
"""

import subprocess
import unittest

from tools.factory import (
    probe_harness_auth,
    FACTORY_ROOT
)


class TestV7FreebuffAndBoardGates(unittest.TestCase):
    def test_probe_harness_auth_freebuff(self):
        probe = probe_harness_auth("freebuff", force_refresh=True)
        self.assertEqual(probe["harness"], "freebuff")
        self.assertFalse(probe["authenticated"])
        self.assertEqual(probe["auth_source"], "FREEBUFF_HEADLESS_BLOCKED")
        self.assertIn("lacks official headless/non-interactive", probe["evidence"])

    def test_doctor_script_executes_and_reports_gates(self):
        proc = subprocess.run(
            ["./scripts/doctor.sh"],
            cwd=str(FACTORY_ROOT),
            capture_output=True,
            text=True
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("FREEBUFF Feasibility Gate: FREEBUFF_HEADLESS_BLOCKED", proc.stdout)
        self.assertIn("herdr-board Compatibility: BLOCKED_EXTERNAL_COMPATIBILITY", proc.stdout)

    def test_update_package_script_check_reports_freebuff_gate(self):
        proc = subprocess.run(
            ["./scripts/update-package.sh", "--check"],
            cwd=str(FACTORY_ROOT),
            capture_output=True,
            text=True
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Freebuff CLI", proc.stdout)
        self.assertIn("FREEBUFF_HEA", proc.stdout)


if __name__ == "__main__":
    unittest.main()
