# REPRODUCIBILITY.md — AGY-Herdr Software Factory (v4.0.0)

This guide specifies how to reproduce, bootstrap, verify, and operate the AGY-Herdr Software Factory on any compatible host from a clean checkout.

---

## 1. Quick Start Workflow

To verify the factory from a fresh repository clone, execute the standard sequence:

```bash
# 1. Environment & Toolchain Diagnostics (Read-Only)
./scripts/doctor.sh

# 2. Package & Compatibility Gate Audit (Read-Only)
./scripts/update-package.sh --check

# 3. Project-Local Runtime Initialization (Idempotent)
./scripts/bootstrap.sh

# 4. Deterministic Verification Matrix (Provider-Free)
./scripts/verify.sh
```

---

## 2. Script Reference

All scripts dynamically resolve the repository root and do not assume fixed absolute host paths.

| Script | Mode | Description |
| :--- | :--- | :--- |
| `scripts/doctor.sh` | Read-only | Probes host OS, Python, Git, Herdr, AGY, Droid, and socket APIs. Distinguishes structural requirements from authenticated provider prerequisites. |
| `scripts/update-package.sh` | Read/Write | `--check`: Inspects installed tools against `toolchain.lock.json` and evaluates upstream compatibility.<br>`--apply`: Refreshes lock and project-local dependency state. |
| `scripts/bootstrap.sh` | Mutative (Local) | Initializes `.agy-factory/` runtime directories and `.tools/` project-local paths. Idempotent. |
| `scripts/env.sh` | Environment | Exports process-local environment variables (`PROJECT_ROOT`, `HERDR_SOCKET_PATH`, etc.). |
| `scripts/verify.sh` | Testing | Runs all 5 deterministic regression and smoke test suites. Requires no external model API calls. |
| `scripts/verify-real.sh` | Testing | Tests real provider execution (AGY and Droid) when authentication credentials are provided. |
| `scripts/board.sh` | Projection | CLI wrapper for factory board synchronization and status commands. |
| `scripts/board-start.sh` | Service | Starts the board service or registers local projector mode. |
| `scripts/board-stop.sh` | Service | Stops the board daemon service. |
| `scripts/portable-smoke.sh` | Clean-Room | Clones the current commit into a fresh isolated temporary directory and runs the complete test harness. |

---

## 3. Real Provider Prerequisites

### AGY (Antigravity CLI)
- Pre-installed at `/root/.local/bin/agy` or in `$PATH`.
- Must have valid user session or Google credentials.
- Verified model: `gemini-3.8-flash-high`.

### Droid (Factory CLI)
- Pre-installed at `/root/.local/bin/droid` or in `$PATH`.
- Requires `FACTORY_API_KEY` set in the environment for live model invocations:
  ```bash
  export FACTORY_API_KEY="fk-..."
  ```
- Certified model: `qwen3.8-max` with `xhigh` reasoning effort and `auto low` autonomy.
- When `FACTORY_API_KEY` is not present, deterministic tests use the mock DroidAdapter harness without failing structural verification.

---

## 4. herdr-board Compatibility Notice

The factory integrates with upstream `nelsonPires5/herdr-board` via a strict one-way authority contract.

- **Compatibility Gate**: Upstream `herdr-board` release `v0.17.0` pins `SUPPORTED_HERDR_VERSION = "0.9.0"`.
- When the host runs Herdr `0.9.1`, the compatibility status is formally recorded as `BLOCKED_EXTERNAL_COMPATIBILITY`.
- In compliance with the operational invariant, the factory does not patch upstream gates or downgrade Herdr.
- Projection operates via direct machine-readable status serialization (`python3 tools/factory.py board sync`).
