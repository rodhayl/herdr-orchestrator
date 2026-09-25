#!/usr/bin/env python3
"""Deterministic tests for Fixture A."""
import subprocess
import sys
import unittest
from record_formatter import RecordFormatter


class TestRecordFormatter(unittest.TestCase):
    def test_canonical_json_sorts_keys(self):
        f = RecordFormatter({"z": 1, "a": 2, "m": 3})
        self.assertEqual(f.to_canonical_json(), '{"a":2,"m":3,"z":1}')

    def test_canonical_json_compact_separators(self):
        f = RecordFormatter({"foo": "bar", "baz": 42})
        self.assertEqual(f.to_canonical_json(), '{"baz":42,"foo":"bar"}')

    def test_cli_canonical_flag(self):
        proc = subprocess.run(
            [sys.executable, "record_formatter.py", '{"b": 2, "a": 1}', "--canonical"],
            capture_output=True,
            text=True
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), '{"a":1,"b":2}')


if __name__ == "__main__":
    unittest.main()
