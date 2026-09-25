#!/usr/bin/env python3
"""Record Formatter Utility — Mechanical Routine Task Fixture A."""
import argparse
import json
import sys


class RecordFormatter:
    """Formats key-value records for logging and export."""

    def __init__(self, data: dict):
        if not isinstance(data, dict):
            raise TypeError("data must be a dict")
        self.data = data

    def to_json(self) -> str:
        """Standard JSON dump."""
        return json.dumps(self.data)

    def to_canonical_json(self) -> str:
        """Deterministic canonical JSON serialization: sorted keys, compact separators."""
        return json.dumps(self.data, sort_keys=True, separators=(",", ":"))


def main():
    parser = argparse.ArgumentParser(description="Format record data")
    parser.add_argument("input", help="JSON string input")
    parser.add_argument("--canonical", action="store_true", help="Output canonical sorted compact JSON")
    args = parser.parse_args()

    try:
        data = json.loads(args.input)
        formatter = RecordFormatter(data)
        if args.canonical:
            print(formatter.to_canonical_json())
        else:
            print(formatter.to_json())
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
