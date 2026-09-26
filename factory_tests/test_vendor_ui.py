"""Deterministic tests for the no-Node Factory UI vendor synchronizer."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import pathlib
import tarfile
import tempfile
import unittest
from unittest import mock

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "vendor_ui.py"
spec = importlib.util.spec_from_file_location("vendor_ui_under_test", MODULE_PATH)
vendor_ui = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(vendor_ui)


def package_tar(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in files.items():
            raw = content.encode("utf-8")
            info = tarfile.TarInfo("package/" + name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


class VendorUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.lock = self.root / "vendor.lock.json"
        self.dest = self.root / "vendor"
        self.lock.write_text(json.dumps({
            "schema_version": 1,
            "packages": [{
                "name": "@example/ui", "version": "1.2.3",
                "files": [{"source": "single.js", "target": "single.js"}],
                "prefixes": [{"source": "dist/", "target": "bundle/"}],
            }],
        }), encoding="utf-8")
        self.tarball = package_tar({"single.js": "one", "dist/a.js": "a", "dist/styles/x.css": "x"})
        digest = base64.b64encode(hashlib.sha512(self.tarball).digest()).decode("ascii")
        self.metadata = {"version": "1.2.3", "dist": {"tarball": "https://example.invalid/ui.tgz", "integrity": "sha512-" + digest}}

    def tearDown(self):
        self.temp.cleanup()

    def test_sync_extracts_exact_file_and_prefix_then_check_passes(self):
        with mock.patch.object(vendor_ui, "_fetch_json", return_value=self.metadata), mock.patch.object(vendor_ui, "_download", return_value=self.tarball):
            state = vendor_ui.sync(self.lock, self.dest)
        self.assertEqual((self.dest / "single.js").read_text(), "one")
        self.assertEqual((self.dest / "bundle" / "a.js").read_text(), "a")
        self.assertEqual((self.dest / "bundle" / "styles" / "x.css").read_text(), "x")
        self.assertEqual(vendor_ui.check(self.lock, self.dest), [])
        self.assertEqual(len(state["files"]), 3)

    def test_check_detects_vendor_tampering(self):
        with mock.patch.object(vendor_ui, "_fetch_json", return_value=self.metadata), mock.patch.object(vendor_ui, "_download", return_value=self.tarball):
            vendor_ui.sync(self.lock, self.dest)
        (self.dest / "bundle" / "a.js").write_text("tampered", encoding="utf-8")
        errors = vendor_ui.check(self.lock, self.dest)
        self.assertTrue(any("hash mismatch" in item for item in errors))

    def test_integrity_failure_aborts_before_install(self):
        metadata = {"version": "1.2.3", "dist": {"tarball": "https://example.invalid/ui.tgz", "integrity": "sha512-" + base64.b64encode(b"0" * 64).decode("ascii")}}
        with mock.patch.object(vendor_ui, "_fetch_json", return_value=metadata), mock.patch.object(vendor_ui, "_download", return_value=self.tarball):
            with self.assertRaises(vendor_ui.VendorError):
                vendor_ui.sync(self.lock, self.dest)
        self.assertFalse(self.dest.exists())

    def test_lock_rejects_path_traversal(self):
        bad = self.root / "bad.json"
        bad.write_text(json.dumps({"schema_version": 1, "packages": [{"name": "x", "version": "1", "files": [{"source": "x", "target": "../escape"}]}]}), encoding="utf-8")
        with self.assertRaises(vendor_ui.VendorError):
            vendor_ui.load_lock(bad)


if __name__ == "__main__":
    unittest.main()
