# Forma Studio — Implementation Record

**Last updated:** 2026-10-30

## Product intent

Forma lets people without programming skills build a web application with a real **FastAPI + SQLite backend** and a **React + TypeScript frontend**, through a standard product process: product description → design → implementation plan → three build phases → review → publish. Every stage must build on the approved output of the stage before it, and the code is written by the model from those documents. See [PRD.md](PRD.md).

## 2026-10-30 — Course correction

Between `426b5fa` and `3a9a2dd`, work drifted away from that intent. The tracker that guided it ("v1.4": baseline → durable jobs → AppSpec → deterministic verification → specialist workers) piled infrastructure around the generator and, behind `APPSPEC_V1`, replaced model-written applications with a deterministic template compiler. That compiler could only emit **one entity with collection CRUD routes**, so every brief ("Mini-Twitter", a booking tool, a portal) became the same item manager. Later commits patched symptoms of that template (heading contracts, datetime adapters, "Mini-Twitter health contract normalization") rather than the product. Meanwhile the core workflow never passed its own documents forward: design, plan, and build prompts saw only the original brief, so `product.md`, `design.md`, and `plan.md` had no effect on the generated app.

### Removed

| Subsystem | Why |
|---|---|
| `app/spec/` — AppSpec schema, compiler, single-entity source synthesis, legacy adapter, Contract tab | Replaced AI generation with a fixed CRUD template; contradicts the product. |
| `app/verification/` — acceptance generation, verifier, publish gate, advisory model review, Verification tab | Generated only from AppSpec; could not verify model-written apps. |
| `app/workers/` — specialist worker supervisor/repair | Operated only on AppSpec manifests. |
| `app/evaluation/`, `scripts/`, `tests/evals/`, `tests/fixtures/` — baseline capture, quality metrics, fixture matrix | Measured the AppSpec pipeline; no bearing on generated app quality. |
| `APPSPEC_V1`, `ACCEPTANCE_GATE_V1`, `SPECIALIST_WORKERS_V1` flags | Their subsystems are gone. |

All of it remains in git history (`3a9a2dd` and earlier) if any part is wanted again.

### Kept

- The original workflow, LLM provider integration, Forma Local, multi-file packages, staged Vite builds, per-app Python runtimes, preview/publish, deployment registry, architecture migration.
- Optional `DURABLE_JOBS_V1` (durable jobs, SSE events, cancellation, usage telemetry) and `SANDBOX_V1` (Docker runtime isolation). Both are generic infrastructure and stay off by default.

### Fixed and improved

- **Stages now chain.** Design is written from the approved `product.md`; the plan from product + design, with `## Phase 1–3` headings; each build phase receives product, design, and *its own section* of the plan (`engine.product_context`, `engine.phase_plan`). Architecture migrations receive the same context.
- **Documents no longer leak into application source.** The version-0 `product.md`/`design.md`/`plan.md` artifacts were treated as "current package files" on the first build and copied into every package.
- **Generated frontends are React + TypeScript.** New packages use `main.tsx`, `App.tsx`, `api.ts`, `types.ts`, `components/*.tsx`, `hooks/*.ts`, with a studio-owned strict `tsconfig.json`, `vite.config.ts`, and `src/forma.d.ts` typing the `Forma.api<T>()` bridge. The Forma Local package passes `tsc --noEmit` under strict mode. Existing `.jsx` packages are detected and keep building unchanged.
- **Defaults match the intent.** New projects default to a project package with FastAPI + SQLite (API and UI). Frontend-only remains an explicit choice; single-file HTML remains for API clients and existing projects.
- **Reviewed optional Python packages are installable.** `SQLAlchemy` and `python-multipart` pins come from the studio's installed versions but were missing from `requirements.txt`; `pytest-asyncio` was missing, so async tests never ran.
- **Package installs work behind proxies.** npm and pip installation steps inherit only the host's proxy/CA variables; generated app processes still get a clean environment.
- **No machine-specific paths.** `npm run dev` and Playwright resolve Python from `PYTHON`, `backend/.venv`, or `python3`.

### Verification

- Backend: full `pytest` suite (including the new `tests/test_stage_context.py`) and Ruff.
- Frontend: `tsc -b`, Vitest, production build.
- Multi-file end to end: TypeScript package → npm install → Vite build → FastAPI runtime → preview, publish, deployment ZIP.

## Open work

1. **Type-check generated code.** Run `tsc --noEmit` on generated packages and feed errors into the existing bounded repair, so model output is held to the same strict standard as Forma Local.
2. **Richer Forma Local sample.** The offline engine still produces one sample app regardless of the brief; it could derive entities and screens from the plan.
3. **Runtime hardening.** Network egress policy for generated backends, separate preview/published databases, and managed end-user authentication.
4. **Generated app tests.** Let phase 3 produce API tests for the generated backend and run them before release review.
