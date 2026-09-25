#!/usr/bin/env python3
"""Tests for Fixture C Deep Debugging."""
import copy
import json
import unicodedata
import unittest
from transactional_cache import TransactionalCache
from hash_chain import HashChainLedger


class TestTransactionalCache(unittest.TestCase):
    def test_nested_mutation_isolation_on_rollback(self):
        cache = TransactionalCache()
        cache.set("config", {"timeout": 30, "retries": {"max": 3, "backoff": 2}})

        cache.begin()
        cfg = cache.get("config")
        cfg["retries"]["max"] = 99
        cache.rollback()

        # The parent state must not be corrupted by uncommitted nested mutation
        restored = cache.get("config")
        self.assertEqual(restored["retries"]["max"], 3)


class TestHashChainLedger(unittest.TestCase):
    def test_unicode_and_key_order_canonical_verification(self):
        ledger = HashChainLedger()
        # Complex payload with non-normalized unicode and unordered keys
        payload1 = {"b": 2, "a": 1, "text": unicodedata.normalize("NFD", "Café")}
        payload2 = {"text": unicodedata.normalize("NFC", "Café"), "a": 1, "b": 2}

        h1 = ledger.add_block(payload1)
        # Even if payload dictionaries have same semantics but different key orders or unicode representations,
        # ledger verification must be invariant
        self.assertTrue(ledger.verify())


if __name__ == "__main__":
    unittest.main()
