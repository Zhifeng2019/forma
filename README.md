# Forma — AI Product Studio

Forma is an AI-native application builder built around a guided product-development cycle: description, design, implementation plan, three build phases, review, and publishing.

## What is included

- Email registration, login, account roles, and admin user controls.
- Shared control-plane SQLite database and one isolated SQLite workspace per user.
- OpenAI-compatible provider management with encrypted API keys and connection tests.
- An offline **Forma Local** engine for deterministic demos without external credentials.
- Product, design, and implementation-plan Markdown artifacts.
- Automatic or explicit architecture selection: frontend-only HTML or HTML plus a dedicated FastAPI backend.
- Bidirectional architecture migration for existing projects, with immediate migration progress, automatic preview refresh, version-specific architecture, preserved phase state, and unchanged published releases until republishing.
- Three implementation phases with working previews and version history.
- Multi-file React project packages with component source, a Vite production build, and modular FastAPI backends.
- A Source tab for reviewing current-version files and downloading a deployment ZIP containing `frontend/`, `frontend/dist/`, and `backend/`.
- Shared per-user Node environments and expanded reviewed Python dependencies, all installed from pinned versions and built-in package validation.
- Versioned `main.py` and pinned `requirements.txt` artifacts for backend-enabled applications.
- Per-app Python environments with packages physically installed from the Aliyun PyPI mirror, application-local SQLite persistence, health checks, runtime logs, and independent preview/public processes.
- A Server panel for backend health, source review, actionable error summaries with expandable technical details, and preview restart.
- Immediate optimistic chat updates and automatic workspace refresh during phase builds, document revisions, architecture migration, and autopilot.
- Feedback that refines the current phase without advancing it; only explicit approval moves to the next phase.
- Conversational revisions and preview element selection for targeted feedback.
- Desktop, tablet, and mobile preview modes.
- Public hosting at `/apps/<application-id>/`, including generated APIs at `/apps/<application-id>/api/`, with publish, republish, and unpublish controls.
- Deferred creation and autopilot, which open the workspace immediately and progress through implementation before pausing at release review.
- Real runtime lifecycle/isolation tests, frontend unit tests, and Playwright coverage for both architectures.

## Run locally

### Start the studio

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

This starts both Vite and FastAPI, and shuts both down together. Open `http://localhost:5173`.

To run the API independently for development:

```bash
cd backend
/Users/zhifengzhang/python_env/env_ai_build/bin/python -m uvicorn app.main:app --reload --reload-exclude 'data/**' --port 8000
```

The initial local administrator is `admin@forma.local` with password `admin123`. Change this account before exposing the service publicly. All data is development-local by default under `data/`.

## Generated project packages

New projects default to **Project package**; **Single file** remains available for legacy generation. A multi-file version is laid out as:

```text
versions/vN/
  frontend/        # React source, package.json, Vite config, and built dist/
  backend/         # FastAPI entrypoint, app modules, requirements.txt
```

The agent validates source files and reviewed dependencies, runs `vite build`, and marks the version ready only after `frontend/dist/index.html` exists. One shared Node environment per user supplies locked React, React DOM, Lucide, Vite, and React-plugin packages. Forma generates `backend/requirements.txt` from the reviewed `python_dependencies` list rather than requiring it from the model. Python environments remain app-specific and support the base FastAPI stack plus reviewed `httpx`, `PyJWT`, `cryptography`, `pydantic-settings`, `python-multipart`, and `SQLAlchemy` packages.

Generated changes are overlaid on the previous complete package, so partial model file lists cannot remove required components. Relative imports are resolved before building. Each version is materialized in `versions/vN.staging`; only a validated, successful production build is promoted to `versions/vN`. Failed builds remove staging and preserve the last usable version. Backend runtimes consume only the promoted, versioned package.

The Source tab displays current-version files. Deployment downloads include frontend source, production `frontend/dist/`, and backend modules, excluding dependency folders, caches, and temporary files. Preview and public hosting serve the built output and its assets. Both `Forma.api` and native same-origin `/api/...` fetch calls are routed through the runtime bridge. Invalid model packages receive one bounded semantic regeneration.

## Generated FastAPI runtime

Backend-enabled applications live under `data/projects/<application-id>/` with one virtual environment, immutable source directories for each version, and an application-local SQLite working directory. Preview and published processes start on demand and have independent lifecycles; their application database is shared across restarts and versions.

Each environment installs its pinned dependencies using its own `.venv/bin/python -m pip` and the Aliyun mirror `https://mirrors.aliyun.com/pypi/simple/` (configurable with `RUNTIME_PIP_INDEX_URL`). Inherited studio and machine site-packages are disabled. Before startup, Forma verifies both the package versions and that FastAPI, Uvicorn, Pydantic, and email-validator import from the application’s own `site-packages`. Older artifacts missing support packages such as `email-validator` are augmented during installation without rewriting those artifacts. Runtime requests have health checks, timeouts, body/concurrency limits, and owner-only diagnostics. Unpublish and delete operations stop their corresponding processes.

Published APIs are public with the application URL and do not require a Forma session. Source validation and process isolation reduce risk, but this is **not a hardened multi-tenant sandbox**. Use this release with trusted local projects only; add container isolation and product-level authentication before handling untrusted users or sensitive application data.

## Deterministic release verification

Enable both `APPSPEC_V1` and `ACCEPTANCE_GATE_V1` to generate and execute typed acceptance contracts. The **Verification** tab supports deferred application checks and optional migration/republishing checks, then displays coverage, required and optional failures, tools, targets, durations, source/spec hashes, and actionable errors.

Publishing a different version always performs a fresh full required-check run while the gate is enabled; a previous manual pass is not reused as release evidence. Failed or incomplete verification blocks the new publish without changing the existing public release. Republishing the already-live version is idempotent. With the gate disabled, legacy publishing behavior remains unchanged.

## Production shape

Build the frontend with `npm run build`; FastAPI serves `frontend/dist` when present. Set a strong `SECRET_KEY`, restrict `CORS_ORIGINS`, put the service behind HTTPS, and replace the initial administrator credentials. Do not expose generated-code execution to untrusted users without a container or equivalent security sandbox.

## v1.4 implementation track

The v1.4 work is additive and disabled by default. Task status and acceptance evidence are tracked in [doc/IMPLEMENTATION.md](doc/IMPLEMENTATION.md).

- Typed feature flags cover durable jobs, AppSpec, acceptance gates, specialist workers, and sandboxing.
- The durable runner supports idempotent jobs, attempts, checkpoints, heartbeat, cancellation, retry, and stale-finalization protection for stage generation, document revision, and architecture migration.
- AppSpec v1 provides schema-aware provider proposals with a structured-JSON fallback, one bounded semantic repair, a typed contract, deterministic single-entity CRUD source synthesis, and a legacy adapter.
- With `APPSPEC_V1` enabled, builds, refinements, and migrations compile from AppSpec and persist `appspec.json` plus `build-manifest.json`. The v1 compiler supports one entity and reviewed collection CRUD routes; flag-off behavior preserves the existing generators.
- Planning creates a version-0 AppSpec draft for the Contract review panel. Plan feedback and pre-build architecture changes revise the draft, and invalid contracts are blocked before compilation.
- AppSpec versions include `acceptance/` artifacts: a provenance manifest plus executable API, browser, security, migration, and republishing checks with explicit environment requirements and mutation flags.
- The deterministic verifier produces durable reports with spec/source hashes, tool-run IDs, durations, blocked/failed details, full-coverage `can_publish` evaluation, and forced retry support. The Verification panel presents this evidence and refreshes deferred runs automatically.
- With `ACCEPTANCE_GATE_V1` and `APPSPEC_V1` enabled, every new publish requires a fresh full required-check run. Failed verification does not replace or unpublish the existing release; republishing the already-live version remains idempotent.
- Public deployments resolve through the control-plane registry with write-through publish, republish, unpublish, and delete synchronization and backfilled version-specific architecture. Public lookup no longer scans every user database.
- Baseline quality metrics and fixtures, broader multi-entity synthesis, resumable SSE, complete cancellation and tool telemetry, specialist workers, and sandboxing remain separate tracked tasks.

Regenerate the evaluation baseline with:

```bash
cd backend && /Users/zhifengzhang/python_env/env_ai_build/bin/python scripts/capture_baseline.py
```

Use `--skip-browser` for a backend/frontend-only capture. Baseline output is written to `backend/tests/evals/baseline.json`.

## Tests

```bash
cd backend && /Users/zhifengzhang/python_env/env_ai_build/bin/python -m pytest -q
cd frontend && npm test && npm run build
cd frontend && npx playwright test
```

## Architecture

- `backend/app/api.py` — authentication, administration, project workflow, private runtime proxy, preview, and publishing API.
- `backend/app/engine.py` — stage orchestration, architecture decisions, artifacts, messages, and versions.
- `backend/app/backend_engine.py` — FastAPI generation contract, source validation, and deterministic local backend.
- `backend/app/source_packages.py` — multi-file React/FastAPI generation, local packages, and file/dependency validation.
- `backend/app/frontend_builder.py` — shared Node environments, Vite production builds, assets, and deployment archives.
- `backend/app/runtime.py` — per-app environments, loopback processes, health checks, proxying, logs, and cleanup.
- `backend/app/runtime_launcher.py` — trusted child-process launcher and OS resource limits.
- `backend/app/llm.py` — structured OpenAI-compatible model calls and output-truncation repair.
- `backend/app/local_engine.py` — offline product documents and frontend-only generation.
- `backend/app/database.py` — control and per-user SQLite schemas plus architecture/source-format migrations.
- `frontend/src/pages/Dashboard.tsx` — project dashboard and architecture/source-format selection.
- `frontend/src/pages/Builder.tsx` — collaborative product studio.
- `frontend/src/components/SourcePanel.tsx` — current-version source browser and deployment download.
- `frontend/src/components/BackendPanel.tsx` — FastAPI health, logs, source, and restart controls.
- `frontend/src/pages/AdminPage.tsx` — provider and member administration.
