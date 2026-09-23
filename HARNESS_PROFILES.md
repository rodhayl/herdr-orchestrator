# HARNESS_PROFILES.md — Harness Execution Profiles Specification

The **Harness Profile** system defines the boundary between task routing and harness-specific execution in the AGY-Herdr Software Factory v6.0.0.

---

## 1. Architectural Purpose

In v4 and earlier, task definitions were bound directly to worker IDs (e.g. `agy3`, `droid`). This coupled scheduling to specific agent instances and obscured model, reasoning effort, and invocation parameters.

In v5 and v6, the factory scheduler operates on **Execution Profiles** deterministically selected from task requirements and semantic **Execution Classes** (`routine`, `standard`, `deep`):

```
                       Task Requirements + Execution Class
                                        |
                                        v
                              Deterministic Router
                                        |
                                        v
                                Execution Profile
                                        |
        +---------------+---------------+---------------+---------------+---------------+
        |               |               |               |               |
        v               v               v               v               v
   AgyAdapter      DroidAdapter    CodexAdapter    ClaudeAdapter  OpenCodeAdapter
        |               |               |               |               |
     AGY CLI       Droid Exec      Codex Exec      Claude Code     OpenCode CLI
```

The Factory core treats execution profiles as normalized entities specifying:
1. **Capabilities**: What tasks the profile can perform.
2. **Normalized Model & Effort**: Semantic representation of reasoning capacity.
3. **Adapter & Command**: The executable substrate.
4. **Native Configuration**: Harness-specific parameters that must not be flattened into universal options.
5. **Execution Class Suitability**: Natural alignment to routine, standard, or deep reasoning workloads.

---

## 2. Profile Data Model

Profiles are stored in [`harness_profiles.json`](file:///root/agy-herdr-factory-poc/harness_profiles.json) and validated against [`schemas/harness-profiles.schema.json`](file:///root/agy-herdr-factory-poc/schemas/harness-profiles.schema.json).

### Core Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `string` | Unique alphanumeric identifier (e.g., `claude-sonnet5-high`). |
| `name` | `string` | Human-readable name. |
| `adapter` | `string` | Production adapter class (`agy`, `droid`, `codex`, `claude`, `opencode`). |
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

## 3. Effort Semantics Across Supported Harnesses

Reasoning effort is model- and harness-specific. A universal enum does not have uniform meaning across providers:
- **AGY CLI**: Appends effort directly to model names (e.g. `gemini-3.8-flash-high`) or accepts `--effort low|medium|high`.
- **Droid CLI**: Validates effort against the specific selected model (e.g. `qwen3.8-max` supports `[none, low, medium, high, xhigh]`).
- **Codex CLI**: Passes `-c model_reasoning_effort="<low|medium|high|xhigh>"` to the OpenAI backend.
- **Claude Code CLI**: Passes `--effort <low|medium|high|xhigh|max>` with non-interactive `-p` execution.
- **OpenCode CLI**: Maps effort to `--variant <variant>` (e.g. `high`, `deep`, `fast`, `free`, `default`) with `opencode run`.

**Rule**: The Factory records normalized `effort` in the profile, and each **WorkerAdapter** translates that value into the exact CLI invocation for that specific harness and model. If a profile declares unsupported effort levels, validation fails closed with `PROFILE_INVALID`.

---

## 4. Production Profiles (v6.0.0)

### 4.1 AGY Profiles
* **`agy-spec-high`**: Model `gemini-3.8-flash`, Effort `high`, Worker `agy2`.
* **`agy-backend-high`**: Model `gemini-3.8-flash`, Effort `high`, Worker `agy3`.
* **`agy-backend-medium`**: Model `gemini-3.8-flash`, Effort `medium`, Worker `agy3`.
* **`agy-frontend-high`**: Model `gemini-3.8-flash`, Effort `high`, Worker `agy4`.
* **`agy-frontend-medium`**: Model `gemini-3.8-flash`, Effort `medium`, Worker `agy4`.
* **`agy-tests-medium`**: Model `gemini-3.8-flash`, Effort `medium`, Worker `agy5`.
* **`agy-integration-high`**: Model `gemini-3.8-flash`, Effort `high`, Worker `agy6`.
* **`agy-audit-high`**: Model `claude-sonnet-4-6`, Effort `high`, Worker `agy7`.

### 4.2 Droid Profiles
* **`droid-backend-medium`**: Model `qwen3.8-max`, Effort `medium`, Worker `droid`.
* **`droid-backend-xhigh`**: Model `qwen3.8-max`, Effort `xhigh`, Worker `droid`.
* **`droid-backend-deep`**: Backward compatibility alias to `droid-backend-xhigh`.

### 4.3 Codex Profiles
* **`codex-luna-medium`**: Model `gpt-5.6-luna`, Effort `medium`, Worker `codex`.
* **`codex-luna-high`**: Model `gpt-5.6-luna`, Effort `high`, Worker `codex`.
* **`codex-luna-xhigh`**: Model `gpt-5.6-luna`, Effort `xhigh`, Worker `codex`.
* **`codex-frontend-high`**: Backward compatibility alias to `codex-luna-high`.

### 4.4 Claude Profiles
* **`claude-sonnet5-high`**: Model `claude-sonnet-5`, Effort `high`, Worker `claude`.
  * Command: `/root/.local/bin/claude`
  * Native: `{"permission_mode": "acceptEdits", "output_format": "json", "no_session_persistence": true}`
* **`claude-sonnet5-medium`**: Model `claude-sonnet-5`, Effort `medium`, Worker `claude`.

### 4.5 OpenCode Profiles
* **`opencode-gemini-high`**: Model `google/gemini-3.8-flash`, Variant/Effort `high`, Worker `opencode`.
  * Command: `/root/.opencode/bin/opencode`
  * Native: `{"pure": true, "auto": true, "format": "json"}`
* **`opencode-mimo-free`**: Model `opencode/mimo-v2.6-flash-free`, Variant/Effort `free`, Worker `opencode`.
  * Command: `/root/.opencode/bin/opencode`
  * Native: `{"pure": true, "auto": true, "format": "json"}`

---

## 5. Profile Lifecycle & Governance

1. **Desired State**: Defined in [`harness_profiles.json`](file:///root/agy-herdr-factory-poc/harness_profiles.json).
2. **Validation**: Verified against live installed CLI catalogs via `python3 tools/factory.py profile validate`.
3. **Certified Lock**: Last verified live stack recorded in [`toolchain.lock.json`](file:///root/agy-herdr-factory-poc/toolchain.lock.json).
4. **Drift Detection**: `scripts/update-package.sh --check` alerts on `PROFILE_DRIFT` if upstream tool updates remove configured models or reasoning effort levels.
