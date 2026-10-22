# Herdr Orchestrator — Harness Profiles

Runtime release: **v9.0.0**

Harness profile schema/config version: **6.1.0**

These versions are intentionally independent. The profile schema did not need a breaking contract change merely because the Factory advanced to v9.

The committed catalog and lock preserve historical host observations, including explicit command paths. They are not evidence that those binaries, credentials or models are available on another host today. Host adaptation changes policy provenance and requires appropriate validation; do not silently treat PATH discovery as a renewed provider certification.

## Purpose

Execution profiles separate:

- task capabilities;
- worker/harness identity;
- model family;
- reasoning effort;
- harness-native invocation details;
- concurrency;
- certification/auth state.

The deterministic router selects eligible profiles. The separate v9 Reasoning Policy selects the certified semantic effort for the task/role and may allow one bounded same-model-family escalation.

Authoritative configuration:

- [harness_profiles.json](harness_profiles.json)
- [schemas/harness-profiles.schema.json](schemas/harness-profiles.schema.json)
- [reasoning_policy.json](reasoning_policy.json)
- [toolchain.lock.json](toolchain.lock.json)

## Historical configured profile families

| Family | Configured models | Recorded state |
| --- | --- | --- |
| AGY | Gemini 3.8 Flash; Claude Sonnet 4.6 audit profile | real-provider certified profiles |
| Droid | Qwen3.8 Max | adapter/profile implementation deterministic; direct profiles recorded AUTH_BLOCKED |
| Codex | GPT-5.6 Luna | adapter/profile implementation deterministic; direct profiles recorded AUTH_BLOCKED |
| Claude Code | Claude Sonnet 5 | adapter/profile implementation deterministic; direct profiles recorded AUTH_BLOCKED |
| OpenCode | OpenRouter free; Gemini profile | free profile REAL_PROVIDER_CERTIFIED; Gemini profile PROFILE_UNAVAILABLE |

Do not collapse these states into a single “certified” label. “Implemented”, “deterministically tested”, “transport available”, “authenticated”, and “REAL_PROVIDER_CERTIFIED” are different facts.

## Data model

Each profile defines the fields required by the schema, including:

- `id`
- `adapter`
- `harness`
- `enabled`
- `command`
- `worker_identity`
- `model`
- `effort`
- `capabilities`
- `max_concurrency`
- `native`
- `certification`

Harness-native semantics remain under `native`; the Factory does not pretend all CLIs share one universal option set.

## Effort semantics

Effort is model-specific.

The current v9 policy has ordered ladders for the configured model families, but runtime selection is always validated against the profile/model family and the committed Reasoning Policy.

The important invariant is:

```text
task + execution_class
      |
      v
router -> harness/model family
      |
      v
reasoning_policy -> semantic effort
      |
      v
adapter -> native CLI representation
```

Unsupported combinations fail closed.

## Reasoning Policy relationship

The v9 policy is an **initial evidence-backed default**, not a universal optimum.

Its primary worker convention is:

- routine: low where supported/certified;
- standard: medium;
- deep: high;
- final audit: conservative high.

At most one effort escalation is allowed by default, within the same model family.

Escalation is reserved for reasoning-quality failures. The following must not cause effort escalation:

- authentication/provider/infrastructure failures;
- timeouts classified as infrastructure;
- Git/worktree failures;
- context guard failures;
- path/scope guardrail violations such as `PATH_VALIDATION_FAILED`.

## Auth and availability

Profile `enabled=true` does not guarantee that a live provider can be used at this moment.

Use read-only diagnostics:

```bash
./scripts/doctor.sh
./scripts/update-package.sh --check
python3 tools/factory.py profile validate
```

Do not log in, replace credentials, or mutate global harness configuration merely to make a profile appear available.

## Drift governance

`toolchain.lock.json` records the last certified environment, while live diagnostics detect drift.

Relevant states include:

- `REAL_PROVIDER_CERTIFIED`
- `AUTH_BLOCKED`
- `PROFILE_UNAVAILABLE`
- `PROFILE_INVALID`
- `PROFILE_DRIFT`
- `NEEDS_REVALIDATION`

A model/effort becoming unavailable is a policy/profile drift condition, not permission to silently substitute another model.

## External compatibility

Current committed lock records:

- Freebuff: `FREEBUFF_HEADLESS_BLOCKED`

Freebuff remains an external blocker and should not be worked around with TUI scraping, unsupported patches, or fake certification. The legacy `herdr-board` integration is retired; Herdr Orchestrator UI owns the supported Kanban/status surface.

See [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) for the concise current baseline.
