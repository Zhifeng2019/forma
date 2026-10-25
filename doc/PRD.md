# Forma Studio — AI-Native Application Builder

**Document status:** Updated to reflect the implemented optional-backend release
**Current release:** Forma Studio v1.1
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

### v1.1 scope

Forma generates and hosts portable, single-page HTML applications with embedded CSS and JavaScript. A project can remain frontend-only or include a generated FastAPI backend with one `main.py`, a pinned `requirements.txt`, and an application-local SQLite workspace. Both architectures follow the same six-stage workflow.

The initial backend runtime supports the reviewed FastAPI/Pydantic/Uvicorn stack and an allowlist of Python standard-library imports. It is a local process-isolation runtime, not a hardened multi-tenant security sandbox. General multi-file projects, arbitrary dependencies, production container isolation, and managed end-user authentication remain future work.

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

- Each backend-enabled application has its own Python virtual environment and directory under `backend/data/projects/<application-id>/`.
- Each environment installs pinned dependencies into its own `site-packages` using its own `.venv/bin/python -m pip` and the Aliyun mirror `https://mirrors.aliyun.com/pypi/simple/` (configurable with `RUNTIME_PIP_INDEX_URL`). Studio and machine site-packages are not inherited.
- Startup verifies package versions and physical import locations inside the application environment. Legacy shared-package links are removed and replaced with local installations before the backend can start. Older artifacts missing support packages, including `email-validator` for Pydantic `EmailStr`, are augmented during installation without rewriting the artifacts.
- Every build version has immutable `versions/v<N>/main.py` and `requirements.txt` source files.
- Preview and published versions run independently on loopback and start on demand. Switching preview versions replaces only that project’s preview process.
- Startup requires a successful `/api/health` check. Requests have timeouts and a 2 MB body limit; runtime logs are available only to the project owner.
- Unpublishing stops the public process. Deleting a project stops its processes and removes its generated runtime directory.
- Runtime capacity is bounded, with idle preview reclamation when capacity is needed. File-size, descriptor, concurrency, and supported OS memory limits are applied; macOS address-space limits are best-effort and may be unavailable.
- An application-local `app.db` persists across process restarts and versions. Preview and published processes for the same application share this database.

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
- Frontend output must contain a complete `<html>` document. Backend output must parse as Python, define `app = FastAPI(...)`, expose `/api/health`, and use the `Forma.api` frontend bridge.
- Generated backend imports are allowlisted. The initial third-party stack is FastAPI, Pydantic, Uvicorn, and email-validator for Pydantic `EmailStr`; dependency pins come from the studio’s verified versions rather than arbitrary model-selected versions.
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
- Deferred creation and autopilot refresh the workspace through the final preview without a manual page reload.
- A user message appears immediately even while its model request is delayed; failed sends restore the composer.
- Feedback during a build phase creates a refinement without advancing that phase; explicit approval is required to advance.
- Preview element selection reaches the revision request, and a revision creates a new version.
- FastAPI versions contain reviewable HTML, Python, and pinned dependency artifacts.
- Dependencies install from the configured Aliyun mirror into the application’s own virtual environment, and imports are verified inside that environment without shared-package links.
- A generated backend passes a real startup health check, supports CRUD requests, and persists SQLite data across restart.
- Private runtime access rejects unauthenticated requests and users who do not own the project.
- An unpublished application and its API are not publicly accessible.
- Publishing exposes the selected HTML and API version; unpublishing stops public access while private preview remains usable.
- Project deletion removes runtime processes and generated files.
- Relative development data paths work correctly with subprocess working directories.
- A truncated provider response is detected and retried with the expanded output budget.
- Backend integration tests, frontend unit tests, TypeScript build, and browser end-to-end tests for both architectures pass.
- Test servers and generated application processes are stopped after validation.

## 10. Planned next iterations

The following capabilities are not part of the v1.1 runtime:

- Hardened container sandboxing with enforced CPU, memory, network, and syscall policies for untrusted multi-tenant execution.
- Generated multi-file frontend projects and backend source packages, plus broader reviewed dependency support.
- One shared Node dependency environment per user for generated multi-file frontends.
- Architecture migration for existing projects, including adding a backend after the first build has already been generated.
- Managed product-level authentication, authorization, storage, and separate preview/published application databases.
- Specialist-agent delegation for parallel frontend, backend, and verification work.
- Streaming model output and resumable background generation jobs.
- Provider usage quotas, token accounting, and cost reporting.
- Custom domains and production edge routing.
