# Reproducibility — Factory v9.0.0

The default reproducibility workflow is **provider-free**. It should verify repository structure, policies, deterministic behavior, recovery logic, and portability without consuming model quota.

## Clean-checkout workflow

```bash
./scripts/doctor.sh
./scripts/update-package.sh --check
./scripts/bootstrap.sh
./scripts/verify.sh
./scripts/portable-smoke.sh
```

`doctor.sh` and `update-package.sh --check` are read-only diagnostics. `bootstrap.sh` initializes only project-local runtime state.

## Script roles

| Script | Purpose | Provider usage |
| --- | --- | --- |
| `scripts/doctor.sh` | environment/tool/profile diagnostics | none |
| `scripts/update-package.sh --check` | lock/profile/policy compatibility and drift | none |
| `scripts/bootstrap.sh` | project-local runtime preparation | none |
| `scripts/verify.sh` | deterministic regression matrix | none |
| `scripts/portable-smoke.sh` | clean-room portability rehearsal | none |
| `scripts/verify-real.sh` | real-provider verification | **may consume provider usage** |
| `scripts/calibrate_effort.py` | v9 effort calibration | **consumes provider usage when run live** |

Real-provider scripts are not part of routine verification.

## Environment baseline

The last certified stack is recorded in [toolchain.lock.json](toolchain.lock.json). It currently identifies Factory v9.0.0, Herdr 0.9.1/protocol 22, CPython 3.12 stdlib-only policy, and the configured harness CLI versions.

Treat that file as a certified baseline, not proof that the host is unchanged. Use the read-only checks above for drift.

## External project isolation

Factory source and target project are distinct concepts.

```text
factory_root      repository containing tools/factory.py
project_root      Git repository being modified
runtime_root      <project_root>/.agy-factory
```

A clean-room rehearsal should prove that:

- target Git operations affect only the target repository;
- Factory source is not copied into target project source;
- runtime state remains under `.agy-factory/`;
- one target cannot mutate another target;
- no machine-specific absolute paths are required by committed project logic.

## Context/reasoning reproducibility

The following committed artifacts are part of the reproducible execution contract:

- `context_policy.json`
- `reasoning_policy.json`
- `harness_profiles.json`
- schemas under `schemas/`

Context packets are content-addressed/hashed and must fail closed when stale. Reasoning policy provenance tracks the relevant policy/profile/lock evidence.

## Real-provider evidence

A real certification requires truthful provenance and cannot be reproduced provider-free. Missing auth is a valid external blocker.

Do not:

- inject mocks into a real-only run;
- mutate authentication;
- change model families silently;
- downgrade effort below a certified safety minimum just to reduce usage.

## Known external blockers at the documented baseline

- Droid direct profiles: `AUTH_BLOCKED`
- Codex direct profiles: `AUTH_BLOCKED`
- Claude Code direct profiles: `AUTH_BLOCKED`
- Freebuff: `FREEBUFF_HEADLESS_BLOCKED`
- herdr-board: `BLOCKED_EXTERNAL_COMPATIBILITY`

AGY and the OpenCode free profile have retained real-provider certification evidence.

## Historical artifacts

Historical certification narratives are archived under [docs/archive/](docs/archive/README.md). Machine-readable evidence remains under [certification/](certification/README.md).

Do not move runtime/config paths merely for documentation aesthetics.
