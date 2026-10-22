#!/usr/bin/env python3
"""Tests for Fixture B."""
import json
import pathlib
import tempfile
import unittest
from models import Event
from store import EventStore


class TestEventStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self.temp_dir.name) / "test_events.jsonl"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_append_and_query(self):
        store = EventStore(self.db_path)
        e1 = Event("e1", "USER_SIGNUP", {"email": "user@example.com"})
        e2 = Event("e2", "LOGIN", {"user": "user1"})
        store.append(e1)
        store.append(e2)

        signups = store.query_by_type("USER_SIGNUP")
        self.assertEqual(len(signups), 1)
        self.assertEqual(signups[0].event_id, "e1")

    def test_persistence_across_instances(self):
        store1 = EventStore(self.db_path)
        store1.append(Event("e1", "TASK_RUN", {"id": 1}))

        store2 = EventStore(self.db_path)
        runs = store2.query_by_type("TASK_RUN")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].payload, {"id": 1})


if __name__ == "__main__":
    unittest.main()
