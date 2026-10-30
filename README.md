# Forma — AI Product Studio

Forma helps people without programming skills turn an idea into a working web application. It walks a project through a standard product-development process, and every step builds on the one before it:

1. **Product description** — `product.md`: vision, users, core workflow, scope, success criteria.
2. **Experience and technical design** — `design.md`, written from the approved product description.
3. **Implementation plan** — `plan.md` with three phases (`## Phase 1–3`), derived from the product and design.
4. **Phased implementation** — each phase is generated from the approved documents and that phase's section of the plan, and produces a working, previewable version.
5. **Review and improve** — conversational feedback and element picking create refinements.
6. **Publish** — host the app at `/apps/<application-id>/` (and its API at `/apps/<application-id>/api/`).

Users approve each stage, or turn on autopilot.

## What Forma generates

New projects are a deployable **React + TypeScript** frontend with a **FastAPI + SQLite** backend:

```text
versions/vN/
  frontend/
    index.html, package.json, tsconfig.json, vite.config.ts
    src/main.tsx, App.tsx, api.ts, types.ts, forma.d.ts, styles.css
    src/components/*.tsx, src/hooks/*.ts
    dist/                 # Vite production build
  backend/
    main.py, requirements.txt
    app/api.py, models.py, database.py   # FastAPI routes, Pydantic models, sqlite3 app.db
```

- The model writes application source. Forma owns `package.json`, the Vite config, `tsconfig.json` (strict), `src/forma.d.ts` (types for the `Forma.api` bridge) and pinned `requirements.txt`.
- Packages are validated (paths, relative imports, allowlisted npm/Python dependencies, Python AST checks, `/api/health`) and built with Vite in a staging directory; only a successful build is promoted. Invalid output gets one bounded repair.
- Each backend runs in its own virtual environment with its own `app.db`, behind health checks, timeouts, and resource limits. Preview and published processes are independent.
- The Source tab shows every file and downloads a deployment ZIP (source, `frontend/dist/`, `backend/`).

A project can also be **frontend only** (React + TypeScript with browser storage), and can migrate between the two architectures as a new version. Older projects keep their original format: legacy JavaScript (`.jsx`) packages and single-file HTML versions still preview, refine, and publish.

## Run locally

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

`npm run dev` starts both Vite and FastAPI (using `PYTHON`, else `backend/.venv/bin/python`, else `python3`) and stops both together. Open `http://localhost:5173`.

The initial administrator is `admin@forma.local` / `admin123`. Change it before exposing the studio. Data lives under `data/`.

Without a configured model provider, projects use **Forma Local**, an offline deterministic engine that produces a working sample app for every stage. An administrator can add OpenAI-compatible providers on the Admin page; each user picks one under Configuration.

Package mirrors default to `https://mirrors.aliyun.com/pypi/simple/` and `https://registry.npmmirror.com`; set `RUNTIME_PIP_INDEX_URL` and `RUNTIME_NPM_REGISTRY` to use others. Installers inherit only the host's proxy and CA-bundle variables; generated apps never receive them.

## Configuration

See [.env.example](.env.example). Two optional infrastructure flags exist, both off by default:

- `DURABLE_JOBS_V1` — run generation through the durable job runner (leases, checkpoints, cancellation, SSE event streaming, usage telemetry).
- `SANDBOX_V1` — run generated backends in Docker as a non-root user with a read-only filesystem, dropped capabilities and memory/CPU/PID limits.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm test && npm run build
cd frontend && npx playwright test
```

## Production

Build the studio with `npm run build`; FastAPI serves `frontend/dist`. Set a strong `SECRET_KEY`, restrict `CORS_ORIGINS`, use HTTPS, and replace the initial administrator. Enable `SANDBOX_V1` (or an equivalent sandbox) before letting untrusted users execute generated code.

## Code map

- `backend/app/engine.py` — the stage workflow; feeds approved documents into every later stage.
- `backend/app/source_packages.py` — React + TypeScript / FastAPI package prompt, validation, and the Forma Local package.
- `backend/app/backend_engine.py` — backend validation, dependency allowlist, architecture recommendation, single-file contract.
- `backend/app/frontend_builder.py` — shared Node environments, staged Vite builds, assets, deployment archives.
- `backend/app/runtime.py`, `runtime_launcher.py`, `runtime_sandbox.py` — per-app Python environments, processes, proxying, sandboxing.
- `backend/app/llm.py` — OpenAI-compatible structured calls with truncation and JSON repair.
- `backend/app/local_engine.py` — offline documents and single-file apps.
- `backend/app/api.py`, `database.py`, `deployment_registry.py` — API, control/per-user SQLite databases, public hosting registry.
- `backend/app/jobs/` — optional durable jobs, events, cancellation, and usage telemetry.
- `frontend/src/pages/Dashboard.tsx`, `Builder.tsx` — project creation and the collaborative studio.
- `frontend/src/components/` — source browser, server panel, usage panel, modals.

Product requirements: [doc/PRD.md](doc/PRD.md). Change history and status: [doc/IMPLEMENTATION.md](doc/IMPLEMENTATION.md).
