# Forma Studio — AI-Native Application Builder

**Document status:** Updated to reflect the implemented multi-file package release
**Current release:** Forma Studio v1.3
**Product name:** *Forma* comes from the Latin word for form, shape, or structure. It represents turning an unstructured idea into a working product.

## 1. Product overview

Forma Studio is a web-based application builder that helps users describe, design, implement, refine, and publish web applications through a guided AI product-development workflow.

The product is built around a visible development cycle rather than a single prompt-to-code action. Users remain in control through document reviews, phase approvals, conversational feedback, preview element selection, and explicit publishing decisions.

### Goals

- Turn a plain-language product idea into a working, shareable application.
- Use the simplest appropriate architecture: frontend-only when no server is needed, or a dedicated FastAPI service when server-side behavior adds real value.
- Make the agent’s plan, artifacts, progress, runtime, and releases visible to the user.
- Support iterative feedback at both document and application levels.
- Provide a complete local experience without requiring an external LLM account.
- Support multiple production LLM providers through administrator configuration.
- Isolate each user’s projects and artifacts in a dedicated SQLite workspace.

### v1.3 scope

New projects can use a multi-file React and FastAPI source package or the legacy single-file format. Project package is the default in the creation UI; Single file remains available and existing versions keep their original behavior. Both formats support frontend-only and FastAPI architectures and preserve the same six-stage workflow.

Each multi-file version has this deployment layout:

```text
versions/vN/
  frontend/        # React source, package.json, Vite config, and built dist/
  backend/         # FastAPI entrypoint, app package modules, requirements.txt
```

The agent validates source files and reviewed dependencies, runs the production Vite build, and only then marks a version ready. Previews serve built assets, publishing serves the same production output, and deployment ZIP downloads contain source plus `frontend/dist/` and `backend/` without dependency folders or caches.

Existing projects can migrate architecture in either direction as a new version without advancing the current phase. Architecture and source format are stored on every version, so historical previews and published releases retain their original behavior until explicit republication.

Reviewed Python dependencies include FastAPI, Pydantic, Uvicorn, email-validator, httpx, PyJWT, cryptography, pydantic-settings, python-multipart, and SQLAlchemy. Reviewed npm dependencies use the studio’s locked React, React DOM, Lucide, Vite, and React-plugin versions. Arbitrary dependencies, production container isolation, and managed end-user authentication remain future work. The runtime is process-isolated, not a hardened multi-tenant security sandbox.

## 2. Target users

- Founders and product managers validating an application concept.
- Designers and makers prototyping an interactive experience.
- Small teams creating focused internal tools or client-facing pages.
- Developers who want an AI-assisted starting point with reviewable artifacts.

## 3. Technology and architecture

### Frontend

- React and TypeScript.
- Vite development and production builds.
- Responsive custom CSS for desktop, tablet, and mobile use.
- Markdown rendering for product, design, and implementation-plan documents.
- Playwright end-to-end validation and Vitest unit tests.

### Backend

- FastAPI and Python.
- SQLite persistence with WAL mode.
- JWT bearer authentication.
- PBKDF2 password hashing.
- Encrypted LLM provider credentials.
- OpenAI-compatible HTTP provider integration.
- Optional generated FastAPI services with versioned source and independent preview/public processes.

### Generated application runtime

- Each backend-enabled application has its own Python virtual environment and directory under `data/projects/<application-id>/`.
- Each environment installs pinned dependencies into its own `site-packages` using its own `.venv/bin/python -m pip` and the Aliyun mirror `https://mirrors.aliyun.com/pypi/simple/` (configurable with `RUNTIME_PIP_INDEX_URL`). Studio and machine site-packages are not inherited.
- Startup verifies package versions and physical import locations inside the application environment. Legacy shared-package links are removed and replaced with local installations before the backend can start. Older artifacts missing support packages, including `email-validator` for Pydantic `EmailStr`, are augmented during installation without rewriting the artifacts.
- Single-file backends keep immutable `versions/v<N>/main.py` and `requirements.txt`. Multi-file backends use `versions/v<N>/backend/main.py` plus the generated `backend/app/` package modules.
- Preview and published versions run independently on loopback and start on demand. Switching preview versions replaces only that project’s preview process.
- Startup requires a successful `/api/health` check. Requests have timeouts and a 2 MB body limit; runtime logs are available only to the project owner.
- Unpublishing stops the public process. Deleting a project stops its processes and removes its generated runtime directory.
- Runtime capacity is bounded, with idle preview reclamation when capacity is needed. File-size, descriptor, concurrency, and supported OS memory limits are applied; macOS address-space limits are best-effort and may be unavailable.
- An application-local `app.db` persists across process restarts and versions. Preview and published processes for the same application share this database.

### Multi-file package build and deployment

- Every multi-file version stores frontend and backend side-by-side. Frontend source, `package.json`, and Vite config live in `versions/v<N>/frontend/`; the FastAPI entrypoint and `backend/app/` modules live in `versions/v<N>/backend/`.
- One shared Node environment per user installs the studio’s locked npm dependencies from `RUNTIME_NPM_REGISTRY` (default `https://registry.npmmirror.com`). Generated frontends link to that environment only during builds; it is never included in deployment archives.
- Generated changes are overlaid on the previous complete package, and every relative JavaScript import must resolve before building. Each version is materialized in `versions/vN.staging`; validation and `vite build` must succeed before the directory is promoted to `versions/vN`. Failed builds remove staging and preserve the last usable version. Backend runtimes consume only promoted packages, and source/build hashes prevent unnecessary rebuilds.
- Private previews serve built HTML and version-scoped asset cookies, including historical versions and CSS dependencies. Public hosting serves the selected published build and its assets.
- The Source tab exposes current-version files and a deployment ZIP. Archives include React source, production `frontend/dist/`, and the backend package when applicable, while excluding `node_modules`, npm caches, temporary files, and bytecode.
- Multi-file model output receives one bounded semantic regeneration when required files, imports, or API contracts fail validation. Empty Python modules such as `__init__.py` are valid.

### Data isolation

Studio persistence uses two database levels:

1. **Control database:** user accounts, roles, provider definitions, and per-user preferences.
2. **Per-user workspace databases:** projects, messages, documents, generated applications, versions, events, and publishing state.

A backend-enabled generated application may additionally own the SQLite database in its runtime workspace. A user must not be able to read or modify another user’s private workspace or private runtime. Published application HTML and its explicitly published API are intentionally exposed without studio authentication.

## 4. Core development workflow

Every application follows six visible stages.

### 4.1 Product description and architecture

The agent converts the user’s initial brief into `product.md`, covering:

- Product vision and opportunity.
- Primary users.
- Core workflow.
- First-release scope.
- Success criteria.

At creation, the user selects **Let Forma decide**, **Frontend only**, or **FastAPI backend**. The default is Let Forma decide. During discovery, an external provider returns a backend recommendation alongside the document; Forma Local uses brief-based architecture rules. Explicit user selection takes precedence. The selected architecture and reason are recorded in project activity and carried into later stages. Existing pre-v1.1 projects remain frontend-only after migration.

The user can submit feedback to revise the document or approve it to continue.

### 4.2 Experience and technical design

The agent creates `design.md`, covering:

- Visual direction and design system.
- Information architecture.
- Responsive and accessible interaction behavior.
- Frontend approach and the selected backend contract.

Feedback updates the design artifact and is carried into subsequent stages without silently changing the selected architecture.

### 4.3 Implementation plan

The agent creates `plan.md` with three implementation phases. Each phase must produce a shareable, working page rather than an isolated or nonfunctional code fragment.

The default phase structure is:

1. Foundation, responsive shell, visual system, and overview; FastAPI projects also expose a working health route and live data view.
2. Core workflow, interactions, state, validation, and feedback; FastAPI projects implement the primary server-backed workflow and persistence.
3. Polish, accessibility, responsive refinement, reliability, and release readiness.

### 4.4 Phased implementation

The agent implements one phase at a time and creates a new application version after each phase or revision. A frontend-only version contains `index.html`. A FastAPI version contains a matched `index.html`, `backend/main.py`, and `backend/requirements.txt`.

The builder provides:

- A live application preview.
- Desktop, tablet, and mobile viewport modes.
- Conversational change requests.
- An element picker for targeted visual feedback.
- Version history and the ability to inspect earlier versions.
- Approval gates between phases unless autopilot is enabled.
- A Server panel for FastAPI health, runtime state, logs, source review, and preview restart.

Project creation opens the workspace immediately in a working state while generation runs in an in-memory background job. The builder polls working projects and active autopilot projects, refreshes the preview when a new version arrives, and stops at review or an error. Studio shutdown marks interrupted jobs as retryable errors; durable resumable jobs remain future work.

User messages appear in the conversation immediately with a working indicator. A failed request removes the unconfirmed optimistic message and restores the composer. During build and review, a feedback message creates a refinement of the **current phase** without changing its approval state. Only the explicit approval action advances to the next phase.

Phase approvals, build-phase feedback, and early document revisions use deferred generation jobs in the builder. The API returns a working project immediately while the current document or preview remains visible. Polling supplies the agent response, revised artifact, or new application version when generation completes. API clients can omit `defer` to retain synchronous behavior.

### 4.4.1 Architecture migration

The architecture control in the builder lets an existing project move from frontend-only to FastAPI or from FastAPI to frontend-only. Migration creates a new version and never counts as phase approval. Before the first build, the selection changes the foundation for the upcoming version instead. Migration runs as a deferred background job: the dialog closes immediately, a migration-specific working label appears, and polling refreshes the preview when the new version is ready rather than blocking the workspace on the model response.

Every version stores its architecture. Preview bootstrap injection, private runtime access, and public hosting all resolve architecture from the selected version rather than the project’s current mode. Migrating a working version does not alter the published version. Moving to frontend-only stops only the working FastAPI preview; an existing public FastAPI process remains available until the user republishes or unpublishes it. Version history labels include the architecture and migration type.

The Server panel presents an actionable error summary first and preserves complete runtime output under expandable technical details. Non-fatal platform notes are not presented as the primary failure.

### 4.5 Review and improvement

After Phase 3, the application enters release review. The user can:

- Exercise the primary workflow, including real API and persistence checks when present.
- Request additional refinements.
- Create a new version from feedback.
- Review project activity and generated documents.
- Inspect backend source and runtime behavior.
- Approve the release candidate.

### 4.6 Publishing

Applications are hosted beneath the base URL:

```text
/apps/<application-id>/
```

A published FastAPI application exposes its generated API beneath:

```text
/apps/<application-id>/api/
```

Publishing capabilities include:

- Publish the current version.
- Republish a newer version while retaining independent preview and public process lifecycles.
- Open and copy the public URL.
- Unpublish an application and stop its public runtime.

Autopilot may progress through implementation automatically, but the release remains available for explicit user review.

## 5. LLM generation requirements

### Provider configuration

Administrators can add, edit, enable, disable, remove, and test OpenAI-compatible providers. Provider settings include:

- Display name.
- Base URL.
- Model name.
- Encrypted API key.
- Enabled state.

Each user selects an available provider in the Configuration page. If no provider is selected, the user’s projects use Forma Local.

### Generation behavior

- Product, design, and planning calls return structured JSON containing Markdown. Discovery also requests `backend_required` and `backend_reason` when architecture is automatic.
- Frontend-only application calls return structured JSON containing complete HTML.
- FastAPI application calls return complete HTML and Python source in one structured result so the UI and API contract evolve together.
- Single-file frontend output must contain a complete `<html>` document. Backend output must parse as Python, define `app = FastAPI(...)`, expose `/api/health`, and use either `Forma.api` or same-origin `/api/...` fetch calls handled by the runtime bridge.
- Multi-file output uses a `files` object with required React and backend paths plus `python_dependencies`. The studio supplies reviewed `package.json` and Vite config, validates every path and module, and requires a production build before saving the ready version. `backend/requirements.txt` is generated by Forma from the reviewed list and is not required from the model. Optional-chaining and native-fetch adapters are supported by the same runtime bridge.
- Generated backend imports are allowlisted. Base packages are FastAPI, Pydantic, Uvicorn, and email-validator; reviewed optional packages are httpx, PyJWT, cryptography, pydantic-settings, python-multipart, and SQLAlchemy. JavaScript application imports are limited to React, React DOM, and Lucide. All dependency pins come from studio lockfiles or verified versions rather than arbitrary model-selected versions.
- The explicit output-token budget is **32,768 tokens** for each structured call.
- DeepSeek deterministic coding calls disable reasoning where supported.
- Moonshot Kimi K3 calls use low reasoning effort.
- The client inspects `finish_reason` before parsing output.
- A response ending with `finish_reason: "length"` is treated as truncated, not as an ordinary JSON syntax error.
- Truncated or invalid structured output receives one bounded regeneration attempt.
- A second output-limit failure returns a clear error recommending a smaller phase.
- Provider network and HTTP errors are reported to the user without exposing credentials.
- Generation activity records the provider and model used for each stage.

### Forma Local

Forma Local is a deterministic offline engine for evaluation, development, and users without external API access. It produces product documents, frontend-only applications, and FastAPI-backed applications without calling an external provider. Its backend example supports health checks, CRUD operations, and SQLite persistence so the complete runtime path can be tested without LLM credentials.

The interface and activity history must distinguish local generation from real LLM generation.

## 6. Application builder interface

The builder uses a two-panel desktop composition:

- **Left panel:** product-team chat, project context, targeted-selection details, and revision composer.
- **Right panel:** preview, documents, FastAPI Server diagnostics when applicable, activity, stage status, and approval controls.

A six-stage tracker appears above the workspace. The header provides project navigation, saved state, architecture, version history, and publishing actions.

On smaller screens, the preview and collaboration panels stack vertically while preserving access to the primary workflow. Architecture selection and Server diagnostics remain usable on mobile layouts.

## 7. Other application pages

### Authentication

- Registration with name, email, and password.
- Login and session restoration.
- Active and disabled account states.

### Project dashboard

- Create an application from a name and plain-language brief.
- Choose automatic architecture, frontend-only, or FastAPI during creation.
- Start from suggested ideas.
- Search existing projects.
- Display project stage, version, update time, FastAPI architecture, and live status.
- Delete projects with confirmation, including generated runtime cleanup.

### User configuration

- Select Forma Local or an available external provider.
- Set autopilot as the default for new projects.

### Administration

- View workspace members and project counts.
- Change member roles.
- Disable or re-enable accounts.
- Manage model providers and test connectivity.

## 8. Security and operational requirements

- API keys are encrypted before persistence and never returned by provider APIs.
- Passwords are salted and hashed.
- Private project and runtime endpoints require authentication and ownership checks.
- Preview access requires a valid user session token. The proxy verifies that token but does not forward the studio bearer token to the generated backend.
- Public hosting returns only explicitly published application versions. Published APIs are public with the application and do not require a studio session; the UI warns against sensitive data until product-level authentication is reviewed and added.
- Generated subprocess environments contain only runtime essentials and do not inherit LLM credentials, studio secrets, or the host environment.
- Backend source validation, import allowlists, loopback binding, scrubbed proxy headers, process groups, and resource limits reduce risk but do not constitute a hardened sandbox. This release is intended for trusted local use, not untrusted multi-tenant code execution.
- Runtime data and source paths are absolute so child-process working-directory changes cannot redirect artifact access.
- Provider clients do not depend on malformed host-level `NO_PROXY` configuration.
- Development startup launches FastAPI and Vite together and shuts them down cleanly. Studio shutdown stops generated application processes.
- Production deployments must replace the initial administrator credentials, set a strong secret key, restrict CORS origins, and use HTTPS. A container or equivalent security sandbox is required before exposing generated-code execution to untrusted users.

## 9. Validation and acceptance criteria

The optional-backend release is accepted when:

- A user can register, create a project, and complete all six stages with either architecture.
- Automatic architecture selection chooses a backend for server-dependent briefs and preserves a frontend-only path for browser-only products.
- Early-stage feedback modifies the corresponding document.
- Three implementation phases create working application versions.
- Multi-file versions build React source into `frontend/dist/` before becoming ready, serve hashed assets in preview and publishing, and run the modular FastAPI backend successfully.
- Deployment downloads contain frontend source, production output, and backend modules without dependency folders or caches; reviewed optional Python and npm dependencies pass validation.
- Real-provider multi-file generation produces a valid React package, production build, healthy backend, and deployable archive.
- Existing projects migrate in both directions without advancing the phase, and each historical version retains its correct architecture.
- A published static version remains static after a FastAPI migration; a published FastAPI version remains operational after migrating the working version to static until republication.
- Deferred creation and autopilot refresh the workspace through the final preview without a manual page reload.
- Deferred document revision and phase generation return `working` immediately, then update the corresponding document or application version in the background; real-provider runs finish with a healthy backend.
- A user message appears immediately even while its model request is delayed; failed sends restore the composer.
- Feedback during a build phase creates a refinement without advancing that phase; explicit approval is required to advance.
- Preview element selection reaches the revision request, and a revision creates a new version.
- FastAPI versions contain reviewable HTML, Python, and pinned dependency artifacts.
- Dependencies install from the configured Aliyun mirror into the application’s own virtual environment, and imports are verified inside that environment without shared-package links.
- A generated backend passes a real startup health check, supports CRUD requests, and persists SQLite data across restart.
- Real-provider architecture migration produces a healthy backend while preserving the published static version.
- Private runtime access rejects unauthenticated requests and users who do not own the project.
- An unpublished application and its API are not publicly accessible.
- Publishing exposes the selected HTML and API version; unpublishing stops public access while private preview remains usable.
- Project deletion removes runtime processes and generated files.
- Relative development data paths work correctly with subprocess working directories.
- A truncated provider response is detected and retried with the expanded output budget.
- Backend integration tests, frontend unit tests, TypeScript build, and browser end-to-end tests for both architectures pass.
- Test servers and generated application processes are stopped after validation.

## 10. Planned next iterations

The following capabilities are not part of the v1.3 runtime:

- Hardened container sandboxing with enforced CPU, memory, network, and syscall policies for untrusted multi-tenant execution.
- Managed product-level authentication, authorization, storage, and separate preview/published application databases.
- Specialist-agent delegation for parallel frontend, backend, and verification work.
- Streaming model output and resumable background generation jobs.
- Provider usage quotas, token accounting, and cost reporting.
- Custom domains and production edge routing.
