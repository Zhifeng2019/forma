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

The initial local administrator is `admin@forma.local` with password `admin123`. Change this account before exposing the service publicly. All data is development-local by default under `backend/data/`.

## Generated FastAPI runtime

Backend-enabled applications live under `backend/data/projects/<application-id>/` with one virtual environment, immutable source directories for each version, and an application-local SQLite working directory. Preview and published processes start on demand and have independent lifecycles; their application database is shared across restarts and versions.

Each environment installs its pinned dependencies using its own `.venv/bin/python -m pip` and the Aliyun mirror `https://mirrors.aliyun.com/pypi/simple/` (configurable with `RUNTIME_PIP_INDEX_URL`). Inherited studio and machine site-packages are disabled. Before startup, Forma verifies both the package versions and that FastAPI, Uvicorn, Pydantic, and email-validator import from the application’s own `site-packages`. Older artifacts missing support packages such as `email-validator` are augmented during installation without rewriting those artifacts. Runtime requests have health checks, timeouts, body/concurrency limits, and owner-only diagnostics. Unpublish and delete operations stop their corresponding processes.

Published APIs are public with the application URL and do not require a Forma session. Source validation and process isolation reduce risk, but this is **not a hardened multi-tenant sandbox**. Use this release with trusted local projects only; add container isolation and product-level authentication before handling untrusted users or sensitive application data.

## Production shape

Build the frontend with `npm run build`; FastAPI serves `frontend/dist` when present. Set a strong `SECRET_KEY`, restrict `CORS_ORIGINS`, put the service behind HTTPS, and replace the initial administrator credentials. Do not expose generated-code execution to untrusted users without a container or equivalent security sandbox.

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
- `backend/app/runtime.py` — per-app environments, loopback processes, health checks, proxying, logs, and cleanup.
- `backend/app/runtime_launcher.py` — trusted child-process launcher and OS resource limits.
- `backend/app/llm.py` — structured OpenAI-compatible model calls and output-truncation repair.
- `backend/app/local_engine.py` — offline product documents and frontend-only generation.
- `backend/app/database.py` — control and per-user SQLite schemas plus architecture migrations.
- `frontend/src/pages/Dashboard.tsx` — project dashboard and architecture selection.
- `frontend/src/pages/Builder.tsx` — collaborative product studio.
- `frontend/src/components/BackendPanel.tsx` — FastAPI health, logs, source, and restart controls.
- `frontend/src/pages/AdminPage.tsx` — provider and member administration.
