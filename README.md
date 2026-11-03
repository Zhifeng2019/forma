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
- Public hosting on a dedicated origin per app, with publish, republish, and unpublish controls.
- Deferred creation and autopilot, which open the workspace immediately and progress through implementation before pausing at release review.
- Real runtime lifecycle/isolation tests, frontend unit tests, and Playwright coverage for both architectures.

## Run locally

### Start the studio

Copy `.env.example` to `backend/.env` and configure your local secrets there. The backend reads
`backend/.env`; exported process variables take precedence. Use Node.js 24 for the frontend tools.
This is the only environment file Forma loads, regardless of the working directory or launcher.
The root `.env` is ignored, and `.env.example` is the sole template. Startup logs identify the
active file, ignored root file if present, process override names, generation path, and effective
feature flags. Secrets and provider credentials are excluded from that report.

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

This starts both Vite and FastAPI, and shuts both down together. Open `http://localhost:5173`.

Generated apps use subdomains of `APPS_BASE_URL` (default `http://apps.localhost:8000`).
Chromium resolves these `.localhost` names to loopback without editing the hosts file.
Each project's public release has its own origin; each preview version has another. Generated
pages cannot read the studio's local storage or parent document. The backend rejects studio
routes on app hosts and rejects unknown hosts. Set `STUDIO_BASE_URL` to the backend's address
and include every actual studio UI origin in `CORS_ORIGINS`, including custom development ports.
When using a different backend port, change `APPS_BASE_URL` to the same port.

The studio requests a 15-minute project/version preview grant using its authorization header.
The grant appears in the isolated preview path so HTML, assets, and API requests work without
third-party cookies. It cannot authenticate to studio APIs, and every request checks expiry,
ownership, and account status. `PREVIEW_TOKEN_MINUTES` allows 1–60 minutes; open studio previews
renew before expiry (reloading the preview). An independently opened preview expires and can
be reopened from the studio. Preview responses use `no-store` and `no-referrer`. Package
downloads also use authorization headers; studio login tokens never appear in preview or
download URLs. The previous query-token preview and runtime routes have been removed.

Existing apps start with fresh browser storage on their new addresses, and preview versions
have separate browser storage. Existing storage at the old address is not deleted or copied;
generated backends keep their existing server-side databases. This follows the browser's
[origin-based storage boundary](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Same-origin_policy).

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

The hosting proxy forwards application bearer tokens, cookies, and standard CSRF token headers.
Each `Set-Cookie` header is kept separate; cookies become host-only with `Path=/` on the dedicated
application host, so a renewed preview grant does not discard the login. Public cookies retain
their SameSite policy and gain Secure on HTTPS. Embedded previews use `SameSite=None; Secure;
Partitioned`, following [Chrome's partitioned-cookie model](https://privacysandbox.google.com/cookies/chips).
Cookie previews require HTTPS in production; Chromium also supports the local `.localhost` setup.
Preview and public sessions are separate, and logout expires cookies in the same scope used at login.

Each environment installs its pinned dependencies using its own `.venv/bin/python -m pip` and the Aliyun mirror `https://mirrors.aliyun.com/pypi/simple/` (configurable with `RUNTIME_PIP_INDEX_URL`). Inherited studio and machine site-packages are disabled. Before startup, Forma verifies both the package versions and that FastAPI, Uvicorn, Pydantic, and email-validator import from the application’s own `site-packages`. Older artifacts missing support packages such as `email-validator` are augmented during installation without rewriting those artifacts. Runtime requests have health checks, timeouts, body/concurrency limits, and owner-only diagnostics. Unpublish and delete operations stop their corresponding processes.

Published APIs are public with the application URL and do not require a Forma session. With `SANDBOX_V1` enabled, generated backends run in Docker as a non-root user with a read-only root filesystem, source mounted read-only, only the application work directory writable, dropped capabilities, no-new-privileges, and enforced memory, CPU, PID, file, and timeout limits. Dependencies install inside the image rather than mounting the host virtual environment. Process-based runtimes remain the fallback when sandboxing is disabled. Network policy, preview/published data isolation, and managed application authentication remain separate work; this is not yet a complete multi-tenant security boundary.

## Generation and historical contracts

Chat messages are routed before generation. Questions (including requests for admin credentials)
receive read-only answers using project documents and the current source. Explicit edit requests
retain the existing document revision or application refinement workflow. Ambiguous messages ask
for clarification; an unavailable model or invalid routing response never falls back to rebuilding.
Answers do not edit artifacts, create application versions, or run generation jobs. They cannot
inspect live application accounts, recover stored passwords, or reset credentials. Without a model,
the local demo only applies clear edit instructions and explains its limits for questions.

After release approval or publication, an edit creates a new working version at the same phase.
It returns to phase review (or release review after phase 3), preserving the previously published
version until the owner explicitly republishes. The new version inherits the approved planning
context and keeps previous versions available.

The LLM receives `product.md` when designing, then the product and design documents when
planning. Builds, refinements, and architecture migrations receive all three planning documents,
the existing source, the selected architecture, and current feedback. The implementation plan
defines each of the three phases; refinement and migration instructions preserve the current
phase. Document revisions also receive their upstream planning inputs.

In manual mode, the generated plan opens in Documents for review. Feedback before the first
build revises `plan.md` and creates no application version. **Build phase 1** approves that plan
and starts generation. Autopilot follows its authorized sequence, but feedback during plan
review pauses it at the unbuilt plan until the user explicitly continues.

Each new application version stores an immutable `generation_context` snapshot in the workspace
database: exact document contents, SHA-256 revision identifiers, artifact references, phase,
architecture, generation mode, brief, and feedback. Later builds, refinements, and migrations
inherit those recorded documents; new drafts cannot silently replace them. Current feedback
and explicitly selected architecture can amend the original direction. Planning documents are
not model-generated source files, and a package that tries to rewrite them gets a repair request.
The private owner API `GET /api/projects/<id>/versions/<version>/context` returns this record.

Database upgrades add a nullable context field without inventing history for older versions;
the API returns `recorded: false` for those releases. When continuing a legacy project, available
documents are supplied with their earlier approval/use marked unrecorded, and missing documents
are listed explicitly. The first new version records the inputs actually supplied. Forma Local
remains a canned offline demo and is identified as `local-demo` in these records.

New builds, refinements, and architecture migrations use LLM-generated application source.
Forma Local remains the offline demo engine when no model provider is selected. The deprecated
AppSpec single-entity compiler, proposal generator, and deterministic specialist workers have
been removed. `APPSPEC_V1` and `SPECIALIST_WORKERS_V1` are no longer settings; stale values in
an environment or dotenv file are ignored and cannot select a different generator.

Existing source versions, published releases, `appspec.json`, build manifests, and acceptance
reports are preserved. Contract review is read-only and scoped to the version that owns the
contract. Refining an old AppSpec application uses its existing source and creates a normal
source version without copying its old contract or acceptance checks.

`ACCEPTANCE_GATE_V1` remains available for **historical versions with stored contracts**. When
enabled, publishing a different contract-bearing version requires fresh verification; an invalid
or incomplete stored contract still blocks publication. Source versions without contracts use
normal publishing. Optional advisory model review is requested explicitly with `include_review`
and never changes deterministic verification results.

`DURABLE_JOBS_V1` and `SANDBOX_V1` remain independent settings for job lifecycle and Docker
runtime isolation. Neither changes how application source is generated.

## Production shape

Build the frontend with `npm run build`; FastAPI serves `frontend/dist` when present. Set a strong `SECRET_KEY`, restrict `CORS_ORIGINS`, put the service behind HTTPS, and replace the initial administrator credentials. Do not expose generated-code execution to untrusted users without a container or equivalent security sandbox.

Direct visits and refreshes on studio routes such as `/login`, `/settings`, and `/projects/<id>`
serve the built application shell. Missing assets and unknown API or application paths keep
their normal error responses; the studio shell is never served on generated application hosts.

For example, use `STUDIO_BASE_URL=https://studio.example.com`,
`CORS_ORIGINS=https://studio.example.com`, and `APPS_BASE_URL=https://apps.example.net`.
Reserve the app domain for generated content. Configure wildcard DNS and TLS for
`*.apps.example.net`, forwarding both studio and app hosts to the backend **with the original
Host header preserved**. Do not rewrite app hosts to the studio host. Using the app domain or
one of its subdomains as a studio/CORS origin fails configuration validation. The public URL
returned by the project API and Publish dialog is canonical; old studio `/apps/<id>/` GET
links redirect there without serving generated content on the studio origin. API writes must
use the canonical app URL directly.

## Runtime and job infrastructure

The active implementation and historical milestones are recorded in [doc/IMPLEMENTATION.md](doc/IMPLEMENTATION.md). Compiler-related milestones in that record describe retired functionality.

- Typed feature flags cover durable jobs, historical acceptance gates, and sandboxing.
- The durable runner supports idempotent jobs, attempts, checkpoints, heartbeat, cancellation, retry, and stale-finalization protection for stage generation, document revision, and architecture migration.
- Attempt-scoped contexts carry cancellation, trace IDs, and tool ownership. Project payloads expose `active_job`, and `POST /api/projects/<project-id>/jobs/<job-id>/cancel` provides owner-checked, idempotent cancellation with persisted `cancel_requested`, `cancelling`, and `cancelled` transitions and no automatic retry.
- A shared process supervisor covers provider calls, npm/pip/venv setup, dependency probes, Vite builds, Playwright, and runtime startup. It races cancellation and timeouts, redacts output, and cleans only attempt-owned process groups with bounded escalation and output draining; unrelated preview and published runtimes remain untouched.
- Shared tool-run envelopes persist job/attempt ownership, tool name/version, input hashes, redacted output references, terminal status, retry sequence, timestamps, durations, and spec/source provenance. Job-scoped provider HTTP calls, build/install processes, runtime launch/health, and verification checks receive distinct spans, including schema fallback and output-repair requests; prompts, credentials, URL queries, and raw environments are not stored.
- Observed model completions record provider request IDs, finish reasons, latency, fallback/repair reasons, and provider-reported prompt/completion/total tokens for every HTTP response. Token availability is explicitly `reported`, `partial`, or `unavailable`. Optional per-provider input/output prices per million tokens and currency are snapshotted into each usage row; computed costs are estimates, while missing tokens or prices remain unknown rather than becoming `$0`. Explicit zero usage and zero prices remain distinguishable from unknown values, and Forma Local emits no synthetic model usage.
- Build/runtime spans include actual executable and host versions, retry sequences, cache-hit outcomes, package/input hashes, and source/spec provenance. Node environment reuse, Vite staging/build/promotion, Python environment probes/install, runtime reuse/launch/health, and verification preserve distinct terminal records without storing credentials, prompt bodies, raw environments, URL queries, or private index secrets. Existing build digests, immutable versions, verification reports, and historical records remain compatible.
- `GET /api/projects/<project-id>/usage` provides owner-only per-job and project aggregation for token availability, partial or estimated costs, retries, tool durations, runtime health, and source/spec hashes. The read-only Activity usage view presents the same evidence with expandable tool details. Cancelled/failed jobs close abandoned spans, legacy running spans are interpreted honestly, and secret scanning covers API output.
- Finalization checks job ownership, input hash, and cancellation state atomically. Cancellation restores pre-attempt project/version state and prior verification reports, prevents cancelled verification from being published, and provides a Builder cancel button with immediate `cancelling` feedback and polling.
- Optional advisory review is requested explicitly with `include_review` and stored separately as `acceptance/model-review.json`. Model suggestions never alter `acceptance/report.json`, deterministic status, `can_publish`, build/test/security failures, or release gates. Review failures, cancellation, and missing providers remain explicit non-gating states in the Verification panel.
- Owner-scoped SSE replay uses versioned envelopes with persisted numeric event IDs, redacted payloads, `Last-Event-ID`/`after` cursors, bounded pages, heartbeat/reconnect hints, and `stream.complete`. `job.started`, `job.succeeded`, and `project.refresh` complement existing checkpoints and terminal events without exposing bearer tokens in URLs.
- Live `follow=true` streams tail persisted events without holding SQLite connections across waits. The Builder’s abortable `useProjectEvents` subscription tracks monotonic cursors, resumes with `Last-Event-ID`, applies bounded backoff, refreshes immediately on project/report/cancellation events, and closes on navigation, completion, and shutdown.
- Live streams replay from the requested cursor without skipping existing events, poll for new persisted events every 250 ms, and retain 15-second idle heartbeats. Network-side aborts reconnect; only disposal stops the subscription.
- Project payloads advertise durable-job support so legacy projects remain polling-only. Disconnected or unsupported streams use 1.5-second polling, while healthy SSE reconciles the authoritative project snapshot every 30 seconds. Expired cursors reload that snapshot before replay resumes; monotonic event IDs and idempotent jobs avoid duplicate versions.
- The deterministic verifier produces durable reports with spec/source hashes, tool-run IDs, durations, blocked/failed details, full-coverage `can_publish` evaluation, and forced retry support. The Verification panel presents this evidence and refreshes deferred runs automatically.
- Public deployments resolve through the control-plane registry with write-through publish, republish, unpublish, and delete synchronization and backfilled version-specific architecture. Public lookup no longer scans every user database.

Regenerate the evaluation baseline with:

```bash
cd backend && /Users/zhifengzhang/python_env/env_ai_build/bin/python scripts/capture_baseline.py
```

Use `--skip-browser` for backend/frontend-only capture. Captures now write suite-only schema
1.1 reports to `backend/tests/evals/current-baseline.json`; the retired AppSpec generation-quality
runner has been removed. Existing 1.0–1.2 reports remain readable as historical evidence.
The checked-in 1.2 baseline and `generation.json` describe the retired compiler and must not
be treated as a quality claim about the current LLM generator. `--generation-report` can attach
such archived evidence explicitly; it never runs the deleted compiler.

Compare two current suite-only captures using:

```bash
cd backend && /Users/zhifengzhang/python_env/env_ai_build/bin/python scripts/capture_baseline.py --check --reference /path/to/suite-baseline.json --output /path/to/candidate.json
```

The check compares reports of the same scope. Compare new suite-only captures against a suite-only reference; do not use the archived compiler-quality baseline as a reference for current generation.

After changing the report contract, regenerate its checked-in JSON Schema and run the schema-drift test:

```bash
cd backend && /Users/zhifengzhang/python_env/env_ai_build/bin/python scripts/capture_baseline.py --write-schema
/Users/zhifengzhang/python_env/env_ai_build/bin/python -m pytest -q tests/test_capture_baseline.py
```

Compatibility fixtures are declared in `backend/tests/fixtures/manifest.json` with resource checksums. Four package bases cover static/FastAPI and single-file/multi-file architectures; shared React sources are extended with replaceable API adapters and a modular backend. Sixteen declarative variants cover current/historical and published/unpublished states, while nine provider fixtures record expected acceptance, normalization, bounded repair, rejection, or overlay handling. Stable package source hashes and normalized AppSpec hashes detect unintended fixture drift.

`FixturePack` materializes project versions, artifacts, publication state, and provider responses only into an explicit empty or marker-approved absolute temporary workspace. The loader refuses application data directories, unmarked nonempty directories, and non-canonical paths; resource checksum mismatches fail before project or provider data is materialized. Multi-file fixture sources also pass the studio's real source-package validator.

The historical AppSpec schema, LLM repair, package-overlay, and requirements-normalization tests consume the same pack. Frozen compiler outputs in `backend/tests/fixtures/archived_appspec/` support historical verification and runtime tests without retaining an executable compiler. Integration coverage exercises real Vite builds, single-file and modular FastAPI health/CRUD, historical preview/public output, owner-scoped registry reads, bidirectional migration, and bounded malformed-output handling.

## Tests

```bash
cd backend && /Users/zhifengzhang/python_env/env_ai_build/bin/python -m pytest -q
cd frontend && npm test && npm run build
cd frontend && npx playwright test
```

After building the frontend, set `FORMA_TEST_PRODUCTION=1` to run the browser suite against
FastAPI's production hosting, including direct studio links and page refreshes. Use a separate
temporary `DATA_DIR` and an unused `FORMA_TEST_BACKEND_PORT` to isolate it from your own apps.

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
