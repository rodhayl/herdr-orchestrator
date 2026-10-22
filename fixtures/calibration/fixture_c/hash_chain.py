"""Merkle Hash Chain Ledger — Deep Debugging Case 2."""
import hashlib
import json
import unicodedata


class HashChainLedger:
    """Tamper-evident hash chain ledger."""

    def __init__(self):
        self.blocks = []

    def add_block(self, payload: dict) -> str:
        prev_hash = self.blocks[-1]["hash"] if self.blocks else "0" * 64
        # Bug: json.dumps without sort_keys and without unicodedata normalization causes non-deterministic hashes
        # when nested dictionaries or unicode strings with different representations are hashed!
        canonical_str = json.dumps({"prev": prev_hash, "payload": payload})
        block_hash = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
        block = {
            "index": len(self.blocks),
            "prev": prev_hash,
            "payload": payload,
            "hash": block_hash
        }
        self.blocks.append(block)
        return block_hash

    def verify(self) -> bool:
        for i, b in enumerate(self.blocks):
            prev = self.blocks[i - 1]["hash"] if i > 0 else "0" * 64
            if b["prev"] != prev:
                return False
            canonical_str = json.dumps({"prev": prev, "payload": b["payload"]})
            h = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
            if h != b["hash"]:
                return False
        return True
