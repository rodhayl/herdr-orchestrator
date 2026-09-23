# HARNESS_PROFILES.md — Harness Execution Profiles Specification

The **Harness Profile** system defines the boundary between task routing and harness-specific execution in the AGY-Herdr Software Factory v5.0.0.

---

## 1. Architectural Purpose

In v4 and earlier, task definitions were bound directly to worker IDs (e.g. `agy3`, `droid`). This coupled scheduling to specific agent instances and obscured model, reasoning effort, and invocation parameters.

In v5, the factory scheduler operates on **Execution Profiles**:

```
                       Task Requirements
                               |
                               v
                     Deterministic Router
                               |
                               v
                       Execution Profile
                               |
           +-------------------+-------------------+
           |                   |                   |
           v                   v                   v
      AgyAdapter          DroidAdapter        CodexAdapter
           |                   |                   |
        AGY CLI            Droid Exec          Codex Exec
```

The Factory core treats execution profiles as normalized entities specifying:
1. **Capabilities**: What tasks the profile can perform.
2. **Normalized Model & Effort**: Semantic representation of reasoning capacity.
3. **Adapter & Command**: The executable substrate.
4. **Native Configuration**: Harness-specific parameters that must not be flattened into universal options.

---

## 2. Profile Data Model

Profiles are stored in [`harness_profiles.json`](file:///root/agy-herdr-factory-poc/harness_profiles.json) and validated against [`schemas/harness-profiles.schema.json`](file:///root/agy-herdr-factory-poc/schemas/harness-profiles.schema.json).

### Core Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `string` | Unique alphanumeric identifier (e.g., `droid-backend-deep`). |
| `name` | `string` | Human-readable name. |
| `adapter` | `string` | Production adapter class (`agy`, `droid`, `codex`). |
| `harness` | `string` | Harness family (`agy`, `droid`, `codex`, `claude`, `opencode`). |
| `enabled` | `boolean` | Whether the profile is eligible for routing. |
| `command` | `string` | Executable path or binary name. |
| `worker_identity` | `string` | Assigned worker identity / Herdr profile binding. |
| `model` | `string` | Model family / identifier. |
| `effort` | `string` | Normalized reasoning effort level. |
| `capabilities` | `list[str]` | Set of satisfied capability tags. |
| `max_concurrency`| `int` | Maximum concurrent tasks allowed (default `1`). |
| `native` | `object` | Adapter-owned native execution parameters. |
| `certification` | `object` | Last certified timestamp, status, and audit notes. |

---

## 3. Effort Semantics: Why Effort is Not a Universal Enum

Reasoning effort is model- and harness-specific. A universal enum (`low`, `medium`, `high`, `xhigh`, `max`) does not have uniform meaning across providers:
- **AGY CLI**: Appends effort directly to model names (e.g. `gemini-3.8-flash-high`) or accepts `--effort low|medium|high`.
- **Droid CLI**: Validates effort against the specific selected model (e.g. `qwen3.8-max` supports `[off, low, medium, high, xhigh]`; other models only support up to `high`).
- **Codex CLI**: Passes `-c model_reasoning_effort="high"` to the OpenAI Responses backend.
- **Claude Code**: Uses adaptive thinking / budget tokens rather than discrete enum levels.
- **OpenCode**: Maps effort to model variants (e.g. `#high`, `#max`) or variant configurations.

**Rule**: The Factory records normalized `effort` in the profile, but the **WorkerAdapter** owns translating that value into the exact CLI invocation for that specific harness and model. If a model does not support the configured effort, validation fails closed with `PROFILE_INVALID`.

---

## 4. Production Profiles (v5.0.0)

### 4.1 AGY Profiles
* **`agy-spec-high`**: Model `gemini-3.8-flash`, Effort `high`, Worker `agy2`.
* **`agy-backend-high`**: Model `gemini-3.8-flash`, Effort `high`, Worker `agy3`.
* **`agy-frontend-high`**: Model `gemini-3.8-flash`, Effort `high`, Worker `agy4`.
* **`agy-tests-medium`**: Model `gemini-3.8-flash`, Effort `medium`, Worker `agy5`.
* **`agy-integration-high`**: Model `gemini-3.8-flash`, Effort `high`, Worker `agy6`.
* **`agy-audit-high`**: Model `claude-sonnet-4-6`, Effort `high`, Worker `agy7`.

### 4.2 Droid Profile
* **`droid-backend-deep`**:
  * Harness: `droid`
  * Model: `qwen3.8-max`
  * Effort: `xhigh`
  * Capabilities: `[coding, backend, testing, debugging, mechanical_change]`
  * Native: `{"autonomy": "low"}`
  * Note: Requires `FACTORY_API_KEY` for live upstream execution. Certified deterministically in test harness.

### 4.3 Codex Profile
* **`codex-frontend-high`**:
  * Harness: `codex`
  * Model: `gpt-5.6-luna`
  * Effort: `high`
  * Capabilities: `[coding, frontend, debugging, testing, review]`
  * Native:
    * `sandbox`: `workspace-write`
    * `approval_policy`: `never`
    * `network_access`: `false`
    * `ephemeral`: `true`
  * Note: Requires OpenAI/Codex authentication in `~/.codex/auth.json` or `OPENAI_API_KEY`. Certified deterministically in test harness.

---

## 5. Future Harness Readiness (Claude & OpenCode)

While production adapters for Claude and OpenCode are deferred to v6, the v5 Harness Profile schema already accommodates their semantics:

### 5.1 Claude Code
* **Harness**: `claude`
* **Adapter**: `claude` (future)
* **Model**: e.g., `claude-sonnet-4-6`
* **Effort**: Normalized to `high` / `medium` / `low`
* **Native**:
  ```json
  "native": {
    "permission_mode": "accept-edits",
    "dangerously_skip_permissions": true
  }
  ```
* **Invocation**: `claude -p "<prompt>" --model <model> --dangerously-skip-permissions`

### 5.2 OpenCode
* **Harness**: `opencode`
* **Adapter**: `opencode` (future)
* **Model**: `provider/model` (e.g. `openrouter/openai/gpt-5.6-luna`)
* **Effort**: Maps to model variant string (e.g. `#high`)
* **Native**:
  ```json
  "native": {
    "variant": "high",
    "auto": true
  }
  ```
* **Invocation**: `opencode run --pure --auto -m <provider/model> "<prompt>"`

---

## 6. Profile Lifecycle & Governance

1. **Desired State**: Defined in [`harness_profiles.json`](file:///root/agy-herdr-factory-poc/harness_profiles.json).
2. **Validation**: Verified against live installed CLI catalogs via `python3 tools/factory.py profile validate`.
3. **Certified Lock**: Last verified live stack recorded in [`toolchain.lock.json`](file:///root/agy-herdr-factory-poc/toolchain.lock.json).
4. **Drift Detection**: `scripts/update-package.sh --check` alerts on `PROFILE_DRIFT` if upstream tool updates remove configured models or reasoning effort levels.
