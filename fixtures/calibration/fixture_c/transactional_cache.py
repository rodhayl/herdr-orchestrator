"""Transactional Cache — Deep Debugging Case 1."""
import threading


class TransactionalCache:
    """Thread-safe transactional in-memory cache with rollback capability."""

    def __init__(self):
        self._data = {}
        self._tx_stack = []
        self._lock = threading.RLock()

    def begin(self):
        with self._lock:
            # Bug: shallow copy causes nested dict mutations inside transaction to leak into parent state
            self._tx_stack.append(self._data.copy())

    def rollback(self):
        with self._lock:
            if not self._tx_stack:
                raise RuntimeError("No active transaction")
            self._data = self._tx_stack.pop()

    def commit(self):
        with self._lock:
            if not self._tx_stack:
                raise RuntimeError("No active transaction")
            self._tx_stack.pop()

    def set(self, key: str, value: dict):
        with self._lock:
            self._data[key] = value

    def get(self, key: str, default=None):
        with self._lock:
            val = self._data.get(key, default)
            return val
