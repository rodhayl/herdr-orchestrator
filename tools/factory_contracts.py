"""Small shared deterministic contracts used by Factory core and local surfaces.

Keep this module pure: no filesystem mutation, subprocesses, provider calls, or
runtime-global state. It exists to prevent drift between the orchestration core
and projections such as the Herdr Orchestrator UI.
"""

from __future__ import annotations

FACTORY_ENGINE_VERSION = "9.0.0"

DISPLAY_STATES = ("BACKLOG", "READY", "RUNNING", "BLOCKED", "REVIEW", "DONE", "FAILED")

CANONICAL_TO_DISPLAY_STATE = {
    "PENDING": "BACKLOG",
    "READY": "READY",
    "DISPATCHING": "RUNNING",
    "RUNNING": "RUNNING",
    "RESULT_RECEIVED": "RUNNING",
    "PATH_VALIDATING": "RUNNING",
    "PATH_VALIDATED": "RUNNING",
    "VALIDATING": "RUNNING",
    "COMMITTING": "RUNNING",
    "COMMITTED": "RUNNING",
    "INTEGRATING": "RUNNING",
    "INTEGRATED": "DONE",
    "COMPLETED": "DONE",
    "BLOCKED": "BLOCKED",
    "TIMED_OUT": "FAILED",
    "FAILED": "FAILED",
    "CONFLICTED": "REVIEW",
    "CANCELLED": "FAILED",
}

TERMINAL_RUN_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
TERMINAL_GOAL_PHASES = frozenset({"COMPLETE", "FAILED", "BLOCKED", "CANCELLED"})


def display_state(canonical_state: object, explicit_display: object = None) -> str:
    """Return the authoritative seven-column display projection.

    A known canonical state always wins so stale persisted display projections
    cannot override scheduler truth. A valid explicit display state is used only
    as a legacy fallback when no known canonical state exists. Unknown data stays
    conservative in BACKLOG rather than being misreported as success/failure.
    """

    canonical = str(canonical_state or "").upper()
    if canonical in CANONICAL_TO_DISPLAY_STATE:
        return CANONICAL_TO_DISPLAY_STATE[canonical]
    explicit = str(explicit_display or "").upper()
    if explicit in DISPLAY_STATES:
        return explicit
    return "BACKLOG"


def run_state(run: dict) -> str:
    """Resolve a run state consistently from current and legacy manifests."""

    return str(run.get("run_state") or run.get("final_status") or "UNKNOWN").upper()


def has_existing_run(run_id: object) -> bool:
    """Whether a durable GoalController run id existed before constructing a run."""

    return bool(str(run_id or "").strip())



def effective_real_only(requested: object, persisted: object, policy_mode: object) -> bool:
    """Resolve real-only as a monotonic safety property across create/resume cycles."""

    return bool(requested or persisted or str(policy_mode or "") == "real_only")


def _strip_porcelain_quotes(path: str) -> str:
    path = path.strip()
    # Fail closed for complex Git quoting. Runtime paths never require quoting in
    # normal Factory operation, so only the simple quoted form is normalized.
    if len(path) >= 2 and path[0] == path[-1] == '"' and "\\" not in path:
        return path[1:-1]
    return path


def is_factory_runtime_path(path: object) -> bool:
    """Return True only for the repository-root .agy-factory runtime subtree."""

    value = _strip_porcelain_quotes(str(path or "")).replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value == ".agy-factory" or value.startswith(".agy-factory/")


def porcelain_line_is_factory_runtime(line: object) -> bool:
    """Whether a `git status --porcelain=v1` record is exclusively runtime state.

    Renames are ignored only when both old and new paths are under .agy-factory.
    Any malformed/quoted/ambiguous record fails closed and is treated as dirty.
    """

    value = str(line or "")
    if len(value) < 4 or value[2] != " ":
        return False
    payload = value[3:]
    if not payload:
        return False
    paths = payload.split(" -> ")
    return bool(paths) and all(is_factory_runtime_path(path) for path in paths)


def non_runtime_porcelain_lines(output: object) -> list[str]:
    """Filter porcelain status output to changes that must make project preflight fail."""

    dirty: list[str] = []
    for line in str(output or "").splitlines():
        if not line.strip():
            continue
        if not porcelain_line_is_factory_runtime(line):
            dirty.append(line.strip())
    return dirty
