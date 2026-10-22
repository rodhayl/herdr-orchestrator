"""Provider-free source contracts for active v9 maintenance scripts."""

from __future__ import annotations

import os
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
        self.assertNotIn("future v6", source)
        self.assertNotIn("herdr_board", source)
        self.assertNotIn("rustc", source)
        self.assertNotIn("cargo", source)

    def test_verify_real_does_not_hide_real_smoke_failures(self):
        source = self._source("scripts/verify-real.sh")
        self.assertNotIn('2>/dev/null || true', source)
        self.assertNotIn('2>&1 || true', source)
        self.assertIn('SMOKE_RC=$?', source)
        self.assertIn('OPENCODE_RC=$?', source)

    def test_portable_smoke_disables_provider_cli_probes(self):
        portable = self._source("scripts/portable-smoke.sh")
        verify = self._source("scripts/verify.sh")
        doctor = self._source("scripts/doctor.sh")
        updater = self._source("scripts/update-package.sh")

        self.assertIn("export FACTORY_PROVIDER_PROBES=0", portable)
        self.assertIn("export FACTORY_PROVIDER_PROBES=0", verify)
        self.assertIn("VERIFY_HEAD_BEFORE", verify)
        self.assertIn("VERIFY_STATUS_BEFORE", verify)
        self.assertIn("deterministic verification changed Git HEAD", verify)
        self.assertIn("deterministic verification changed tracked/untracked Git status", verify)
        self.assertIn('"${FACTORY_PROVIDER_PROBES:-1}"', doctor)
        self.assertIn('"${FACTORY_PROVIDER_PROBES:-1}"', updater)
        self.assertIn("Provider CLI version probes skipped", doctor)
        self.assertIn("Provider auth/catalog probes skipped", doctor)
        self.assertIn("AGY CLI not invoked", updater)
        self.assertIn("--apply requires provider CLI probes", updater)

        gitignore = self._source(".gitignore")
        self.assertIn(".agy-factory/", gitignore)
        self.assertIn('if [[ -e "$TMP_CHECKOUT/.agy-factory" ]]', portable)

    def test_strict_provider_free_mode_never_executes_provider_clis(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = pathlib.Path(tmp)
            fake_bin = tmp_root / "bin"
            fake_bin.mkdir()
            marker = tmp_root / "provider-cli-called"

            tripwire = """#!/usr/bin/env bash
printf '%s\\n' "$0" >> "${PROVIDER_MARKER:?}"
exit 97
"""
            for cli in ("agy", "droid", "codex", "claude", "opencode", "freebuff"):
                path = fake_bin / cli
                path.write_text(tripwire, encoding="utf-8")
                path.chmod(0o755)

            herdr = fake_bin / "herdr"
            herdr.write_text(
                """#!/usr/bin/env bash
case "$*" in
  "--version")
    echo "herdr 0.9.1"
    ;;
  "api snapshot")
    printf '%s\\n' '{"result":{"snapshot":{"protocol":22,"workspaces":[]}}}'
    ;;
  "api schema --json")
    printf '%s\\n' '{}'
    ;;
  *)
    echo "unexpected herdr invocation: $*" >&2
    exit 98
    ;;
esac
""",
                encoding="utf-8",
            )
            herdr.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
            env["FACTORY_PROVIDER_PROBES"] = "0"
            env["PROVIDER_MARKER"] = str(marker)

            commands = (
                ["bash", str(ROOT / "scripts/doctor.sh")],
                ["bash", str(ROOT / "scripts/update-package.sh"), "--check"],
            )
            for command in commands:
                result = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"{command} failed in strict provider-free mode:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
                )

            self.assertFalse(
                marker.exists(),
                marker.read_text(encoding="utf-8") if marker.exists() else "",
            )

            lock_path = ROOT / "toolchain.lock.json"
            lock_before = lock_path.read_bytes()
            apply_result = subprocess.run(
                ["bash", str(ROOT / "scripts/update-package.sh"), "--apply"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(apply_result.returncode, 2)
            self.assertIn("--apply requires provider CLI probes", apply_result.stderr)
            self.assertEqual(lock_path.read_bytes(), lock_before)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
