# Source snapshot validation — 2026-10-22

## Scope and provenance

Reviewed the 153-file source tree `7f0bc4e3aee049d9ca71f2d3a2f6f7383366f995` at baseline commit `479a4e9415e3f2f4e4b459ab083cd0f98db30d17`. The maintenance delta retains active runtime modules, application examples, versioned tests, schemas and evidence consumed by policy provenance.

Five review lenses cover the source inventory: purpose and content; dependency/reachability analysis; documentation and links; privacy and licensing; final change-impact verification. This combines complete inventories and machine-assisted structural analysis with focused semantic reading and deterministic tests, not a claim of five manual line-by-line security audits.

Redundant historical narratives are consolidated in `UPDATE_HISTORY.md`. Five unconsumed raw historical prompts and a bare MiniLinks certification stub are omitted. The v7 aggregate metrics are preserved byte-for-byte in `certification/v7/context-baseline-metrics.json`; historical prompt-level reconstruction is no longer available. No historical numerical measurement or verdict was rewritten.

## Initial cleanup verification

Validation environment: CPython 3.12.14, Git 2.52.0, Linux. JavaScript syntax checking uses Node 24.19.0 only as a development check; Node is not a runtime dependency. The historical lock is unchanged, not refreshed to imply a newly certified provider stack.

- Strict provider-free package compatibility check: PASS; reasoning-policy provenance VALID, provider probes skipped.
- Full `scripts/verify.sh`: PASS, exit 0, preserving Git HEAD and status.
- Factory: 381 tests, zero failures/errors, one explicit live-Herdr skip.
- MiniBoard: 34 tests PASS and its 12-step HTTP smoke PASS.
- MiniLinks: 51 tests PASS and its 12-step HTTP smoke PASS (including the archive/restore substep).
- Nine added maintenance regressions cover bootstrap scope/identity, current status version, explicit binary overrides, config-collection removal, ignore rules and the three directory-fsync error paths. Seven defect-specific cases reproduced the original failures before repair; the existing v3 status test was updated from an obsolete v3–v6 list to the current engine contract.
- Python AST, all committed JSON/JSONL, shell syntax and JavaScript syntax checks: PASS. Relative documentation links and removal references: no broken targets found.

The initial cleanup tree contained 140 files, down from 153. Fifteen old paths were removed, including the aggregate metrics' former path; two paths were added, including its exact relocation and the regression module. No active runtime module, application, consumed schema or versioned regression module was deleted.

The first full run correctly rejected the newly accurate v9 status value because one old test only allowed versions 3–6. After aligning that assertion with the current engine constant, the full five-suite run passed. Later changes were limited to prose and the demo plan's description of its existing `(server, thread)` return contract; plan validation and static/link checks were repeated.

These are local deterministic results, not GitHub Actions CI or fresh real-provider certification.

## Presentation naming follow-up

A focused follow-up on source tree `b1f457272dcb5fb1bce7b58eada542b3c70b1a5c` corrected legacy visible branding missed by the earlier cleanup. The README, current documentation, CLI help/banners and local UI now use **Herdr Orchestrator**. Internal engine paths, provider identifiers, state roots, environment variables and API/schema keys remain compatible. The catalog description and its active provenance fingerprint changed together; profile definitions, calibration dates and historical evidence are unchanged.

Four added regressions first failed against the old presentation and then passed. They cover documentation/catalog naming, actual CLI help, and the real HTML and snapshot HTTP endpoints, including stable frontend bindings and `.agy-factory` state paths. The complete provider-free verification matrix was rerun: **385 Factory tests (one live-Herdr skip), 34 MiniBoard tests, 51 MiniLinks tests, and both 12-step HTTP smoke suites passed**, with Git HEAD/status preserved. Strict compatibility/provenance and final static/link checks also passed. This follow-up adds one regression module, for **141 files**, without deleting or renaming runtime paths.

These are local deterministic and HTTP checks, not a visual-browser acceptance run, GitHub Actions CI, provider recertification or a new full security audit.

## Boundaries

No real provider inference, authentication change, generated vendor redistribution, deployment or repository visibility change is part of this validation. Herdr is unavailable here, so the live-Herdr test is skipped and `portable-smoke.sh` is not claimed PASS. Browser/live-provider acceptance and production readiness are not established by offline tests.

No usable credentials or unrelated private-project content were detected in the reviewed source snapshot; that is a bounded inspection result, not a guarantee of absence. A project license has not been chosen. No existing license or notice was removed; future vendor redistribution needs its own license/notice review.

This review does not certify or purge old Git objects, pull-request references, caches, forks or attachments. Repository visibility remains a separate owner decision.
