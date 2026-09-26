"""Provider-free tests for shared Factory/core/UI deterministic contracts."""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.factory_contracts import (  # noqa: E402
    CANONICAL_TO_DISPLAY_STATE,
    DISPLAY_STATES,
    FACTORY_ENGINE_VERSION,
    TERMINAL_GOAL_PHASES,
    display_state,
    effective_real_only,
    has_existing_run,
    is_factory_runtime_path,
    non_runtime_porcelain_lines,
    porcelain_line_is_factory_runtime,
    run_state,
)


class FactoryContractsTests(unittest.TestCase):
    def test_state_projection_covers_intermediate_and_conflict_states(self):
        expected = {
            "PENDING": "BACKLOG",
            "RESULT_RECEIVED": "RUNNING",
            "PATH_VALIDATING": "RUNNING",
            "PATH_VALIDATED": "RUNNING",
            "VALIDATING": "RUNNING",
            "COMMITTING": "RUNNING",
            "COMMITTED": "RUNNING",
            "INTEGRATING": "RUNNING",
            "CONFLICTED": "REVIEW",
            "INTEGRATED": "DONE",
            "TIMED_OUT": "FAILED",
        }
        for state, projected in expected.items():
            with self.subTest(state=state):
                self.assertEqual(CANONICAL_TO_DISPLAY_STATE[state], projected)
                self.assertEqual(display_state(state), projected)
                self.assertIn(projected, DISPLAY_STATES)
        self.assertEqual(display_state("UNKNOWN_NEW_STATE"), "BACKLOG")
        self.assertEqual(display_state("RUNNING", "REVIEW"), "RUNNING")

    def test_canonical_state_wins_over_stale_display_projection(self):
        self.assertEqual(display_state("CONFLICTED", "FAILED"), "REVIEW")
        self.assertEqual(display_state("VALIDATING", "REVIEW"), "RUNNING")
        self.assertEqual(display_state("UNKNOWN_LEGACY", "BLOCKED"), "BLOCKED")

    def test_run_and_goal_terminal_contracts(self):
        self.assertEqual(FACTORY_ENGINE_VERSION, "9.0.0")
        self.assertEqual(run_state({"final_status": "COMPLETED"}), "COMPLETED")
        self.assertEqual(run_state({"run_state": "RUNNING", "final_status": "COMPLETED"}), "RUNNING")
        self.assertIn("CANCELLED", TERMINAL_GOAL_PHASES)
        self.assertFalse(has_existing_run(None))
        self.assertFalse(has_existing_run(""))
        self.assertTrue(has_existing_run("run-123"))
        self.assertFalse(effective_real_only(False, False, "mock_allowed"))
        self.assertTrue(effective_real_only(True, False, "mock_allowed"))
        self.assertTrue(effective_real_only(False, True, "mock_allowed"))
        self.assertTrue(effective_real_only(False, False, "real_only"))

    def test_runtime_path_matching_is_root_scoped_not_substring_based(self):
        self.assertTrue(is_factory_runtime_path(".agy-factory"))
        self.assertTrue(is_factory_runtime_path(".agy-factory/runs/run-1/manifest.json"))
        self.assertFalse(is_factory_runtime_path("docs/.agy-factory-notes.md"))
        self.assertFalse(is_factory_runtime_path("src/foo.agy-factory/bar.py"))
        self.assertFalse(is_factory_runtime_path("../.agy-factory/escape"))

    def test_porcelain_filter_fails_closed_and_handles_renames(self):
        self.assertTrue(porcelain_line_is_factory_runtime("?? .agy-factory/tmp/file"))
        self.assertTrue(porcelain_line_is_factory_runtime(" M .agy-factory/state/x.json"))
        self.assertTrue(porcelain_line_is_factory_runtime("R  .agy-factory/a -> .agy-factory/b"))
        self.assertFalse(porcelain_line_is_factory_runtime(" M docs/foo.agy-factory-note.md"))
        self.assertFalse(porcelain_line_is_factory_runtime("R  .agy-factory/a -> src/a"))
        self.assertFalse(porcelain_line_is_factory_runtime("R  src/a -> .agy-factory/a"))
        self.assertFalse(porcelain_line_is_factory_runtime("malformed"))
        output = "?? .agy-factory/tmp/x\n M docs/readme.md\n M src/foo.agy-factory.py\n"
        self.assertEqual(non_runtime_porcelain_lines(output), ["M docs/readme.md", "M src/foo.agy-factory.py"])


if __name__ == "__main__":
    unittest.main()
