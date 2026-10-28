# Forma Studio v1.4 — Implementation Tracker

**Last updated:** 2026-10-28

**Current focus:** JOB-07C — build/runtime provenance (next slice; not started)

**Status legend:** `[x]` accepted and verified · `[ ]` not complete · **Partial** means useful foundations exist but the acceptance gate remains open

This is the persistent implementation record for the approved sequence:

> Baseline → durable jobs → AppSpec → deterministic verification → specialist workers → runtime hardening and scale

Do not mark a milestone complete until its acceptance gate is verified. Keep schemas additive, preserve published applications, and retain legacy behavior behind feature flags.

## Latest completed increment — VER-04 release gate and verification visibility

- [x] **VER-04A — Verification API.** Synchronous and deferred verification endpoints expose running state and persisted reports; deferred failures produce actionable project errors and agent messages.
- [x] **VER-04B — Publish enforcement.** New publishes require fresh full-coverage verification when the gate is enabled. Idempotent republishing is allowed, and failed verification leaves the existing release online.
- [x] **VER-04C — Verification panel.** The panel exposes status, coverage, failed checks, tools, targets, durations, actionable errors, and optional migration checks with responsive desktop/mobile layouts.
- [x] **VER-04D — Regression coverage.** Pass/fail gates, legacy flag-off behavior, report APIs, deferred refresh and failure reporting, single-file source materialization, and verification panel states are covered.

## Earlier completed increment — VER-03 deployment registry lookup

- [x] **Registry-only public lookup.** Public HTML, assets, and API routing resolve deployment metadata from the control-plane registry instead of scanning every user database.
- [x] **Owner-scoped artifacts.** Published source is read only from the registered owner’s workspace and selected published version.
- [x] **Write-through synchronization.** Publish, republish, unpublish, and project deletion update registry rows atomically with the existing workflow.
- [x] **Backfill and version compatibility.** Backfill upgrades stale rows with version-specific architecture and source format; migration preserves the published deployment until explicit republication.
- [x] **Verification evidence.** Registry write-through, backfill, no-scan lookup, migration, republication, and all existing public-hosting regressions pass.

## Earlier completed increment — VER-02 verifier and report model

- [x] **Durable verification jobs.** Idempotent verification, forced retry attempts, heartbeat, and persisted report events are integrated with the existing job runner.
- [x] **Tool-run provenance.** Every check records its tool, input hash, output reference, status, timestamps, duration, environment names, and spec/source hashes without exposing credential values.
- [x] **Deterministic report model.** Reports distinguish passed, failed, blocked, skipped, and warning states, include actionable errors and tool-run IDs, and require full required-check coverage for `can_publish`.
- [x] **Build/runtime and browser execution.** Acceptance artifacts are rematerialized after staging, generated runtimes are health-checked and cleaned up, and Playwright runs with an available system Chrome or configured browser path.
- [x] **Verification evidence.** Pass/fail/blocked/warning outcomes, partial coverage, stale hashes, forced retries, live FastAPI/CRUD/security, and real Playwright checks pass. Publish enforcement and the verification UI remain VER-04.

## Earlier completed increment — VER-01 acceptance generation

- [x] **VER-01A — Acceptance manifest.** Deterministic check IDs, provenance hashes, required environment, timeouts, and mutation flags are generated for every AppSpec build.
- [x] **VER-01B — API and persistence checks.** Health, CRUD, required-validation, and restart-persistence tests are generated from the declared entity and operations.
- [x] **VER-01C — Browser, security, and migration checks.** Primary workflow, field validation, credential/host policy, migration history, and republishing tests are generated.
- [x] **VER-01D — Version integration.** Acceptance artifacts are stored beside each AppSpec build and excluded from generation inputs and frontend build hashes.
- [x] **VER-01E — Verification.** Output is deterministic, generated security checks execute and detect violations, generated API tests pass against a live backend, and full regressions pass. Execution reports and publish gating remain VER-02/VER-04.

## Earlier completed increment — Deterministic package builds

- [x] **Complete-source overlay.** Generated changes are applied to the previous complete package, preserving required components when model file lists are partial.
- [x] **Relative-import validation.** Every import resolves before Vite, with missing-component and traversal errors reported before build or semantic repair.
- [x] **Deterministic staging and promotion.** Builds use `versions/vN.staging`, promote only after success, clean failed staging, and preserve the last usable version. Backend runtimes consume promoted packages.
- [x] **Cruto recovery and regression.** Versions 2 and 3 were rebuilt from complete existing sources with workspace backups; the full backend, frontend, runtime, and multi-file browser checks pass.

## Earlier completed increment — SPEC-06 contract review

- [x] **SPEC-06A — Pre-build draft.** Planning generates a validated AppSpec at version 0 before the first application build.
- [x] **SPEC-06B — Feedback and compatibility.** Plan feedback and pre-build architecture changes revise the draft; the first build reuses it, and legacy/flag-off behavior remains intact.
- [x] **SPEC-06C — Review API and invalid-contract gate.** Project payloads expose parsed metadata and schema/hash status; invalid drafts are rejected before approval or compilation.
- [x] **SPEC-06D — Contract panel.** Product, entity, API, dependency, manifest, and acceptance sections are inspectable with responsive styling and an approval guard.
- [x] **SPEC-06E — Verification.** Pre-build review, revision, invalid drafts, first-build reuse, component rendering, focused desktop/mobile browser flow, and full regressions pass.

## Earlier completed increment — SPEC-03 schema-aware generation

- [x] **SPEC-03A — Structured proposal transport.** Provider JSON Schema is supported with a structured-JSON compatibility fallback; existing truncation repair remains intact.
- [x] **SPEC-03B — Proposal normalization and bounded repair.** Studio owns name, architecture, dependencies, and manifest policy. Valid JSON with an invalid contract receives exactly one semantic repair.
- [x] **SPEC-03C — Deterministic source synthesis.** One declared entity and its reviewed CRUD contract compile into single-file or multi-file applications without model-supplied source blobs.
- [x] **SPEC-03D — Engine integration.** Builds, refinements, and migrations consume previous AppSpecs rather than provider file maps. Legacy-source and flag-off behavior remain intact.
- [x] **SPEC-03E — Verification.** Invalid proposals, repair bounds, deterministic output, both architectures/formats, real CRUD/persistence, Vite builds, deferred jobs, and the complete regression suite pass.

**v1 synthesis boundary:** exactly one entity and reviewed collection CRUD routes. Multi-entity relationships and arbitrary operations remain later extensions; the compiler rejects them clearly rather than silently emitting an unrelated template.

## Earlier completed increment — AppSpec compatibility slice

- [x] **SPEC-01 — Versioned AppSpec schema.** Typed product, architecture, entity, API, frontend, dependency, manifest, and acceptance sections reject invalid references before compilation.
- [x] **SPEC-02 — Deterministic package compiler.** Documented path aliases, allowed paths, ownership, size limits, reviewed dependencies, and deterministic source/spec hashes are implemented and tested.
- [x] **SPEC-04 — Legacy adapter.** Existing single-file and multi-file packages are represented without regeneration while preserving source, architecture, and source format.
- [x] **SPEC-05A — Dual-write generation.** With `APPSPEC_V1` enabled, new and migrated versions store `appspec.json` and `build-manifest.json`. Existing generators still produce source in this slice.
- [x] **SPEC-05B — Compatibility verification.** Both source formats and architectures, bidirectional migration, durable/deferred autopilot, flag-off behavior, real Vite preview, and deployment archives pass.

**Status:** AppSpec is now the source contract when enabled; legacy generation remains available with the flag off. Next is optional contract review (SPEC-06), followed by deterministic verification.

## Milestone 0 — Baseline and compatibility

- [x] **BASE-01 — Reproducible evaluation baseline.** Schema 1.2, deterministic quality metrics, two semantically identical captures, directional accepted thresholds, and case-level regression checks are implemented and verified.
- [x] **BASE-02 — Typed feature flags.** `backend/app/features.py`, settings, `.env.example`, and `backend/tests/test_features.py`; every flag defaults off and invalid booleans are rejected.
- [x] **BASE-03 — Compatibility fixture pack.** Versioned checksum-linked project/provider/package fixtures cover all architecture, history, and publication combinations, with isolated materialization and real consumer integration.

**Milestone gate:** `[x]` The checked-in 1.2 baseline validates, repeated quality captures are semantically identical, comparison rejects injected regressions with case IDs, and the reusable fixture matrix passes.

## Milestone 1 — Durable job orchestration

- [x] **JOB-01 — Additive durable schemas.** Job, attempt, event, tool-run, usage, and deployment-registry tables migrate repeatedly without changing existing project tables.
- [x] **JOB-02 — Leasing and idempotency.** Stable keys, guarded attempts, heartbeat, expiration recovery, cancellation, and stale-finalization checks are covered by `test_job_service.py`.
- [x] **JOB-03 — Durable generation runner.** Stage generation, document revision, and architecture migration use `backend/app/jobs/runner.py` when enabled. `complete_package` remains inside its parent stage job by design.
- [x] **JOB-04 — Preserve synchronous and deferred behavior.** Engine wrappers route deferred and synchronous work through the durable runner under `DURABLE_JOBS_V1`; legacy scheduling remains the fallback.
- [x] **JOB-05 — Resumable event delivery.** Versioned replay, live delivery, reconnect, polling fallback, authoritative reconciliation, and fault coverage are complete.
- [x] **JOB-06 — End-to-end cooperative cancellation.** Cancellation is owner-scoped and idempotent, with attempt-scoped context, provider/process cleanup, atomic finalization guards, rollback of attempt-owned source and reports, and a busy-state Builder cancel control.
- [ ] **JOB-07 — Usage and provenance tracking.** Wire provider/model, tokens, cost, retries, build duration, runtime health, and source hashes into tool runs and the usage ledger.

**Milestone gate:** `[ ]` Telemetry remains open; event delivery and cancellation are complete.

**Deferred by design:** BASE-01, BASE-03, JOB-05, and JOB-06 are complete. JOB-07C/D still need build/runtime provenance and owner-only usage inspection. They remain deliberate follow-ups before specialist workers, not completed capabilities or forgotten tasks.

## Next checkpoint — BASE/JOB pre-specialist readiness

**Checkpoint status:** `[ ]` In progress — BASE-01, BASE-03, JOB-06, JOB-05A–C, and JOB-07A/B are complete; JOB-07C is the next review slice.

**Starting revision:** `a706e5a` (`Gate new releases with deterministic verification`).

**Starting evidence:** 143 backend tests, 12 frontend unit tests, and 6 targeted browser journeys passed; production build and Ruff were clean.

**Goal:** Close Milestones 0 and 1 before WRK-01. Establish reproducible quality evidence, safe attempt ownership, resumable progress, and complete provenance before work is divided among specialist workers. Do not enable specialist-worker behavior or change the release-gate semantics in this checkpoint.

### Execution order and review slices

1. **BASE-01A** — versioned baseline schema and capture contract.
2. **BASE-03A–C** — reusable compatibility fixtures and their validation.
3. **BASE-01B–C** — fixture-driven quality metrics, reproducibility, and baseline comparison.
4. **JOB-06A–C** — cooperative cancellation, process cleanup, and guarded finalization.
5. **JOB-05A–C** — ordered event replay, SSE delivery, UI reconnect, and polling fallback.
6. **JOB-07A–D** — provider/build/runtime telemetry and owner-only usage visibility.

The ID order is intentionally not the execution order. Fixtures supply BASE-01's quality corpus; cancellation defines terminal semantics before the event UI consumes them; telemetry instruments the finalized tool boundaries. Each numbered slice is independently reviewable and committable only after its focused tests and the full regression pass. Do not batch the entire checkpoint into one implementation commit.

### BASE-01 — Reproducible evaluation baseline

- [x] **BASE-01A — Versioned report contract.** `backend/app/evaluation/baseline.py` and the checked-in `baseline.schema.json` define the 1.1 report with revision, dirty-tree state, feature flags, Python/Node/platform metadata, fixture-pack provenance, and mandatory skip reasons. New captures write validated 1.1 documents with redacted metadata; existing 1.0 reports remain readable without fabricated fields. `--write-schema` and schema-drift tests keep the contract synchronized.
- [x] **BASE-01B — Deterministic generation-quality metrics.** The offline runner and checked-in `generation.json` record 22/22 successful cases with stable IDs and expected/actual outcomes. Metrics cover first-pass proposal validity (5/9), repair invocation (3/9), repair success (3/3), source/import validity (12/12), production builds (2/2), runtime health (2/2), full verification (2/2), publish-gate decisions (2/2), and deterministic hashes (5/5). Schema 1.2 embeds this evidence in full captures; suite-only 1.1 and legacy 1.0 reports remain readable. No timing or external-provider availability is used as a quality threshold.
- [x] **BASE-01C — Repeatability and comparison.** Two independent quality captures are semantically identical and match the accepted report. `capture_baseline.py --check` derives minimum/maximum rates and expected denominators from the accepted 1.2 baseline, ignores timestamps and suite durations, supports reusable `--generation-report` evidence, and rejects injected failures with actionable case IDs. The checked-in full baseline validates against the current schema; real-provider smoke remains separate and opt-in.

**Primary files:** `backend/scripts/capture_baseline.py`, `backend/tests/test_capture_baseline.py`, `backend/tests/evals/baseline.json`, and the new baseline model/schema plus deterministic evaluation runner.

**Acceptance:** The checked-in baseline validates against the checked-in schema; repeated offline quality results are identical; regressions fail comparison with actionable case IDs; credentials, absolute workspace paths, and provider secrets are absent.

### BASE-03 — Compatibility fixture pack

- [x] **BASE-03A — Manifest and isolated loader.** The versioned `backend/tests/fixtures/manifest.json` links checksum-validated AppSpec, project/version/artifact, publication, and provider resources. `FixturePack` materializes them only into explicit empty or marker-approved absolute temporary workspaces, reuses the existing Item Manager AppSpec, and rejects unsafe directories, non-canonical paths, duplicate projects, and checksum mismatches before fixture data is written. No SQLite databases, dependency environments, caches, or production data are checked in.
- [x] **BASE-03B — Declarative coverage matrix.** Four package bases cover static/FastAPI and single-file/multi-file sources. Sixteen variants cover current/historical and published/unpublished states using shared React sources, replaceable API adapters, and a modular FastAPI backend. Nine provider fixtures declare acceptance, normalization, bounded repair, rejection, or overlay expectations for valid and malformed outputs. Resource checksums, stable package source hashes, and the normalized Item Manager AppSpec hash are verified; both multi-file packages pass the real source-package validator.
- [x] **BASE-03C — Fixture validation and consumers.** AppSpec schema/compiler, all four legacy-adapter cases, LLM repair, package overlay, invalid-package repair, and requirements normalization now consume the shared pack. Six integration tests verify historical preview/public output, owner-only registry reads, real Vite builds, single-file and modular FastAPI health/CRUD, bidirectional migration with release preservation, and the remaining provider boundaries. Manifest/hash checks and real source validation complete the reusable fixture contract for the later BASE-01 quality runner.

**Primary files:** `backend/tests/fixtures/`, fixture-aware tests, and existing compatibility/workflow suites.

**Acceptance:** A fresh checkout can materialize every declared case without reading `data/projects` or contacting a provider; all four architecture/source-format combinations and both publication/history states pass; malformed cases fail only for their documented reason.

### JOB-06 — End-to-end cooperative cancellation

- [x] **JOB-06A — Attempt-scoped cancellation contract.** `backend/app/jobs/context.py` propagates cancellation, trace IDs, and tool/process-group ownership through async operation tasks and resets on every exit. `POST /api/projects/{project_id}/jobs/{job_id}/cancel` is owner-checked and idempotent; project payloads expose `active_job`. Persistent `cancel_requested` → `cancelling` → `cancelled` transitions and separate event/checkpoint dedupe keys work on both cancellation paths, with no automatic retry or extra attempt. Tool-boundary cancellation and finalization/UI safety remain JOB-06B/C.
- [x] **JOB-06B — Provider and process boundaries.** Provider requests abort in flight and stop before schema fallback or repair. `backend/app/jobs/processes.py` owns each spawned process group, races cancellation and timeout, bounds/redacts output, and handles graceful termination, bounded escalation, reaping, and output draining. npm, pip, venv creation, dependency probes, Vite builds, Playwright, runtime startup, and health waits use the shared supervisor or attempt-scoped ownership checks. Real child-process tests verify only the cancelled group is stopped; unrelated preview and published runtimes remain alive.
- [x] **JOB-06C — Finalization and UI safety.** Finalization checks lease/worker ownership, input hash, and cancellation state atomically. Attempt snapshots restore prior project fields, artifacts, physical versions, staging, and previous verification reports on cancellation, while preserving published releases and emitting one terminal event. Cancelled verification is rejected before it can be returned or published. The Builder cancel button shows immediate `cancelling` feedback, disables duplicates, and polls during synchronous and deferred work.

**Primary files:** `backend/app/jobs/`, `backend/app/llm.py`, `backend/app/frontend_builder.py`, `backend/app/runtime.py`, `backend/app/verification/runner.py`, API schemas/routes, and Builder job controls.

**Acceptance:** Fault-injection tests cancel at every model/npm/pip/browser/runtime/finalization boundary, including a finalization race and studio shutdown. Tests verify PID/process-group and listener cleanup, no new version or duplicate terminal event, intact published output, and unchanged legacy behavior with durable jobs disabled.

### JOB-05 — Resumable event delivery

- [x] **JOB-05A — Versioned replay contract.** `backend/app/jobs/events.py` defines schema 1.0 envelopes with numeric IDs, job/attempt IDs, types, timestamps, and recursively redacted payloads. Owner-checked `GET /api/projects/{project_id}/events` supports `Last-Event-ID` and `after`, bounded ordered replay, cursor-expiry responses, heartbeat/reconnect hints, and `stream.complete` with `X-Event-Cursor`. Lifecycle writes add `job.started`, `job.succeeded`, and `project.refresh` while preserving historical checkpoints and terminal events; no bearer tokens appear in URLs.
- [x] **JOB-05B — Live delivery and reconnect.** `follow=true` tails persisted events with idle heartbeats and no SQLite connection held across awaits. Invalid/expired cursors fail before streaming for project reconciliation. `ProjectEventStream` and `useProjectEvents` maintain one abortable subscription per mounted project, monotonic cursor dedupe, bounded reconnect delay, and sequential refresh on project/report/cancellation events. Reader and timer cancellation cover navigation, completion, logout, and shutdown; tests verify resume-after-disconnect and abort cleanup.
- [x] **JOB-05C — Polling fallback and fault coverage.** Legacy projects remain polling-only through the explicit durable-job capability flag; disconnected or unsupported streams poll every 1.5 seconds, while healthy SSE reconciles the authoritative project payload every 30 seconds. Live replay preserves the requested cursor before tailing, and persisted-event polling runs every 250 ms independently of 15-second idle heartbeats. Shared in-flight loading, monotonic cursors, cursor-expiry snapshot reconciliation, bounded reconnect, and distinct network-abort/disposal handling prevent duplicate transitions. Tests cover replay across jobs and attempts, checkpoint-close recovery, cursor expiry, ownership isolation, heartbeat timing, shutdown cleanup, offline fallback, and deferred autopilot without duplicate versions.

**Primary files:** `backend/app/jobs/service.py`, a new event stream service/route, `backend/app/jobs/runner.py`, `frontend/src/useProjectEvents.ts`, and Builder polling/integration tests.

**Acceptance:** A browser that disconnects between checkpoints resumes from its last event ID with no lost or duplicated transitions; polling-only projects behave unchanged; no stream, timer, or server task remains after completion or navigation.

### JOB-07 — Usage and provenance tracking

- [x] **JOB-07A — Shared tool-run envelope.** `backend/app/jobs/tool_runs.py` provides immutable attempt-owned envelopes and terminal finalization for tool name/version, input hash, redacted output reference, status, retry sequence, start/end/duration, and spec/source provenance. Shared redaction removes credentials and URL queries. Provider HTTP requests, subprocess-based build/install and dependency checks, runtime launch/health, and verification checks persist distinct spans; schema fallback and output repair use an independent HTTP request sequence without changing repair limits. Detached legacy contexts remain uninstrumented, and existing verification report IDs and cancellation behavior are preserved.
- [x] **JOB-07B — Model usage and honest cost estimates.** `backend/app/jobs/usage.py` observes every provider HTTP response without changing the existing generation wrappers or repair budget. Usage rows link to their tool run and snapshot provider/model, request ID, finish reason, initial/fallback/output-repair reason, retry sequence, latency, and reported prompt/completion/total tokens. Availability is explicitly `reported`, `partial`, or `unavailable`; missing totals are not fabricated. Optional provider input/output prices per million tokens and currency are migrated and configurable in Administration, then snapshotted into each row. Computed costs are labelled estimates; missing tokens or prices remain `unknown`, while explicit zero usage and zero prices produce a legitimate estimated `$0`. Forma Local emits no synthetic model usage, and additive migrations preserve historical rows with explicit unknown defaults.
- [ ] **JOB-07C — Build/runtime provenance.** Instrument dependency resolution/install, Vite builds, staging/promotion, runtime startup/health, and verification with durations, retries, cache hits, package/input hashes, source/spec hashes, environment/tool versions, and terminal status. Redact credentials, prompt bodies, access tokens, URL query strings, and private index credentials. Preserve existing verification reports and historical records.
- [ ] **JOB-07D — Owner-only inspection and aggregation.** Add `GET /api/projects/{project_id}/usage` and a read-only Activity view for per-job and project totals, token availability, estimated/unknown cost, retries, tool durations, runtime health, and source/spec provenance. Test aggregation across attempts, cancelled-span closure, absent usage/pricing, legacy records, ownership checks, and secret scanning. Real-provider usage smoke remains opt-in.

**Primary files:** `backend/app/llm.py`, the new shared tool-run service, provider configuration/schemas, build/runtime/verification instrumentation, `usage_ledger`, and an owner-only usage API/UI.

**Acceptance:** Every completed, failed, or cancelled operation has one traceable terminal tool run; retries remain individually visible; aggregates equal their underlying rows; unknown token/cost data is explicit; no credential or prompt content appears in stored or returned telemetry.

### Checkpoint exit gate for specialist workers

- [ ] All BASE-01, BASE-03, JOB-05, JOB-06, and JOB-07 subtasks are complete, and the Milestone 0/1 gates are checked with dated evidence.
- [ ] Two offline baseline captures are semantically identical, comparison detects an injected regression, and the complete fixture matrix passes from a fresh temporary workspace.
- [ ] Cancellation/finalization fault tests leave no owned process, listener, staging directory, or duplicate finalization; existing published releases remain available.
- [ ] SSE reconnect and polling fallback pass without event loss, duplicate project transitions, duplicate versions, or leaked subscriptions.
- [ ] Model, build, runtime, and verification tool runs link to their job/attempt and source/spec hashes; token/cost availability and estimates are represented honestly with no secret leakage.
- [ ] Full backend/frontend regressions, both architecture browser flows, release-gate tests, production build, and Ruff pass. Test servers and generated processes are stopped.
- [ ] Update this tracker and README with actual evidence. WRK-01 may begin only after the user accepts this checkpoint; passing these tests does not automatically enable specialist workers.

**Non-goals for this checkpoint:** WebSockets, a distributed event bus, automatic model-price discovery, budget enforcement, multi-worker orchestration, specialist-worker implementation, sandboxing, and preview/published data isolation remain separate work.

## Milestone 2 — AppSpec and deterministic compilation

- [x] **SPEC-01 — Versioned schema.** Implemented in `backend/app/spec/types.py` and `schema.py`; schema and cross-contract tests pass.
- [x] **SPEC-02 — Deterministic compiler.** Implemented in `manifest.py`, `dependencies.py`, and `compiler.py`; deterministic manifest, dependency, alias, ownership, and size-policy tests pass.
- [x] **SPEC-03 — Schema-aware model generation.** Provider JSON Schema fallback, bounded semantic repair, deterministic source synthesis, and AppSpec-hash provenance are implemented; the flagged engine no longer requests free-form source maps.
- [x] **SPEC-04 — Legacy adapter.** Existing artifacts are represented without regeneration or changes to preview/published URLs; all architecture/source-format combinations pass.
- [x] **SPEC-05 — AppSpec generation integration.** Builds, refinements, and migrations compile from AppSpec and persist provenance; phase/version semantics and flag-off behavior pass.
- [x] **SPEC-06 — Contract review.** Pre-build drafts, revisions, review metadata, an inspectable Contract panel, and invalid-contract approval gates are implemented and verified.

**Milestone gate:** `[x]` AppSpec is the generation contract when enabled, with pre-build review and deterministic source compilation. Legacy behavior remains available behind the flag.

## Milestone 3 — Deterministic verification and deployment registry

- [x] **VER-01 — Generate acceptance checks.** Deterministic API, persistence, browser, validation, migration, republishing, and security artifacts are generated from AppSpec and verified.
- [x] **VER-02 — Verifier and report model.** Durable reports include spec/source hashes, tool-run IDs, durations, full-coverage publish evaluation, and actionable failures; subprocess results—not model review—determine outcomes.
- [x] **VER-03 — Deployment registry lookup.** Public hosting resolves through the control-plane registry with owner-scoped artifacts, write-through synchronization, and backfilled version metadata; no user database scan is required.
- [x] **VER-04 — Gate new releases and expose results.** Fresh full-coverage verification blocks failing new publishes without taking existing releases offline; the verification API and panel expose actionable evidence.

**Milestone gate:** `[x]` With `ACCEPTANCE_GATE_V1` enabled, deterministic verification is the required new-release gate. Legacy publishing remains available with the feature flag off.

## Milestone 4 — Scoped specialist workers

- [ ] **WRK-01 — Scoped frontend/backend workers.** Enforce role-specific file, data, and credential permissions; the supervisor owns the shared API adapter.
- [ ] **WRK-02 — Supervised parallel execution and merge.** Reject conflicting writes and preserve contract/source provenance.
- [ ] **WRK-03 — File-scoped repair.** Repair only failed files/workers while unrelated hashes remain unchanged.
- [ ] **WRK-04 — Optional non-gating review.** Model suggestions never override build, test, or security failures.

**Milestone gate:** `[ ]` Parallel workers are optional, scoped, and behaviorally equivalent to sequential generation.

## Milestone 5 — Runtime hardening and scale

- [ ] **RUN-01 — Production sandbox.** Non-root container, read-only base filesystem, writable app workspace only, and enforced resource limits.
- [ ] **RUN-02 — Network and dependency policy.** Deny egress by default, verify dependency provenance, and disallow deployed-runtime installation.
- [ ] **DATA-01 — Separate preview/published data.** Prevent preview writes from affecting published data; make migration explicit.
- [ ] **AUTH-01 — Managed application authentication.** Enforce generated-app access policy and block sensitive unauthenticated releases.
- [ ] **OPS-01 — External orchestration.** Safe multi-worker leasing, single finalization, concurrency limits, and unique runtime ownership.
- [ ] **OPS-02 — Operational evaluation.** Add soak/fault tests and dashboards for validity, repair, latency, cost, recovery, health, and orphan counts.

**Milestone gate:** `[ ]` Untrusted execution, data isolation, and multi-worker acceptance tests pass.

## Rollout and rollback rules

1. Land additive services and schemas with legacy defaults.
2. Enable one flag for test users/new projects and compare against the baseline.
3. Keep existing artifacts, historical versions, providers, and published URLs unchanged.
4. Roll back by disabling new work on the affected flag; never automatically unpublish or rewrite an existing release.
5. Remove legacy paths only after compatibility, recovery, and rollback evidence is accepted.

## Verification log

| Date | Increment | Evidence | Result |
|---|---|---|---|
| 2026-10-26 | Foundation and data relocation | Backend regression and Ruff | 31 passed; data moved to project-root `data/` |
| 2026-10-27 | Durable runner and engine integration | Complete backend regression and Ruff | 46 passed, including 15 durable-runner tests; lint clean |
| 2026-10-27 | AppSpec compatibility slice | Complete backend regression, real Vite preview/archive, and Ruff | 83 passed, including 37 AppSpec-focused tests; lint clean |
| 2026-10-27 | SPEC-03 schema-aware generation | Backend/frontend regressions, real Vite and FastAPI CRUD/restart, Ruff | 102 backend and 5 frontend tests passed; production build and lint clean |
| 2026-10-27 | SPEC-06 contract review and Milestone 2 | Backend/frontend regressions, focused and legacy browser suites, production build, Ruff | 109 backend and 9 frontend unit tests passed; 1 AppSpec and 5 legacy browser tests passed; build and lint clean |
| 2026-10-27 | Relative-import validation and Cruto repair | Import/repair regressions, complete backend/frontend checks, Cruto v2 Vite build and preview | 113 backend and 9 frontend unit tests passed; Cruto v2 is ready with HTTP 200 preview; workspace backup retained |
| 2026-10-27 | Deterministic overlay and staged builds | Complete-source, staging, failure/promotion, full backend/frontend, and multi-file browser checks | 118 backend and 9 frontend unit tests plus 1 browser test passed; Cruto v3 reached review with HTTP 200 preview; backups retained |
| 2026-10-27 | VER-01 acceptance generation | Deterministic artifacts, generated security execution and violation detection, live generated API health/CRUD/validation, full regressions | 123 backend and 9 frontend unit tests passed; production build and lint clean |
| 2026-10-27 | VER-02 verifier and report model | Nine verifier tests covering retries, coverage, failures, stale hashes, runtime, security, and Playwright; full regressions | 132 backend and 9 frontend unit tests passed; production build and lint clean |
| 2026-10-27 | VER-03 deployment registry lookup | Registry write-through, backfill, no-scan lookup, migration/republication, and full regressions | 136 backend and 9 frontend unit tests passed; production build and lint clean |
| 2026-10-27 | VER-04 release gate and Milestone 3 | Gate/API/deferred-error coverage, verification panel, full regressions, and desktop/mobile browser evidence | 143 backend and 12 frontend unit tests passed; 1 verification and 5 legacy browser journeys passed; production build and lint clean |
| 2026-10-27 | BASE-01A versioned baseline contract | Seven focused baseline tests, schema generation/drift, legacy 1.0 parsing, real repository metadata, and full regressions | 147 backend and 12 frontend unit tests passed; production build and Ruff clean |
| 2026-10-27 | BASE-03A fixture manifest and isolated loader | Six loader tests covering materialization, historical publication, providers, traversal, checksums, and unsafe-directory refusal; full regressions | 153 backend and 12 frontend unit tests passed; production build and Ruff clean |
| 2026-10-27 | BASE-03B compatibility coverage matrix | Five matrix tests plus existing fixture/baseline tests; all 16 variants materialized, source/AppSpec hashes and nine provider expectations verified, multi-file source validation and full regressions | 158 backend and 12 frontend unit tests passed; production build and Ruff clean |
| 2026-10-28 | BASE-03C fixture validation and consumers | Six integration tests plus converted AppSpec/adapter/provider consumers; real Vite builds, FastAPI health/CRUD, history, registry, migration, and full regressions | 164 backend and 12 frontend unit tests passed; production build and Ruff clean |
| 2026-10-28 | BASE-01B deterministic quality metrics | 22/22 quality cases, schema 1.2 capture and legacy compatibility, real verification and publish gates, full regressions | 166 backend and 12 frontend unit tests passed; production build and Ruff clean |
| 2026-10-28 | BASE-01C repeatability and Milestone 0 | Two semantically identical quality captures, current 1.2 baseline validation, directional thresholds, clean and injected-regression CLI checks, full regressions | 169 backend and 12 frontend unit tests passed; production build and Ruff clean |
| 2026-10-28 | JOB-06A cancellation contract | Context/tool ownership, owner-scoped idempotent API, both cancellation paths, transition/event dedupe, and full regressions | 173 backend and 12 frontend unit tests passed; production build and Ruff clean |
| 2026-10-28 | JOB-06B provider and process boundaries | Real owned/unrelated process-group cleanup, in-flight/fallback provider cancellation, timeout/redaction, runtime preservation, and full regressions | 178 backend and 12 frontend unit tests passed; production build and Ruff clean |
| 2026-10-28 | JOB-06C finalization and UI safety | Version/report rollback, worker/cancel guards, cancelled-outcome rejection, immediate Builder feedback, and full regressions | 182 backend and 13 frontend unit tests passed; production build and Ruff clean |
| 2026-10-28 | JOB-05A versioned event replay | Ordered bounded SSE, redaction, cursor expiry, owner isolation, lifecycle/refresh events, and full regressions | 185 backend and 13 frontend unit tests passed; production build and Ruff clean |
| 2026-10-28 | JOB-05B live delivery and reconnect | Live tailing, cursor resume after disconnect, bounded backoff, immediate refresh, abort cleanup, and full regressions | 187 backend and 15 frontend unit tests passed; production build and Ruff clean |
| 2026-10-28 | JOB-05C polling fallback and fault coverage | Two repeatable quality evaluations, initial live replay, prompt persisted-event polling, cursor-expiry reconciliation, checkpoint-close recovery, deferred autopilot, and full regressions | 191 backend and 16 frontend unit tests passed; 2 event browser journeys passed; production build and Ruff clean |
| 2026-10-28 | JOB-07A shared tool-run envelope | Provider fallback sequencing, process success/failure, detached cancellation, redaction, spec/source provenance, real verifier build and runtime launch/health, two quality evaluations, and full regressions | 194 backend and 16 frontend unit tests passed; production build and Ruff clean |
| 2026-10-28 | JOB-07B model usage and honest costs | Reported/partial/missing tokens, unknown versus free costs, provider pricing API/migrations, schema fallback and output-repair observations, two quality evaluations, and full regressions | 200 backend and 16 frontend unit tests passed; production build and Ruff clean |
