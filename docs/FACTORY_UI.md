# Herdr Orchestrator — Local Control UI

This is the local browser surface for Herdr Orchestrator v9.
It is intentionally a **thin projection and control facade**, not a second orchestrator.

## Design

```text
Factory durable state / policies
        |
        v
FactoryReadModel (read-only)
        |
        v
stdlib HTTP + JSON API
        |
        v
Alpine CSP + Web Awesome
```

The UI has no database, scheduler, routing logic, retry engine, provider client, or model logic of its own.
Factory remains authoritative for goals, runs, tasks, Git integration, context, reasoning policy, validation and certification.

## Run

From the target project directory:

```bash
/path/to/herdr-orchestrator/scripts/ui.sh
```

Or select a target explicitly:

```bash
./scripts/ui.sh --project-root /path/to/project --port 8765
```

Open `http://127.0.0.1:8765`.

The server is loopback-only by design. For remote access, use a trusted SSH tunnel or reverse proxy rather than binding the v1 server to a public interface.

## Frontend dependencies

No Node/npm runtime or build step is required.

Exact browser packages are locked in `ui/vendor.lock.json`:

- `@awesome.me/webawesome` 3.14.0
- `@alpinejs/csp` 3.17.4

On first launch `scripts/vendor_ui.py ensure` downloads the exact npm tarballs, verifies the npm registry SRI, and self-hosts the locked browser assets under `.tools/ui/vendor/`. Subsequent launches are fully local as long as the verified assets remain present.

For an offline launch after the initial sync:

```bash
FACTORY_UI_OFFLINE=1 ./scripts/ui.sh --project-root /path/to/project
```

Manage assets explicitly:

```bash
python3 scripts/vendor_ui.py check
python3 scripts/vendor_ui.py sync
```

`.tools/ui/vendor/` is generated local tooling state and is not committed.

## Source assets

- `ui/index.html`: four-view shell and Web Awesome markup.
- `ui/app.js`: Alpine CSP state, API adapter, polling and detail presentation.
- `ui/factory.css`: layout and Kanban styles.
- `ui/vendor.lock.json`: exact dependency versions and extraction policy.

Generated assets are not committed. SRI proves integrity, not licensing compliance. Before redistributing downloaded assets, review and preserve each upstream package's license and notice requirements; the extractor is not a license-audit tool.

## Views

### Overview

Shows current project, active goal, selected run, task/attempt counts, Factory-supplied context bytes, observed provider usage and aggregated provider/profile status.

### Board

Projects Factory task state into the canonical seven columns:

`BACKLOG -> READY -> RUNNING -> BLOCKED -> REVIEW -> DONE / FAILED`

The board is read-only. There is no drag/drop mutation of scheduler state.

### Goals / Runs

Inspects durable GoalController state, persisted GoalSpec criteria (including provenance/derived-from links), plan/requirement traceability, remediation-round counters, run/task state, deterministic validation evidence, final-audit findings and task evidence.

### System

Shows committed execution profiles, context policy, reasoning policy and external compatibility status.

Task details open in a drawer rather than creating a separate navigation surface. The drawer provides Overview, Requirements, Context, Validation, Git, Attempts and Events tabs. It shows routing/reasoning provenance (profile, model, effort, effort source, escalation), ContextPacket identity/role/compiler/budget metadata, safe included/referenced-file provenance, anchor recall, deterministic validation evidence, commits/changed paths and bounded event/usage summaries. Raw inline file content, raw prompts, raw provider outputs, validation stdout/stderr, source hashes and arbitrary event payloads are deliberately not exposed.

## API

Read endpoints:

- `GET /health`
- `GET /api/v1/snapshot`
- `GET /api/v1/system`
- `GET /api/v1/goals/<goal-id>`
- `GET /api/v1/runs/<run-id>`
- `GET /api/v1/runs/<run-id>/tasks/<task-id>`

`/api/v1/snapshot` has a stable state-derived `ETag`; polling with `If-None-Match` returns `304` when Factory state has not changed.

The only mutable v1 operation is:

- `POST /api/v1/goals/<goal-id>/resume`

It delegates to the existing public `factory.py ... goal resume` operation. It does not implement a second resume path. The UI warns that resuming a real goal may consume provider usage.

There are deliberately no UI-specific `cancel`, `retry`, state-transition, or DAG-edit APIs until Factory exposes stable public operations for those actions.

## Refresh model

The browser uses adaptive polling rather than WebSockets:

- active Factory: ~2 s
- idle: ~8 s
- background browser tab: ~30 s

`ETag`/`304` avoids repeated snapshot payloads when nothing changes. SSE can be added later if measurement demonstrates a real need.

## Security

v1 security is based on a local control surface:

- loopback-only bind;
- loopback/localhost Host validation to resist DNS rebinding;
- no CORS;
- same-origin check for mutations;
- JSON-only bounded action bodies;
- strict path traversal checks for static files and IDs;
- Content Security Policy without `unsafe-eval`;
- Alpine CSP build;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`;
- compact allowlisted fields instead of raw credential/configuration or provider transcript files.

Allowlisting is data minimization, not a guarantee that arbitrary user-supplied titles or other retained text cannot contain a secret. Keep sensitive data out of those fields.

The server returns allowlisted task/attempt/context/validation/event/telemetry projections rather than raw provider prompt/output files. Validation stdout/stderr, arbitrary event payloads, raw telemetry fields, inline ContextPacket content and source-hash fingerprints stay server-side.

## Maintenance rules

1. Keep `FactoryReadModel` read-only.
2. Reuse existing Factory public actions; do not implement scheduler semantics in HTTP handlers.
3. Prefer browser/Web Awesome primitives over custom components.
4. Keep frontend dependencies exact and self-hosted.
5. Do not introduce a frontend database, build pipeline, framework router, WebSocket layer, charting library, or data-grid until a measured requirement justifies it.
6. Keep UI tests provider-free.


## Shared contracts

`tools/factory_contracts.py` is a small pure module shared by the Factory core and the UI. It owns the canonical task-to-Kanban mapping, run/goal terminal semantics, real-only monotonicity helpers and root-scoped `.agy-factory/` Git-status filtering. This prevents the UI from maintaining a second interpretation of scheduler state.
