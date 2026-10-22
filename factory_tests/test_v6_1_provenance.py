import os
import unittest
from tools.factory import assert_real_certifiable, verify_binary_identity

class TestV61Provenance(unittest.TestCase):
    def setUp(self):
        self.orig_test_harness = os.environ.get("FACTORY_TEST_HARNESS")

    def tearDown(self):
        if self.orig_test_harness is not None:
            os.environ["FACTORY_TEST_HARNESS"] = self.orig_test_harness
        else:
            os.environ.pop("FACTORY_TEST_HARNESS", None)

    def test_guard_rejects_active_test_harness(self):
        os.environ["FACTORY_TEST_HARNESS"] = "1"
        manifest = {
            "final_status": "COMPLETED",
            "run_state": "COMPLETED",
            "contains_mock_execution": False,
            "tasks": {
                "t1": {
                    "attempts": [{
                        "execution_mode": "REAL",
                        "real_evidence": {
                            "executable_realpath": "/root/.local/bin/agy",
                            "raw_result_hash": "abc123hash"
                        }
                    }]
                }
            }
        }
        passed, reason = assert_real_certifiable(manifest)
        self.assertFalse(passed)
        self.assertIn("FACTORY_TEST_HARNESS=1", reason)

    def test_guard_rejects_contains_mock_execution(self):
        os.environ.pop("FACTORY_TEST_HARNESS", None)
        manifest = {
            "final_status": "COMPLETED",
            "run_state": "COMPLETED",
            "contains_mock_execution": True,
            "tasks": {
                "t1": {
                    "attempts": [{
                        "execution_mode": "REAL",
                        "real_evidence": {
                            "executable_realpath": "/root/.local/bin/agy",
                            "raw_result_hash": "abc123hash"
                        }
                    }]
                }
            }
        }
        passed, reason = assert_real_certifiable(manifest)
        self.assertFalse(passed)
        self.assertIn("contains mock execution", reason)

    def test_guard_rejects_incomplete_run(self):
        os.environ.pop("FACTORY_TEST_HARNESS", None)
        manifest = {
            "final_status": "FAILED",
            "run_state": "FAILED",
            "contains_mock_execution": False,
            "tasks": {
                "t1": {
                    "attempts": [{
                        "execution_mode": "REAL",
                        "real_evidence": {
                            "executable_realpath": "/root/.local/bin/agy",
                            "raw_result_hash": "abc123hash"
                        }
                    }]
                }
            }
        }
        passed, reason = assert_real_certifiable(manifest)
        self.assertFalse(passed)
        self.assertIn("did not complete successfully", reason)

    def test_guard_rejects_mock_attempt_mode(self):
        os.environ.pop("FACTORY_TEST_HARNESS", None)
        manifest = {
            "final_status": "COMPLETED",
            "run_state": "COMPLETED",
            "contains_mock_execution": False,
            "tasks": {
                "t1": {
                    "attempts": [{
                        "execution_mode": "MOCK",
                        "real_evidence": None
                    }]
                }
            }
        }
        passed, reason = assert_real_certifiable(manifest)
        self.assertFalse(passed)
        self.assertIn("attempt mode is 'MOCK'", reason)

    def test_guard_rejects_missing_real_evidence(self):
        os.environ.pop("FACTORY_TEST_HARNESS", None)
        manifest = {
            "final_status": "COMPLETED",
            "run_state": "COMPLETED",
            "contains_mock_execution": False,
            "tasks": {
                "t1": {
                    "attempts": [{
                        "execution_mode": "REAL",
                        "real_evidence": None
                    }]
                }
            }
        }
        passed, reason = assert_real_certifiable(manifest)
        self.assertFalse(passed)
        self.assertIn("missing real_evidence", reason)

    def test_guard_rejects_fake_or_fixture_executable(self):
        os.environ.pop("FACTORY_TEST_HARNESS", None)
        manifest = {
            "final_status": "COMPLETED",
            "run_state": "COMPLETED",
            "contains_mock_execution": False,
            "tasks": {
                "t1": {
                    "attempts": [{
                        "execution_mode": "REAL",
                        "real_evidence": {
                            "executable_realpath": "/root/agy-herdr-factory-poc/factory_tests/fake_opencode.sh",
                            "raw_result_hash": "abc123hash"
                        }
                    }]
                }
            }
        }
        passed, reason = assert_real_certifiable(manifest)
        self.assertFalse(passed)
        self.assertIn("test fixture executable", reason)

    def test_guard_accepts_verified_real_manifest(self):
        os.environ.pop("FACTORY_TEST_HARNESS", None)
        manifest = {
            "final_status": "COMPLETED",
            "run_state": "COMPLETED",
            "contains_mock_execution": False,
            "tasks": {
                "t1": {
                    "attempts": [{
                        "execution_mode": "REAL",
                        "real_evidence": {
                            "executable_realpath": "/root/.local/bin/agy",
                            "raw_result_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                            "invocation_argv": ["/root/.local/bin/agy", "--print", "hello"]
                        }
                    }]
                }
            }
        }
        passed, reason = assert_real_certifiable(manifest)
        self.assertTrue(passed)
        self.assertIn("REAL_PROVIDER_CERTIFIED", reason)

    def test_verify_binary_identity_detects_fixture(self):
        res = verify_binary_identity("/tmp/fake_shim.sh")
        self.assertTrue(res["is_fixture"])
        self.assertIn("/tmp/", res["fixture_reason"])

if __name__ == "__main__":
    unittest.main()
