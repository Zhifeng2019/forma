# Forma Studio v1.4 — Implementation Tracker

**Last updated:** 2026-10-27  
**Current focus:** SPEC-03 — Schema-aware model proposals and bounded repair  
**Status legend:** `[x]` accepted and verified · `[ ]` not complete · **Partial** means useful foundations exist but the acceptance gate remains open

This is the persistent implementation record for the approved sequence:

> Baseline → durable jobs → AppSpec → deterministic verification → specialist workers → runtime hardening and scale

Do not mark a milestone complete until its acceptance gate is verified. Keep schemas additive, preserve published applications, and retain legacy behavior behind feature flags.

## Latest completed increment — AppSpec compatibility slice

- [x] **SPEC-01 — Versioned AppSpec schema.** Typed product, architecture, entity, API, frontend, dependency, manifest, and acceptance sections reject invalid references before compilation.
- [x] **SPEC-02 — Deterministic package compiler.** Documented path aliases, allowed paths, ownership, size limits, reviewed dependencies, and deterministic source/spec hashes are implemented and tested.
- [x] **SPEC-04 — Legacy adapter.** Existing single-file and multi-file packages are represented without regeneration while preserving source, architecture, and source format.
- [x] **SPEC-05A — Dual-write generation.** With `APPSPEC_V1` enabled, new and migrated versions store `appspec.json` and `build-manifest.json`. Existing generators still produce source in this slice.
- [x] **SPEC-05B — Compatibility verification.** Both source formats and architectures, bidirectional migration, durable/deferred autopilot, flag-off behavior, real Vite preview, and deployment archives pass.

**Next:** schema-aware model proposals (SPEC-03), followed by optional contract review UI (SPEC-06) and specialist source workers. AppSpec is currently a dual-written contract, not yet the sole source generator.

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
- [ ] **SPEC-03 — Schema-aware model generation — Next.** Add provider proposals, bounded repair, structured-output compatibility, and AppSpec-hash linkage. Do not substitute free-form file generation for this task.
- [x] **SPEC-04 — Legacy adapter.** Existing artifacts are represented without regeneration or changes to preview/published URLs; all architecture/source-format combinations pass.
- [x] **SPEC-05 — Dual-write integration.** New and migrated versions persist AppSpec and build provenance; phase/version semantics and flag-off behavior pass. SPEC-03 remains necessary before AppSpec is the sole generation contract.
- [ ] **SPEC-06 — Optional contract review.** Add an inspectable entity/API/dependency/acceptance view and prevent invalid specs from proceeding.

**Milestone gate:** `[ ]` AppSpec must become the generation contract after SPEC-03; dual-write alone is not the final gate.

## Milestone 3 — Deterministic verification and deployment registry

- [ ] **VER-01 — Generate acceptance checks.** Cover API, persistence, browser workflow, validation, migration, and security from AppSpec.
- [ ] **VER-02 — Verifier and report model.** Produce deterministic reports with spec/source hashes, tool-run references, duration, and actionable failures; model review cannot override them.
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
