# Herdr Orchestrator — Reproducibility

## Offline source verification

Use Python 3.12 and Git from a checkout of this repository:

```bash
FACTORY_PROVIDER_PROBES=0 ./scripts/update-package.sh --check
./scripts/verify.sh
```

This path uses Python's standard library, synthetic fixtures and local temporary repositories/HTTP servers. It does not require provider credentials or live Herdr. A live-Herdr test is explicitly skipped if that CLI is absent. The runner forces strict provider-probe suppression and verifies unchanged Git HEAD/status.

`bootstrap.sh` is optional for this workflow. It initializes ignored runtime state in its own repository and configures only that repository's Git identity if no identity is already available. It does not manufacture Herdr session IDs.

See [snapshot validation](docs/PORTFOLIO_VALIDATION.md) for the exact tested environment and limits.

## Host-dependent, provider-free checks

```bash
FACTORY_PROVIDER_PROBES=0 ./scripts/doctor.sh
./scripts/portable-smoke.sh
```

These are **not** the offline quick start. `doctor.sh` checks live Herdr prerequisites and can fail when Herdr is missing. `portable-smoke.sh` clones committed Git content into a disposable directory, calls doctor, then runs bootstrap and verification. It therefore needs the compatible Herdr host prerequisites too; it does not include uncommitted edits.

Both can suppress provider CLI calls, but “provider-free” does not mean “host-independent.” No portable-smoke PASS is claimed for an environment without Herdr.

## Live execution

The historical `toolchain.lock.json` records Factory 9.0.0, Herdr 0.9.1/protocol 22 and then-observed CLI versions. Profile commands and host paths are historical configuration, not portable installation instructions. Configure explicit commands for the intended host, inspect binary identity and auth state, and respect reasoning-policy provenance checks before execution. Do not silently reinterpret old certification as certification of another executable.

| Tool | Boundary |
| --- | --- |
| `update-package.sh --check` | Read-only compatibility; provider CLI version probes unless `FACTORY_PROVIDER_PROBES=0` |
| `doctor.sh` | Read-only host diagnostics; provider metadata/auth probes unless strict mode |
| `update-package.sh --apply` | Changes the lock; refuses strict mode to avoid certifying stale versions |
| `verify.sh` | Offline deterministic regression; strict mode enforced |
| `portable-smoke.sh` | Committed clean-checkout rehearsal with Herdr prerequisites; strict mode enforced |
| `verify-real.sh` | Real execution, may consume provider usage |
| `calibrate_effort.py` | Live calibration consumes provider usage |

Authentication failure is a valid blocker. Do not inject mocks into a real-only run, mutate credentials, silently change model families or lower certified safety minima to obtain a green result.

## Isolation and evidence

Factory source, target project and runtime state are separate:

```text
factory_root = repository containing tools/factory.py
project_root = Git repository being modified
runtime_root = <project_root>/.agy-factory
```

Task worktrees and path checks do not sandbox arbitrary processes. Use synthetic data and independent operating-system isolation when inspecting generated code.

Policies and schemas are committed reproducibility inputs. Context packets are hashed and stale packets fail closed. Reasoning-policy provenance checks relevant profile, lock and calibration evidence. Versioned tests and calibration fixtures remain because they are consumed, including fixtures with intentional faults.

[Certification records](certification/README.md) preserve historical measurements. The v7 aggregate context baseline is retained byte-for-byte, but its raw prompt transcripts are omitted; prompt-level reproduction of that old measurement is not available from this snapshot. Historical provider-backed results cannot be reproduced with offline tests. Generated runtime state is neither committed nor guaranteed to be recoverable from the current Git ancestry.
