#!/usr/bin/env python3
"""
Provider-free regression tests for the Freebuff headless feasibility gate and maintenance diagnostics.
"""

import os
import subprocess
import pathlib
import tempfile
import unittest

from tools.factory import (
    probe_harness_auth,
    FACTORY_ROOT
)


class TestFreebuffGate(unittest.TestCase):
    def test_probe_harness_auth_freebuff(self):
        probe = probe_harness_auth("freebuff", force_refresh=True)
        self.assertEqual(probe["harness"], "freebuff")
        self.assertFalse(probe["authenticated"])
        if probe["auth_source"] == "FREEBUFF_HEADLESS_BLOCKED":
            self.assertIn("lacks official headless/non-interactive", probe["evidence"])
        else:
            self.assertEqual(probe["auth_source"], "unauthenticated")
            self.assertIn("not found", probe["evidence"])

    def test_doctor_script_executes_and_reports_gates(self):
        env = os.environ.copy()
        env["FACTORY_PROVIDER_PROBES"] = "0"
        # Explicit deterministic Herdr fixture; this does not certify a live host.
        with tempfile.TemporaryDirectory() as tmp:
            herdr = pathlib.Path(tmp) / "herdr"
            herdr.write_text("#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'Herdr test fixture'; else echo '{}'; fi\n")
            herdr.chmod(0o755)
            env["PATH"] = tmp + os.pathsep + env.get("PATH", "")
            proc = subprocess.run(
                ["./scripts/doctor.sh"], cwd=str(FACTORY_ROOT),
                capture_output=True, text=True, env=env,
            )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Provider auth/catalog probes skipped", proc.stdout)
        self.assertIn("DOCTOR STATUS: STRUCTURAL PREREQUISITES SATISFIED", proc.stdout)

    def test_update_package_script_check_reports_freebuff_gate(self):
        env = os.environ.copy()
        env["FACTORY_PROVIDER_PROBES"] = "0"
        proc = subprocess.run(
            ["./scripts/update-package.sh", "--check"],
            cwd=str(FACTORY_ROOT),
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Freebuff CLI", proc.stdout)
        self.assertIn("FREEBUFF_HEA", proc.stdout)


if __name__ == "__main__":
    unittest.main()
