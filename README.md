# Forma — AI Product Studio

Forma is an AI-native application builder built around a guided product-development cycle: description, design, implementation plan, three build phases, review, and publishing.

## What is included

- Email registration, login, account roles, and admin user controls.
- Shared control-plane SQLite database and one isolated SQLite workspace per user.
- OpenAI-compatible provider management with encrypted API keys and connection tests.
- An offline **Forma Local** engine for deterministic demos without external credentials.
- Product, design, and implementation-plan Markdown artifacts.
- Three implementation phases with working previews and version history.
- Conversational revisions and preview element selection for targeted feedback.
- Desktop, tablet, and mobile preview modes.
- Public hosting at `/apps/<application-id>/` with publish, republish, and unpublish controls.
- Autopilot creation, which progresses through implementation and pauses at release review.
- Backend lifecycle/isolation tests, frontend unit tests, and Playwright end-to-end coverage.

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
/Users/zhifengzhang/python_env/env_ai_build/bin/python -m uvicorn app.main:app --reload --port 8000
```

The initial local administrator is `admin@forma.local` with password `admin123`. Change this account before exposing the service publicly. All data is development-local by default under `backend/data/`.

## Production shape

Build the frontend with `npm run build`; FastAPI serves `frontend/dist` when present. Set a strong `SECRET_KEY`, restrict `CORS_ORIGINS`, put the service behind HTTPS, and replace the initial administrator credentials. Generated applications are static, dependency-free HTML documents in version 1; arbitrary generated backend execution is intentionally not enabled.

## Tests

```bash
cd backend && /Users/zhifengzhang/python_env/env_ai_build/bin/python -m pytest -q
cd frontend && npm test && npm run build
cd frontend && npx playwright test
```

## Architecture

- `backend/app/api.py` — authentication, administration, project workflow, preview, and publishing API.
- `backend/app/engine.py` — stage orchestration, artifacts, messages, and versions.
- `backend/app/llm.py` — structured OpenAI-compatible model calls.
- `backend/app/local_engine.py` — offline product documents and application generation.
- `backend/app/database.py` — control and per-user SQLite schemas.
- `frontend/src/pages/Builder.tsx` — collaborative product studio.
- `frontend/src/pages/AdminPage.tsx` — provider and member administration.
