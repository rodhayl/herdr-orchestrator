"""Incomplete unit tests for Fixture F (missing security and error tests)."""
import unittest
from server import handle_request


class TestServerBasic(unittest.TestCase):
    def test_unknown_method(self):
        res = handle_request("POST", "/data", {})
        self.assertEqual(res["status"], 405)


if __name__ == "__main__":
    unittest.main()
