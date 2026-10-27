# Forma Studio v1.4 — Implementation Tracker

**Last updated:** 2026-10-27  
**Current focus:** VER-02 — Deterministic verifier and report model
**Status legend:** `[x]` accepted and verified · `[ ]` not complete · **Partial** means useful foundations exist but the acceptance gate remains open

This is the persistent implementation record for the approved sequence:

> Baseline → durable jobs → AppSpec → deterministic verification → specialist workers → runtime hardening and scale

Do not mark a milestone complete until its acceptance gate is verified. Keep schemas additive, preserve published applications, and retain legacy behavior behind feature flags.

## Latest completed increment — VER-01 acceptance generation

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

- [ ] **BASE-01 — Reproducible evaluation baseline — Partial.** `backend/scripts/capture_baseline.py` and `backend/tests/evals/baseline.json` record real suite results. Add the checked-in baseline schema and generation-quality metrics before acceptance.
- [x] **BASE-02 — Typed feature flags.** `backend/app/features.py`, settings, `.env.example`, and `backend/tests/test_features.py`; every flag defaults off and invalid booleans are rejected.
- [ ] **BASE-03 — Compatibility fixture pack — Partial.** Baseline categories cover source format, architecture, publication, history, and malformed outputs. Materialize the reusable project/provider/package fixture directories.

**Milestone gate:** `[ ]` Baseline schema, generation-quality metrics, and reusable fixtures remain open.

## Milestone 1 — Durable job orchestration

- [x] **JOB-01 — Additive durable schemas.** Job, attempt, event, tool-run, usage, and deployment-registry tables migrate repeatedly without changing existing project tables.
- [x] **JOB-02 — Leasing and idempotency.** Stable keys, guarded attempts, heartbeat, expiration recovery, cancellation, and stale-finalization checks are covered by `test_job_service.py`.
- [x] **JOB-03 — Durable generation runner.** Stage generation, document revision, and architecture migration use `backend/app/jobs/runner.py` when enabled. `complete_package` remains inside its parent stage job by design.
- [x] **JOB-04 — Preserve synchronous and deferred behavior.** Engine wrappers route deferred and synchronous work through the durable runner under `DURABLE_JOBS_V1`; legacy scheduling remains the fallback.
- [ ] **JOB-05 — Resumable event delivery.** Add ordered SSE replay, reconnect resume, UI progress, and polling fallback. Persistent job events alone do not complete this task.
- [ ] **JOB-06 — End-to-end cooperative cancellation — Partial.** Runner and shutdown cancellation are implemented. Add checks around model, npm, pip, runtime startup, and finalization, plus process-group cleanup verification.
- [ ] **JOB-07 — Usage and provenance tracking.** Wire provider/model, tokens, cost, retries, build duration, runtime health, and source hashes into tool runs and the usage ledger.

**Milestone gate:** `[ ]` SSE, full tool-boundary cancellation, and telemetry remain open.

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
- [ ] **VER-02 — Verifier and report model — Next.** Produce deterministic reports with spec/source hashes, tool-run references, duration, and actionable failures; model review cannot override them.
- [ ] **VER-03 — Deployment registry lookup — Partial.** Registry schema and published-project backfill exist. Route public deployment lookup through the registry instead of scanning user databases.
- [ ] **VER-04 — Gate new releases and expose results.** Block failing new publishes without taking existing releases offline; add the verification panel.

**Milestone gate:** `[ ]` Deterministic verification becomes the only new-release gate.

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
